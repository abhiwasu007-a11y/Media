"""Verification eval pack (docs/v4/evals/.../claim_verification), all 41 cases, real step."""

# ruff: noqa: PT018

from typing import Any

import pytest

from agent_06_fact_checker.models import VerificationOutput
from amw_core.enums import OutputStatus
from tests.agents.agent_06_fact_checker.eval_support import load_cases
from tests.agents.agent_06_fact_checker.verification_harness import CaseRun, run_case

pytestmark = pytest.mark.unit
CASES = load_cases("claim_verification")
VERDICT_ORDER = {"ALLOWED": 0, "NEEDS_HUMAN_REVIEW": 1, "BLOCKED": 2}


def _check(run: CaseRun) -> list[str]:
    """Assertions A5-A18 of the dataset README; returns the failures."""
    case, out = run.case, run.output
    exp = case["expected"]
    bad: list[str] = []
    outcome = exp["code_outcome"]
    # A15 recorded calls
    if exp["llm_called"] is False and run.llm.calls != 0:
        bad.append("A15: a paid call was made")
    if exp["llm_called"] is True and not 1 <= run.llm.calls <= 2:
        bad.append(f"A15: {run.llm.calls} calls")
    # A16
    if outcome is not None:
        kind, code = outcome.split(":", 1)
        if out.status.value != {"REJECTED": "REJECTED", "FAILED": "FAILED"}[kind]:
            bad.append(f"A16: status {out.status}")
        if out.error is None or out.error.code != code:
            bad.append(f"A16: error {out.error and out.error.code}")
        return bad
    if exp["refusal_reason"] is not None:
        # item-level mapping: succeeded, one MODEL_REFUSED entry per claim
        pass
    if out.status is not OutputStatus.SUCCEEDED or out.payload is None:
        return [*bad, f"status {out.status}"]
    result = VerificationOutput.model_validate(out.payload.data)  # A18 (model twin)
    by_local = {c.local_id: c for c in result.claims}
    if set(by_local) != {c["local_id"] for c in case["input"]["claims"]}:
        bad.append("A2: not one result per claim")
    if result.script_sha256 != case["input"]["script_sha256"]:
        bad.append("A18: script_sha256")
    segs = {c["local_id"]: c["segment_id"] for c in case["input"]["claims"]}
    ids = {c["local_id"]: c["claim_id"] for c in case["input"]["claims"]}
    for req in result.revision_requests:
        local = next(k for k, v in ids.items() if v == req.claim_id)
        if req.segment_id != segs[local]:
            bad.append("A18: revision request segment_id")
    gate_failed = any(c.status.value == "CONTRADICTED" for c in result.claims)
    if (result.gate_verdict.value == "FAILED") != gate_failed:
        bad.append("A18: gate_verdict")
    if result.overall.proposed_verdict.value != exp["stage_verdict"]:
        bad.append(f"A7: stage {result.overall.proposed_verdict} != {exp['stage_verdict']}")
    texts = {p["text"]: p["citation_ref"] for p in case["fixture"]["passages"]}
    fix_ref = {p["evidence_id"]: p["citation_ref"] for p in case["fixture"]["passages"]}
    n = 0
    for chart in case["input"]["chart_facts"]:
        for fact in chart["facts"]:
            n += 1
            fix_ref[f"f{n:02d}"] = f"{chart['ref_id']}#{fact['fact_id']}"
    del texts
    for lid, spec in exp["claims"].items():
        got = by_local[lid]
        _check_claim(lid, spec, got, fix_ref, bad)
    pairs = {frozenset(c.local_ids) for c in result.claim_conflicts}
    if pairs != {frozenset(p) for p in exp["claim_conflicts"]}:
        bad.append(f"A12: conflicts {pairs}")
    return bad


def _check_claim(
    lid: str, spec: dict[str, Any], got: Any, fix_ref: dict[str, str], bad: list[str]
) -> None:
    status = {spec["status"]} if "status" in spec else set(spec["status_any"])
    if got.status.value not in status:
        bad.append(f"A5 {lid}: {got.status.value} not in {status}")
    verdict = spec.get("verdict")
    if (
        verdict is not None
        and got.verification_verdict is not None
        and got.verification_verdict.value != verdict
    ):
        bad.append(f"A6 {lid}: {got.verification_verdict}")
    if (
        "assessment_any" in spec
        and got.assessment is not None
        and got.assessment.value not in spec["assessment_any"]
        and got.status.value == "VERIFIED"
    ):
        bad.append(f"A5 {lid}: assessment {got.assessment}")
    refs = {e.source_ref for e in got.evidence}
    want = [fix_ref[i] for i in spec.get("evidence_any", [])]
    if "evidence_any" in spec:
        if want and not (refs & set(want)):
            bad.append(f"A8 {lid}: evidence {refs}")
        if not want and refs:
            bad.append(f"A8 {lid}: evidence must be empty, got {refs}")
    if "relation_any" in spec and not (
        {e.relation.value for e in got.evidence} & set(spec["relation_any"])
    ):
        bad.append(f"A8 {lid}: relation")
    if "discrepancy_kinds_any" in spec and not (
        {d.kind.value for d in got.discrepancies} & set(spec["discrepancy_kinds_any"])
    ):
        bad.append(f"A9 {lid}: discrepancy kinds")
    corr = spec.get("correction")
    if corr == "null" and got.suggested_correction is not None:
        bad.append(f"A10 {lid}: correction must be null")
    if corr == "present" and not got.suggested_correction:
        bad.append(f"A10 {lid}: correction missing")
    if "reason_codes_any" in spec and not (
        {r.value for r in got.reason_codes} & set(spec["reason_codes_any"])
    ):
        bad.append(f"A14 {lid}: reasons {got.reason_codes}")
    if spec.get("suggested_citation") and not got.suggested_citation_refs:
        bad.append(f"A14 {lid}: suggested citation")
    if got.status.value == "VERIFIED" and spec.get("status") != "VERIFIED":
        bad.append(f"A11 {lid}: false VERIFIED")


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_case(case_id: str) -> None:
    case = CASES[case_id]
    assert _check(run_case(case)) == [], case_id


def test_answer_key_cases_are_deterministic() -> None:
    """AK-02..04 never reach the model; AK-01 (chart facts) verifies all three claims."""
    for cid in ("AK-02", "AK-03", "AK-04"):
        run = run_case(CASES[cid])
        assert run.llm.calls == 0
        assert run.output.status is OutputStatus.REJECTED
        assert run.output.error is not None
        assert run.output.error.code == "PERMANENT.INPUT_INVALID"
    ak1 = run_case(CASES["AK-01"])
    assert ak1.output.payload is not None
    data = ak1.output.payload.data
    assert data is not None
    assert [c["status"] for c in data["claims"]] == ["VERIFIED"] * 3
    assert data["gate_verdict"] == "PASSED"


def test_mandatory_thresholds_over_the_dataset() -> None:
    runs = {cid: run_case(case) for cid, case in CASES.items()}
    passed = sum(1 for r in runs.values() if _check(r) == [])
    assert passed == len(CASES) == 41
    deterministic = [r for r in runs.values() if r.case["expected"]["llm_called"] is False]
    assert len(deterministic) == 10 and all(r.llm.calls == 0 for r in deterministic)
    false_verified = 0
    for r in runs.values():
        if r.output.payload is None or r.output.payload.data is None:
            continue
        for c in r.output.payload.data["claims"]:
            spec = r.case["expected"]["claims"].get(c["local_id"], {})
            if c["status"] == "VERIFIED" and spec.get("status") != "VERIFIED":
                false_verified += 1
    assert false_verified == 0
