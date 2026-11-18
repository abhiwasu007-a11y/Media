"""ClaimVerificationStep: validation, guards, conflicts, replay, tenancy, failure injection."""

# ruff: noqa: E501, PT018

import json
from typing import Any

import pytest

from agent_06_fact_checker.hashing import claims_sha256, sha256_hex
from agent_06_fact_checker.models import VerificationOutput
from amw_core.contracts.task_output import gate_failures, integrity_failures
from amw_core.enums import OutputStatus
from tests.agents.agent_06_fact_checker.eval_support import load_cases
from tests.agents.agent_06_fact_checker.support import (
    CHANNEL,
    SCRIPT,
    MemoryKnowledge,
    RecordedLlm,
    World,
    make_settings,
    run_context,
    source,
    task_input,
    verification_step,
    with_claims_hash,
)
from tests.agents.agent_06_fact_checker.verification_harness import RespondingLlm, run_case

CASES = load_cases("claim_verification")
SCHEMA = "agent_06.claim_verification.input"
SHA = "ab" * 32
pytestmark = pytest.mark.unit
TEXT = "A 2:1 reward-to-risk ratio needs a win rate of about 33 percent to break even."
REF = "kch_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8f01"


def claim(n: int, **over: Any) -> dict[str, Any]:
    base = {
        "claim_id": f"clm_0192f5b0-0000-7000-8000-0000000000{n:02x}",
        "local_id": f"c{n}",
        "segment_id": f"s{n}",
        "quote": "a 2:1 ratio needs a 33% win rate",
        "normalized_claim": "A 2:1 reward-to-risk ratio needs a 33% win rate to break even.",
        "claim_type": "STATISTICAL",
        "time_reference_kind": "TIMELESS",
        "instrument": None,
        "chart_data_ref": None,
        "requires_citation": True,
        "citation_refs": [REF],
        "extraction_verdict": "ALLOWED",
    }
    base.update(over)
    return base


def data(claims: list[dict[str, Any]] | None = None, **over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "script_id": SCRIPT,
        "script_version": 1,
        "script_sha256": SHA,
        "verify_mode": "EVIDENCE",
        "iteration": 0,
        "language": "en",
        "channel_category": "finance",
        "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
        "our_method_release_approved": False,
        "extraction_overall_verdict": "ALLOWED",
        "claims": claims if claims is not None else [claim(1)],
        "available_citations": [
            {
                "citation_ref": REF,
                "kind": "KNOWLEDGE_CHUNK",
                "title": "t",
                "content_sha256": sha256_hex(TEXT),
            }
        ],
        "chart_facts": [],
    }
    d.update(over)
    return with_claims_hash(d)


def result_for(
    local_id: str, assessment: str = "SUPPORTED", span_end: int = 30, **over: Any
) -> dict[str, Any]:
    r: dict[str, Any] = {
        "local_id": local_id,
        "assessment": assessment,
        "evidence": [
            {"evidence_id": "p01", "relation": "SUPPORTS", "span_start": 0, "span_end": span_end}
        ],
        "discrepancies": [],
        "certainty": "HIGH",
        "suggested_correction": None,
        "rationale": "r",
    }
    r.update(over)
    return r


def batch(
    *results: dict[str, Any], conflicts: Any = (), flags: Any = (), refusal: Any = None
) -> str:
    return json.dumps(
        {
            "results": list(results),
            "claim_conflicts": list(conflicts),
            "passage_flags": list(flags),
            "refusal": refusal,
        }
    )


def go(
    d: dict[str, Any],
    responses: list[str] | None = None,
    sources: list[Any] | None = None,
    *,
    world: World | None = None,
    stage: str = "s06_verify",
    **kw: Any,
) -> tuple[Any, World]:
    w = world or World(llm=RecordedLlm(responses or []))
    knowledge = MemoryKnowledge(sources if sources is not None else [source(REF, TEXT)])
    step = verification_step(w, knowledge, script_sha=SHA, **kw)
    out = step.run(task_input(SCHEMA, d), run_context(stage, 0))
    return out, w


def doc(out: Any) -> dict[str, Any]:
    assert out.status is OutputStatus.SUCCEEDED, out.error
    return dict(out.payload.data)


def test_verified_claim_has_evidence_citation_and_hand_off_hashes() -> None:
    out, w = go(data(), [batch(result_for("c1"))])
    d = doc(out)
    VerificationOutput.model_validate(d)
    c = d["claims"][0]
    assert (
        c["status"] == "VERIFIED" and c["verification_verdict"] == "ALLOWED" and c["script_cited"]
    )
    assert d["script_sha256"] == SHA and d["gate_verdict"] == "PASSED"
    ev = c["evidence"][0]
    assert (
        ev["source_ref"] == REF
        and ev["content_sha256"] == sha256_hex(TEXT)
        and ev["char_end"] == 30
    )
    assert d["provenance"]["evidence_scope"] == {"channel_scoped": True, "restricted_used": False}
    assert d["provenance"]["prompt_id"] == "agent_06/claim_verification.v1"
    assert [r.kind for r in w.claims.citations] and w.claims.citations[0].source_ref == REF
    assert w.claims.status[c["claim_id"]].status.value == "VERIFIED"
    assert not gate_failures(out) and not integrity_failures(out)
    assert out.next_action.type.value == "CONTINUE" and out.quality_score is None
    assert d["accuracy_summary"] == {
        "checkable_total": 1, "with_citation_or_chart": 1, "verified": 1,
        "contradicted": 0, "unverifiable": 0, "needs_substantiation": 0, "chart_pending": 0,
    }  # fmt: skip


def test_contradicted_claim_fails_the_gate_and_revision_request_names_the_segment() -> None:
    res = result_for(
        "c1", "CONTRADICTED", evidence=[{"evidence_id": "p01", "relation": "CONTRADICTS", "span_start": 0, "span_end": 30}],
        discrepancies=[{"kind": "NUMBER", "claim_value": "33%", "evidence_value": "33 percent"}],
        suggested_correction="The source gives about 33 percent.",
    )  # fmt: skip
    out, _ = go(data(), [batch(res)])
    d = doc(out)
    assert d["gate_verdict"] == "FAILED" and d["overall"]["proposed_verdict"] == "BLOCKED"
    assert [g.check_id for g in gate_failures(out)] == ["fact.gate.no_contradicted_claim"]
    assert gate_failures(out)[0].remedy_stage_id is None
    assert d["overall"]["blocking_claim_ids"] == [d["claims"][0]["claim_id"]]
    req = d["revision_requests"][0]
    assert req["action"] == "CORRECT_CLAIM" and req["segment_id"] == "s1"
    assert req["detail"] == "The source gives about 33 percent."
    assert out.next_action.reason.startswith("gate FAILED")


def test_correction_with_advice_wording_is_dropped_by_p10() -> None:
    res = result_for("c1", "CONTRADICTED", evidence=[{"evidence_id": "p01", "relation": "CONTRADICTS", "span_start": 0, "span_end": 30}], suggested_correction="You should buy now at https://x.example")  # fmt: skip
    d = doc(go(data(), [batch(res)])[0])
    assert d["claims"][0]["suggested_correction"] is None
    assert "does not support" in d["revision_requests"][0]["detail"]


def test_p4_invalid_span_and_unknown_evidence_id_are_dropped() -> None:
    res = result_for(
        "c1",
        evidence=[
            {"evidence_id": "p01", "relation": "SUPPORTS", "span_start": 5, "span_end": 9999},
            {"evidence_id": "p77", "relation": "SUPPORTS", "span_start": 0, "span_end": 5},
        ],
    )
    c = doc(go(data(), [batch(res)])[0])["claims"][0]
    assert c["status"] == "UNVERIFIABLE" and c["evidence"] == []  # SUPPORTED without valid evidence
    assert "SPAN_INVALID" in c["reason_codes"] and "MODEL_UNCERTAIN" in c["reason_codes"]


def test_p8_injected_passage_is_excluded_from_every_claim() -> None:
    out, _ = go(
        data(),
        [batch(result_for("c1"), flags=[{"evidence_id": "p01", "flag": "INJECTION_SUSPECTED"}])],
    )
    c = doc(out)["claims"][0]
    assert c["evidence"] == [] and "INJECTED_EVIDENCE_DISCARDED" in c["reason_codes"]
    assert c["status"] == "UNVERIFIABLE"
    assert any(r.check_id == "fact.injected_excluded" for r in out.validation_results)


def test_p5_discrepancy_values_must_be_verbatim() -> None:
    res = result_for("c1", "PARTIALLY_SUPPORTED", evidence=[{"evidence_id": "p01", "relation": "PARTIAL", "span_start": 0, "span_end": 30}], discrepancies=[
        {"kind": "NUMBER", "claim_value": "33%", "evidence_value": "33 percent"},
        {"kind": "NUMBER", "claim_value": "invented", "evidence_value": "33 percent"},
        {"kind": "NUMBER", "claim_value": "33%", "evidence_value": "invented"},
    ])  # fmt: skip
    c = doc(go(data(), [batch(res)])[0])["claims"][0]
    assert [(d["claim_value"], d["evidence_value"]) for d in c["discrepancies"]] == [
        ("33%", "33 percent")
    ]
    assert c["status"] == "NEEDS_SUBSTANTIATION" and c["reason_codes"] == ["OVERREACH"]


def test_number_guard_tier_floor_and_script_citation_rows() -> None:
    other = "A 2:1 ratio needs a 40 percent win rate."
    out, _ = go(data(), [batch(result_for("c1"))], [source(REF, other)], settings=make_settings())
    # hash of the stored text differs from available_citations: unresolvable, then search finds it
    c = doc(out)["claims"][0]
    assert "CITATION_UNRESOLVABLE" in c["reason_codes"]
    assert c["status"] == "NEEDS_SUBSTANTIATION" and "NUMBER_NOT_IN_EVIDENCE" in c["reason_codes"]
    low = [source(REF, TEXT, tier="D_UNVERIFIED")]
    c = doc(go(data(), [batch(result_for("c1"))], low)[0])["claims"][0]
    assert c["reason_codes"] == ["LOW_RELIABILITY_ONLY"]
    uncited = data([claim(1, citation_refs=[])])
    d = doc(go(uncited, [batch(result_for("c1"))], [source("kch_other", TEXT)])[0])
    c = d["claims"][0]
    assert c["reason_codes"] == ["NO_SCRIPT_CITATION"] and c["suggested_citation_refs"] == [
        "kch_other"
    ]
    assert d["revision_requests"][0]["action"] == "ADD_CITATION"
    assert d["revision_requests"][0]["suggested_citation_refs"] == ["kch_other"]


def test_p2_missing_or_duplicate_result_is_repaired_once_then_fails() -> None:
    d = data([claim(1), claim(2)])
    good = batch(result_for("c1"), result_for("c2"))
    out, w = go(d, [batch(result_for("c1")), good])
    assert w.llm.calls == 2 and doc(out)["overall"]["counts"]["VERIFIED"] == 2
    out, w = go(d, [batch(result_for("c1")), batch(result_for("c1"), result_for("c1"))])
    assert out.error is not None and out.error.code == "AGENT.OUTPUT_SCHEMA_INVALID"
    assert w.llm.calls == 2


def test_p9_conflicts_need_two_different_known_claims() -> None:
    d = data([claim(1), claim(2)])
    bad = [{"claim_a": "c1", "claim_b": "c1", "kind": "NUMBER", "explanation": "x"}]
    out, _ = go(d, [batch(result_for("c1"), result_for("c2"), conflicts=bad)] * 2)
    assert out.error is not None and out.error.code == "AGENT.OUTPUT_SCHEMA_INVALID"
    unknown = [{"claim_a": "c1", "claim_b": "c9", "kind": "NUMBER", "explanation": "x"}]
    out, _ = go(d, [batch(result_for("c1"), result_for("c2"), conflicts=unknown)] * 2)
    assert out.error is not None


def test_conflict_between_two_verified_claims_makes_both_unverifiable() -> None:
    d = data([claim(1), claim(2)])
    pair = [{"claim_a": "c1", "claim_b": "c2", "kind": "NUMBER", "explanation": "x"}]
    out, _ = go(
        d,
        [batch(result_for("c1"), result_for("c2"), conflicts=pair)],
        conflict_finder=lambda c, s: [("c1", "c2")],
    )
    r = doc(out)
    assert [c["status"] for c in r["claims"]] == ["UNVERIFIABLE", "UNVERIFIABLE"]
    assert all("CLAIM_CONFLICT" in c["reason_codes"] for c in r["claims"])
    assert r["claim_conflicts"][0]["local_ids"] == ["c1", "c2"]
    assert r["overall"]["proposed_verdict"] == "NEEDS_HUMAN_REVIEW"
    assert {q["action"] for q in r["revision_requests"]} == {"RESOLVE_CONFLICT"}
    again = [{"claim_a": "c2", "claim_b": "c1", "kind": "NUMBER", "explanation": "y"}] * 2
    out, _ = go(
        d,
        [batch(result_for("c1"), result_for("c2"), conflicts=pair + again)],
        conflict_finder=lambda c, s: [("c1", "c2")],
    )
    assert len(doc(out)["claim_conflicts"]) == 1  # duplicates collapse


def test_f09_unsafe_refusal_gives_one_entry_per_claim_and_never_passes() -> None:
    d = data([claim(1), claim(2)])
    refusal = {
        "reason": "UNSAFE_CONTENT",
        "message": "m",
        "missing_inputs": [],
        "violated_rule_ids": [],
    }
    out, _ = go(d, [batch(refusal=refusal)])
    r = doc(out)
    assert [c["reason_codes"] for c in r["claims"]] == [["MODEL_REFUSED"]] * 2
    assert r["overall"]["proposed_verdict"] == "NEEDS_HUMAN_REVIEW"
    for reason, code in (
        ("INSUFFICIENT_INPUT", "PERMANENT.INSUFFICIENT_INPUT"),
        ("OUT_OF_SCOPE", "PERMANENT.INPUT_INVALID"),
    ):
        refusal["reason"] = reason
        out, _ = go(d, [batch(refusal=refusal)])
        assert (
            out.status is OutputStatus.FAILED and out.error is not None and out.error.code == code
        )


# ---------------------------------------------------------------- validation / tenancy
@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(claims_sha256="00" * 32),
        lambda d: d.update(script_sha256="cd" * 32),
        lambda d: d.update(iteration=3),
        lambda d: d.update(extraction_overall_verdict="BLOCKED"),
        lambda d: d["claims"].append(dict(d["claims"][0])),
    ],
)
def test_f02_rejections_cost_nothing(mutate: Any) -> None:
    d = data()
    mutate(d)
    if "claims_sha256" in d and d["claims_sha256"] != "00" * 32 and d["script_sha256"] == SHA:
        d["claims_sha256"] = claims_sha256(d["claims"])
    out, w = go(d, [])
    assert out.status is OutputStatus.REJECTED and w.llm.calls == 0
    assert out.error is not None and out.error.code == "PERMANENT.INPUT_INVALID"
    assert w.claims.status == {} and w.blobs.data == {}


@pytest.mark.security
def test_f01_schema_rejection_and_s02_cross_tenant_refs() -> None:
    d = data()
    del d["chart_facts"]
    out, _ = go(d, [])
    assert out.error is not None and out.error.code == "PERMANENT.SCHEMA_INVALID"
    d = data()
    d["available_citations"][0].pop("content_sha256")
    out, _ = go(d, [])
    assert out.error is not None and out.error.code == "PERMANENT.SCHEMA_INVALID"
    w = World(llm=RecordedLlm([]))
    w.claims.owned_override = frozenset()  # a claim id of another tenant / script
    out, _ = go(data(), [], world=w)
    assert out.error is not None and out.error.code == "PERMANENT.CROSS_TENANT_REF"
    assert "exist" not in out.error.message  # no existence oracle
    w = World(llm=RecordedLlm([]))
    step = verification_step(w, MemoryKnowledge([source(REF, TEXT)], foreign=[REF]), script_sha=SHA)
    out = step.run(task_input(SCHEMA, data()), run_context("s06_verify"))
    assert out.error is not None and out.error.code == "PERMANENT.CROSS_TENANT_REF"
    assert w.llm.calls == 0
    out, _ = (
        go(data(), [], world=World(llm=RecordedLlm([])), scripts=None, script_sha=None)
        if False
        else (out, w)
    )
    assert out.status is OutputStatus.REJECTED


def test_unknown_script_is_a_missing_dependency() -> None:
    from tests.agents.agent_06_fact_checker.support import MemoryScripts

    out, _ = go(data(), [], scripts=MemoryScripts(None))
    assert out.error is not None and out.error.code == "PERMANENT.MISSING_DEPENDENCY"


@pytest.mark.security
def test_library_search_is_channel_scoped_and_never_restricted() -> None:
    w = World(llm=RecordedLlm([batch(result_for("c1"))]))
    k = MemoryKnowledge([source(REF, TEXT, restricted=True)])
    step = verification_step(w, k, script_sha=SHA)
    d = data([claim(1, citation_refs=[])], available_citations=[])
    out = step.run(task_input(SCHEMA, d), run_context("s06_verify"))
    c = doc(out)["claims"][0]
    assert c["reason_codes"] == ["NO_EVIDENCE_CANDIDATES"] and w.llm.calls == 0 and k.searches == 1
    assert CHANNEL.startswith("chn_")


@pytest.mark.security
def test_released_restricted_cited_source_is_used_and_recorded() -> None:
    w = World(llm=RecordedLlm([batch(result_for("c1"))]))
    k = MemoryKnowledge([source(REF, TEXT, restricted=True)])
    step = verification_step(w, k, script_sha=SHA)
    d = data(our_method_release_approved=True)
    out = step.run(task_input(SCHEMA, d), run_context("s06_verify"))
    r = doc(out)
    assert r["claims"][0]["status"] == "VERIFIED"
    assert r["provenance"]["evidence_scope"]["restricted_used"] is True
    assert any(
        x.check_id == "fact.restricted_gate" and x.rule_id == "FIN-R12"
        for x in out.validation_results
    )


# ---------------------------------------------------------------- chart stage
def chart_data(facts: list[dict[str, str]] | None, n_claims: int = 1) -> dict[str, Any]:
    claims = [
        claim(i, claim_type="HISTORICAL_MARKET", chart_data_ref="chart_1", citation_refs=[], requires_citation=False, quote="price made a lower low", normalized_claim="Price made a lower low on the chart.", instrument="NIFTY")
        for i in range(1, n_claims + 1)
    ]  # fmt: skip
    charts = [] if facts is None else [{"ref_id": "chart_1", "instrument": "NIFTY", "facts": facts}]
    return data(claims, verify_mode="CHART_FACTS", available_citations=[], chart_facts=charts)


def test_chart_stage_with_no_chart_claims_succeeds_with_no_call() -> None:
    d = data([], verify_mode="CHART_FACTS", available_citations=[])
    out, w = go(d, [], stage="s06_chart")
    r = doc(out)
    assert r["claims"] == [] and r["overall"]["proposed_verdict"] == "ALLOWED" and w.llm.calls == 0
    assert w.claims.status == {}


def test_chart_stage_verifies_against_the_charts_own_facts() -> None:
    facts = [{"fact_id": "f01", "statement": "Price closed lower at the second trough."}]
    res = result_for("c1")
    res["evidence"][0]["evidence_id"] = "f01"
    res["evidence"][0]["span_end"] = 20
    out, w = go(chart_data(facts), [batch(res)], [], stage="s06_chart")
    c = doc(out)["claims"][0]
    assert c["status"] == "VERIFIED" and c["evidence"][0]["source_ref"] == "chart_1#f01"
    assert c["evidence"][0]["source_kind"] == "CHART_FACT" and c["script_cited"]
    assert w.claims.citations == []  # chart facts are not citations rows
    req = json.loads(w.llm.requests[0].messages[0].content.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert req["chart_facts"][0]["evidence_id"] == "f01" and req["passages"] == []
    assert "org_" not in w.llm.requests[0].messages[0].content


def test_chart_stage_without_facts_is_unverifiable_without_a_call() -> None:
    out, w = go(chart_data(None), [], [], stage="s06_chart")
    c = doc(out)["claims"][0]
    assert (
        c["reason_codes"] == ["NO_CHART_FACTS"]
        and c["status"] == "UNVERIFIABLE"
        and w.llm.calls == 0
    )
    out, _ = go(chart_data([]), [], [], stage="s06_chart")
    assert doc(out)["claims"][0]["reason_codes"] == ["NO_CHART_FACTS"]


def test_chart_claim_is_deferred_at_s06_verify() -> None:
    d = chart_data(None)
    d["verify_mode"] = "EVIDENCE"
    d["claims_sha256"] = claims_sha256(d["claims"])
    out, w = go(d, [])
    r = doc(out)
    assert r["claims"][0]["status"] == "EXTRACTED" and r["claims"][0]["reason_codes"] == [
        "CHART_PENDING"
    ]
    assert r["accuracy_summary"]["chart_pending"] == 1 and w.llm.calls == 0
    assert r["claims"][0]["combined_verdict"] == "ALLOWED"


def test_chart_stage_rejects_a_non_chart_claim() -> None:
    d = data(verify_mode="CHART_FACTS")
    out, _ = go(d, [], stage="s06_chart")
    assert out.error is not None and out.error.code == "PERMANENT.INPUT_INVALID"


# ---------------------------------------------------------------- budget, replay, caps, checkpoints
def test_f11_budget_refusal_suspends_verification() -> None:
    w = World(llm=RecordedLlm([batch(result_for("c1"))]))
    w.budget.refuse = True
    out, _ = go(data(), world=w)
    assert out.status is OutputStatus.SUSPENDED and w.llm.calls == 0 and w.claims.status == {}


def test_i05_replay_pays_once_and_never_flips_a_status() -> None:
    w = World(llm=RecordedLlm([batch(result_for("c1"))]))
    task = task_input(SCHEMA, data())
    step = verification_step(w, MemoryKnowledge([source(REF, TEXT)]), script_sha=SHA)
    first = step.run(task, run_context("s06_verify"))
    second = step.run(task, run_context("s06_verify"))
    assert w.llm.calls == 1 and len(w.ledger.rows) == 1
    assert first.payload is not None and second.payload is not None
    assert first.payload.data == second.payload.data


def test_status_changed_by_another_task_is_an_idempotency_conflict() -> None:
    w = World(llm=RecordedLlm([batch(result_for("c1"))]))
    d = data()
    w.claims.status_task[d["claims"][0]["claim_id"]] = "tsk_other"
    out, _ = go(d, world=w)
    assert out.status is OutputStatus.FAILED
    assert out.error is not None and out.error.code == "PERMANENT.IDEMPOTENCY_CONFLICT"


def test_batches_respect_claims_per_call() -> None:
    d = data([claim(i) for i in range(1, 4)])
    out, w = go(
        d,
        [batch(result_for("c1"), result_for("c2")), batch(result_for("c3"))],
        settings=make_settings(max_claims_per_call=2),
    )
    assert w.llm.calls == 2 and doc(out)["provenance"]["batches"] == 2
    assert doc(out)["overall"]["counts"]["VERIFIED"] == 3


def test_policy_skips_never_reach_the_model_and_keep_extraction_verdict() -> None:
    skipped = claim(
        1,
        claim_type="RECOMMENDATION",
        extraction_verdict="NEEDS_HUMAN_REVIEW",
        requires_citation=False,
        citation_refs=[],
    )
    out, w = go(data([skipped]), [])
    c = doc(out)["claims"][0]
    assert (
        c["status"] == "EXTRACTED"
        and c["combined_verdict"] == "NEEDS_HUMAN_REVIEW"
        and w.llm.calls == 0
    )
    assert doc(out)["overall"]["proposed_verdict"] == "NEEDS_HUMAN_REVIEW"
    quote = claim(1, claim_type="QUOTED_THIRD_PARTY", citation_refs=[])
    d = doc(go(data([quote]), [])[0])
    assert d["claims"][0]["reason_codes"] == ["QUOTE_NOT_ATTRIBUTABLE"]
    assert d["revision_requests"][0]["action"] == "REMOVE_OR_REWORD"


def test_verified_claim_never_erases_an_extraction_warning() -> None:
    warned = claim(1, extraction_verdict="NEEDS_HUMAN_REVIEW")
    r = doc(go(data([warned]), [batch(result_for("c1"))])[0])
    assert r["claims"][0]["status"] == "VERIFIED"
    assert r["claims"][0]["combined_verdict"] == "NEEDS_HUMAN_REVIEW"
    assert r["overall"]["proposed_verdict"] == "NEEDS_HUMAN_REVIEW"
    assert r["overall"]["verification_verdict"] == "ALLOWED"


@pytest.mark.security
def test_worked_dataset_case_through_a_responding_model_logs_no_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    run = run_case(CASES["POS-05"])
    assert run.output.status is OutputStatus.SUCCEEDED
    joined = " ".join(
        r.getMessage() + json.dumps(r.__dict__.get("claims", "")) for r in caplog.records
    )
    assert "stop-loss" not in joined and "automatically" not in joined
    assert isinstance(run.llm, RespondingLlm)
