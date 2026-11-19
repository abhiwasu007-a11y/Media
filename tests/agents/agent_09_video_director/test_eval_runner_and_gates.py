# ruff: noqa: PT018, E501
"""The shot_direction pack through the amw_evals runner (fake adapter), and T4/T6 for the gate
cases of the timeline_engine pack (the step is run with a fake LLM that must never be called)."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_09_video_director.contracts import AspectRatio, Scene, ScriptDoc, Segment, SegmentKind
from agent_09_video_director.step import Verification
from amw_core.errors import AmwError
from amw_evals.adapter import FakeAdapter, LlmResponse
from amw_evals.runner import run_eval
from tests.agents.agent_09_video_director.support import (
    EVALS,
    REPO,
    SHA_A,
    codes,
    make_request,
    make_step,
    sample_script,
)
from tests.agents.agent_09_video_director.test_shot_direction_eval import CASES, recorded

TE = {
    c["case_id"]: c
    for c in map(json.loads, (EVALS / "timeline_engine/cases.jsonl").read_text().splitlines())
}


def test_shot_direction_pack_through_the_amw_evals_runner(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        {c["case_id"]: LlmResponse(output=json.loads(recorded(c))) for c in CASES}
    )
    records, summary = run_eval(
        REPO / "docs/v4", EVALS / "shot_direction", adapter, {}, tmp_path / "r.jsonl"
    )
    assert summary.total == 30 and summary.passed == 30 and summary.ok
    assert summary.answer_key_total == 4 and summary.answer_key_passed == 4
    assert summary.cost_micros == 0 and len(adapter.calls) == 30  # fake adapter: free, no network
    assert all(
        json.dumps(r["assertions"]).count(chr(34) + "passed" + chr(34) + ": false") == 0
        for r in records
    )


def script_from(kinds: list[tuple[str, str]], ids: list[str] | None = None) -> ScriptDoc:
    ids = ids or [i for i, _ in kinds]
    segs = tuple(
        Segment(segment_id=i, kind=SegmentKind(k), scene_id="sc", text="x")
        for i, (_, k) in zip(ids, kinds, strict=False)
    )
    return ScriptDoc(script_id="scr_x", version=1, language="en-IN", aspect_ratio=AspectRatio.LANDSCAPE,
                     scenes=(Scene(scene_id="sc", segment_ids=tuple(ids)),), segments=segs)  # fmt: skip


def run_gate(**kw: Any) -> tuple[AmwError, int]:
    from tests.agents.agent_09_video_director.support import timeline_for

    script = kw.pop("script")
    durs = kw.pop("durs", None)
    step, llm, rec = make_step()
    tl = kw.pop("timeline", None)
    req = make_request(script, durs or {s.segment_id: 1000 for s in script.segments}, **kw)
    if tl is not None:
        req = type(req)(
            **{**{f: getattr(req, f) for f in req.__dataclass_fields__}, "timeline": tl}
        )
    with pytest.raises(AmwError) as ei:
        step.run(req)
    assert llm.requests == [] and llm.engine.calls == [] and rec.rows == []  # T4: zero model calls
    _ = timeline_for
    return ei.value, len(llm.requests)


def test_te12_hook_outside_window_through_the_step() -> None:
    segs = TE["TE-12"]["input"]["segments"]
    script = script_from([(s["id"], s["kind"]) for s in segs])
    durs = {s["id"]: s["end_ms"] - s["start_ms"] for s in segs}
    err, _ = run_gate(script=script, durs=durs)
    assert err.code == "PERMANENT.INPUT_INVALID" and codes(err.details) == ["HOOK_WINDOW_EXCEEDED"]


def test_te27_hash_mismatch_through_the_step() -> None:
    inp = TE["TE-27"]["input"]
    script, durs = sample_script()
    err, _ = run_gate(script=script, durs=durs, script_sha256=inp["script_sha256"], script_ref_sha256=inp["script_sha256"],
                      verification=Verification(inp["verified_script_sha256"], inp["stage_verdict"]))  # fmt: skip
    assert codes(err.details) == TE["TE-27"]["expected"]["violations"]


def test_te28_te34_timelines_through_the_step() -> None:
    from agent_09_video_director.contracts import NarrationTimeline

    inp = TE["TE-28"]["input"]
    script = script_from([(i, "BODY") for i in inp["script_segment_ids"]])
    tl = NarrationTimeline.model_validate({"source": "PROVIDER_CLIPS", "segments": [
        {"segment_id": s, "start_ms": i * 1000, "end_ms": i * 1000 + 1000} for i, s in enumerate(inp["timeline_segment_ids"])]})  # fmt: skip
    err, _ = run_gate(script=script, timeline=tl)
    assert codes(err.details) == ["TIMELINE_INCOMPLETE"]
    inp34 = TE["TE-34"]["input"]
    script34 = script_from([(i, "BODY") for i in inp34["script_segment_ids"]])
    for var in inp34["variants"]:
        err, _ = run_gate(
            script=script34, timeline=NarrationTimeline.model_validate(var["timeline"])
        )
        assert codes(err.details) == ["TIMELINE_UNALIGNED"]


def test_t6_no_narration_or_on_screen_text_in_engine_outputs() -> None:
    script, durs = sample_script()
    script = script.model_copy(
        update={
            "segments": tuple(s.model_copy(update={"text": "NARR-CANARY"}) for s in script.segments)
        }
    )
    plan = make_step()[0].run(make_request(script, durs)).plan
    assert "NARR-CANARY" not in plan.model_dump_json() and SHA_A
