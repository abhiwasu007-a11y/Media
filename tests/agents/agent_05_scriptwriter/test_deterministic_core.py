# mypy: ignore-errors
# ruff: noqa: PT018
"""The 114-case ``deterministic_core`` golden dataset (blueprint 21 U-series, 26.5: 114 of 114).

Every case is run against the real component; the flow cases (SC-*) run the real step with a
scripted LLM and in-memory ports. No network, no paid call.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_05_scriptwriter import ScriptDraftRequest, ScriptDraftStep
from agent_05_scriptwriter.assemble.assembler import AssemblyInput, assemble
from agent_05_scriptwriter.assemble.parts import (
    DisclaimerTemplate,
    allocate_charts,
    chapter_starts,
    disclaimer_plan,
    estimate_ms,
    split_segments,
)
from agent_05_scriptwriter.checks import script_validator as sv
from agent_05_scriptwriter.checks.cadence import check_cadence
from agent_05_scriptwriter.checks.language import check_language
from agent_05_scriptwriter.checks.near_copy import check_sentence
from agent_05_scriptwriter.contracts import FeedbackItem, GlossaryTerm
from agent_05_scriptwriter.hooks import HookScore, select_hook
from agent_05_scriptwriter.llm.prompt_renderer import render
from agent_05_scriptwriter.observability import safe_fields
from agent_05_scriptwriter.persist.hook_history import HookHistoryMemory
from agent_05_scriptwriter.pre.brief_mapper import ApprovalView, ResearchPackView, map_briefs
from agent_05_scriptwriter.pre.speech_budget import hook_budget, scene_budget
from agent_05_scriptwriter.pre.tenant_guard import RefFact, TenantFacts, check_tenant
from agent_05_scriptwriter.protocols import HookHistoryEntry, RulePack
from agent_05_scriptwriter.refusal import map_refusal
from agent_05_scriptwriter.revision.router import route_feedback
from agent_05_scriptwriter.settings import NearCopySettings
from amw_core.errors import AmwError, DbTransientError
from tests.agents.agent_05_scriptwriter import support as sp

DATASET = (
    Path(__file__).resolve().parents[3]
    / "docs/v4/evals/agent_05_scriptwriter/deterministic_core/cases.jsonl"
)
CASES = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]


def _check_equal(actual: dict[str, Any], expected: dict[str, Any], case_id: str) -> None:
    for key, want in expected.items():
        got = actual.get(key)
        if isinstance(want, float):
            assert got is not None and round(got, 1) == want, (case_id, key, got, want)
        elif isinstance(want, list) and want and all(isinstance(w, dict) for w in want):
            assert isinstance(got, list) and len(got) == len(want), (case_id, key)
            for g, w in zip(got, want, strict=True):
                assert {k: g[k] for k in w} == w, (case_id, key, g, w)
        else:
            assert got == want, (case_id, key, got, want)


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    fn, i = case["function"], case["input"]
    if fn == "HookSelector":
        opts = [HookScore(o["hook_id"], o["vr"], o["cw"], o["qualified"]) for o in i["options"]]
        try:
            sel = select_hook(opts, i["proposed"], i["min_options"])
        except AmwError as exc:
            return {"status": "ERROR", "error_code": exc.code}
        return {
            "status": sel.status,
            "selected": sel.selected,
            "totals": sel.totals,
            "mismatch": sel.mismatch,
        }
    if fn == "SpeechBudgeter":
        if i["method"] == "budgets":
            r = hook_budget(i["rate_cps"], i["window_ms"], i["min_fill_ratio"])
            return {"budget": r.budget.model_dump() if r.budget else None, "verdict": r.verdict}
        b = scene_budget(
            share_permille=i["share_permille"],
            target_ms=i["target_ms"],
            rate_cps=i["rate_cps"],
            size_tolerance=i["size_tolerance"],
            max_scenes=i["max_scenes_cfg"],
            max_change_gap_ms=5000,
        )
        return {"chars_min": b.chars_min, "chars_max": b.chars_max, "max_scenes": b.max_scenes}
    if fn == "ConceptBriefMapper":
        pack = ResearchPackView.model_validate(
            {**i, "citations_available": [], "topic_verdict": None}
        )
        approvals = [
            ApprovalView(a["id"], a["kind"], a["state"], a["same_org"]) for a in i["approvals"]
        ]
        return {"briefs": [b.model_dump() for b in map_briefs(pack, approvals).briefs]}
    if fn == "FinPrefilter":
        return {"rule_ids": sp.SCANNERS.fin_ids(i["text"], i["language"])}
    if fn == "ForbiddenTokenScanner":
        return {"tokens": sp.SCANNERS.tokens(i["text"], i["language"])}
    if fn == "ForwardLookingScanner":
        return {"rule_ids": sp.SCANNERS.forward_ids(i["text"], i["language"], i["scene_kind"])}
    if fn == "LanguageChecker":
        terms = [GlossaryTerm(**t) for t in i["terms"]]
        return {
            "violations": check_language(
                i["text"], i["language"], i["allow"], i["terms_introduced"], terms
            )
        }
    if fn == "CadenceChecker":
        r = check_cadence(
            explanatory=i["explanatory"],
            chars=i["chars"],
            sentences=i["sentences"],
            pause_ms=i["pause_ms"],
            rate_cps=i["rate_cps"],
            max_gap_ms=i["max_gap_ms"],
            change_beats=i["change_beats"],
            hold_reason=i["hold_reason"],
            needs_interrupt=i["needs_interrupt"],
            scene_interrupts=i["scene_interrupts"],
        )
        return {
            "verdict": r.verdict,
            "required": r.required,
            "interrupt_missing": r.interrupt_missing,
        }
    if fn == "NearCopyGuard":
        r = check_sentence(i["sentence"], i["cited"], NearCopySettings(**i["thresholds"]))
        return {"violation": r.violation, "overlap_ratio": r.overlap_ratio}
    if fn == "Segmenter":
        parts, splits = split_segments(i["text"], i["pace"], i["emotion"])
        return {
            "segments": [{"text": p.text, "pace": p.pace, "emotion": p.emotion} for p in parts],
            "split_count": splits,
        }
    if fn == "ChartIdAllocator":
        a = allocate_charts(i["hook_charts"], i["selected"], i["pool_n"])
        return {"hook_chart": a.hook_chart, "dropped": a.dropped, "pool": a.pool}
    if fn == "DurationEstimator":
        return {"est_ms": estimate_ms(i["speech_chars"], i["rate_cps"], i["pause_ms"])}
    if fn == "ChapterBuilder":
        ms = [None if v is None or i["rate_cps"] is None else v for v in i["section_ms"]]
        return {"starts": chapter_starts(ms)}
    if fn == "DisclaimerSlotter":
        return _disclaimer(i)
    if fn == "ScriptAssembler":
        return _assembler(i)
    if fn == "ScriptValidator":
        return _validator(i)
    if fn == "FeedbackRouter":
        return _router(i)
    if fn == "RefusalMapper":
        from agent_05_scriptwriter.contracts import Refusal

        m = map_refusal(Refusal(message="m", **i["refusal"]), i["step"])
        emitted = [r.check_id for r in m.results]
        out: dict[str, Any] = {
            "status": m.status,
            "error_code": m.error_code,
            "scripts_row": m.scripts_row,
            "verdict": m.verdict,
            "script_document": None,
            "earlier_sections_discarded": m.earlier_sections_discarded,
        }
        if m.results:
            out["results_emitted_prefixes"] = ["a05.pre.", emitted[-1]]
            out["all_emitted_results_pass"] = all(r.verdict.value == "PASS" for r in m.results)
        return out
    if fn == "TenantGuard":
        return _tenant(i)
    if fn == "HookHistoryMemory":
        return _hook_memory(i)
    if fn == "LogRedaction":
        return _redaction(i)
    if fn == "PromptRenderer":
        return _renderer(i)
    if fn == "ScriptDraftStep":
        return _flow(case)
    raise AssertionError(fn)


def _disclaimer(i: dict[str, Any]) -> dict[str, Any]:
    tpl = (
        DisclaimerTemplate("r", i["template"]["version"], i["template"]["text"])
        if i["template"]
        else None
    )
    try:
        placements = disclaimer_plan(
            category=i["category"],
            required_categories=frozenset({"finance"}),
            template=tpl,
            placements=i.get("placements", []),
        )
    except AmwError as exc:
        return {"error_code": exc.code}
    if tpl is None or not placements:
        return {"inserted": 0}
    doc = _assemble_min(placements=placements, template=tpl)
    segs = [s for s in doc.segments if s.kind == "DISCLAIMER"]
    first_kind_after_hook = doc.segments[3].kind
    return {
        "inserted": len(segs),
        "text_equals_template": segs[0].text == tpl.text,
        "after_hook": first_kind_after_hook == "DISCLAIMER",
        "records_version": doc.disclaimer_slots[0].template_version == tpl.version,
    }


def _assemble_min(
    *, placements=(), template=None, hook_sentences=(1, 1, 1), sections=(2, 1), same=True, tag=""
):
    plan = sp.plan_json(len(sections))
    from agent_05_scriptwriter.contracts import PlanOutput, Scene

    p = PlanOutput.model_validate(plan)
    hook = p.hooks[0]
    sc: dict[str, list[Scene]] = {}
    for idx, count in enumerate(sections):
        sid = f"sec{idx + 1}"
        base = sp.section_json(
            {
                "section_plan": {
                    "section_id": sid,
                    "concept_ids": ["k1"],
                    "needs_interrupt": False,
                    "section_kind": "CONCEPT",
                },
                "concept_briefs": [{"concept_id": "k1", "citation_refs": ["kch_x"]}],
            }
        )
        first = base["scenes"][0]
        first["sentences"] = [
            {"text": "One plain sentence here.", "pace": "NORMAL", "emotion": "NEUTRAL"}
        ] * count
        scenes = [Scene.model_validate(first)]
        if not same:
            scenes = [s.model_copy(update={"on_screen_text": ["changed"]}) for s in scenes]
        sc[sid] = scenes
    secs = [
        p.sections[i].model_copy(update={"section_id": f"sec{i + 1}"}) for i in range(len(sections))
    ]
    return assemble(
        AssemblyInput(
            script_id="scr_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8001",
            job_id="job_x",
            channel_id="chn_x",
            language="en-IN",
            version=1,
            iteration=0,
            promise=_promise(p),
            hook_beats=hook.beats,
            hook_chart_id="chart_1",
            sections=secs,
            section_scenes=sc,
            concept_map={"k1": "c01", "k2": "c02"},
            hook_options=[],
            omitted=[],
            description_draft=None,
            thumbnail_brief=None,
            rate_cps=None,
            disclaimer_template=template,
            disclaimer_placements=list(placements),
        )
    ).document


def _promise(p):
    from agent_05_scriptwriter.contracts import DocPromise

    assert p.title_promise
    return DocPromise(**p.title_promise.model_dump())


def _assembler(i: dict[str, Any]) -> dict[str, Any]:
    if "hook_sentences" in i:
        doc = _assemble_min(
            placements=i["placements"],
            template=DisclaimerTemplate("r", "v", "TEST DISCLAIMER TEXT."),
            sections=tuple(i["sections"]),
        )
        return {"kinds": _kinds(doc), "ids": [s.segment_id for s in doc.segments]}
    if i["op"] == "section_hash":
        a = _assemble_min(sections=(1, 1)).provenance.section_sha256["sec2"]
        if i["same_section_text"]:
            b = _assemble_min(sections=(3, 1)).provenance.section_sha256["sec2"]
        else:
            b = _assemble_min(sections=(1, 1), same=False).provenance.section_sha256["sec2"]
        return {"hash_equal": a == b}
    runs = [assemble_bytes() for _ in range(i["runs"])]
    return {"bytes_identical": len(set(runs)) == 1}


def assemble_bytes() -> bytes:
    from agent_05_scriptwriter.assemble.assembler import canonical_bytes

    return canonical_bytes(_assemble_min().model_dump(mode="json"))


def _kinds(doc: Any) -> list[str]:
    return [s.kind if s.kind != "RECAP" else "BODY" for s in doc.segments]


def _validator(i: dict[str, Any]) -> dict[str, Any]:
    check = i["check"]
    if check == "edit.hook.window":
        r = sv.check_hook_window(i["hook_segment_chars"], i["rate_cps"], i["window_ms"])
        return {"verdict": r.verdict, "measured": r.measured, "blocking": r.blocking}
    if check == "a05.script.coverage":
        r = sv.check_coverage(i["concept_plan"], i["segment_concepts"], i["omitted"])
        return {"verdict": r.verdict, "missing": r.details.get("missing")}
    if check == "a05.script.citations":
        r = sv.check_citations(
            i["briefs"],
            [{"concept": s["concept"], "citations": s["citations"]} for s in i["segments"]],
        )
    elif check == "a05.script.promise_delivery":
        r = sv.check_promise_delivery(i["key_terms"], i["covered_terms"], i["headings"])
    elif check == "a05.script.tags":
        r = sv.check_tags(i["tags"])
    elif check == "edit.hook.options":
        r = sv.check_hook_options(i["hook_count"], i["min_options"], i["selected"])
    elif check == "edit.chapters":
        r = sv.check_chapters(i["starts"])
    elif check == "a05.script.duration_fit":
        r = sv.check_duration_fit(
            i["est_duration_ms"], i["target_duration_ms"], i["tolerance"], i["rate_cps"]
        )
    else:
        r = sv.check_disclaimer(
            required=i["category"] == "finance", expected_slots=0, slot_hashes_ok=[]
        )
    return {"verdict": r.verdict, "blocking": r.blocking}


def _router(i: dict[str, Any]) -> dict[str, Any]:
    items = [
        FeedbackItem(
            source=x.get("source", "COMPLIANCE"),
            segment_ref=x["segment_ref"],
            rule_ids=x["rule_ids"],
            instruction=x["instruction"],
            suggested_citation_refs=x.get("suggested_citation_refs", []),
        )
        for x in i["items"]
    ]
    shorts = i.get("task_type") == "agent_05.shorts_adaptation"
    try:
        plan = route_feedback(i["prior"], items, shorts=shorts)
    except AmwError as exc:
        return {"error_code": exc.code}
    return {
        "sections_to_rewrite": plan.sections_to_rewrite,
        "rerun_plan": plan.rerun_plan,
        "rerun_cut": plan.rerun_cut or None,
        "items_per_section": plan.items_per_section,
    }


def _tenant(i: dict[str, Any]) -> dict[str, Any]:
    events: list[str] = []
    facts = TenantFacts(
        envelope_org=i["envelope_org"],
        input_org=i["input_org"],
        db_org=i["db_org"],
        channel_org=i["channel_org"],
        tenant_status=i["tenant_status"],
        refs=[RefFact(r["purpose"], r["org"], r["channel"], r["sha_ok"]) for r in i["refs"]],
        task_channel=i["task_channel"],
    )
    try:
        check_tenant(facts, lambda e, _f: events.append(e))
    except AmwError as exc:
        return {"error_code": exc.code, "security_event": bool(events)}
    return {"ok": True}


def _hook_memory(i: dict[str, Any]) -> dict[str, Any]:
    ctx = sp.make_ctx()
    other = "chn_other"

    class Store:
        def read(self, c: Any, n: int) -> list[HookHistoryEntry]:
            return [
                HookHistoryEntry(
                    ctx.channel_id if r["channel"] == i["channel"] else other, r["text"], "QUESTION"
                )
                for r in i["stored"]
            ]

        def write(self, c: Any, entries: Any) -> None: ...

    return {"texts": HookHistoryMemory(Store()).read(ctx, i["n"])}


def _redaction(i: dict[str, Any]) -> dict[str, Any]:
    canary = i["canary"]
    cleaned = safe_fields(
        {
            "step_key": canary + " spoken text",
            "check_ids": [canary + " x"],
            "count": 3,
            "section_id": "sec1",
        }
    )
    return {"canary_in_logs": canary in json.dumps(cleaned)}


def _renderer(i: dict[str, Any]) -> dict[str, Any]:
    pr = sp.prompts().plan
    plat = {k: RulePack(k, "v1", f"PLATFORM TEXT {k}", "PLATFORM") for k in i["platform_packs"]}
    tenant = {k: RulePack(k, "v1", v, "TENANT") for k, v in i["tenant_packs"].items()}
    active = [*i["platform_packs"], *i["tenant_packs"]]
    from agent_05_scriptwriter.contracts import PlanStepInput

    def plan_in(topic: str) -> PlanStepInput:
        return PlanStepInput.model_validate(
            {
                "language": "en-IN",
                "channel_category": "finance",
                "owner_sebi_registration": "UNREGISTERED",
                "active_rule_packs": ["rp.youtube_general"],
                "video_kind": "GENERAL",
                "topic": {"title": topic, "angle": None, "target_duration_ms": 480000},
                "concept_briefs": [],
                "available_citations": [],
                "latin_allow_list": [],
                "speech_budget": None,
                "min_hook_options": 3,
                "max_hook_options": 5,
                "max_sections": 8,
                "hook_history": [],
                "course_chapter_pointer": None,
                "revision_feedback": None,
            }
        )

    a = render(pr, {**plat, **tenant}, active, plan_in("TENANT_TOPIC_77"))
    b = render(pr, plat, list(plat), plan_in("another topic here"))
    return {
        "prefix_contains_tenant_string": any(s in a.system for s in i["tenant_strings"]),
        "prefix_equal_across_tenants": a.system == b.system,
        "tenant_pack_in_tenant_part": "TENANT_PACK_TEXT_77" in a.user,
    }


def _flow(case: dict[str, Any]) -> dict[str, Any]:
    i = case["input"]
    n = i.get("sections", 2)
    script = i.get("script", [])
    ctx = sp.make_ctx(max_calls=i.get("max_llm_calls", 30))
    st = sp.MemoryState(refuse_budget=i.get("budget") == "REFUSE")
    if "persist_failures" in i:
        st.persist_failures = [DbTransientError("transient")]
    if i.get("control", "").startswith("DRAIN_AFTER_"):
        st.drain_after = i["control"].removeprefix("DRAIN_AFTER_")
    llm = sp.ScriptedLlm(script, n)
    step = ScriptDraftStep(
        llm, sp.make_ports(st), sp.make_settings(), sp.prompts(), sp.scanners_for
    )
    req = ScriptDraftRequest(ctx, sp.make_input(), sp.make_resolved(ctx))
    if "checkpoint" in i:  # resume: first run drained after sec2
        first = sp.MemoryState(drain_after="sec2")
        st.checkpoints = first.checkpoints
        pre = ScriptDraftStep(
            sp.ScriptedLlm(["VALID_PLAN", "VALID_SECTIONS"], n),
            sp.make_ports(st),
            sp.make_settings(),
            sp.prompts(),
            sp.scanners_for,
        )
        st.drain_after = "sec2"
        pre.run(req)
        st.drain_after = None
        llm.requests.clear()
    if i.get("idempotency") == "COMPLETED_SAME_HASH":
        done = ScriptDraftStep(
            sp.ScriptedLlm(["VALID_PLAN", "VALID_SECTIONS"], n),
            sp.make_ports(st),
            sp.make_settings(),
            sp.prompts(),
            sp.scanners_for,
        )
        done.run(req)
        llm.requests.clear()
    out = step.run(req)
    if "persist_failures" in i:
        out = step.run(req)
    result: dict[str, Any] = {"adapter_calls": len(llm.requests)}
    if out.error is not None:
        result["error_code"] = out.error.code
        result["retry_after_ms"] = out.error.retry_after_ms
    if out.status == "SUCCEEDED":
        result["result"] = "OK"
    if out.status == "SUSPENDED":
        result["status"] = "SUSPENDED"
    result["wait_reason"] = out.wait_reason
    result["checkpoint_step"] = out.checkpoint_step
    plan_calls = sum(1 for r in llm.requests if "section_plan" not in r.messages[0].content)
    result["plan_calls"] = plan_calls
    result["plan_called"] = plan_calls > 0
    result["ledger_rows_plan"] = plan_calls
    result["stored_output_returned"] = out.stored_output_returned
    result["scripts_rows"] = len(st.scripts)
    result["blob_writes"] = st.blob_writes
    return result


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_deterministic_core_case(case: dict[str, Any]) -> None:
    assert datetime.now(UTC)
    _check_equal(run_case(case), case["expected"], case["case_id"])


def test_dataset_has_114_cases() -> None:
    assert len(CASES) == 114
