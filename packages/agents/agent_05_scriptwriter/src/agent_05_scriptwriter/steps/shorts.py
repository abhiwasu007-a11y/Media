"""``ShortsAdaptationStep`` (blueprint 4.2, 10.4, FR-12, FR-16): one cut call, assemble, persist."""

import json
from dataclasses import dataclass
from typing import Any

from agent_05_scriptwriter.assemble.assembler import canonical_bytes
from agent_05_scriptwriter.assemble.cut_assembler import CutAssemblyInput, assemble_cut
from agent_05_scriptwriter.checks.context import Scanners
from agent_05_scriptwriter.checks.cut_checker import CutChecker, CutReport
from agent_05_scriptwriter.checks.results import CheckResult, failing_ids, passed, skipped
from agent_05_scriptwriter.checks.script_validator import (
    HOOK_KINDS,
    _assembly,
    _selected,
    _selection_valid,
    check_hook_options,
    check_hook_window,
    check_tags,
)
from agent_05_scriptwriter.contracts import (
    CutHook,
    CutOutput,
    CutPromiseOut,
    CutProvenance,
    CutSpeechBudget,
    DocPromise,
    DocumentProvenance,
    Flags,
    GlossaryTerm,
    OptionOut,
    OutCutCoverage,
    OutScene,
    ParentEcho,
    ParentPromise,
    ParentSection,
    ParentSegment,
    ParentView,
    PrevCutHook,
    PrevCutScene,
    PrevCutSentence,
    PreviousCut,
    Refusal,
    ScriptDocument,
    ShortsAdaptationInput,
    ShortsAdaptationResult,
    Totals,
)
from agent_05_scriptwriter.errors import InputInvalid, MissingDependency, QualityRepeatedFailure
from agent_05_scriptwriter.hooks import HookScore, select_hook
from agent_05_scriptwriter.llm.prompt_renderer import render
from agent_05_scriptwriter.llm.structured_caller import CallCounter, CallRecord, StructuredCaller
from agent_05_scriptwriter.observability import log_event
from agent_05_scriptwriter.pre.brief_mapper import map_briefs
from agent_05_scriptwriter.pre.speech_budget import hook_budget
from agent_05_scriptwriter.protocols import CheckpointState, HookHistoryEntry, Ports, StepContext
from agent_05_scriptwriter.refusal import map_refusal
from agent_05_scriptwriter.revision.router import route_feedback
from agent_05_scriptwriter.settings import Agent05Settings
from agent_05_scriptwriter.steps.common import (
    PromptSet,
    ResolvedInputs,
    StepOutcome,
    pre_checks,
    provenance_calls,
    records_from_state,
)
from agent_05_scriptwriter.text import speech_chars, word_count
from amw_adapters.llm import LlmAdapter
from amw_core.errors import AmwError, BudgetExhaustedError


@dataclass(frozen=True, slots=True)
class ShortsRequest:
    ctx: StepContext
    input: ShortsAdaptationInput
    inputs: ResolvedInputs


def parent_view(doc: ScriptDocument, removed: list[str]) -> ParentView:
    """The cleared parent as the cut prompt sees it (no disclaimer text, no hook scenes)."""
    sections = []
    for sec in doc.sections:
        segs = [
            ParentSegment(
                segment_id=s.segment_id,
                text=s.text,
                concept_refs=[r.concept_id for r in s.concept_refs],
                chart_ref=s.chart_ref,
                method_label=s.method_label,
                hypothetical_example=s.hypothetical_example,
            )
            for s in doc.segments
            if s.section_id == sec.section_id
        ]
        if segs:
            sections.append(
                ParentSection(
                    section_id=sec.section_id, heading_local=sec.heading_local, segments=segs
                )
            )
    return ParentView(
        promise=ParentPromise(
            working_title_local=doc.promise.working_title_local,
            promise_key_terms=list(doc.promise.promise_key_terms),
        ),
        claims_cleared=True,
        removed_segment_ids=removed,
        sections=sections,
    )


def previous_cut_view(doc: ScriptDocument) -> PreviousCut:
    hook = [s for s in doc.segments if s.kind == "SHORT_HOOK"]
    scenes = []
    for position, scene in enumerate((x for x in doc.scenes if x.scene_id != "hook.sc1"), start=1):
        segs = [s for s in doc.segments if s.scene_id == scene.scene_id]
        scenes.append(
            PrevCutScene(
                scene_local_id=f"sc{position}",
                parent_segment_ids=list(segs[0].parent_segment_ids) if segs else [],
                sentences=[PrevCutSentence(segment_id=s.segment_id, text=s.text) for s in segs],
            )
        )
    return PreviousCut(
        hook=PrevCutHook(
            hook_id=next((o.hook_id for o in doc.hook_options if o.segment_ids), "h1"),
            sentences=[PrevCutSentence(segment_id=s.segment_id, text=s.text) for s in hook],
        ),
        scenes=scenes,
    )


class ShortsAdaptationStep:
    def __init__(
        self,
        llm: LlmAdapter,
        ports: Ports,
        settings: Agent05Settings,
        prompts: PromptSet,
        scanners_for: Any,
    ) -> None:
        self._llm = llm
        self._p = ports
        self._s = settings
        self._prompts = prompts
        self._scanners_for = scanners_for

    def run(self, req: ShortsRequest) -> StepOutcome:
        ctx = req.ctx
        stored = self._p.idempotency.stored_output(ctx)
        if isinstance(stored, StepOutcome):
            stored.stored_output_returned = True
            return stored
        cp = self._p.checkpoints.latest(ctx)
        state: dict[str, Any] = dict(cp.state) if cp else {}
        try:
            outcome = self._run(req, state)
        except BudgetExhaustedError as exc:
            outcome = StepOutcome(
                "SUSPENDED",
                None,
                [],
                error=exc,
                wait_reason="AWAITING_BUDGET",
                checkpoint_step=state.get("last_step"),
                records=records_from_state(state),
            )
        except AmwError as exc:
            log_event("shorts_adaptation.failed", code=exc.code, task_id=ctx.task_id)
            outcome = StepOutcome("FAILED", None, [], error=exc, records=records_from_state(state))
        if outcome.status == "SUCCEEDED" and not outcome.stored_output_returned:
            self._p.idempotency.complete(ctx, outcome)
        return outcome

    def _checkpoint(self, ctx: StepContext, state: dict[str, Any], key: str) -> None:
        state["last_step"] = key
        self._p.checkpoints.write(ctx, CheckpointState(key, json.loads(json.dumps(state))))

    def _run(self, req: ShortsRequest, state: dict[str, Any]) -> StepOutcome:
        ctx, inp, res, s = req.ctx, req.input, req.inputs, self._s
        pre = pre_checks(
            ctx,
            s,
            res,
            language=inp.language,
            active_rule_packs=inp.active_rule_packs,
            channel_category=inp.channel_category,
        )
        limit = s.require_shorts_limit()
        step_cfg = s.require_cut()
        parent = res.parent_script
        if parent is None or res.parent_script_sha256 != inp.parent_script.sha256:
            raise MissingDependency("the parent script is missing or its hash differs")
        if parent.channel_id != ctx.channel_id or parent.script_id != inp.parent_script.script_id:
            raise InputInvalid("the parent script belongs to another channel or script")
        if not res.parent_claims_cleared:
            raise MissingDependency("the parent script is not cleared by Agent 06 and Agent 16")
        pre.append(passed("a05.sh.pre", "parent loaded by hash, cleared, same org and channel"))
        records = records_from_state(state)
        if "pre" not in state:
            state["pre"] = {
                "script_id": res.new_script_id,
                "version": self._p.scripts.next_version(ctx, inp.language),
            }
            self._checkpoint(ctx, state, "pre_done")
        scanners: Scanners = self._scanners_for(res.lexicons)
        checker = CutChecker(s, scanners)
        concept_map: dict[str, str] = {}
        glossary: list[GlossaryTerm] = []
        if res.pack is not None:
            briefs = map_briefs(res.pack, res.approvals)
            concept_map = briefs.concept_map
            glossary = [
                GlossaryTerm(concept_id=b.concept_id, term_local=b.term_local, term_en=b.term_en)
                for b in briefs.briefs
            ]
        if not concept_map:
            concept_map = {
                r.concept_id: r.pack_concept_id for seg in parent.segments for r in seg.concept_refs
            }
        parent_citations: dict[str, set[str]] = {}
        for seg in parent.segments:
            for r in seg.concept_refs:
                parent_citations.setdefault(r.concept_id, set()).update(r.citation_refs)
        history = [
            e.text
            for e in self._p.hook_history.read(ctx, s.hook_history_size)
            if e.channel_id == ctx.channel_id
        ]
        feedback = list(inp.revision.feedback) if inp.revision else None
        previous = None
        if inp.revision is not None:
            if res.previous_cut is None:
                raise MissingDependency("the previous cut is missing")
            previous = previous_cut_view(res.previous_cut)
            route_feedback(
                {
                    "cut": [x.segment_id for h in previous.hook.sentences for x in [h]]
                    + [x.segment_id for sc in previous.scenes for x in sc.sentences]
                },
                inp.revision.feedback,
                shorts=True,
            )
        budget = hook_budget(s.rate_for(inp.language), s.hook_window_ms, s.hook_min_fill_ratio)
        step_in = _cut_input(
            req, parent, glossary, history, limit, budget.budget, feedback, previous, s
        )
        holder: dict[str, CutReport] = {}

        def check(out: CutOutput) -> list[CheckResult]:
            holder["r"] = checker.check(
                out, step_in, parent_citations=parent_citations, shorts_limit_ms=limit
            )
            return holder["r"].results

        if "cut" in state:
            cut = CutOutput.model_validate(state["cut"])
            check(cut)
        else:
            caller = StructuredCaller(
                self._llm, self._p.ledger, self._p.budget, CallCounter(used=len(records))
            )
            rendered = render(
                self._prompts.cut or _missing(), res.rule_packs, inp.active_rule_packs, step_in
            )
            step = caller.run_step(
                ctx,
                model_cls=CutOutput,
                step=step_cfg,
                step_key="cut",
                rendered=rendered,
                language=inp.language,
                check=check,
                is_refusal=lambda o: o.refusal is not None,
            )
            records += step.records
            state["calls"] = [r.as_dict() for r in records]
            cut = step.parsed
            if cut.refusal is not None:
                return self._refusal(req, cut.refusal, pre, records)
            state["cut"] = cut.model_dump(mode="json")
            self._checkpoint(ctx, state, "cut_done")
        report = holder["r"]
        assert cut.title_promise is not None  # noqa: S101 - not a refusal
        options, selected = _options(cut, report, s)
        hook = next(h for h in cut.hooks if h.hook_id == selected)
        provenance = DocumentProvenance(
            prompt_ids={"cut": (self._prompts.cut or _missing()).prompt_id},
            prompt_sha256={
                (self._prompts.cut or _missing()).prompt_id: (
                    self._prompts.cut or _missing()
                ).sha256
            },
            rule_pack_versions={k: v.version for k, v in res.rule_packs.items()},
            config_key_families=[step_cfg.config_key_family],
            section_sha256={},
        )
        assembled = assemble_cut(
            CutAssemblyInput(
                script_id=state["pre"]["script_id"],
                job_id=ctx.job_id,
                channel_id=ctx.channel_id,
                language=inp.language,
                version=int(state["pre"]["version"]),
                iteration=inp.iteration,
                promise=DocPromise(
                    working_title_local=cut.title_promise.short_title_local,
                    promise_statement=cut.title_promise.promise_statement,
                    promise_key_terms=cut.title_promise.promise_key_terms,
                ),
                hook=hook,
                scenes=cut.scenes,
                concept_map=concept_map,
                hook_options=options,
                rate_cps=s.rate_for(inp.language),
                provenance=provenance,
            )
        )
        doc = assembled.document
        validation = [*report.results, *_cut_validation(doc, s, inp.language)]
        blocking = failing_ids(validation)
        if blocking:
            raise QualityRepeatedFailure("cut checks failed", details={"check_ids": blocking})
        saved = self._p.scripts.save(
            ctx,
            script_id=doc.script_id,
            version=doc.version,
            iteration=inp.iteration,
            language=inp.language,
            content=assembled.content,
            sha256=assembled.sha256,
            parent_script_id=inp.parent_script.script_id,
            segment_count=len(doc.segments),
            word_count=sum(word_count(x.text) for x in doc.segments),
            est_duration_ms=report.estimated_ms,
            prompt_id=(self._prompts.cut or _missing()).prompt_id,
        )
        self._p.hook_history.write(
            ctx,
            [HookHistoryEntry(ctx.channel_id, doc.segments[0].text, hook.hook_style, ctx.job_id)],
        )
        self._p.audit.record(ctx, "shorts_adaptation.persisted", {"script_id": saved.script_id})
        self._checkpoint(ctx, state, "persisted")
        result = _result(
            doc,
            cut,
            inp,
            saved.uri,
            assembled.sha256,
            records,
            provenance,
            step_cfg.config_key_family,
        )
        return StepOutcome(
            "SUCCEEDED",
            result,
            [*pre, *validation],
            saved=saved,
            records=records,
            document_bytes=assembled.content,
        )

    def _refusal(
        self,
        req: ShortsRequest,
        refusal: Refusal,
        pre: list[CheckResult],
        records: list[CallRecord],
    ) -> StepOutcome:
        mapped = map_refusal(
            refusal,
            "cut",
            [r.to_validation_result() for r in pre if r.check_id.startswith("a05.pre.")],
        )
        if mapped.status == "FAILED":
            assert mapped.error_code is not None  # noqa: S101
            return StepOutcome(
                "FAILED",
                None,
                [],
                error=AmwError.for_code(mapped.error_code)("model refusal"),
                records=records,
            )
        inp = req.input
        result = ShortsAdaptationResult(
            script_id=None,
            version=1,
            iteration=inp.iteration,
            language=inp.language,
            verdict=mapped.verdict,  # type: ignore[arg-type]
            parent=ParentEcho(
                script_id=inp.parent_script.script_id, sha256=inp.parent_script.sha256
            ),
            title_promise=None,
            hook_options=[],
            selected_hook_id=None,
            scenes=[],
            concept_coverage=[],
            dropped_parent_content=[],
            chart_refs=[],
            totals=Totals(
                segment_count=0,
                word_count=0,
                speech_chars=0,
                est_duration_ms=None,
                llm_calls=len(records),
            ),
            flags=Flags(
                method_used=False,
                method_segment_ids=[],
                hypothetical_segment_ids=[],
                course_pointer_present=False,
            ),
            script_document=None,
            refusal=refusal,
            provenance=CutProvenance(
                cut_prompt_id=(self._prompts.cut or _missing()).prompt_id,
                prompt_sha256={},
                rule_pack_versions={},
                config_key_families=[],
                calls=provenance_calls(records),
            ),
        )
        out = StepOutcome("SUCCEEDED", result, pre, records=records)
        out.validation_results = [
            *pre,
            *[
                CheckResult(v.check_id, v.verdict.value, v.blocking, v.message)
                for v in mapped.results
            ],
        ]
        out.refusal_rule_ids = list(refusal.violated_rule_ids)
        return out


def _missing() -> Any:
    from agent_05_scriptwriter.errors import ConfigInvalid

    raise ConfigInvalid("the shorts_adaptation prompt is not loaded")


def _cut_input(
    req: ShortsRequest,
    parent: ScriptDocument,
    glossary: list[GlossaryTerm],
    history: list[str],
    limit: int,
    budget: Any,
    feedback: Any,
    previous: PreviousCut | None,
    s: Agent05Settings,
) -> Any:
    from agent_05_scriptwriter.contracts import CutStepInput

    inp = req.input
    allow = list(req.inputs.brand_latin_allow_list or s.latin_allow_list_default)
    return CutStepInput(
        language=inp.language,
        channel_category=inp.channel_category,
        owner_sebi_registration="UNREGISTERED",
        active_rule_packs=inp.active_rule_packs,
        video_kind=inp.video_kind,
        parent=parent_view(parent, inp.removed_segment_ids),
        glossary_terms=glossary,
        short_target_duration_ms=inp.short_target_duration_ms,
        max_duration_ms=limit,
        speech_budget=CutSpeechBudget(hook_chars_max=budget.hook_chars_max) if budget else None,
        owner_instruction=inp.owner_instruction,
        latin_allow_list=allow,
        min_hook_options=s.hooks_min_options,
        max_hook_options=s.hooks_max_options,
        hook_history=history,
        course_chapter_pointer=inp.course_chapter_pointer,
        revision_feedback=feedback,
        previous_cut=previous,
    )


def _options(cut: CutOutput, report: CutReport, s: Agent05Settings) -> tuple[list[OptionOut], str]:
    scores = [
        HookScore(
            h.hook_id,
            h.rubric.viewer_relevance,
            h.rubric.curiosity_without_clickbait,
            not report.option_failures.get(h.hook_id),
        )
        for h in cut.hooks
    ]
    selection = select_hook(scores, cut.selected_hook_id, s.hooks_min_options)
    if selection.selected is None:
        raise QualityRepeatedFailure("too few qualified hook options")
    options = [
        OptionOut(
            hook_id=h.hook_id,
            hook_style=h.hook_style,
            rubric=h.rubric,
            total=selection.totals[h.hook_id],
            qualified=not report.option_failures.get(h.hook_id),
            disqualified_by=list(report.option_failures.get(h.hook_id, [])),
            segment_ids=["s0"] if h.hook_id == selection.selected else [],
        )
        for h in cut.hooks
    ]
    return options, selection.selected


def _cut_validation(doc: ScriptDocument, s: Agent05Settings, language: str) -> list[CheckResult]:
    rate = s.rate_for(language)
    selected = _selected(doc)
    results = [
        _assembly(doc),
        check_tags([(x.pace, x.emotion) for x in doc.segments]),
        check_hook_options(len(doc.hook_options), s.hooks_min_options, selected),
        _selection_valid(doc, selected, s.hooks_min_options),
        check_hook_window(
            [speech_chars(x.text) for x in doc.segments if x.kind == "SHORT_HOOK"],
            rate,
            s.hook_window_ms,
        ),
    ]
    for check_id in ("edit.chapters", "a05.script.interrupts", "a05.script.promise_delivery"):
        results.append(skipped(check_id, "section-based check does not apply to a cut"))
    _ = HOOK_KINDS
    return results


def _result(
    doc: ScriptDocument,
    cut: CutOutput,
    inp: ShortsAdaptationInput,
    uri: str,
    sha: str,
    records: list[CallRecord],
    provenance: DocumentProvenance,
    family: str,
) -> ShortsAdaptationResult:
    assert cut.title_promise is not None  # noqa: S101
    segs = doc.segments
    scenes: list[OutScene] = []
    coverage: dict[str, OutCutCoverage] = {}
    for sc in (x for x in doc.scenes if x.scene_id != "hook.sc1"):
        own = [s for s in segs if s.scene_id == sc.scene_id]
        durations = [s.est_duration_ms for s in own]
        scenes.append(
            OutScene(
                scene_id=sc.scene_id,
                beat=sc.beat,  # type: ignore[arg-type]
                segment_ids=[s.segment_id for s in own],
                parent_segment_ids=list(own[0].parent_segment_ids),
                est_start_ms=own[0].est_start_ms,
                est_duration_ms=None
                if any(d is None for d in durations)
                else sum(d or 0 for d in durations),
            )
        )
        for seg in own:
            for ref in seg.concept_refs:
                entry = coverage.setdefault(
                    ref.concept_id,
                    OutCutCoverage(
                        concept_id=ref.concept_id, taught_in_scene_ids=[], segment_ids=[]
                    ),
                )
                if sc.scene_id not in entry.taught_in_scene_ids:
                    entry.taught_in_scene_ids.append(sc.scene_id)
                entry.segment_ids.append(seg.segment_id)
    ests = [x.est_duration_ms for x in segs]
    method = [x.segment_id for x in segs if x.method_label]
    return ShortsAdaptationResult(
        script_id=doc.script_id,
        version=doc.version,
        iteration=doc.iteration,
        language=doc.language,
        verdict="ALLOWED",
        parent=ParentEcho(script_id=inp.parent_script.script_id, sha256=inp.parent_script.sha256),
        title_promise=CutPromiseOut(**cut.title_promise.model_dump()),
        hook_options=doc.hook_options,
        selected_hook_id=next(o.hook_id for o in doc.hook_options if o.segment_ids),
        scenes=scenes,
        concept_coverage=list(coverage.values()),
        dropped_parent_content=cut.dropped_parent_content,
        chart_refs=sorted({x.chart_ref for x in segs if x.chart_ref}),
        totals=Totals(
            segment_count=len(segs),
            word_count=sum(word_count(x.text) for x in segs),
            speech_chars=sum(speech_chars(x.text) for x in segs),
            est_duration_ms=None if any(e is None for e in ests) else sum(e or 0 for e in ests),
            llm_calls=len(records),
        ),
        flags=Flags(
            method_used=bool(method),
            method_segment_ids=method,
            hypothetical_segment_ids=[x.segment_id for x in segs if x.hypothetical_example],
            course_pointer_present=False,
        ),
        script_document={"uri": uri, "sha256": sha},  # type: ignore[arg-type]
        refusal=None,
        provenance=CutProvenance(
            cut_prompt_id=next(iter(provenance.prompt_ids.values())),
            prompt_sha256=dict(provenance.prompt_sha256),
            rule_pack_versions=dict(provenance.rule_pack_versions),
            config_key_families=[family],
            calls=provenance_calls(records),
        ),
    )


__all__ = ["CutHook", "ShortsAdaptationStep", "ShortsRequest", "canonical_bytes"]
