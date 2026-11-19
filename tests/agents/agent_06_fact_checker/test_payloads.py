# ruff: noqa: PT018
"""Agent 06 payload registration: the registered models accept what the steps really emit."""

import pytest

from agent_06_fact_checker.models import (
    ExtractionInput,
    ExtractionOutput,
    VerificationInput,
    VerificationOutput,
)
from amw_core.enums import OutputStatus
from tests.agents.agent_06_fact_checker.eval_support import load_cases
from tests.agents.agent_06_fact_checker.recorded_extraction import recorded_response
from tests.agents.agent_06_fact_checker.support import (
    SCRIPT_SHA,
    RecordedLlm,
    World,
    extraction_step,
    run_context,
    task_input,
)
from tests.agents.agent_06_fact_checker.verification_harness import run_case
from tests.agents.payload_support import round_trip

pytestmark = pytest.mark.contract


def test_claim_extraction_input_and_output_round_trip() -> None:
    case = load_cases("claim_extraction")["AK-02"]
    world = World(llm=RecordedLlm([recorded_response(case)]))
    ti = task_input(
        "agent_06.claim_extraction.input", case["input"], version="1.1.0", script_sha=SCRIPT_SHA
    )
    assert isinstance(round_trip(ti.payload), ExtractionInput)
    out = extraction_step(world).run(ti, run_context())
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_06.claim_extraction.output"
    assert isinstance(round_trip(out.payload), ExtractionOutput)


def test_claim_verification_input_and_output_round_trip() -> None:
    run = run_case(load_cases("claim_verification")["POS-05"])
    ti = task_input("agent_06.claim_verification.input", run.case["input"])
    assert isinstance(round_trip(ti.payload), VerificationInput)
    assert run.output.status is OutputStatus.SUCCEEDED and run.output.payload is not None
    assert run.output.payload.payload_schema == "agent_06.claim_verification.output"
    assert isinstance(round_trip(run.output.payload), VerificationOutput)
