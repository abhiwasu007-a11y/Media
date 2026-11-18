"""ClaimExtractionStep: validation, repair, failure injection, tenancy, replay (U-*, F-*, I-*, S-*)."""

# ruff: noqa: E501, PT018

import json
from typing import Any

import pytest

from agent_06_fact_checker.hashing import sha256_hex
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import gate_failures, has_gate_results, integrity_failures
from amw_core.enums import CheckVerdict, NextActionType, OutputStatus
from amw_core.errors import CrossTenantRefError
from amw_core.ids import ActorRef, OrgId, TaskId
from amw_core.interfaces import TenantContext
from amw_core.testing.memory import MemoryTransaction
from tests.agents.agent_06_fact_checker.eval_support import load_cases
from tests.agents.agent_06_fact_checker.recorded_extraction import recorded_response
from tests.agents.agent_06_fact_checker.support import (
    ORG,
    OTHER_ORG,
    SCRIPT_SHA,
    TASK,
    MemoryScripts,
    RecordedLlm,
    StaticPacks,
    World,
    extraction_step,
    make_settings,
    run_context,
    task_input,
)

CASES = load_cases("claim_extraction")
SCHEMA = "agent_06.claim_extraction.input"
pytestmark = pytest.mark.unit


def run(case_id: str, responses: list[str] | None = None, **kw: Any) -> tuple[Any, World]:
    case = CASES[case_id]
    world = World(
        llm=RecordedLlm(responses if responses is not None else [recorded_response(case)])
    )
    data = kw.pop("data", case["input"])
    task = kw.pop("task", None) or task_input(SCHEMA, data, version="1.1.0", script_sha=SCRIPT_SHA)
    step = extraction_step(world, **kw)
    return step.run(task, run_context()), world


def payload(out: Any) -> dict[str, Any]:
    assert out.status is OutputStatus.SUCCEEDED, out.error
    assert out.payload is not None and out.payload.data is not None
    return dict(out.payload.data)


def test_answer_key_blocked_case_reports_failed_gate_but_succeeds() -> None:
    out, world = run("AK-02")
    data = payload(out)
    assert data["overall"]["proposed_verdict"] == "BLOCKED"
    assert data["overall"]["blocking_rule_ids"] == ["FIN-R1", "FIN-R2", "FIN-R3"]
    gates = gate_failures(out)
    assert [g.check_id for g in gates] == ["claims.gate.rule_flags"]
    assert gates[0].remedy_stage_id is None and gates[0].blocking  # target stage s05_script
    assert has_gate_results(out) and not integrity_failures(out)
    assert out.next_action.type is NextActionType.CONTINUE
    assert out.next_action.reason == "gate FAILED: claims.gate.rule_flags"
    assert out.quality_score is None and out.confidence is None and out.downstream_agent is None
    assert world.llm.calls == 1 and len(world.ledger.rows) == 1
    assert out.resource_usage.llm_calls == 1 and len(out.resource_usage.cost_entry_ids) == 1


def test_allowed_and_human_review_verdicts_have_passing_gate() -> None:
    out, _ = run("AK-01")
    assert payload(out)["overall"]["proposed_verdict"] == "ALLOWED"
    assert not gate_failures(out)
    assert out.next_action.type is NextActionType.CONTINUE
    out, _ = run("HN-33")
    assert payload(out)["overall"]["proposed_verdict"] == "NEEDS_HUMAN_REVIEW"
    assert not gate_failures(out)  # never a gate failure: it inserts the approval
    assert out.next_action.type is NextActionType.ESCALATE
    assert any(r.check_id == "claims.citation_required" for r in out.validation_results)


def test_d11_lexicon_comes_from_the_rule_pack_record_and_fails_closed_when_empty() -> None:
    out, world = run("HN-33", packs=StaticPacks(markers={}))  # M-2: no silent no-op filter
    assert out.status is OutputStatus.FAILED and world.llm.calls == 0
    assert out.error is not None and out.error.code == "PERMANENT.CONFIG_INVALID"
    out, world = run("HN-33", packs=StaticPacks(markers={"en": ()}))
    assert out.error is not None and out.error.code == "PERMANENT.CONFIG_INVALID"
    out, _ = run("HN-33", packs=StaticPacks(markers={"en": ("measured",)}))
    flags = payload(out)["claims"][0]["rule_flags"]
    assert [f["rule_id"] for f in flags] == ["FIN-R13"] and flags[0]["evidence"] == "measured"


def test_lexicon_must_cover_the_script_language() -> None:
    marathi = json.loads(json.dumps(CASES["AK-03"]["input"]))
    marathi["language"] = "mr-IN"
    base = StaticPacks()
    only_en = StaticPacks(markers={"en": base.markers["en"]})
    out, world = run("AK-03", data=marathi, packs=only_en)
    assert out.error is not None and out.error.code == "PERMANENT.CONFIG_INVALID"
    assert out.error.details.model_extra == {"missing_languages": ["mr"]}
    assert world.llm.calls == 0
    out, _ = run("AK-03", data=marathi, packs=base)  # the provisional baseline has mr and en
    assert out.status is OutputStatus.SUCCEEDED
    latin = dict(marathi, language="hi-Latn")
    out, _ = run(
        "AK-03",
        data=latin,
        packs=StaticPacks(markers={k: v for k, v in base.markers.items() if k != "hinglish"}),
    )
    assert out.error is not None and out.error.code == "PERMANENT.CONFIG_INVALID"


def test_d3_chart_age_flag_is_code_not_model() -> None:
    for cid in ("EDGE-14", "EDGE-15"):
        out, _ = run(cid)
        claim = payload(out)["claims"][0]
        assert claim["rule_flags"][0]["rule_id"] == "FIN-R9"
        assert claim["rule_flags"][0]["severity"] == "BLOCKING"
        assert claim["proposed_verdict"] == "BLOCKED"
    out, _ = run("EDGE-34")  # schematic chart: null age, no FIN-R9
    assert payload(out)["claims"][0]["rule_flags"] == []


def test_d0_measured_range_overrides_a_permissive_supplied_value() -> None:
    from datetime import date

    class Ranges:
        def range_end(self, ref_id: str) -> date | None:
            return date(2026, 11, 10)  # 8 days before the fixed clock date

    case = CASES["HN-32"]
    data = json.loads(json.dumps(case["input"]))
    out, _ = run("HN-32", data=data, chart_ranges=Ranges())
    claim = payload(out)["claims"][0]
    assert [f["rule_id"] for f in claim["rule_flags"]] == ["FIN-R9"]
    assert payload(out)["overall"]["proposed_verdict"] == "BLOCKED"


def test_d4_url_attaches_to_its_sentence_and_loose_findings_decide_the_verdict() -> None:
    resp = json.loads(recorded_response(CASES["AK-04"]))
    resp["claims"][0]["rule_flags"] = []  # the model missed it; the code net must not
    out, _ = run("AK-04", [json.dumps(resp)])
    data = payload(out)
    flag = data["claims"][0]["rule_flags"][0]
    assert (flag["rule_id"], flag["severity"]) == ("FIN-R8", "BLOCKING")  # broker + link detector
    assert data["overall"]["proposed_verdict"] == "BLOCKED"
    empty = json.dumps({"claims": [], "overall": resp["overall"], "refusal": None})
    out, _ = run("AK-04", [empty])  # no claim at all: still BLOCKED, by code alone
    data = payload(out)
    assert data["overall"]["proposed_verdict"] == "BLOCKED"
    assert data["overall"]["blocking_rule_ids"] == ["FIN-R8"]
    assert any(
        r.check_id == "claims.code_findings" and r.verdict is CheckVerdict.WARN
        for r in out.validation_results
    )
    plain = json.loads(json.dumps(CASES["HN-05"]["input"]))
    plain["segments"][0]["text"] = "Download the free notes at https://example.com/notes today."
    out, _ = run("HN-05", [json.dumps(resp | {"claims": []})], data=plain)
    assert payload(out)["overall"]["proposed_verdict"] == "NEEDS_HUMAN_REVIEW"  # a link alone


def test_d10_non_finance_script_has_no_fin_flags() -> None:
    resp = json.loads(recorded_response(CASES["EDGE-29"]))
    resp["claims"][0]["rule_flags"] = [
        {"rule_id": "FIN-R1", "severity": "BLOCKING", "evidence": "x"}
    ]
    out, _ = run("EDGE-29", [json.dumps(resp)])
    assert payload(out)["claims"][0]["rule_flags"] == []
    assert any(
        r.check_id == "claims.chart_lag" and r.verdict is CheckVerdict.SKIPPED
        for r in out.validation_results
    )


def test_bad_quote_is_repaired_once_then_fails_typed() -> None:
    good = recorded_response(CASES["AK-03"])
    bad = json.loads(good)
    bad["claims"][0]["quote"] = "My strategy made 19% last month"
    out, world = run("AK-03", [json.dumps(bad), good])
    assert payload(out)["overall"]["proposed_verdict"] == "BLOCKED"
    assert world.llm.calls == 2
    repair = world.llm.requests[1].messages
    assert [m.role for m in repair] == ["user", "assistant", "user"]
    assert "c1" in repair[2].content and "19%" not in repair[2].content  # ids, never claim text
    out, world = run("AK-03", [json.dumps(bad), json.dumps(bad)])
    assert out.status is OutputStatus.FAILED
    assert out.error is not None and out.error.code == "AGENT.OUTPUT_SCHEMA_INVALID"
    assert world.llm.calls == 2 and out.payload is None


def test_invalid_json_and_schema_failures_are_typed() -> None:
    out, _ = run("AK-03", ["not json", "still not"])
    assert out.error is not None and out.error.code == "AGENT.INVALID_JSON"
    out, _ = run("AK-03", ['{"claims": []}', '{"claims": []}'])
    assert out.error is not None and out.error.code == "AGENT.OUTPUT_SCHEMA_INVALID"
    fenced = "```json\n" + recorded_response(CASES["AK-03"]) + "\n```"
    out, _ = run("AK-03", [fenced])
    assert out.status is OutputStatus.SUCCEEDED


def test_invented_citation_or_chart_ref_is_rejected_after_repair() -> None:
    resp = json.loads(recorded_response(CASES["EDGE-35"]))
    resp["claims"][0]["citation_refs"] = ["kch_invented"]
    out, _ = run("EDGE-35", [json.dumps(resp), json.dumps(resp)])
    assert out.error is not None and out.error.code == "AGENT.OUTPUT_SCHEMA_INVALID"
    resp = json.loads(recorded_response(CASES["EDGE-14"]))
    resp["claims"][0]["chart_data_ref"] = "chart_99"
    out, _ = run("EDGE-14", [json.dumps(resp), json.dumps(resp)])
    assert out.error is not None and out.error.code == "AGENT.OUTPUT_SCHEMA_INVALID"


@pytest.mark.parametrize(
    ("reason", "status", "code", "verdict"),
    [
        ("UNSAFE_CONTENT", OutputStatus.SUCCEEDED, None, "NEEDS_HUMAN_REVIEW"),
        ("RULE_WOULD_BE_BROKEN", OutputStatus.SUCCEEDED, None, "BLOCKED"),
        ("INSUFFICIENT_INPUT", OutputStatus.FAILED, "PERMANENT.INSUFFICIENT_INPUT", None),
        ("OUT_OF_SCOPE", OutputStatus.FAILED, "PERMANENT.INPUT_INVALID", None),
        ("CONFLICTING_INSTRUCTIONS", OutputStatus.FAILED, "PERMANENT.INPUT_INVALID", None),
    ],
)
def test_f09_refusal_mapping(
    reason: str, status: OutputStatus, code: str | None, verdict: str | None
) -> None:
    refusal = {
        "reason": reason,
        "message": "m",
        "missing_inputs": [],
        "violated_rule_ids": ["FIN-R1"] if reason == "RULE_WOULD_BE_BROKEN" else [],
    }
    response = json.dumps(
        {
            "claims": [],
            "overall": {
                "proposed_verdict": "ALLOWED",
                "blocking_rule_ids": [],
                "needs_human_review_reasons": [],
            },
            "refusal": refusal,
        }
    )
    out, world = run("HN-05", [response])
    assert out.status is status
    if code is None:
        data = payload(out)
        assert data["claims"] == [] and data["overall"]["proposed_verdict"] == verdict
        assert world.claims.rows == {} or all(not v for v in world.claims.rows.values())
    else:
        assert out.error is not None and out.error.code == code


def test_u02_multi_batch_claims_are_renumbered_in_segment_order() -> None:
    case = CASES["MIX-30"]
    full = json.loads(recorded_response(case))
    one = {"claims": [full["claims"][0]], "overall": full["overall"], "refusal": None}
    two = {
        "claims": [dict(full["claims"][1], local_id="c1")],
        "overall": full["overall"],
        "refusal": None,
    }
    out, world = run(
        "MIX-30",
        [json.dumps(one), json.dumps(two)],
        settings=make_settings(extract_max_chars_per_call=60),
    )
    data = payload(out)
    assert world.llm.calls == 2
    assert [c["local_id"] for c in data["claims"]] == ["c1", "c2"]
    assert [c["segment_id"] for c in data["claims"]] == ["s1", "s2"]
    assert data["overall"]["proposed_verdict"] == "BLOCKED"
    tx = MemoryTransaction(TenantContext(org_id=OrgId(ORG), actor=ActorRef("agent_06")))
    assert len(world.checkpoints.list_for_task(tx, TaskId(TASK))) == 3  # E1 + two batches


def test_i02_replay_makes_no_second_paid_call_and_same_claim_ids() -> None:
    case = CASES["AK-02"]
    world = World(llm=RecordedLlm([recorded_response(case)]))
    step = extraction_step(world)
    task = task_input(SCHEMA, case["input"], version="1.1.0", script_sha=SCRIPT_SHA)
    first = step.run(task, run_context())
    second = step.run(task, run_context())  # resume from the latest checkpoint
    assert world.llm.calls == 1 and len(world.ledger.rows) == 1
    assert payload(first) == payload(second)
    assert len({tuple(v.items()) for v in world.claims.rows.values()}) == 1
    assert [o.uri for o in first.output_refs] == [o.uri for o in second.output_refs]


def test_idempotency_keys_follow_task_step_and_attempt() -> None:
    out, world = run("AK-03", [recorded_response(CASES["AK-03"])])
    assert out.status is OutputStatus.SUCCEEDED
    assert world.llm.keys[0].startswith("idk_") and len(world.llm.keys[0]) == 68
    assert world.ledger.rows[0].entry.idempotency_key == world.llm.keys[0]


@pytest.mark.security
def test_hand_off_artifacts_and_audit_carry_ids_and_counts_only() -> None:
    out, world = run("AK-02")
    names = [r.uri.rsplit("/", 1)[1] for r in out.output_refs]
    assert names == ["claim_extraction_output.json", "claim_ids.json"]
    ids = json.loads(world.blobs.data[out.output_refs[1].uri])
    assert sorted(ids) == ["c1", "c2"] and all(v.startswith("clm_") for v in ids.values())
    assert out.output_refs[0].sha256 == sha256_hex(world.blobs.data[out.output_refs[0].uri])
    entry = world.audit.entries[0]
    assert entry.action == "claims.extracted" and entry.details["claims"] == 2
    assert "NIFTY" not in json.dumps(dict(entry.details))


# ---------------------------------------------------------------- validation (F-01, F-02, S-*)
def test_f01_schema_violation_is_rejected_without_a_call() -> None:
    data = json.loads(json.dumps(CASES["AK-03"]["input"]))
    del data["segments"]
    out, world = run("AK-03", data=data)
    assert out.status is OutputStatus.REJECTED
    assert out.error is not None and out.error.code == "PERMANENT.SCHEMA_INVALID"
    assert out.error.attempt_no == 0 and world.llm.calls == 0
    task = task_input("agent_06.other", CASES["AK-03"]["input"])
    out, _ = run("AK-03", task=task)
    assert out.error is not None and out.error.code == "PERMANENT.SCHEMA_INVALID"
    task = task_input(SCHEMA, CASES["AK-03"]["input"], version="2.0.0")
    out, _ = run("AK-03", task=task)
    assert out.error is not None and out.error.code == "PERMANENT.SCHEMA_VERSION_UNSUPPORTED"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d.update(owner_sebi_registration="REGISTERED"), "PERMANENT.INPUT_INVALID"),
        (lambda d: d["segments"].append(dict(d["segments"][0])), "PERMANENT.INPUT_INVALID"),
        (lambda d: d.update(active_rule_packs=["rp.finance_sebi_in"]), "PERMANENT.SCHEMA_INVALID"),
    ],
)
def test_f02_input_invalid_rejections(mutate: Any, code: str) -> None:
    data = json.loads(json.dumps(CASES["AK-03"]["input"]))
    mutate(data)
    out, world = run("AK-03", data=data)
    assert out.status is OutputStatus.REJECTED and world.llm.calls == 0
    assert out.error is not None and out.error.code == code


def test_f02_missing_pack_script_or_blob_ref() -> None:
    packs = StaticPacks()
    packs.missing = {"rp.finance_sebi_in"}  # D9
    out, _ = run("AK-03", packs=packs)
    assert out.error is not None and out.error.code == "PERMANENT.MISSING_DEPENDENCY"
    out, _ = run("AK-03", scripts=MemoryScripts(None))
    assert out.error is not None and out.error.code == "PERMANENT.MISSING_DEPENDENCY"
    task = task_input(SCHEMA, CASES["AK-03"]["input"], version="1.1.0")  # no script blob ref
    out, _ = run("AK-03", task=task)
    assert out.error is not None and out.error.code == "PERMANENT.MISSING_DEPENDENCY"
    out, world = run("AK-03", scripts=MemoryScripts("22" * 32))  # content hash differs
    assert out.error is not None and out.error.code == "PERMANENT.INPUT_INVALID"
    assert world.llm.calls == 0


@pytest.mark.security
def test_s01_s02_tenant_isolation() -> None:
    data = CASES["AK-03"]["input"]
    bad = task_input(SCHEMA, data, version="1.1.0", script_sha=SCRIPT_SHA).model_dump(mode="json")
    bad["context_refs"][0]["uri"] = f"amw-blob://{OTHER_ORG}/jobs/x/script.json"
    with pytest.raises(CrossTenantRefError):  # a ref of another org never becomes a task
        TaskInput.model_validate(bad)
    task = task_input(SCHEMA, data, version="1.1.0", script_sha=SCRIPT_SHA)
    out, world = run("AK-03", task=task)
    assert out.status is OutputStatus.SUCCEEDED
    assert len(world.ledger.rows) == 1
    assert all(uri.startswith(f"amw-blob://{ORG}/") for uri in world.blobs.data)


def test_finance_script_needs_a_channel() -> None:
    task = task_input(SCHEMA, CASES["AK-03"]["input"], version="1.1.0", script_sha=SCRIPT_SHA)
    doc = task.model_dump(mode="json")
    doc["channel_id"] = None
    out, _ = run("AK-03", task=TaskInput.model_validate(doc))
    assert out.error is not None and out.error.code == "PERMANENT.INPUT_INVALID"
    wrong = task.model_dump(mode="json")
    wrong["agent_id"] = "agent_05"
    out, _ = run("AK-03", task=TaskInput.model_validate(wrong))
    assert out.error is not None and out.error.code == "PERMANENT.INPUT_INVALID"


# ---------------------------------------------------------------- budget and caps (F-11, F-12)
def test_f11_budget_refusal_suspends_without_a_call() -> None:
    case = CASES["AK-03"]
    world = World(llm=RecordedLlm([recorded_response(case)]))
    world.budget.refuse = True
    task = task_input(SCHEMA, case["input"], version="1.1.0", script_sha=SCRIPT_SHA)
    out = extraction_step(world).run(task, run_context())
    assert out.status is OutputStatus.SUSPENDED
    assert (
        out.next_action.wait_reason is not None
        and out.next_action.wait_reason.value == "AWAITING_BUDGET"
    )
    assert world.llm.calls == 0 and world.ledger.rows == []


def test_f12_call_cap_stops_the_repair_loop() -> None:
    bad = json.loads(recorded_response(CASES["AK-03"]))
    bad["claims"][0]["quote"] = "wrong"
    task = task_input(
        SCHEMA, CASES["AK-03"]["input"], version="1.1.0", script_sha=SCRIPT_SHA, max_llm_calls=1
    )
    out, world = run("AK-03", [json.dumps(bad), json.dumps(bad)], task=task)
    assert out.error is not None and out.error.code == "AGENT.LOOP_CAP_EXCEEDED"
    assert world.llm.calls == 1


@pytest.mark.security
def test_cache_prefix_has_no_tenant_text_and_inputs_are_data() -> None:
    _, world = run("AK-03")
    req = world.llm.requests[0]
    assert req.cache_system_prompt and "AK-03" not in req.system
    assert "[rules of rp.finance_sebi_in]" in req.system and "{{rule_pack" not in req.system
    assert (
        req.messages[0].content.startswith("<<<INPUT")
        and "My strategy made 18%" in req.messages[0].content
    )
    assert "content_sha256" not in req.messages[0].content and "org_" not in req.messages[0].content
    assert req.language == "en-IN"
