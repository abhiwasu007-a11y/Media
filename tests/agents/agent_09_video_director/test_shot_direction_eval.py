# ruff: noqa: PT018, E501
"""R-01 (deterministic part): the ``shot_direction`` dataset through the real parser and guards.

The dataset's ``expected`` object describes constraints, not a recorded model answer, so the
recorded response of each case is built from it (the minimal compliant answer). That exercises
A1-A14 and the production ``VisualGuard`` end to end offline. What is NOT proven here: that a
real model produces such answers (judged run, J1-J4, and the online eval gate under the owner cap).
"""

import json
import re
from typing import Any

import jsonschema
import pytest

from agent_09_video_director.contracts import Direction, DirectionInput
from agent_09_video_director.direction.guard import scan_direction
from agent_09_video_director.direction.parser import parse_direction_output
from tests.agents.agent_09_video_director.support import DEP_OFF, EVALS, PROMPT_PATH

pytestmark = pytest.mark.contract

CASES = [json.loads(x) for x in (EVALS / "shot_direction/cases.jsonl").read_text().splitlines()]
PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
BLOCKS = re.findall(r"```json\n(.*?)\n```", PROMPT, re.S)
IN_SCHEMA = next(json.loads(b) for b in BLOCKS if "direction.input:1.0.0" in b)
OUT_SCHEMA = next(json.loads(b) for b in BLOCKS if "direction.output:1.0.0" in b)
FRAMINGS = ["CLOSE_UP", "WIDE", "MEDIUM", "DETAIL", "TOP_DOWN"]
MOTIONS = ["SLOW_PUSH_IN", "SLOW_PULL_OUT", "PAN_LEFT", "PAN_RIGHT", "STATIC"]


def recorded(case: dict[str, Any]) -> str:
    inp, exp = case["input"], case["expected"]
    if exp["refusal_reason"]:
        ref = {"reason": exp["refusal_reason"], "message": "batch refused", "missing_inputs": [],
               "violated_rule_ids": ["FIN-R7"] if exp["refusal_reason"] == "RULE_WOULD_BE_BROKEN" else []}  # fmt: skip
        return json.dumps({"batch_id": inp["batch_id"], "directions": [], "refusal": ref})
    out = []
    for i, slot in enumerate(inp["slots"]):
        want = exp["per_slot"][slot["slot_id"]]
        portrait = inp["aspect_ratio"] == "9:16"
        d: dict[str, Any] = {
            "slot_id": slot["slot_id"], "status": want["status"], "reason_code": want["reason_code"],
            "intent_kind": None, "intent_text": "", "framing": "NONE", "motion": "STATIC",
            "still_ok": want.get("still_ok", False), "needs_ai_video": want.get("needs_ai_video", False),
            "interrupt_device": None, "transition_hint": want.get("transition_hint_in", ["CUT"])[0],
            "text_ids": [], "subject_anchor": None, "depiction": dict(DEP_OFF),
            "rationale": "Picture follows the point.",
        }  # fmt: skip
        if want["status"] == "OK":
            kinds = want["kinds_any"]
            kind = (
                "FOOTAGE"
                if "FOOTAGE" in kinds
                else ("DIAGRAM" if "DIAGRAM" in kinds else "TEXT_CARD")
            )
            d["intent_kind"] = kind
            if kind == "FOOTAGE":
                bad = set(want.get("framing_not", []))
                d["framing"] = next(f for f in FRAMINGS[i % 5 :] + FRAMINGS if f not in bad)
                d["motion"] = MOTIONS[i % 5]
                d["intent_text"] = "A quiet scene of hands on a wooden table, soft light."
            elif kind == "DIAGRAM":
                d["intent_text"] = "A generic schematic of boxes joined by an arrow flow."
                d["depiction"]["schematic"] = True
            ids = want.get("text_ids_exact")
            if ids is None and kind == "TEXT_CARD":
                ids = [slot["text_options"][0]["text_id"]]
            d["text_ids"] = ids or []
            if slot["role"] == "INTERRUPT_REQUIRED":
                allowed = want.get("device_in") or slot["allowed_devices"]
                d["interrupt_device"] = allowed[0]
                d["motion"] = "PUNCH_IN" if kind == "FOOTAGE" else "STATIC"
            if portrait:
                bad = set(want.get("anchor_not", []))
                d["subject_anchor"] = next(
                    a for a in ("CENTER", "UPPER_THIRD", "LEFT") if a not in bad
                )
        out.append(d)
    return json.dumps({"batch_id": inp["batch_id"], "directions": out, "refusal": None})


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_case(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    jsonschema.validate(inp, IN_SCHEMA)  # 27 6.1: every input is valid for the prompt's schema
    step_in = DirectionInput.model_validate(inp)  # ... and for the Pydantic model (C-03)
    raw = recorded(case)
    jsonschema.validate(json.loads(raw), OUT_SCHEMA)  # A1 (JSON Schema of the prompt)
    out = parse_direction_output(raw, [s["slot_id"] for s in inp["slots"]])  # A1 + A2 (Pydantic)
    if exp["refusal_reason"]:
        assert out.refusal is not None and out.refusal.reason == exp["refusal_reason"]  # A11
        assert out.directions == ()
        return
    assert out.refusal is None
    slots = {s.slot_id: s for s in step_in.slots}
    previous = step_in.previous_tail[-1:] if step_in.previous_tail else ()
    last: tuple[str | None, str | None, str | None] = (
        (previous[0].intent_kind, previous[0].framing.value, None)
        if previous
        else (None, None, None)
    )
    for d in out.directions:
        want = exp["per_slot"][d.slot_id]
        assert (d.status, d.reason_code) == (want["status"], want["reason_code"])  # A3
        if d.status == "OK":
            assert d.intent_kind in want["kinds_any"]  # A4
            assert not re.search(r"\d|https?://|[ऀ-ॿ]", d.intent_text)  # A5
            for banned in step_in.banned_subjects:
                assert banned.lower() not in d.intent_text.lower()
            dep = d.depiction
            assert not (
                dep.real_person or dep.identifiable_person or dep.brand_or_logo or dep.ai_presenter
            )  # A6
            assert not (dep.market_direction_imagery or dep.market_data_screen)
            if "device_in" in want and d.interrupt_device is not None:
                assert d.interrupt_device.value in want["device_in"]  # A8
            if want.get("anchor_not"):
                assert (
                    d.subject_anchor is None or d.subject_anchor.value not in want["anchor_not"]
                )  # A10
            if want.get("framing_not"):
                assert d.framing.value not in want["framing_not"]  # A13
            # A14 variety with the neighbour
            key = (d.intent_kind, d.framing.value, d.motion.value)
            assert not (
                key[0] == last[0]
                and key[1] not in ("NONE", None)
                and key[1] == last[1]
                and key[2] == last[2]
            )
            last = key
        slot = slots[d.slot_id]
        assert all(t in {o.text_id for o in slot.text_options} for t in d.text_ids)  # A7
        assert (d.interrupt_device is not None) == (
            slot.role.value == "INTERRUPT_REQUIRED" and d.status == "OK"
        )
        if not step_in.capabilities.still_allowed:
            assert not d.still_ok  # A9
        if not step_in.capabilities.ai_video_allowed:
            assert not d.needs_ai_video
        assert (d.subject_anchor is not None) == (
            step_in.aspect_ratio.value == "9:16" and d.status == "OK"
        )  # A10
        assert scan_direction(d, slot, step_in) == []  # A13: production guard agrees
    blob = raw.lower()
    assert all(m.lower() not in blob for m in exp["must_not_contain"])  # A12


def test_dataset_shape() -> None:
    assert len(CASES) == 30
    cats = {c["case_id"].split("-")[0] for c in CASES}
    assert {"AK", "POS", "HN", "EDGE", "REF"} <= cats


def test_pydantic_output_model_matches_the_prompt_schema() -> None:  # C-03 (fields)
    schema_fields = set(OUT_SCHEMA["properties"]["directions"]["items"]["properties"])
    assert schema_fields == set(Direction.model_fields)
    assert set(OUT_SCHEMA["properties"]) == {"batch_id", "directions", "refusal"}
    assert set(IN_SCHEMA["properties"]) == set(DirectionInput.model_fields)
