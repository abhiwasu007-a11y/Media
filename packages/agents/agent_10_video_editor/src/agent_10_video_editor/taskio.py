"""Task Output envelope helpers shared by the three stages (03 section 5; blueprint 10 s8)."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from agent_10_video_editor.errors import input_invalid
from agent_10_video_editor.qc.result import CheckResult
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
    ValidationResult,
)
from amw_core.enums import (
    CheckKind,
    CheckVerdict,
    CostFigureKind,
    CostOperation,
    CostUnitKind,
    NextActionType,
    OutputRefKind,
    OutputStatus,
    WaitReason,
)
from amw_core.ids import AttemptId, ChannelId, ExecutorId, JobId, TaskId, make_idempotency_key
from amw_core.interfaces.cost_ledger import NewCostEntry

ACTOR = "agent_10"
SCHEMA_VERSION = "1.0.0"


def validate_budget(task_input: TaskInput) -> None:
    """7.4 (a): ``max_cost_micros = 0`` and ``max_llm_calls = 0``, else ``INPUT_INVALID``."""
    budget = task_input.resource_budget
    if budget.max_cost_micros != 0 or (budget.max_llm_calls or 0) != 0:
        raise input_invalid("BUDGET_NOT_ZERO")


def to_validation_result(result: CheckResult) -> ValidationResult:
    measured = result.measured
    threshold = result.threshold
    message = result.message or (
        f"{result.check_id}: {result.verdict}"
        + (f" ({', '.join(str(o) for o in result.offending[:5])})" if result.offending else "")
    )
    rule = result.details.get("rule_id")
    return ValidationResult(
        check_id=result.check_id,
        kind=CheckKind.DETERMINISTIC,
        verdict=result.verdict,
        blocking=result.blocking and result.verdict is not CheckVerdict.WARN,
        rule_id=rule if isinstance(rule, str) else None,
        measured=measured,
        threshold=threshold,
        unit=result.unit,
        message=message[:2000],
        gate=result.gate,
        remedy_stage_id=result.remedy_stage_id if result.gate else None,
    )


def output_ref(
    uri: str, kind: OutputRefKind, sha256: str, size_bytes: int, media_type: str
) -> OutputRef:
    return OutputRef(
        uri=uri, kind=kind, sha256=sha256, size_bytes=size_bytes, media_type=media_type
    )


def usage(render_ms: int, currency: str, cost_entry_ids: Sequence[str] = ()) -> ResourceUsage:
    return ResourceUsage(
        cpu_ms=render_ms,
        peak_rss_bytes=0,
        tokens_in=0,
        tokens_out=0,
        tokens_cached_in=0,
        llm_calls=0,
        provider_calls=0,
        render_ms=render_ms,
        cost_estimate_micros=0,
        currency=currency,
        cost_entry_ids=tuple(cost_entry_ids),
    )


def build_output(
    *,
    status: OutputStatus,
    schema: str,
    data: dict[str, Any] | None,
    refs: Sequence[OutputRef],
    results: Sequence[ValidationResult],
    duration_ms: int,
    resource_usage: ResourceUsage,
    next_action: NextAction,
    now: datetime,
) -> TaskOutput:
    return TaskOutput(
        status=status,
        payload=(
            PayloadObject(payload_schema=schema, payload_schema_version=SCHEMA_VERSION, data=data)
            if data is not None
            else None
        ),
        output_refs=tuple(refs),
        quality_score=None,
        confidence=None,
        validation_results=tuple(results),
        duration=duration_ms,
        resource_usage=resource_usage,
        error=None,
        next_action=next_action,
        downstream_agent=None,
        timestamp=now,
    )


def continue_action(reason: str) -> NextAction:
    return NextAction(
        type=NextActionType.CONTINUE, wait_reason=None, escalation_level=None, reason=reason[:1000]
    )


def drain_action(reason: str) -> NextAction:
    return NextAction(
        type=NextActionType.WAIT,
        wait_reason=WaitReason.DRAIN,
        escalation_level=None,
        reason=reason[:1000],
    )


def ffmpeg_cost_entry(
    task_input: TaskInput, attempt_id: str, *, task_type: str, occurred_at: datetime, units_ms: int
) -> NewCostEntry:
    """The zero-amount ESTIMATE row of an FFmpeg stage, attributed and idempotent (09 section 5).

    The key depends on (org, task type, job, task) and not on the attempt, so a retry of the same
    task after a persist records the row once.
    """
    return NewCostEntry(
        provider="ffmpeg",
        operation=CostOperation.RENDER_FFMPEG,
        amount_micros=0,
        currency=task_input.resource_budget.currency,
        figure_kind=CostFigureKind.ESTIMATE,
        occurred_at=occurred_at,
        job_id=JobId(task_input.job_id),
        task_id=TaskId(task_input.task_id),
        attempt_id=AttemptId(attempt_id),
        channel_id=ChannelId(task_input.channel_id) if task_input.channel_id else None,
        agent_id=ExecutorId(task_input.agent_id),
        units=Decimal(units_ms),
        unit_kind=CostUnitKind.RENDER_MS,
        idempotency_key=make_idempotency_key(
            task_input.org_id,
            f"task.{task_type}",
            ["cost", task_input.job_id, task_input.task_id],
        ),
    )
