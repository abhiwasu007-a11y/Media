# mypy: ignore-errors
# ruff: noqa: PT018, RUF059
"""Shorts adaptation (FR-12, FR-16; I-03, E-03): a re-edit of a cleared parent, no new content."""

import json
from datetime import UTC, datetime
from typing import Any

from agent_05_scriptwriter import (
    ScriptDraftRequest,
    ScriptDraftStep,
    ShortsAdaptationStep,
    ShortsRequest,
)
from agent_05_scriptwriter.contracts import ScriptDocument, ShortsAdaptationInput
from agent_05_scriptwriter.steps.common import StepOutcome
from agent_05_scriptwriter.task_output import build_task_output
from amw_core.contracts.validation import validate_task_output
from tests.agents.agent_05_scriptwriter import support as sp


def parent_script() -> tuple[ScriptDocument, str, dict[str, list[str]], Any]:
    ctx = sp.make_ctx()
    st = sp.MemoryState()
    step = ScriptDraftStep(
        sp.ScriptedLlm(["VALID_PLAN", "VALID_SECTIONS"], 3),
        sp.make_ports(st),
        sp.make_settings(),
        sp.prompts(),
        sp.scanners_for,
    )
    out = step.run(ScriptDraftRequest(ctx, sp.make_input(), sp.make_resolved(ctx)))
    assert out.status == "SUCCEEDED", out.error
    doc = ScriptDocument.model_validate(json.loads(st.saved_contents[out.saved.uri]))
    cites: dict[str, list[str]] = {}
    for seg in doc.segments:
        for r in seg.concept_refs:
            cites.setdefault(r.concept_id, [])
            cites[r.concept_id] += [c for c in r.citation_refs if c not in cites[r.concept_id]]
    return doc, out.saved.sha256, cites, ctx


def shorts_input(doc: ScriptDocument, sha: str, **over: Any) -> ShortsAdaptationInput:
    data: dict[str, Any] = {
        "parent_script": {
            "uri": "amw-blob://org_x/p.json",
            "sha256": sha,
            "script_id": doc.script_id,
        },
        "removed_segment_ids": [],
        "short_target_duration_ms": 45000,
        "owner_instruction": None,
        "language": "en-IN",
        "channel_category": "finance",
        "owner_sebi_registration": "UNREGISTERED",
        "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
        "video_kind": "GENERAL",
        "course_chapter_pointer": None,
        "iteration": 0,
        "revision": None,
    }
    data.update(over)
    return ShortsAdaptationInput.model_validate(data)


def run_cut(
    script: list[Any],
    *,
    cleared: bool = True,
    inp_over: dict[str, Any] | None = None,
    **res_over: Any,
) -> tuple[StepOutcome, sp.ScriptedLlm, sp.MemoryState, Any]:
    doc, sha, cites, _ = parent_script()
    ctx = sp.make_ctx()
    st = sp.MemoryState()
    llm = sp.ScriptedLlm(script, 3, cites)
    step = ShortsAdaptationStep(
        llm, sp.make_ports(st), sp.make_settings(), sp.prompts(), sp.scanners_for
    )
    res = sp.make_resolved(
        ctx, parent_script=doc, parent_script_sha256=sha, parent_claims_cleared=cleared, **res_over
    )
    doc = doc.model_copy(update={"channel_id": ctx.channel_id})
    res.parent_script = doc
    out = step.run(ShortsRequest(ctx, shorts_input(doc, sha, **(inp_over or {})), res))
    return out, llm, st, ctx


def test_cut_end_to_end_and_task_output():
    out, llm, st, ctx = run_cut(["VALID_CUT"])
    assert out.status == "SUCCEEDED", out.error
    doc = json.loads(st.saved_contents[out.saved.uri])
    assert doc["aspect_ratio"] == "9:16" and doc["sections"] == []
    assert doc["segments"][0]["kind"] == "SHORT_HOOK"
    assert all(s["parent_segment_ids"] for s in doc["segments"])
    skipped = {r.check_id for r in out.validation_results if r.verdict == "SKIPPED"}
    assert {"edit.chapters", "a05.script.interrupts", "a05.script.promise_delivery"} <= skipped
    validate_task_output(
        build_task_output(out, ctx, now=datetime.now(UTC), duration_ms=1, attempt_no=1).model_dump(
            mode="json"
        ),
        version="1.0.0",
    )
    assert len(llm.requests) == 1


def test_uncleared_parent_is_refused_before_any_call():
    out, llm, _, _ = run_cut(["VALID_CUT"], cleared=False)
    assert out.error.code == "PERMANENT.MISSING_DEPENDENCY" and not llm.requests


def test_shorts_limit_unset_is_config_invalid():
    doc, sha, cites, _ = parent_script()
    ctx = sp.make_ctx()
    step = ShortsAdaptationStep(
        sp.ScriptedLlm([], 3),
        sp.make_ports(sp.MemoryState()),
        sp.make_settings(shorts_max_duration_ms=None),
        sp.prompts(),
        sp.scanners_for,
    )
    res = sp.make_resolved(
        ctx, parent_script=doc, parent_script_sha256=sha, parent_claims_cleared=True
    )
    out = step.run(ShortsRequest(ctx, shorts_input(doc, sha), res))
    assert out.error.code == "PERMANENT.CONFIG_INVALID"


def test_removed_segment_is_never_used_and_is_not_dropped_either():
    doc, _, _, _ = parent_script()
    removed = next(s for s in doc.segments if s.section_id == "sec1").segment_id
    out, _, st, _ = run_cut(["VALID_CUT"], inp_over={"removed_segment_ids": [removed]})
    assert out.status == "SUCCEEDED", out.error
    cut = json.loads(st.saved_contents[out.saved.uri])
    used = {p for s in cut["segments"] for p in s["parent_segment_ids"]}
    assert removed not in used
    dropped = {d.parent_segment_id for d in out.result.dropped_parent_content}
    assert removed not in dropped


def test_invalid_json_twice_is_a_typed_error():
    out, llm, _, _ = run_cut(["INVALID_JSON", "INVALID_JSON"])
    assert out.error.code == "AGENT.INVALID_JSON" and len(llm.requests) == 2


def test_refusal_rule_would_be_broken_is_blocked_verdict():
    refusal = {
        "title_promise": None,
        "hooks": [],
        "selected_hook_id": None,
        "scenes": [],
        "dropped_parent_content": [],
        "refusal": {
            "reason": "RULE_WOULD_BE_BROKEN",
            "message": "a broker link was asked",
            "missing_inputs": [],
            "violated_rule_ids": ["FIN-R8"],
        },
    }
    out, _, st, ctx = run_cut([{"text": json.dumps(refusal)}], inp_over={"owner_instruction": "x"})
    assert out.status == "SUCCEEDED" and out.result.verdict == "BLOCKED"
    assert out.result.script_document is None and not st.scripts
    task_out = build_task_output(out, ctx, now=datetime.now(UTC), duration_ms=1, attempt_no=1)
    validate_task_output(task_out.model_dump(mode="json"), version="1.0.0")


def test_shorts_revision_reruns_the_single_cut_step():
    doc, sha, cites, _ = parent_script()
    ctx = sp.make_ctx()
    st = sp.MemoryState()
    llm = sp.ScriptedLlm(["VALID_CUT"], 3, cites)
    step = ShortsAdaptationStep(
        llm, sp.make_ports(st), sp.make_settings(), sp.prompts(), sp.scanners_for
    )
    doc = doc.model_copy(update={"channel_id": ctx.channel_id})
    res = sp.make_resolved(
        ctx, parent_script=doc, parent_script_sha256=sha, parent_claims_cleared=True
    )
    first = step.run(ShortsRequest(ctx, shorts_input(doc, sha), res))
    assert first.status == "SUCCEEDED", first.error
    cut_doc = ScriptDocument.model_validate(json.loads(st.saved_contents[first.saved.uri]))
    target = next(s for s in cut_doc.segments if s.kind == "BODY").segment_id
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
    llm2 = sp.ScriptedLlm(["VALID_CUT"], 3, cites)
    st2 = sp.MemoryState()
    step2 = ShortsAdaptationStep(
        llm2, sp.make_ports(st2), sp.make_settings(), sp.prompts(), sp.scanners_for
    )
    res2 = sp.make_resolved(
        ctx2,
        parent_script=doc,
        parent_script_sha256=sha,
        parent_claims_cleared=True,
        previous_cut=cut_doc,
    )
    out = step2.run(ShortsRequest(ctx2, shorts_input(doc, sha, iteration=1, revision=rev), res2))
    # the scripted model returns the flagged sentence verbatim: a05.sh.revision fails the repair
    assert out.error is not None and out.error.code == "AGENT.QUALITY_REPEATED_FAILURE"
    assert len(llm2.requests) == 2
