"""Failure injection, prompt registry, blob payloads and self-checks."""

# ruff: noqa: PT018

import io
import json
from typing import Any

import pytest

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.hashing import sha256_hex
from agent_06_fact_checker.models import ClaimMode, VerifiedClaim
from agent_06_fact_checker.prompts import FilePromptSource
from agent_06_fact_checker.reconcile import Outcome
from agent_06_fact_checker.verification_step import _verified_violations
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import ClaimStatus, OutputStatus
from amw_core.errors import ConfigInvalidError, RateLimitedError
from tests.agents.agent_06_fact_checker.eval_support import load_cases
from tests.agents.agent_06_fact_checker.recorded_extraction import recorded_response
from tests.agents.agent_06_fact_checker.support import (
    ORG,
    PROMPTS,
    SCRIPT_SHA,
    MemoryBlobs,
    RecordedLlm,
    World,
    extraction_step,
    make_settings,
    run_context,
    task_input,
)
from tests.agents.agent_06_fact_checker.test_verification_step import claim as v_claim_doc

CASES = load_cases("claim_extraction")
SCHEMA = "agent_06.claim_extraction.input"
pytestmark = pytest.mark.failure_injection


class FailingLlm(RecordedLlm):
    def complete(self, request: Any, *, idempotency_key: str) -> Any:
        raise RateLimitedError("slow down", retry_after_ms=1000)


def test_f05_transient_provider_error_propagates_to_the_worker_and_pays_nothing() -> None:
    case = CASES["AK-03"]
    world = World(llm=FailingLlm([]))
    task = task_input(SCHEMA, case["input"], version="1.1.0", script_sha=SCRIPT_SHA)
    with pytest.raises(RateLimitedError):
        extraction_step(world).run(task, run_context())
    assert world.ledger.rows == [] and world.claims.rows == {}


def test_f06_resume_after_a_crash_between_batches_skips_the_paid_batch() -> None:
    case = CASES["MIX-30"]
    full = json.loads(recorded_response(case))
    one = {"claims": [full["claims"][0]], "overall": full["overall"], "refusal": None}
    two = {
        "claims": [dict(full["claims"][1], local_id="c1")],
        "overall": full["overall"],
        "refusal": None,
    }
    world = World(llm=RecordedLlm([json.dumps(one)]))  # the second call crashes (no response left)
    settings = make_settings(extract_max_chars_per_call=60)
    task = task_input(SCHEMA, case["input"], version="1.1.0", script_sha=SCRIPT_SHA)
    with pytest.raises(IndexError):
        extraction_step(world, settings=settings).run(task, run_context())
    assert world.llm.calls == 2 and len(world.ledger.rows) == 1
    world.llm.texts.append(json.dumps(two))
    out = extraction_step(world, settings=settings).run(task, run_context())
    assert out.status is OutputStatus.SUCCEEDED
    assert world.llm.calls == 3  # only the missing batch was paid for again
    assert len(world.ledger.rows) == 2


def test_failure_outputs_are_valid_task_outputs() -> None:
    case = CASES["AK-03"]
    task = task_input(SCHEMA, case["input"], version="1.1.0")  # no script blob ref
    rejected = extraction_step(World(llm=RecordedLlm([]))).run(task, run_context())
    suspended_world = World(llm=RecordedLlm([recorded_response(case)]))
    suspended_world.budget.refuse = True
    ok_task = task_input(SCHEMA, case["input"], version="1.1.0", script_sha=SCRIPT_SHA)
    suspended = extraction_step(suspended_world).run(ok_task, run_context())
    failed = extraction_step(World(llm=RecordedLlm(["x", "y"]))).run(ok_task, run_context())
    assert [o.status for o in (rejected, suspended, failed)] == [
        OutputStatus.REJECTED,
        OutputStatus.SUSPENDED,
        OutputStatus.FAILED,
    ]
    for out in (rejected, suspended, failed):
        validate_task_output(out.to_doc(), version="1.0.0")
        assert out.error is not None and out.payload is None and out.output_refs == ()


def test_payload_by_reference_is_read_with_its_hash() -> None:
    case = CASES["AK-03"]
    world = World(llm=RecordedLlm([recorded_response(case)]))
    body = json.dumps(case["input"]).encode()
    uri = f"amw-blob://{ORG}/jobs/in/payload.json"
    world.blobs.put(None, uri, io.BytesIO(body))  # type: ignore[arg-type]
    doc = task_input(SCHEMA, {}, version="1.1.0", script_sha=SCRIPT_SHA).model_dump(mode="json")
    doc["payload"] = {
        "payload_schema": SCHEMA,
        "payload_schema_version": "1.1.0",
        "data_ref": uri,
        "data_sha256": sha256_hex(body),
    }
    from amw_core.contracts.task_input import TaskInput

    out = extraction_step(world).run(TaskInput.model_validate(doc), run_context())
    assert out.status is OutputStatus.SUCCEEDED
    bad = TaskInput.model_validate({**doc, "payload": {**doc["payload"], "data_sha256": "00" * 32}})
    failed = extraction_step(World(llm=RecordedLlm([]), blobs=world.blobs)).run(bad, run_context())
    assert failed.error is not None and failed.error.code == "AGENT.CORRUPTED_OUTPUT"


def test_prompt_registry_checks_the_file_hash() -> None:
    raw = (PROMPTS / "claim_extraction.v1.md").read_bytes()
    good = FilePromptSource(PROMPTS.parent, {"agent_06/claim_extraction.v1": sha256_hex(raw)})
    assert good.load("agent_06/claim_extraction.v1").sha256 == sha256_hex(raw)
    stale = FilePromptSource(PROMPTS.parent, {"agent_06/claim_extraction.v1": "00" * 32})
    with pytest.raises(ConfigInvalidError, match="registry"):
        stale.load("agent_06/claim_extraction.v1")
    with pytest.raises(ConfigInvalidError, match="unknown"):
        good.load("agent_06/nope.v1")
    with pytest.raises(ConfigInvalidError, match="unknown"):
        good.load("agent_05/claim_extraction.v1")


def test_verified_self_check_catches_a_status_that_lost_its_preconditions() -> None:
    from agent_06_fact_checker.models import VerificationClaim

    claim = VerificationClaim.model_validate(v_claim_doc(1))
    settings: FactCheckSettings = make_settings()

    def verified(**over: Any) -> tuple[VerifiedClaim, Outcome]:
        base: dict[str, Any] = {
            "claim_id": claim.claim_id,
            "local_id": "c1",
            "mode": "EVIDENCE",
            "status": "VERIFIED",
            "reason_codes": [],
            "verification_verdict": "ALLOWED",
            "combined_verdict": "ALLOWED",
            "assessment": "SUPPORTED",
            "certainty": "HIGH",
            "script_cited": True,
            "evidence": [
                {
                    "source_kind": "KNOWLEDGE_CHUNK",
                    "source_ref": "kch_a",
                    "relation": "SUPPORTS",
                    "char_start": 0,
                    "char_end": 5,
                    "content_sha256": "a" * 64,
                }
            ],
            "discrepancies": [],
            "suggested_correction": None,
            "suggested_citation_refs": [],
        }
        base.update(over)
        out = Outcome(claim, ClaimMode(base["mode"]), ClaimStatus.VERIFIED)
        out.support_texts = ["a 2:1 ratio needs a 33% win rate"]
        out.support_tiers = ["B_PUBLISHED"]
        return VerifiedClaim.model_validate(base), out

    def violations(**over: Any) -> dict[str, str]:
        v, o = verified(**over)
        return _verified_violations([v], {"c1": o}, settings)

    assert violations() == {}
    assert violations(evidence=[]) == {"c1": "evidence"}
    assert violations(script_cited=False) == {"c1": "tier_or_citation"}
    v, o = verified()
    o.support_texts = ["no numbers here"]
    assert _verified_violations([v], {"c1": o}, settings) == {"c1": "number"}
    v, o = verified()
    o.support_tiers = ["D_UNVERIFIED"]
    assert _verified_violations([v], {"c1": o}, settings) == {"c1": "tier_or_citation"}
    v, o = verified(mode="CHART_FACTS", script_cited=False)
    o.mode = ClaimMode.CHART_FACTS
    assert _verified_violations([v], {"c1": o}, settings) == {"c1": "chart"}


def test_memory_blobs_are_write_once_for_the_fakes_used_here() -> None:
    blobs = MemoryBlobs()
    uri = f"amw-blob://{ORG}/jobs/x"
    blobs.put(None, uri, io.BytesIO(b"a"))  # type: ignore[arg-type]
    with pytest.raises(Exception, match="write-once"):
        blobs.put(None, uri, io.BytesIO(b"a"))  # type: ignore[arg-type]
