"""ShotPlanStep (F-27): P1..P10 of blueprint 4.1 for task ``agent_09.shot_plan``.

Dependencies are injected (27 section 7.1): the LLM adapter, the prompt store, the call recorder
(ledger) and the config. The step reads no DB and no storage itself; the worker resolves refs
(``persistence.load_model``) and hands over typed documents. Tenant isolation: every org and URI
is checked first (``gates.assert_tenant_consistent``); the LLM receives the sanitised slot data of
one tenant only; no content reaches a log (counts, IDs, hashes only).
"""

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from agent_09_video_director.assemble import (
    Assembled,
    AssembleInput,
    assemble_plan,
    canonical_json,
    direction_from_shot,
    plan_hash,
)
from agent_09_video_director.checks import CheckContext, FeedbackItem, run_all
from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import (
    AspectRatio,
    BrandKit,
    Capabilities,
    DirectionInput,
    Limits,
    NarrationTimeline,
    Origin,
    Provenance,
    RevisionFeedback,
    ScriptDoc,
    Shot,
    ShotPlan,
    Slot,
    StepLimits,
    TailItem,
)
from agent_09_video_director.direction.batcher import Batch, make_batches
from agent_09_video_director.direction.client import (
    Breaker,
    CallMeter,
    CallRecorder,
    DirectionClient,
)
from agent_09_video_director.direction.prompt import PROMPT_ID, PromptStore
from agent_09_video_director.direction.runner import (
    Accepted,
    DirectionResult,
    ResumeState,
    run_direction,
)
from agent_09_video_director.gates import assert_tenant_consistent, script_gate
from agent_09_video_director.problems import input_invalid
from agent_09_video_director.skeleton import build_skeleton, direction_slots
from agent_09_video_director.timeline.hook import HookInfo, TimedSegment, analyze_hook
from agent_09_video_director.timeline.rebase import rebase_shots
from agent_09_video_director.timeline.timemap import TimeMap, build_time_map
from amw_adapters.llm.protocol import LlmAdapter
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import CheckVerdict
from amw_core.errors import BudgetExhaustedError, ConfigInvalidError, QualityRepeatedFailureError

log = logging.getLogger("agent_09")


@dataclass(frozen=True, slots=True)
class Verification:
    verified_script_sha256: str
    stage_verdict: str
    approval_approved: bool = False
    claim_blocked: bool = False
    script_status: str = "ACTIVE"


@dataclass(frozen=True, slots=True, kw_only=True)
class ShotPlanRequest:
    org_id: str
    task_id: str
    declared_orgs: Sequence[str]
    uris: Sequence[str]
    production_type_key: str
    aspect_ratio: AspectRatio
    script: ScriptDoc
    script_sha256: str
    script_ref_sha256: str
    verification: Verification
    timeline: NarrationTimeline
    timeline_sha256: str
    brand: BrandKit
    channel_category: str
    banned_subjects: Sequence[str] = ()
    limits: Limits = field(default_factory=Limits)
    rule_packs: Mapping[str, str] = field(default_factory=dict)
    rule_pack_versions: Mapping[str, str] = field(default_factory=dict)
    previous_timeline: NarrationTimeline | None = None
    """The timeline ``previous_plan`` was made on; required when the timeline hash changed."""
    iteration: int = 0
    previous_plan: ShotPlan | None = None
    feedback: Sequence[RevisionFeedback] = ()
    parent_shots: Mapping[str, Sequence[str]] | None = None
    max_calls: int
    max_cost_micros: int
    worst_case_call_micros: int
    """No defaults: the S4 reservation of the task (resource_budget) is required config."""


@dataclass(slots=True)
class StepResult:
    plan: ShotPlan
    plan_sha256: str
    results: list[ValidationResult]
    meter: CallMeter
    state: ResumeState
    guard_hits: dict[str, int]
    accepted: dict[str, Accepted]


class ShotPlanStep:
    def __init__(
        self,
        *,
        llm: LlmAdapter,
        prompts: PromptStore,
        recorder: CallRecorder,
        cfg: Agent09Config,
        breaker: Breaker | None = None,
    ) -> None:
        self._llm, self._prompts, self._recorder = llm, prompts, recorder
        self._cfg, self._breaker = cfg, breaker

    # ------------------------------------------------------------------ preconditions (P1-P4)
    def _preconditions(self, req: ShotPlanRequest) -> tuple[TimeMap, HookInfo]:
        assert_tenant_consistent(req.org_id, declared_orgs=req.declared_orgs, uris=req.uris)
        pair_ok = (req.production_type_key, req.aspect_ratio) in {
            ("CHANNEL_LONG_FORM", AspectRatio.LANDSCAPE),
            ("SHORTS", AspectRatio.PORTRAIT),
        }
        if not pair_ok or req.script.aspect_ratio is not req.aspect_ratio:
            raise input_invalid("ASPECT_PRODUCTION_TYPE")
        if (req.iteration >= 1) != (req.previous_plan is not None):
            raise input_invalid("PREVIOUS_PLAN_REF")
        script_gate(
            script_sha256=req.script_sha256,
            ref_sha256=req.script_ref_sha256,
            verified_script_sha256=req.verification.verified_script_sha256,
            stage_verdict=req.verification.stage_verdict,
            approval_approved=req.verification.approval_approved,
            claim_blocked=req.verification.claim_blocked,
            script_status=req.verification.script_status,
        )
        if req.max_calls < 1 or req.max_cost_micros < 1 or req.worst_case_call_micros < 1:
            raise ConfigInvalidError("resource_budget / reservation config missing or not positive")
        tm = build_time_map([s.segment_id for s in req.script.segments], req.timeline)
        timed = [
            TimedSegment(s.segment_id, s.kind, *tm.spans[s.segment_id]) for s in req.script.segments
        ]
        hook = analyze_hook(timed, req.aspect_ratio, self._cfg.hook_window_ms)
        return tm, hook

    # ------------------------------------------------------------------ rebase (FR-16)
    def _previous_shots(self, req: ShotPlanRequest, tm: TimeMap) -> Sequence[Shot]:
        """Previous shots, rebased to the new measured timeline when its hash changed (F-24)."""
        prev = req.previous_plan
        if prev is None:
            return ()
        if prev.narration_timeline_sha256 == req.timeline_sha256:
            return prev.shots
        if req.previous_timeline is None:
            raise input_invalid("PREVIOUS_TIMELINE_MISSING")
        old = {
            s.segment_id: (s.start_ms, s.end_ms)
            for s in req.previous_timeline.segments
            if s.start_ms is not None and s.end_ms is not None
        }
        common = {k: v for k, v in old.items() if k in tm.spans}
        if not common:
            raise input_invalid("REBASE_LIMIT")
        return rebase_shots(prev.shots, common, {k: tm.spans[k] for k in common}, self._cfg)

    # ------------------------------------------------------------------ revision reuse
    @staticmethod
    def _reuse(
        req: ShotPlanRequest, slots: Sequence[Slot], prev_shots: Sequence[Shot]
    ) -> dict[str, Accepted]:
        """Directions of untouched shots of the previous plan are kept (24 section 3.3 rule 6)."""
        named = {sid for f in req.feedback for sid in f.shot_ids}
        out: dict[str, Accepted] = {}
        for slot in slots:
            if slot.origin is not Origin.MODEL:
                continue
            shot_id = f"sh{slot.slot_id[2:]}"
            old = next(
                (
                    p
                    for p in prev_shots
                    if p.shot_id == shot_id
                    and p.scene_id == slot.scene_id
                    and p.segment_ids == slot.segment_ids
                ),
                None,
            )
            if old is None or old.shot_id in named or old.origin is Origin.FALLBACK:
                continue
            direction = direction_from_shot(old).model_copy(update={"slot_id": slot.slot_id})
            out[slot.slot_id] = Accepted(direction=direction, origin=old.origin)
        return out

    def _input_hash(self, req: ShotPlanRequest, slot_ids: Sequence[str]) -> str:
        """Binds a checkpoint to its inputs and config (blueprint 16 rule 1)."""
        material = {
            "script": req.script_sha256,
            "timeline": req.timeline_sha256,
            "cfg": json.loads(self._cfg.model_dump_json()),
            "aspect": req.aspect_ratio.value,
            "limits": json.loads(req.limits.model_dump_json()),
            "banned": list(req.banned_subjects),
            "iteration": req.iteration,
            "packs": dict(req.rule_pack_versions),
            "slots": list(slot_ids),
        }
        return hashlib.sha256(canonical_json(material).encode()).hexdigest()

    # ------------------------------------------------------------------ run
    def run(
        self,
        req: ShotPlanRequest,
        *,
        resume: ResumeState | None = None,
        checkpoint: Callable[[ResumeState], None] | None = None,
    ) -> StepResult:
        cfg = self._cfg
        tm, hook = self._preconditions(req)
        slots = build_skeleton(req.script, tm, hook, cfg, req.limits)
        prev_shots = self._previous_shots(req, tm)
        reused = self._reuse(req, slots, prev_shots)
        input_hash = self._input_hash(req, [x.slot_id for x in slots])
        dslots = [
            s for s in direction_slots(slots, req.script, tm, req.limits) if s.slot_id not in reused
        ]
        batches = make_batches(dslots, cfg.llm_batch_slots)
        worst_calls = len(batches) * (2 + cfg.llm_max_repairs_per_batch)
        if batches and (
            worst_calls > req.max_calls
            or worst_calls * req.worst_case_call_micros > req.max_cost_micros
        ):
            raise BudgetExhaustedError("reservation does not cover the worst case of the plan")
        meter = CallMeter(req.max_calls, req.max_cost_micros, req.worst_case_call_micros)
        client = DirectionClient(
            llm=self._llm,
            cfg=cfg,
            meter=meter,
            recorder=self._recorder,
            org_id=req.org_id,
            task_id=req.task_id,
            language=req.script.language,
            breaker=self._breaker,
        )

        def base(batch: Batch, tail: Sequence[TailItem]) -> DirectionInput:
            return DirectionInput(
                batch_id=batch.batch_id,
                language=req.script.language,
                channel_category=req.channel_category,
                aspect_ratio=req.aspect_ratio,
                banned_subjects=tuple(req.banned_subjects),
                limits=StepLimits(
                    max_intent_chars=cfg.llm_max_intent_chars,
                    max_rationale_chars=cfg.llm_max_rationale_chars,
                ),
                capabilities=Capabilities(
                    ai_video_allowed=req.limits.ai_video_allowed_ms > 0 and cfg.tier_d_enabled,
                    still_allowed=req.limits.ai_still_allowed,
                    sound_cue_available=req.limits.sfx_library_enabled,
                ),
                previous_tail=tuple(tail),
                slots=batch.slots,
            )

        prompt_text = self._prompts.get(PROMPT_ID)
        result: DirectionResult = run_direction(
            batches=batches,
            base=base,
            prompt_text=prompt_text,
            packs=req.rule_packs,
            client=client,
            cfg=cfg,
            resume=resume,
            checkpoint=checkpoint,
            input_sha256=input_hash,
        )
        accepted = {**reused, **result.accepted}
        model_slots = [s for s in slots if s.origin is Origin.MODEL]
        fallbacks = sum(1 for s in model_slots if accepted[s.slot_id].origin is Origin.FALLBACK)
        if (
            cfg.fallback_max_share_permille is not None
            and model_slots
            and fallbacks * 1000 > cfg.fallback_max_share_permille * len(model_slots)
        ):
            raise QualityRepeatedFailureError(
                "too many slots ended as fallback", details={"violations": ["FALLBACK_SHARE"]}
            )
        ainp = AssembleInput(
            script=req.script,
            script_sha256=req.script_sha256,
            timeline_sha256=req.timeline_sha256,
            tm=tm,
            hook=hook,
            slots=slots,
            accepted=accepted,
            brand=req.brand,
            limits=req.limits,
            cfg=cfg,
            iteration=req.iteration,
            refusal=result.refusal,
            parent_shots=req.parent_shots,
        )
        assembled: Assembled = assemble_plan(ainp)
        plan = assembled.plan.model_copy(
            update={
                "provenance": Provenance(
                    prompt_id=PROMPT_ID,
                    prompt_sha256=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
                    rule_pack_versions=dict(req.rule_pack_versions),
                    config_key_families=(
                        "agent_09.*",
                        "qc.*",
                        "llm.agent_09.shot_plan.direction.*",
                    ),
                    calls=tuple(meter.call_log),
                )
            }
        )
        ctx = CheckContext(
            plan=plan,
            script=req.script,
            tm=tm,
            cfg=cfg,
            limits=req.limits,
            channel_category=req.channel_category,
            accepted=accepted,
            slot_ids=[s.slot_id for s in slots],
            banned_subjects=req.banned_subjects,
            jl_eligible_count=assembled.jl_eligible_count,
            feedback=tuple(
                FeedbackItem(f.check_id, f.shot_ids, f.measured, f.threshold) for f in req.feedback
            ),
            previous_plan=req.previous_plan,
            cost=(meter.spent_micros, req.max_cost_micros, meter.calls, req.max_calls),
            rerun_hash=lambda: plan_hash(assemble_plan(ainp).plan),
        )
        results = run_all(ctx)
        failed = [r.check_id for r in results if r.blocking and r.verdict is not CheckVerdict.PASS]
        log.info("plan.checks", extra={"shots": len(plan.shots), "failed": len(failed)})
        if failed:
            raise QualityRepeatedFailureError(
                "blocking plan checks failed", details={"violations": failed}
            )
        return StepResult(
            plan, plan_hash(plan), results, meter, result.state, result.guard_hits, accepted
        )
