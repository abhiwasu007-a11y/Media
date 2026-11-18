# mypy: ignore-errors
# ruff: noqa: PT018, RUF059
"""End-to-end flow with fakes (I-01, I-02, F-series, E-01): no network, no paid call."""

import json
import logging
from datetime import UTC, datetime

from agent_05_scriptwriter import ScriptDraftRequest, ScriptDraftStep
from agent_05_scriptwriter.task_output import build_task_output
from amw_core.contracts.validation import validate_task_output
from tests.agents.agent_05_scriptwriter import support as sp


def build(script, n=2, **state_over):
    st = sp.MemoryState(**state_over)
    llm = sp.ScriptedLlm(script, n)
    step = ScriptDraftStep(
        llm, sp.make_ports(st), sp.make_settings(), sp.prompts(), sp.scanners_for
    )
    return st, llm, step


def request(ctx=None, **over):
    ctx = ctx or sp.make_ctx()
    return ScriptDraftRequest(ctx, sp.make_input(**over), sp.make_resolved(ctx)), ctx


def test_happy_path_produces_scored_script_and_valid_task_output():
    st, llm, step = build(["VALID_PLAN", "VALID_SECTIONS"])
    req, ctx = request()
    out = step.run(req)
    assert out.status == "SUCCEEDED", out.error
    result = out.result
    assert result.verdict == "ALLOWED" and result.selected_hook_id == "h1"
    assert len(result.hook_options) == 3
    assert len(llm.requests) == 3  # plan + 2 sections
    assert all(r.verdict in ("PASS", "WARN", "SKIPPED") for r in out.validation_results)
    # disclaimer slots inserted by code, verbatim
    doc = json.loads(st.saved_contents[out.saved.uri])
    kinds = [s["kind"] for s in doc["segments"]]
    assert kinds[:3] == ["HOOK_PROOF", "HOOK_WHY", "HOOK_COVERS"] and kinds.count("DISCLAIMER") == 2
    assert [s["segment_id"] for s in doc["segments"]] == [f"s{i}" for i in range(1, len(kinds) + 1)]
    task_out = build_task_output(out, ctx, now=datetime.now(UTC), duration_ms=5, attempt_no=1)
    validate_task_output(task_out.model_dump(mode="json"), version="1.0.0")
    assert st.hooks and st.hooks[0].channel_id == ctx.channel_id


def test_replay_returns_stored_output_without_calls():
    st, llm, step = build(["VALID_PLAN", "VALID_SECTIONS"])
    req, _ = request()
    first = step.run(req)
    calls = len(llm.requests)
    second = step.run(req)
    assert second.stored_output_returned and second is first and len(llm.requests) == calls


def test_failure_modes_map_to_07_codes():
    cases = [
        (["INVALID_JSON", "INVALID_JSON"], "AGENT.INVALID_JSON", 2),
        (["SCHEMA_INVALID", "SCHEMA_INVALID"], "AGENT.OUTPUT_SCHEMA_INVALID", 2),
        ([{"http": 429, "retry_after_ms": 15000}], "TEMPORARY.RATE_LIMITED", 1),
        ([{"provider_refusal": True}], "PERMANENT.PROVIDER_REFUSAL", 1),
        (["VALID_PLAN", "NEAR_COPY_FAIL", "NEAR_COPY_FAIL"], "AGENT.QUALITY_REPEATED_FAILURE", 3),
    ]
    for script, code, calls in cases:
        st, llm, step = build(script)
        st.chunk_texts = {}
        out = step.run(request()[0])
        assert out.status == "FAILED" and out.error.code == code
        assert len(llm.requests) == calls
    st, llm, step = build([{"http": 429, "retry_after_ms": 15000}])
    assert step.run(request()[0]).error.retry_after_ms == 15000


def test_parse_repair_then_valid():
    st, llm, step = build(["INVALID_JSON", "VALID_PLAN", "VALID_SECTIONS"])
    out = step.run(request()[0])
    assert out.status == "SUCCEEDED" and len(st.ledger) == 4
    assert llm.keys[0] != llm.keys[1]  # call_seq is part of the idempotency key


def test_budget_refused_suspends_without_a_call():
    st, llm, step = build(["VALID_PLAN"], refuse_budget=True)
    out = step.run(request()[0])
    assert out.status == "SUSPENDED" and out.wait_reason == "AWAITING_BUDGET"
    assert out.error.code == "RESOURCE.BUDGET_EXHAUSTED" and not llm.requests


def test_loop_cap_and_drain_resume_without_rebuying():
    ctx = sp.make_ctx(max_calls=3)
    st, llm, step = build(["VALID_PLAN", "VALID_SECTIONS"], n=4)
    out = step.run(request(ctx)[0])
    assert out.error.code == "AGENT.LOOP_CAP_EXCEEDED" and len(llm.requests) == 3
    # drain after sec2, then resume from the checkpoint
    ctx = sp.make_ctx()
    st, llm, step = build(["VALID_PLAN", "VALID_SECTIONS"], n=4, drain_after="sec2")
    out = step.run(request(ctx)[0])
    assert out.status == "SUSPENDED" and out.checkpoint_step == "section_sec2_done"
    assert len(llm.requests) == 3
    st.drain_after = None
    llm2 = sp.ScriptedLlm(["VALID_SECTIONS"], 4)
    step2 = ScriptDraftStep(
        llm2, sp.make_ports(st), sp.make_settings(), sp.prompts(), sp.scanners_for
    )
    out2 = step2.run(request(ctx)[0])
    assert out2.status == "SUCCEEDED" and len(llm2.requests) == 2
    assert not any("plan" in r.system[:0] for r in llm2.requests)


def test_persist_failure_resumes_at_assembled_without_new_calls():
    from amw_core.errors import DbTransientError

    ctx = sp.make_ctx()
    st, llm, step = build(
        ["VALID_PLAN", "VALID_SECTIONS"], persist_failures=[DbTransientError("x")]
    )
    req, _ = request(ctx)
    first = step.run(req)
    assert first.error.code == "TEMPORARY.DB_TRANSIENT"
    calls = len(llm.requests)
    second = step.run(req)
    assert second.status == "SUCCEEDED" and len(llm.requests) == calls
    assert len(st.scripts) == 1 and st.blob_writes == 1


def test_no_content_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    st, llm, step = build(["VALID_PLAN", "VALID_SECTIONS"])
    out = step.run(request()[0])
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "lesson" not in text and "divergence" not in text and out.status == "SUCCEEDED"


def test_partial_revision_rewrites_only_the_pointed_section():
    ctx = sp.make_ctx()
    st, llm, step = build(["VALID_PLAN", "VALID_SECTIONS"], n=3)
    first = step.run(request(ctx)[0])
    prior_bytes = st.saved_contents[first.saved.uri]
    prior = json.loads(prior_bytes)
    from agent_05_scriptwriter.contracts import ScriptDocument

    doc = ScriptDocument.model_validate(prior)
    target = next(s for s in doc.segments if s.section_id == "sec2").segment_id
    rev = {
        "prior_script": {"uri": first.saved.uri, "sha256": first.saved.sha256},
        "feedback": [
            {
                "source": "CLAIM_VERIFICATION",
                "segment_ref": target,
                "rule_ids": [],
                "instruction": "REMOVE_OR_REWORD: reword",
                "suggested_citation_refs": [],
            }
        ],
    }
    ctx2 = sp.make_ctx()
    st2 = sp.MemoryState()
    llm2 = sp.ScriptedLlm(["VALID_SECTIONS"], 3)
    step2 = ScriptDraftStep(
        llm2, sp.make_ports(st2), sp.make_settings(), sp.prompts(), sp.scanners_for
    )
    res = sp.make_resolved(ctx2, prior_script=doc, prior_script_sha256=first.saved.sha256)
    out = step2.run(ScriptDraftRequest(ctx2, sp.make_input(revision=rev, iteration=1), res))
    assert out.status == "SUCCEEDED", out.error
    assert len(llm2.requests) == 1  # only sec2 re-run
    new = json.loads(st2.saved_contents[out.saved.uri])
    old_hash, new_hash = prior["provenance"]["section_sha256"], new["provenance"]["section_sha256"]
    assert old_hash["sec1"] == new_hash["sec1"] and old_hash["sec3"] == new_hash["sec3"]
    assert old_hash["sec2"] == new_hash["sec2"]  # scripted model reproduces the same text


def test_unknown_segment_ref_is_input_invalid():
    ctx = sp.make_ctx()
    st, llm, step = build(["VALID_PLAN", "VALID_SECTIONS"])
    first = step.run(request(ctx)[0])
    from agent_05_scriptwriter.contracts import ScriptDocument

    doc = ScriptDocument.model_validate(json.loads(st.saved_contents[first.saved.uri]))
    rev = {
        "prior_script": {"uri": first.saved.uri, "sha256": first.saved.sha256},
        "feedback": [
            {"source": "COMPLIANCE", "segment_ref": "s99", "rule_ids": [], "instruction": "x"}
        ],
    }
    ctx2 = sp.make_ctx()
    step2 = ScriptDraftStep(
        sp.ScriptedLlm([]),
        sp.make_ports(sp.MemoryState()),
        sp.make_settings(),
        sp.prompts(),
        sp.scanners_for,
    )
    res = sp.make_resolved(ctx2, prior_script=doc, prior_script_sha256=first.saved.sha256)
    out = step2.run(ScriptDraftRequest(ctx2, sp.make_input(revision=rev, iteration=1), res))
    assert out.error.code == "PERMANENT.INPUT_INVALID"
