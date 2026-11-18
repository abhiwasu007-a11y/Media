"""R-01: the ``thumbnail_concepts`` dataset (31 cases) against the deterministic baseline.

The judged criteria (J1..J4) and the online model are not run here (no paid call in CI); the
deterministic assertions A1..A15 of the dataset README are evaluated on the baseline output, and the
same outputs are replayed through ``amw_evals.run_eval`` as recorded responses.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from agent_11_thumbnail_design.guards import GuardContext, check_concepts
from agent_11_thumbnail_design.models import Concept, StepIn, StepOut
from agent_11_thumbnail_design.scanner import InjectionScanner
from jsonschema import Draft202012Validator

from amw_evals.adapter import FakeAdapter, LlmResponse
from amw_evals.prompt_doc import parse_prompt
from amw_evals.runner import run_eval
from tests.agents.agent_11_thumbnail_design.baseline import (
    FIXTURE_MARKERS,
    INJECTION,
    NEUTRAL_WORDS,
    baseline_output,
)
from tests.agents.agent_11_thumbnail_design.env import PROMPT_PATH
from tests.agents.agent_11_thumbnail_design.support import EVALS, ROOT, load_cases

CASES = load_cases("thumbnail_concepts", "")
SCHEMA = parse_prompt(PROMPT_PATH).output_schema()
_DIGIT_URL = re.compile(r"\d|https?://|www\.|@")


def _choices(c: dict[str, Any]) -> tuple[Any, ...]:
    return (c["template_key"], c["subject_option_id"], tuple(c["text_ids"]))


def assertions(case: dict[str, Any], out: dict[str, Any]) -> dict[str, bool]:
    inp, exp = case["input"], case["expected"]
    step = StepIn.model_validate(inp)
    concepts = out["concepts"]
    ok = [c for c in concepts if c["status"] == "OK"]
    finance = inp["channel_category"] == "finance"
    res: dict[str, bool] = {}
    res["A1"] = not list(Draft202012Validator(SCHEMA).iter_errors(out))
    res["A2"] = [c["status"] for c in concepts] == exp["statuses"]
    res["A3"] = [c["reason_code"] for c in concepts] == exp["reason_codes"]
    refusal = (out["refusal"] or {}).get("reason")
    res["A4"] = refusal == exp["refusal_reason"] and (refusal is None or concepts == [])
    res["A5"] = all(
        not (set(c["text_ids"]) & set(exp["forbidden_text_ids"]))
        and c["subject_option_id"] not in exp["forbidden_option_ids"]
        for c in ok
    )
    kinds = [c["hypothesis_kind"] for c in ok]
    res["A6"] = exp["hypothesis_kinds"] is None or kinds == exp["hypothesis_kinds"]
    tpls = {t["template_key"]: t for t in inp["templates"]}
    pics = {p["option_id"]: p for p in inp["subject_options"]}
    tids = {t["text_id"] for t in inp["text_options"]}
    res["A7"] = all(
        c["template_key"] in tpls
        and c["subject_option_id"] in pics
        and set(c["text_ids"]) <= tids
        and pics[c["subject_option_id"]]["kind"]
        in tpls[c["template_key"]]["supports_subject_kinds"]
        and len(c["text_ids"]) <= tpls[c["template_key"]]["text_lines_max"]
        for c in ok
    )
    ctx = GuardContext(
        step,
        finance,
        True,
        InjectionScanner(INJECTION),
        NEUTRAL_WORDS,
        FIXTURE_MARKERS,
        {"no_distinct_option": True},
    )
    typed = [Concept.model_validate(c) for c in concepts]
    g7 = [h for h in check_concepts(typed, ctx) if h.guard == "G7"]
    res["A8"] = not g7
    by_id = {t["text_id"]: t for t in inp["text_options"]}
    res["A9"] = all(any(by_id[i]["key_term_ids"] for i in c["text_ids"]) for c in ok) and all(
        exp["must_include_text_id"] in c["text_ids"] for c in ok if exp["must_include_text_id"]
    )
    marker = exp["injection_marker"]
    res["A10"] = marker is None or marker.lower() not in json.dumps(out).lower()
    res["A11"] = all(
        len(c["rationale"]) <= inp["limits"]["max_rationale_chars"]
        and not _DIGIT_URL.search(c["rationale"])
        for c in concepts
    )
    res["A12"] = not finance or all(
        tpls[c["template_key"]]["direction_neutral"]
        and pics[c["subject_option_id"]]["direction_neutral"]
        and not pics[c["subject_option_id"]]["has_face"]
        for c in ok
    )
    retry = inp.get("retry_context")
    if inp["call_seq"] == 2 and retry:
        prev = {r["concept_id"]: r["previous"] for r in retry if r["guard_id"] is None}
        res["A14"] = all(
            (c["template_key"], c["subject_option_id"], c["text_ids"])
            == (prev[c["concept_id"]]["template_key"], prev[c["concept_id"]]["subject_option_id"], prev[c["concept_id"]]["text_ids"])
            for c in concepts if c["concept_id"] in prev
        )  # fmt: skip
    pc = inp.get("previous_concepts")
    if pc:
        old = {p["concept_id"]: p for p in pc}
        cur = {c["concept_id"]: c for c in concepts}
        res["A15"] = all(
            (cur[k]["template_key"], cur[k]["subject_option_id"], cur[k]["text_ids"], cur[k]["angle"], cur[k]["hypothesis_kind"])
            == (old[k]["template_key"], old[k]["subject_option_id"], old[k]["text_ids"], old[k]["angle"], old[k]["hypothesis_kind"])
            for k in exp["keep_concept_ids"]
        ) and all(
            _choices(cur[k]) != _choices({**old[k], "text_ids": old[k]["text_ids"]})
            for k in exp["changed_concept_ids"]
        )  # fmt: skip
    return res


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_baseline_satisfies_deterministic_assertions(case: dict[str, Any]) -> None:
    out = baseline_output(case["input"])
    StepOut.model_validate(out)  # C-03: the Pydantic model accepts it
    failed = [k for k, v in assertions(case, out).items() if not v]
    assert not failed, f"{case['case_id']}: {failed}"
    assert baseline_output(case["input"]) == out  # deterministic


def test_dataset_through_the_eval_runner_with_recorded_responses(tmp_path: Path) -> None:
    responses = {
        c["case_id"]: LlmResponse(baseline_output(c["input"]), 10, 20, 0, 0, "USD", 1)
        for c in CASES
    }
    records, summary = run_eval(
        ROOT,
        EVALS / "thumbnail_concepts",
        FakeAdapter(responses),
        {},
        tmp_path / "records.jsonl",
        prompt_path=PROMPT_PATH,
    )
    assert summary.total == 31
    assert summary.passed == 31
    assert summary.answer_key_total == 4
    assert summary.answer_key_passed == 4
    assert summary.ok
    assert len(records) == 31


def test_case_inputs_validate_against_the_step_input_schema() -> None:
    """C-07: every case input validates against the 7.3 JSON Schema (from the blueprint)."""
    doc = (ROOT / "docs/v4/agents/agent_11_thumbnail_design.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", doc, re.DOTALL)
    schema = next(
        json.loads(b) for b in blocks if "agent_11.thumbnail_variants.concepts.input:1.0.0" in b
    )
    validator = Draft202012Validator(schema)
    for case in CASES:
        errors = list(validator.iter_errors(case["input"]))
        assert not errors, (case["case_id"], errors[0].message[:200])
        StepIn.model_validate(case["input"])
