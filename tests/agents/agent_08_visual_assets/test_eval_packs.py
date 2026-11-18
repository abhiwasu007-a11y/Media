"""query_plan and candidate_rank packs through amw_evals with a replaying fake (no model)."""

import json
from pathlib import Path

import pytest

from amw_evals.adapter import FakeAdapter, LlmResponse
from amw_evals.runner import run_eval

ROOT = Path(__file__).resolve().parents[3]
PACKS = ROOT / "docs/v4/evals/agent_08_visual_assets"


@pytest.mark.integration
@pytest.mark.parametrize("pack", ["query_plan", "candidate_rank"])
def test_pack_runs_with_recorded_outputs(pack: str) -> None:
    cases = [json.loads(x) for x in (PACKS / pack / "cases.jsonl").read_text().splitlines() if x]
    adapter = FakeAdapter({c["case_id"]: LlmResponse(output=c["expected"]) for c in cases})
    records, summary = run_eval(ROOT / "docs/v4", PACKS / pack, adapter, {})
    assert len(records) == len(cases)
    assert summary.total == len(cases)
    # The datasets' `expected` is a case summary (e.g. `refusal_reason`), not a full model output
    # that validates against the prompt's output schema, so a replay of it cannot pass the schema
    # assertion. The pass rate is therefore NOT asserted: the model-in-the-loop run of these packs
    # is listed as an open item (README); the runner and the pack structure are exercised here.
    assert all("assertions" in r for r in records)
    assert summary.passed == 0 or summary.ok
