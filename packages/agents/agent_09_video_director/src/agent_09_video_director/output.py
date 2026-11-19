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
    Overlay,
    Provenance,
    Refusal,
    ScriptDoc,
    Shot,
    ShotPlan,
    Stats,
    TierBudget,
)
from agent_09_video_director.persistence import OutputRefData
from agent_09_video_director.step import StepResult
from agent_09_video_director.views import Views, build_views
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.error import error_object_from_exception
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
)
from amw_core.enums import NextActionType, OutputRefKind, OutputStatus, WaitReason
from amw_core.errors import (
    AmwError,
    BudgetExhaustedError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    TenantInactiveError,
    TenantMismatchError,
)
from amw_core.exec_context import ExecContext

SCHEMA = "agent_09.shot_plan.output"
SCHEMA_VERSION = "1.0.0"


class PlanRef(Model):
    """The four fields of Agent 08's ``shot_plan_ref``; the orchestrator copies them unchanged."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    uri: str
    sha256: str
    schema_: Literal["agent_09.shot_plan.output"] = Field(alias="schema")
    schema_version: Literal["1.0.0"]


class _PlanSummary(Model):
    """The fields of the output document that are neither ``plan_ref`` nor the shot lists."""

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


class ShotPlanDocument(_PlanSummary):
    """``agent_09.shot_plan.output`` 1.0.0 as stored in the plan blob (8.1, CCR-203): the whole
    document **without** ``plan_ref`` (it cannot hold its own hash), ``views`` included. Agents
    08, 10, 11 and 16 read the plan only from this blob."""

    shots: tuple[Shot, ...]
    overlays: tuple[Overlay, ...]


class ShotPlanPayload(_PlanSummary):
    """``payload.data``: the summary and the views; shots and overlays live in the blob."""

    plan_ref: PlanRef


_SUMMARY_FIELDS = tuple(_PlanSummary.model_fields)


def build_document(plan: ShotPlan, script: ScriptDoc) -> ShotPlanDocument:
    """The blob document of ``plan`` (``realism`` is internal; its facts are the realism view)."""
    summary = {name: getattr(plan, name) for name in _SUMMARY_FIELDS if name != "views"}
    summary["deliberate_black"] = ()
    return ShotPlanDocument(
        **summary, views=build_views(plan, script), shots=plan.shots, overlays=plan.overlays
    )


def plan_from_document(doc: ShotPlanDocument) -> ShotPlan:
    """A previous iteration's plan, read back from its blob (revision input, 24 3.3 rule 6)."""
    fields = {name: getattr(doc, name) for name in ShotPlan.model_fields if hasattr(doc, name)}
    return ShotPlan(**fields)


def build_payload(doc: ShotPlanDocument, ref: OutputRefData) -> ShotPlanPayload:
    summary = {name: getattr(doc, name) for name in _SUMMARY_FIELDS}
    return ShotPlanPayload(
        plan_ref=PlanRef.model_validate(
            {
                "uri": ref.uri,
                "sha256": ref.sha256,
                "schema": SCHEMA,
                "schema_version": SCHEMA_VERSION,
            }
        ),
        **summary,
    )


def build_task_output(
    result: StepResult,
    doc: ShotPlanDocument,
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
    payload = build_payload(doc, ref)
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


AGENT_ID = "agent_09"

_REJECTED = (
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    InputInvalidError,
    TenantMismatchError,
    CrossTenantRefError,
    TenantInactiveError,
    MissingDependencyError,
)


def check_ctx(task_input: TaskInput, ctx: ExecContext) -> None:
    """The context and the Task Input must name the same org, job and task (19.1 layer 1)."""
    if (
        str(ctx.org_id) != task_input.org_id
        or str(ctx.job_id) != task_input.job_id
        or str(ctx.task_id) != task_input.task_id
    ):
        raise TenantMismatchError("execution context does not match the Task Input")


def error_output(
    exc: AmwError,
    *,
    task_input: TaskInput,
    now: datetime,
    duration_ms: int,
) -> TaskOutput:
    """Map a typed exception to ``REJECTED`` (the input was never accepted), ``SUSPENDED``
    (budget) or ``FAILED`` (blueprint 18; 03 section 5: failures are returned as Task Output).
    Retryable infrastructure errors are not mapped here: the worker owns retry."""
    suspended = isinstance(exc, BudgetExhaustedError)
    rejected = isinstance(exc, _REJECTED)
    status = (
        OutputStatus.SUSPENDED
        if suspended
        else OutputStatus.REJECTED
        if rejected
        else OutputStatus.FAILED
    )
    error = error_object_from_exception(
        exc,
        actor=AGENT_ID,
        attempt_no=0 if rejected else task_input.retry_count,
        occurred_at=now,
        correlation_id=task_input.correlation_id,
    )
    if suspended:
        action = NextAction(
            type=NextActionType.WAIT,
            wait_reason=WaitReason.AWAITING_BUDGET,
            escalation_level=None,
            reason="budget guard refused the call",
        )
    else:
        action = NextAction(
            type=NextActionType.RETRY if exc.retryable else NextActionType.STOP,
            wait_reason=None,
            escalation_level=None,
            reason=exc.code,
        )
    return TaskOutput(
        status=status,
        payload=None,
        output_refs=(),
        quality_score=None,
        confidence=None,
        validation_results=(),
        duration=duration_ms,
        resource_usage=ResourceUsage(
            cpu_ms=0,
            peak_rss_bytes=0,
            tokens_in=0,
            tokens_out=0,
            tokens_cached_in=0,
            llm_calls=0,
            provider_calls=0,
            cost_estimate_micros=0,
            currency=task_input.resource_budget.currency,
            cost_entry_ids=(),
        ),
        error=error,
        next_action=action,
        downstream_agent=None,
        timestamp=now,
    )
