"""``ScriptDraftStep`` (blueprint 4.1, 10.1, 16): plan, sections, assemble, validate, persist.

Orchestrates only: every decision that can be computed is a pure function in ``checks``,
``assemble``, ``hooks`` or ``revision``. It is the only class that writes checkpoints and builds the
step outcome. Content (narration, briefs, feedback) never reaches a log line.
"""

import json
from dataclasses import dataclass
from typing import Any

from agent_05_scriptwriter.assemble.assembler import AssemblyInput, assemble
from agent_05_scriptwriter.assemble.parts import allocate_charts, section_pool
from agent_05_scriptwriter.checks.context import Scanners
from agent_05_scriptwriter.checks.plan_checker import PlanChecker, PlanReport
from agent_05_scriptwriter.checks.results import CheckResult, failing_ids
from agent_05_scriptwriter.checks.script_validator import ValidationContext, validate_document
from agent_05_scriptwriter.checks.section_checker import SectionChecker
from agent_05_scriptwriter.contracts import (
    DocPromise,
    DocumentProvenance,
    Flags,
    HookBeat,
    OptionOut,
    OutCoverage,
    OutOmitted,
    OutSection,
    PlanHook,
    PlanOutput,
    PlanSection,
    PlanStepInput,
    Refusal,
    RunningSummary,
    Scene,
    ScriptDocument,
    ScriptDraftInput,
    ScriptDraftResult,
    SectionOutput,
    SectionPlanIn,
    SectionStepInput,
    ThumbnailBrief,
    Totals,
)
from agent_05_scriptwriter.errors import (
    MissingDependency,
    QualityRepeatedFailure,
)
from agent_05_scriptwriter.hooks import HookScore, select_hook
from agent_05_scriptwriter.llm.prompt_renderer import render
from agent_05_scriptwriter.llm.structured_caller import CallCounter, CallRecord, StructuredCaller
from agent_05_scriptwriter.observability import log_event
from agent_05_scriptwriter.pre.brief_mapper import BriefSet, map_briefs
from agent_05_scriptwriter.pre.speech_budget import hook_budget, scene_budget
from agent_05_scriptwriter.protocols import (
    CheckpointState,
    HookHistoryEntry,
    Ports,
    StepContext,
)
from agent_05_scriptwriter.refusal import map_refusal
from agent_05_scriptwriter.revision.router import RevisionPlan, route_feedback
from agent_05_scriptwriter.settings import Agent05Settings
from agent_05_scriptwriter.steps import doc_rebuild
from agent_05_scriptwriter.steps.common import (
    PromptSet,
    ResolvedInputs,
    StepOutcome,
    make_provenance,
    pre_checks,
    records_from_state,
    require_pack,
)
from agent_05_scriptwriter.text import speech_chars, word_count
from amw_adapters.llm import LlmAdapter
from amw_core.errors import AmwError, BudgetExhaustedError


@dataclass(frozen=True, slots=True)
class ScriptDraftRequest:
    ctx: StepContext
    input: ScriptDraftInput
    inputs: ResolvedInputs


@dataclass(slots=True)
class PlanView:
    """What assembly needs from the plan, whether freshly planned or rebuilt from a prior script."""

    promise: DocPromise
    hook_beats: list[HookBeat]
    hook_chart_id: str | None
    options: list[OptionOut]
    sections: list[PlanSection]
    concept_plan_ids: list[str]
    omitted: list[OutOmitted]
    description: str | None
    thumbnail: ThumbnailBrief | None


class _RefusedError(Exception):
    """Internal: a model refusal already mapped to an outcome."""

    def __init__(self, outcome: StepOutcome) -> None:
        super().__init__("refused")
        self.outcome = outcome


class ScriptDraftStep:
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

    # ------------------------------------------------------------------ entry point
    def run(self, req: ScriptDraftRequest) -> StepOutcome:
        ctx = req.ctx
        stored = self._p.idempotency.stored_output(ctx)
        if isinstance(stored, StepOutcome):
            stored.stored_output_returned = True
            return stored
        log_event("script_draft.started", org_id=ctx.org_id, task_id=ctx.task_id)
        checkpoint = self._p.checkpoints.latest(ctx)
        state: dict[str, Any] = dict(checkpoint.state) if checkpoint else {}
        last_step = checkpoint.step_key if checkpoint else None
        try:
            outcome = self._run(req, state)
        except _RefusedError as refused:
            outcome = refused.outcome
        except BudgetExhaustedError as exc:
            outcome = StepOutcome(
                "SUSPENDED",
                None,
                [],
                error=exc,
                wait_reason="AWAITING_BUDGET",
                checkpoint_step=state.get("last_step", last_step),
                records=records_from_state(state),
            )
        except AmwError as exc:
            log_event("script_draft.failed", code=exc.code, task_id=ctx.task_id)
            outcome = StepOutcome("FAILED", None, [], error=exc, records=records_from_state(state))
        if outcome.status == "SUCCEEDED" and not outcome.stored_output_returned:
            self._p.idempotency.complete(ctx, outcome)
        return outcome

    # ------------------------------------------------------------------ pipeline
    def _checkpoint(self, ctx: StepContext, state: dict[str, Any], step_key: str) -> None:
        state["last_step"] = step_key
        self._p.checkpoints.write(ctx, CheckpointState(step_key, json.loads(json.dumps(state))))

    def _run(self, req: ScriptDraftRequest, state: dict[str, Any]) -> StepOutcome:
        ctx, inp, res = req.ctx, req.input, req.inputs
        s = self._s
        pre = pre_checks(
            ctx,
            s,
            res,
            language=inp.language,
            active_rule_packs=inp.active_rule_packs,
            channel_category=inp.channel_category,
        )
        pack = require_pack(res)
        scanners: Scanners = self._scanners_for(res.lexicons)
        verdict = pack.topic_verdict
        if verdict is not None and verdict.verdict != "ALLOWED":
            reason = "RULE_WOULD_BE_BROKEN" if verdict.verdict == "BLOCKED" else "UNSAFE_CONTENT"
            refusal = Refusal(
                reason=reason,  # type: ignore[arg-type]
                message="the research pack topic verdict stops the script",
                missing_inputs=[],
                violated_rule_ids=list(verdict.violated_rule_ids),
            )
            raise _RefusedError(self._refusal_outcome(req, refusal, "plan", pre, []))
        briefs = map_briefs(pack, res.approvals)
        if not any(b.citation_refs for b in briefs.briefs):
            from agent_05_scriptwriter.errors import InsufficientInput

            raise InsufficientInput("the research pack has no usable cited note")
        if "pre" not in state:
            state["pre"] = {
                "script_id": res.new_script_id,
                "concept_map": briefs.concept_map,
                "version": self._p.scripts.next_version(ctx, inp.language),
            }
            self._checkpoint(ctx, state, "pre_done")
        script_id = state["pre"]["script_id"]
        version = int(state["pre"]["version"])
        records = records_from_state(state)
        if "assembled" in state:
            return self._persist(req, state, pre, records, scanners_results=[])
        history = [
            e.text
            for e in self._p.hook_history.read(ctx, s.hook_history_size)
            if e.channel_id == ctx.channel_id
        ]
        allow = list(res.brand_latin_allow_list or s.latin_allow_list_default)
        counter = CallCounter(used=len(records))
        caller = StructuredCaller(self._llm, self._p.ledger, self._p.budget, counter)
        revision = self._route(req)
        # ---- plan
        plan_checker = PlanChecker(s, scanners)
        if "plan" in state and state["plan"].get("reused"):
            view = self._view_from_prior(req)
        else:
            if "plan" in state:
                plan = PlanOutput.model_validate(state["plan"]["output"])
                report: PlanReport | None = plan_checker.check(
                    plan, self._plan_input(req, briefs, history, allow, None)
                )
            elif revision is not None and not revision.rerun_plan:
                state["plan"] = {"reused": True}
                self._checkpoint(ctx, state, "plan_done")
                plan, report = None, None
            else:
                plan, report = self._run_plan(
                    req, briefs, history, allow, plan_checker, caller, records, state, pre
                )
            view = (
                self._view_from_prior(req)
                if plan is None
                else self._view(plan, report, briefs, req)
            )
        self._checkpoint(ctx, state, "plan_done")
        log_event("script_draft.plan_done", count=len(view.options))
        # ---- charts and sections
        first_free = 2 if view.hook_chart_id else 1
        prior = res.prior_script if revision is not None else None
        section_scenes: dict[str, list[Scene]] = {}
        sec_checker = SectionChecker(s, scanners)
        terms_text = " ".join(x.text for b in view.hook_beats for x in b.sentences)
        used_charts: list[str] = [view.hook_chart_id] if view.hook_chart_id else []
        for index, sec in enumerate(view.sections):
            pool = section_pool(first_free + index * s.charts_per_section, s.charts_per_section)
            cached = state.setdefault("sections", {}).get(sec.section_id)
            reuse = self._reusable(prior, revision, index, sec)
            if cached is not None:
                scenes = SectionOutput.model_validate(cached["output"]).scenes
            elif reuse and prior is not None:
                scenes = doc_rebuild.section_scenes(prior, sec.section_id)
                state["sections"][sec.section_id] = {
                    "output": SectionOutput(
                        section_id=sec.section_id, scenes=scenes, refusal=None
                    ).model_dump(mode="json"),
                    "reused": True,
                }
            else:
                feedback = revision.feedback_per_section.get(sec.section_id) if revision else None
                previous = (
                    doc_rebuild.section_text(prior, sec.section_id)
                    if prior is not None and feedback
                    else None
                )
                scenes = self._section_step(
                    req,
                    view.sections,
                    sec,
                    index,
                    briefs,
                    allow,
                    pool,
                    used_charts,
                    terms_text,
                    feedback,
                    previous,
                    sec_checker,
                    caller,
                    records,
                    state,
                    pre,
                )
            section_scenes[sec.section_id] = list(scenes)
            used_charts += [c.chart_request.chart_id for c in scenes if c.chart_request]
            terms_text += " " + " ".join(x.text for sc in scenes for x in sc.sentences)
            self._checkpoint(ctx, state, f"section_{sec.section_id}_done")
            stop = self._p.control.stop_requested(ctx)
            if stop in ("DRAIN", "PAUSE") and index < len(view.sections) - 1:
                return StepOutcome(
                    "SUSPENDED",
                    None,
                    [],
                    wait_reason=stop,
                    checkpoint_step=f"section_{sec.section_id}_done",
                    records=records,
                )
        # ---- assemble and validate
        provenance = DocumentProvenance(
            prompt_ids={
                "plan": self._prompts.plan.prompt_id,
                "section": self._prompts.section.prompt_id,
            },
            prompt_sha256={
                self._prompts.plan.prompt_id: self._prompts.plan.sha256,
                self._prompts.section.prompt_id: self._prompts.section.sha256,
            },
            rule_pack_versions={k: v.version for k, v in res.rule_packs.items()},
            config_key_families=[s.plan.config_key_family, s.section.config_key_family],
            section_sha256={},
        )
        rate = s.rate_for(inp.language)
        assembled = assemble(
            AssemblyInput(
                script_id=script_id,
                job_id=ctx.job_id,
                channel_id=ctx.channel_id,
                language=inp.language,
                version=version,
                iteration=inp.iteration,
                promise=view.promise,
                hook_beats=view.hook_beats,
                hook_chart_id=view.hook_chart_id,
                sections=view.sections,
                section_scenes=section_scenes,
                concept_map=briefs.concept_map,
                hook_options=view.options,
                omitted=view.omitted,
                description_draft=view.description,
                thumbnail_brief=view.thumbnail,
                rate_cps=rate,
                disclaimer_template=res.disclaimer_template,
                disclaimer_placements=self._placements(inp.channel_category, res),
                provenance=provenance,
            )
        )
        log_event("script_draft.assembled", segments=len(assembled.document.segments))
        validation = validate_document(
            assembled.document,
            ValidationContext(
                min_hook_options=s.hooks_min_options,
                rate_cps=rate,
                window_ms=s.hook_window_ms,
                briefs={b.concept_id: b for b in briefs.briefs},
                concept_plan_ids=view.concept_plan_ids,
                pack_concept_ids=[c.concept_id for c in pack.concepts],
                target_duration_ms=inp.topic.target_duration_ms,
                duration_tolerance=s.duration_tolerance,
                disclaimer_required=inp.channel_category in s.disclaimer_categories,
                disclaimer_text_sha256=(
                    _sha(res.disclaimer_template.text) if res.disclaimer_template else None
                ),
                expected_disclaimer_slots=len(self._placements(inp.channel_category, res)),
                beat_tolerance=s.hook_beat_tolerance,
            ),
        )
        blocking = failing_ids(validation)
        if blocking:
            raise QualityRepeatedFailure(
                "whole-script checks failed", details={"check_ids": blocking}
            )
        state["assembled"] = {
            "document": assembled.document.model_dump(mode="json"),
            "sha256": assembled.sha256,
            "splits": assembled.split_count,
            "validation": [
                {
                    "check_id": r.check_id,
                    "verdict": r.verdict,
                    "blocking": r.blocking,
                    "message": r.message,
                }
                for r in validation
            ],
        }
        self._checkpoint(ctx, state, "assembled")
        return self._persist(req, state, pre, records, scanners_results=validation)

    # ------------------------------------------------------------------ steps
    def _section_step(
        self,
        req: ScriptDraftRequest,
        sections: list[PlanSection],
        sec: PlanSection,
        index: int,
        briefs: BriefSet,
        allow: list[str],
        pool: list[str],
        used_charts: list[str],
        previous_terms_text: str,
        feedback: Any,
        previous_text: str | None,
        checker: SectionChecker,
        caller: StructuredCaller,
        records: list[CallRecord],
        state: dict[str, Any],
        pre: list[CheckResult],
    ) -> list[Scene]:
        ctx, inp, res, s = req.ctx, req.input, req.inputs, self._s
        done = [x.section_id for x in sections[:index]]
        introduced = [b.concept_id for b in briefs.briefs if b.term_local in previous_terms_text]
        tail = _tail(state, done)
        step_in = SectionStepInput(
            language=inp.language,
            channel_category=inp.channel_category,
            owner_sebi_registration="UNREGISTERED",
            active_rule_packs=inp.active_rule_packs,
            video_kind=inp.video_kind,
            section_plan=SectionPlanIn(
                section_id=sec.section_id,
                section_kind=sec.section_kind,
                heading_local=sec.heading_local,
                heading_en=sec.heading_en,
                purpose=sec.purpose,
                concept_ids=sec.concept_ids,
                needs_interrupt=sec.needs_interrupt,
                is_case_study=sec.section_kind == "CASE_STUDY_HISTORICAL",
            ),
            concept_briefs=[b for b in briefs.briefs if b.concept_id in sec.concept_ids],
            available_citations=briefs.available_citations,
            latin_allow_list=allow,
            running_summary=RunningSummary(
                sections_done=done, terms_introduced=introduced, previous_tail=tail
            ),
            scene_budget=scene_budget(
                share_permille=sec.share_permille,
                target_ms=inp.topic.target_duration_ms,
                rate_cps=s.rate_for(inp.language),
                size_tolerance=s.size_tolerance,
                max_scenes=s.max_scenes_per_section,
                max_change_gap_ms=s.max_change_gap_ms,
            ),
            chart_ids_available=pool,
            revision_feedback=feedback or None,
            previous_text=previous_text,
        )
        refs = sorted({c for b in step_in.concept_briefs for c in b.citation_refs})
        cited = self._p.chunks.read_cited(ctx, refs)
        rendered = render(self._prompts.section, res.rule_packs, inp.active_rule_packs, step_in)
        step = caller.run_step(
            ctx,
            model_cls=SectionOutput,
            step=s.section,
            step_key=f"section_{sec.section_id}",
            rendered=rendered,
            language=inp.language,
            check=lambda o: checker.check(
                o, step_in, cited_texts=cited, used_chart_ids=used_charts
            ),
            is_refusal=lambda o: o.refusal is not None,
        )
        records += step.records
        state["calls"] = [r.as_dict() for r in records]
        if step.parsed.refusal is not None:
            raise _RefusedError(
                self._refusal_outcome(
                    req, step.parsed.refusal, f"section_{sec.section_id}", pre, records
                )
            )
        state["sections"][sec.section_id] = {"output": step.parsed.model_dump(mode="json")}
        log_event(
            "script_draft.section_done",
            section_id=sec.section_id,
            scenes=len(step.parsed.scenes),
            repair=step.repaired,
        )
        return step.parsed.scenes

    def _plan_input(
        self,
        req: ScriptDraftRequest,
        briefs: BriefSet,
        history: list[str],
        allow: list[str],
        feedback: Any,
    ) -> PlanStepInput:
        inp, s = req.input, self._s
        budget = hook_budget(s.rate_for(inp.language), s.hook_window_ms, s.hook_min_fill_ratio)
        return PlanStepInput(
            language=inp.language,
            channel_category=inp.channel_category,
            owner_sebi_registration="UNREGISTERED",
            active_rule_packs=inp.active_rule_packs,
            video_kind=inp.video_kind,
            topic=inp.topic,
            concept_briefs=briefs.briefs,
            available_citations=briefs.available_citations,
            latin_allow_list=allow,
            speech_budget=budget.budget,
            min_hook_options=s.hooks_min_options,
            max_hook_options=s.hooks_max_options,
            max_sections=s.max_sections,
            hook_history=history,
            course_chapter_pointer=inp.course_chapter_pointer,
            revision_feedback=feedback,
        )

    def _options(
        self, plan: PlanOutput, report: PlanReport | None, req: ScriptDraftRequest
    ) -> list[OptionOut]:
        failures = report.option_failures if report else {h.hook_id: [] for h in plan.hooks}
        scores = [
            HookScore(
                h.hook_id,
                h.rubric.viewer_relevance,
                h.rubric.curiosity_without_clickbait,
                not failures.get(h.hook_id),
            )
            for h in plan.hooks
        ]
        selection = select_hook(scores, plan.selected_hook_id, self._s.hooks_min_options)
        if selection.selected is None:
            raise QualityRepeatedFailure("too few qualified hook options")
        if selection.mismatch:
            log_event("agent_05.hook_selection_mismatch", hook_id=selection.selected)
        return [
            OptionOut(
                hook_id=h.hook_id,
                hook_style=h.hook_style,
                rubric=h.rubric,
                total=selection.totals[h.hook_id],
                qualified=not failures.get(h.hook_id),
                disqualified_by=list(failures.get(h.hook_id, [])),
                segment_ids=["s0"] if h.hook_id == selection.selected else [],
            )
            for h in plan.hooks
        ]

    # ------------------------------------------------------------------ revision
    def _route(self, req: ScriptDraftRequest) -> RevisionPlan | None:
        inp, res = req.input, req.inputs
        if inp.revision is None:
            return None
        prior = res.prior_script
        if prior is None or res.prior_script_sha256 != inp.revision.prior_script.sha256:
            raise MissingDependency("the prior script is missing or its hash differs")
        return route_feedback(doc_rebuild.routing_map(prior), inp.revision.feedback)

    def _run_plan(
        self,
        req: ScriptDraftRequest,
        briefs: BriefSet,
        history: list[str],
        allow: list[str],
        plan_checker: PlanChecker,
        caller: StructuredCaller,
        records: list[CallRecord],
        state: dict[str, Any],
        pre: list[CheckResult],
    ) -> tuple[PlanOutput, PlanReport]:
        ctx, inp, res, s = req.ctx, req.input, req.inputs, self._s
        feedback = list(inp.revision.feedback) if inp.revision else None
        plan_in = self._plan_input(req, briefs, history, allow, feedback)
        holder: dict[str, PlanReport] = {}

        def check_plan(out: PlanOutput) -> list[CheckResult]:
            holder["r"] = plan_checker.check(out, plan_in)
            return holder["r"].results

        rendered = render(self._prompts.plan, res.rule_packs, inp.active_rule_packs, plan_in)
        step = caller.run_step(
            ctx,
            model_cls=PlanOutput,
            step=s.plan,
            step_key="plan",
            rendered=rendered,
            language=inp.language,
            check=check_plan,
            is_refusal=lambda o: o.refusal is not None,
        )
        records += step.records
        state["calls"] = [r.as_dict() for r in records]
        if step.parsed.refusal is not None:
            raise _RefusedError(
                self._refusal_outcome(req, step.parsed.refusal, "plan", pre, records)
            )
        state["plan"] = {"output": step.parsed.model_dump(mode="json")}
        return step.parsed, holder["r"]

    def _view(
        self, plan: PlanOutput, report: PlanReport | None, briefs: BriefSet, req: ScriptDraftRequest
    ) -> PlanView:
        assert plan.title_promise is not None  # noqa: S101 - not a refusal
        options = self._options(plan, report, req)
        selected = next(o.hook_id for o in options if o.segment_ids)
        hook = next(h for h in plan.hooks if h.hook_id == selected)
        alloc = allocate_charts(
            {h.hook_id: _hook_chart(h) for h in plan.hooks},
            selected,
            self._s.charts_per_section * len(plan.sections),
        )
        return PlanView(
            promise=DocPromise(**plan.title_promise.model_dump()),
            hook_beats=hook.beats,
            hook_chart_id=alloc.hook_chart,
            options=options,
            sections=list(plan.sections),
            concept_plan_ids=[c.concept_id for c in plan.concept_plan],
            omitted=[
                OutOmitted(
                    concept_id=o.concept_id,
                    pack_concept_id=briefs.concept_map[o.concept_id],
                    reason=o.reason,
                )
                for o in plan.omitted_concepts
            ],
            description=plan.description_draft,
            thumbnail=plan.thumbnail_brief,
        )

    def _view_from_prior(self, req: ScriptDraftRequest) -> PlanView:
        """An unchanged plan, rebuilt from the prior script document (partial revision)."""
        prior = req.inputs.prior_script
        if prior is None:
            raise MissingDependency("the prior script is missing")
        beats = doc_rebuild.hook_beats(prior)
        charts = [b.chart_request.chart_id for b in beats if b.chart_request]
        return PlanView(
            promise=prior.promise,
            hook_beats=beats,
            hook_chart_id=charts[0] if charts else None,
            options=list(prior.hook_options),
            sections=[doc_rebuild.plan_section(x) for x in prior.sections],
            concept_plan_ids=sorted(
                {r.concept_id for seg in prior.segments for r in seg.concept_refs}
            ),
            omitted=list(prior.omitted_concepts),
            description=prior.description_draft,
            thumbnail=prior.thumbnail_brief,
        )

    def _reusable(
        self,
        prior: ScriptDocument | None,
        revision: RevisionPlan | None,
        index: int,
        sec: PlanSection,
    ) -> bool:
        if prior is None or revision is None or sec.section_id in revision.sections_to_rewrite:
            return False
        same_index = (
            index < len(prior.sections) and prior.sections[index].section_id == sec.section_id
        )
        return same_index and doc_rebuild.plan_section(prior.sections[index]) == sec

    def _placements(self, category: str, res: ResolvedInputs) -> list[str]:
        if category not in self._s.disclaimer_categories:
            return []
        from agent_05_scriptwriter.assemble.parts import disclaimer_plan

        return disclaimer_plan(
            category=category,
            required_categories=self._s.disclaimer_categories,
            template=res.disclaimer_template,
            placements=self._s.disclaimer_placements,
        )

    # ------------------------------------------------------------------ outcomes
    def _refusal_outcome(
        self,
        req: ScriptDraftRequest,
        refusal: Refusal,
        step: str,
        pre: list[CheckResult],
        records: list[CallRecord],
    ) -> StepOutcome:
        from agent_05_scriptwriter.steps.common import make_provenance

        pre_results = [r.to_validation_result() for r in pre if r.check_id.startswith("a05.pre.")]
        mapped = map_refusal(refusal, step, pre_results)
        log_event("script_draft.refused", reason=refusal.reason, rule_ids=refusal.violated_rule_ids)
        if mapped.status == "FAILED":
            assert mapped.error_code is not None  # noqa: S101
            return StepOutcome(
                "FAILED",
                None,
                [],
                error=AmwError.for_code(mapped.error_code)(
                    "model refusal", details={"reason": refusal.reason}
                ),
                records=records,
            )
        inp = req.input
        result = ScriptDraftResult(
            script_id=None,
            version=1,
            iteration=inp.iteration,
            language=inp.language,
            verdict=mapped.verdict,  # type: ignore[arg-type]
            title_promise=None,
            hook_options=[],
            selected_hook_id=None,
            sections=[],
            concept_coverage=[],
            omitted_concepts=[],
            chart_requests=[],
            description_draft=None,
            thumbnail_brief=None,
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
            provenance=make_provenance(
                self._prompts, {}, [self._s.plan.config_key_family], records
            ),
        )
        outcome = StepOutcome("SUCCEEDED", result, pre, records=records)
        outcome.validation_results = [*pre, *_as_results(mapped.results)]
        outcome.refusal_rule_ids = list(refusal.violated_rule_ids)
        return outcome

    def _persist(
        self,
        req: ScriptDraftRequest,
        state: dict[str, Any],
        pre: list[CheckResult],
        records: list[CallRecord],
        scanners_results: list[CheckResult],
    ) -> StepOutcome:
        ctx, inp, res, s = req.ctx, req.input, req.inputs, self._s
        asm = state["assembled"]
        document = ScriptDocument.model_validate(asm["document"])
        from agent_05_scriptwriter.assemble.assembler import canonical_bytes

        content = canonical_bytes(document.model_dump(mode="json"))
        sha = asm["sha256"]
        if scanners_results == []:
            scanners_results = [
                CheckResult(v["check_id"], v["verdict"], v["blocking"], v["message"])
                for v in asm["validation"]
            ]
        parent_id = res.prior_script.script_id if res.prior_script else None
        est = (
            None
            if any(x.est_duration_ms is None for x in document.segments)
            else sum(x.est_duration_ms or 0 for x in document.segments)
        )
        saved = self._p.scripts.save(
            ctx,
            script_id=document.script_id,
            version=document.version,
            iteration=inp.iteration,
            language=inp.language,
            content=content,
            sha256=sha,
            parent_script_id=parent_id,
            segment_count=len(document.segments),
            word_count=sum(word_count(x.text) for x in document.segments),
            est_duration_ms=est,
            prompt_id=self._prompts.plan.prompt_id,
        )
        selected = next(o for o in document.hook_options if o.segment_ids)
        first_sentence = document.segments[0].text
        self._p.hook_history.write(
            ctx, [HookHistoryEntry(ctx.channel_id, first_sentence, selected.hook_style, ctx.job_id)]
        )
        self._p.audit.record(
            ctx, "script_draft.persisted", {"script_id": saved.script_id, "version": saved.version}
        )
        self._checkpoint(ctx, state, "persisted")
        result = _build_result(
            document, saved.uri, sha, records, self._prompts, s, state, len(records)
        )
        results = [*pre, *scanners_results]
        log_event("script_draft.completed", script_id=saved.script_id, version=saved.version)
        return StepOutcome(
            "SUCCEEDED",
            result,
            results,
            saved=saved,
            records=records,
            document_bytes=content,
        )


# ---------------------------------------------------------------------- helpers
def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_results(validation_results: list[Any]) -> list[CheckResult]:
    return [
        CheckResult(v.check_id, v.verdict.value, v.blocking, v.message) for v in validation_results
    ]


def _tail(state: dict[str, Any], done: list[str]) -> list[str]:
    """Last sentences of the previous section (code-built running summary, 11.1)."""
    if not done:
        return []
    out = SectionOutput.model_validate(state["sections"][done[-1]]["output"])
    sentences = [x.text[:500] for sc in out.scenes for x in sc.sentences]
    return sentences[-5:]


def _hook_chart(hook: PlanHook) -> str | None:
    return next((b.chart_request.chart_id for b in hook.beats if b.chart_request), None)


def _build_result(
    doc: ScriptDocument,
    uri: str,
    sha: str,
    records: list[CallRecord],
    prompts: PromptSet,
    s: Agent05Settings,
    state: dict[str, Any],
    llm_calls: int,
) -> ScriptDraftResult:
    segs = doc.segments
    by_section: dict[str, list[str]] = {}
    for seg in segs:
        if seg.section_id:
            by_section.setdefault(seg.section_id, []).append(seg.segment_id)
    seg_index = {x.segment_id: x for x in segs}
    out_sections: list[OutSection] = []
    for sec in doc.sections:
        ids = by_section[sec.section_id]
        first, last = seg_index[ids[0]], seg_index[ids[-1]]
        durations = [seg_index[i].est_duration_ms for i in ids]
        out_sections.append(
            OutSection(
                section_id=sec.section_id,
                section_kind=sec.section_kind,
                heading_local=sec.heading_local,
                heading_en=sec.heading_en,
                share_permille=sec.share_permille,
                first_segment_id=first.segment_id,
                last_segment_id=last.segment_id,
                est_start_ms=first.est_start_ms,
                est_duration_ms=None
                if any(d is None for d in durations)
                else sum(d or 0 for d in durations),
                sha256=doc.provenance.section_sha256[sec.section_id],
            )
        )
    pack_of = {o.concept_id: o.pack_concept_id for o in doc.omitted_concepts}
    cov: dict[str, OutCoverage] = {}
    for seg in segs:
        for ref in seg.concept_refs:
            entry = cov.setdefault(
                ref.concept_id,
                OutCoverage(
                    concept_id=ref.concept_id,
                    pack_concept_id=ref.pack_concept_id,
                    taught_in_section_ids=[],
                    segment_ids=[],
                ),
            )
            if seg.section_id and seg.section_id not in entry.taught_in_section_ids:
                entry.taught_in_section_ids.append(seg.section_id)
            entry.segment_ids.append(seg.segment_id)
    _ = pack_of
    method = [x.segment_id for x in segs if x.method_label]
    ests = [x.est_duration_ms for x in segs]
    return ScriptDraftResult(
        script_id=doc.script_id,
        version=doc.version,
        iteration=doc.iteration,
        language=doc.language,
        verdict="ALLOWED",
        title_promise=doc.promise,
        hook_options=doc.hook_options,
        selected_hook_id=next(o.hook_id for o in doc.hook_options if o.segment_ids),
        sections=out_sections,
        concept_coverage=list(cov.values()),
        omitted_concepts=doc.omitted_concepts,
        chart_requests=doc.chart_requests,
        description_draft=doc.description_draft,
        thumbnail_brief=doc.thumbnail_brief,
        totals=Totals(
            segment_count=len(segs),
            word_count=sum(word_count(x.text) for x in segs),
            speech_chars=sum(speech_chars(x.text) for x in segs),
            est_duration_ms=None if any(e is None for e in ests) else sum(e or 0 for e in ests),
            llm_calls=llm_calls,
        ),
        flags=Flags(
            method_used=bool(method),
            method_segment_ids=method,
            hypothetical_segment_ids=[x.segment_id for x in segs if x.hypothetical_example],
            course_pointer_present=any(x.section_kind == "COURSE_POINTER" for x in doc.sections),
        ),
        script_document={"uri": uri, "sha256": sha},  # type: ignore[arg-type]
        refusal=None,
        provenance=make_provenance(
            prompts,
            dict(doc.provenance.rule_pack_versions),
            list(doc.provenance.config_key_families),
            records,
        ),
    )
