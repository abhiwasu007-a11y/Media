"""Task Output layer (blueprint 8, F-27): ``agent_09.shot_plan.output`` payload and 03 envelope."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from agent_09_video_director.contracts import (
    AspectRatio,
    AudioPlan,
    Chapter,
    DeliberateHold,
    HookFacts,
    InterruptSummary,
    JlCutSummary,
    Model,
    Provenance,
    Refusal,
    ScriptDoc,
    Stats,
    TierBudget,
)
from agent_09_video_director.persistence import OutputRefData
from agent_09_video_director.step import StepResult
from agent_09_video_director.views import Views, build_views
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
)
from amw_core.enums import NextActionType, OutputRefKind, OutputStatus

SCHEMA = "agent_09.shot_plan.output"
SCHEMA_VERSION = "1.0.0"


class PlanRef(Model):
    """The four fields of Agent 08's ``shot_plan_ref``; the orchestrator copies them unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    uri: str
    sha256: str
    schema_: Literal["agent_09.shot_plan.output"] = Field(alias="schema")
    schema_version: Literal["1.0.0"]


class ShotPlanPayload(Model):
    """``payload.data``: the summary and the views; shots and overlays live in the blob."""

    plan_ref: PlanRef
    script_id: str
    script_version: int
    script_sha256: str
    language: str
    aspect_ratio: AspectRatio
    iteration: int
    timing_basis: Literal["MEASURED"]
    narration_timeline_sha256: str
    content_end_ms: int
    total_duration_ms: int
    hook: HookFacts
    audio_plan: AudioPlan
    chapters: tuple[Chapter, ...]
    deliberate_hold: tuple[DeliberateHold, ...]
    deliberate_black: tuple[()]
    interrupts: tuple[InterruptSummary, ...]
    jl_cuts: tuple[JlCutSummary, ...]
    tier_budget: TierBudget
    views: Views
    stats: Stats
    refusal: Refusal | None
    provenance: Provenance | None


def build_payload(result: StepResult, script: ScriptDoc, ref: OutputRefData) -> ShotPlanPayload:
    p = result.plan
    return ShotPlanPayload(
        plan_ref=PlanRef.model_validate(
            {
                "uri": ref.uri,
                "sha256": ref.sha256,
                "schema": SCHEMA,
                "schema_version": SCHEMA_VERSION,
            }
        ),
        script_id=p.script_id,
        script_version=p.script_version,
        script_sha256=p.script_sha256,
        language=p.language,
        aspect_ratio=p.aspect_ratio,
        iteration=p.iteration,
        timing_basis=p.timing_basis,
        narration_timeline_sha256=p.narration_timeline_sha256,
        content_end_ms=p.content_end_ms,
        total_duration_ms=p.total_duration_ms,
        hook=p.hook,
        audio_plan=p.audio_plan,
        chapters=p.chapters,
        deliberate_hold=p.deliberate_hold,
        deliberate_black=(),
        interrupts=p.interrupts,
        jl_cuts=p.jl_cuts,
        tier_budget=p.tier_budget,
        views=build_views(p, script),
        stats=p.stats,
        refusal=p.refusal,
        provenance=p.provenance,
    )


def build_task_output(
    result: StepResult,
    script: ScriptDoc,
    ref: OutputRefData,
    *,
    now: datetime,
    duration_ms: int,
    currency: str,
    media_type: str = "application/json",
) -> TaskOutput:
    """03 section 5: SUCCEEDED only reaches here (the step raises on any blocking failure).

    ``cpu_ms`` / ``peak_rss_bytes`` are not measured by this library (the worker fills them).
    """
    payload = build_payload(result, script, ref)
    m = result.meter
    data: dict[str, Any] = payload.model_dump(mode="json", by_alias=True)
    return TaskOutput(
        status=OutputStatus.SUCCEEDED,
        payload=PayloadObject(
            payload_schema=SCHEMA, payload_schema_version=SCHEMA_VERSION, data=data
        ),
        output_refs=(
            OutputRef(
                uri=ref.uri,
                kind=OutputRefKind.DATA,
                sha256=ref.sha256,
                size_bytes=ref.size_bytes,
                media_type=media_type,
            ),
        ),
        quality_score=None,
        confidence=None,
        validation_results=tuple(result.results),
        duration=duration_ms,
        resource_usage=ResourceUsage(
            cpu_ms=0,
            peak_rss_bytes=0,
            tokens_in=m.tokens_in,
            tokens_out=m.tokens_out,
            tokens_cached_in=m.tokens_cached_in,
            llm_calls=m.calls,
            provider_calls=m.calls,
            cost_estimate_micros=m.spent_micros,
            currency=currency,
            cost_entry_ids=tuple(m.cost_entry_ids),
        ),
        error=None,
        next_action=NextAction(
            type=NextActionType.CONTINUE,
            wait_reason=None,
            escalation_level=None,
            reason="plan ready for agent_08 asset sourcing",
        ),
        downstream_agent="agent_08",
        timestamp=now,
    )


def views_of(payload: ShotPlanPayload) -> Sequence[Any]:
    return payload.views.agent_08_shots
