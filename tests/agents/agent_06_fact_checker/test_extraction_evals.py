"""Extraction eval pack (docs/v4/evals/.../claim_extraction) through amw_evals, recorded fixtures."""

# ruff: noqa: E501

import json
from pathlib import Path

import pytest

from amw_evals.runner import run_eval
from tests.agents.agent_06_fact_checker.eval_support import (
    EVALS,
    ExtractionStepAdapter,
    load_cases,
)

ROOT = Path(__file__).resolve().parents[3] / "docs" / "v4"
pytestmark = pytest.mark.unit


def test_all_35_cases_pass_through_the_real_step() -> None:
    cases = load_cases("claim_extraction")
    adapter = ExtractionStepAdapter(cases)
    records, summary = run_eval(ROOT, EVALS / "claim_extraction", adapter, {})
    failed = {str(r["case_id"]): r["assertions"] for r in records if not r["passed"]}
    assert failed == {}, json.dumps(failed, indent=1)
    assert summary.total == 35 == len(adapter.calls)
    assert (summary.answer_key_passed, summary.answer_key_total) == (4, 4)
    assert summary.ok, summary.failures


def test_no_false_allowed_on_a_blocked_case() -> None:
    cases = load_cases("claim_extraction")
    adapter = ExtractionStepAdapter(cases)
    records, _ = run_eval(ROOT, EVALS / "claim_extraction", adapter, {})
    for rec in records:
        expected = cases[str(rec["case_id"])]["expected"]["verdict"]
        got = rec["assertions"]["verdict"]["detail"]  # type: ignore[index]
        if expected == "BLOCKED":
            assert "got ALLOWED" not in got, rec["case_id"]
