"""Run the eval datasets through ``amw_evals`` with the real step and recorded model responses."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_06_fact_checker.models import ChartFacts
from amw_core.enums import OutputStatus
from amw_evals.adapter import LlmRequest as EvalRequest
from amw_evals.adapter import LlmResponse as EvalResponse
from tests.agents.agent_06_fact_checker.recorded_extraction import recorded_response
from tests.agents.agent_06_fact_checker.support import (
    SCRIPT_SHA,
    RecordedLlm,
    World,
    extraction_step,
    ranges_for,
    run_context,
    task_input,
)

EVALS = Path(__file__).resolve().parents[3] / "docs" / "v4" / "evals" / "agent_06_fact_checker"


def load_cases(task: str) -> dict[str, dict[str, Any]]:
    path = EVALS / task / "cases.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {r["case_id"]: r for r in rows}


class ExtractionStepAdapter:
    """``amw_evals`` adapter: the 'model' is the recorded response, the step is the real one."""

    provider = "fake_llm"
    model = "recorded"
    is_fake = True

    def __init__(self, cases: Mapping[str, dict[str, Any]]) -> None:
        self.cases = cases
        self.calls: list[str] = []

    def complete(self, request: EvalRequest) -> EvalResponse:
        case = self.cases[request.case_id]
        self.calls.append(request.case_id)
        world = World(llm=RecordedLlm([recorded_response(case)]))
        step = extraction_step(world, chart_ranges=ranges_for(case["input"]))
        task = task_input(
            "agent_06.claim_extraction.input",
            case["input"],
            version="1.1.0",
            script_sha=SCRIPT_SHA,
        )
        out = step.run(task, run_context())
        if out.status is OutputStatus.SUCCEEDED and out.payload is not None:
            return EvalResponse(out.payload.data, 100, 50, 0, 300, "USD", 5)
        assert out.error is not None
        refusal = (out.error.details.model_extra or {}).get("refusal")
        shaped: dict[str, Any] = {
            "claims": [],
            "overall": {
                "proposed_verdict": "NEEDS_HUMAN_REVIEW",
                "blocking_rule_ids": [],
                "needs_human_review_reasons": [out.error.code],
            },
            "refusal": refusal,
        }
        return EvalResponse(shaped, 100, 50, 0, 300, "USD", 5)


__all__ = ["ChartFacts"]
