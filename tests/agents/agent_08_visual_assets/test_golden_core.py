"""All 184 cases of evals/agent_08_visual_assets/deterministic_core run as unit tests (R-03)."""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.agents.agent_08_visual_assets import golden

CASES = (
    Path(__file__).resolve().parents[3]
    / "docs/v4/evals/agent_08_visual_assets/deterministic_core/cases.jsonl"
)
ALL = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]


def test_dataset_is_complete() -> None:
    assert len(ALL) == 184


@pytest.mark.unit
@pytest.mark.parametrize("case", ALL, ids=[c["case_id"] for c in ALL])
def test_case(case: dict[str, Any]) -> None:
    golden._expected_hint.clear()
    if case["function"] == "ChartFactsBuilder.build" and case["expected"].get("emit_document"):
        golden._expected_hint.add("emit_document")
    got = golden.run_case(case["function"], case["input"])
    assert got == case["expected"], case["case_id"]
