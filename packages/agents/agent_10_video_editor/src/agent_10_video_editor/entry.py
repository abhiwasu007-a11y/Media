"""The shared worker entry point of the three stages (03 section 1 rule 5, CCR-203).

``run(task_input, ctx)`` of each stage calls :func:`run_task`: the execution context must match the
Task Input (19.1 layer 1, ``TENANT_MISMATCH``), the typed stage logic runs, and every failure is
RETURNED as a Task Output (``REJECTED`` for a payload or upstream document that fails its schema,
else ``FAILED``), never raised past the entry point. The error output reports the time actually
spent; Agent 10 has no provider spend (``cost_estimate_micros`` is the real figure, 0).
"""

from collections.abc import Callable

from pydantic import ValidationError

from agent_10_video_editor.taskio import ACTOR
from amw_core.contracts.error import error_object_from_exception
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import NextAction, ResourceUsage, TaskOutput
from amw_core.enums import EscalationLevel, NextActionType, OutputStatus
from amw_core.errors import (
    AgentCrashError,
    AmwError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    TenantMismatchError,
)
from amw_core.exec_context import ExecContext
from amw_core.interfaces.clock import Clock

AGENT_ID = "agent_10"


def check_ctx(task_input: TaskInput, ctx: ExecContext) -> None:
    """The context and the Task Input must name the same agent, org, job and task (19.1 layer 1).
    Anything else is ``TENANT_MISMATCH`` before any step runs."""
    if task_input.agent_id != AGENT_ID:
        raise TenantMismatchError("task is not addressed to agent_10")
    if (
        str(ctx.org_id) != task_input.org_id
        or str(ctx.job_id) != task_input.job_id
        or str(ctx.task_id) != task_input.task_id
    ):
        raise TenantMismatchError("execution context does not match the Task Input")


def classify(exc: BaseException) -> AmwError:
    """One typed exception to one 07 code; a document that does not parse is ``SCHEMA_INVALID``;
    anything else is ``AGENT.CRASH`` (no message text of the original is copied)."""
    if isinstance(exc, AmwError):
        return exc
    if isinstance(exc, ValidationError):
        return SchemaInvalidError("a document does not match its schema")
    return AgentCrashError("unhandled exception in agent_10", details={"type": type(exc).__name__})


def run_task(
    task_input: TaskInput,
    ctx: ExecContext,
    clock: Clock,
    execute: Callable[[], TaskOutput],
) -> TaskOutput:
    started = clock.monotonic_ms()
    try:
        check_ctx(task_input, ctx)
        return execute()
    except Exception as raw:
        return _failed(classify(raw), task_input, ctx, clock, started)


def _failed(
    exc: AmwError, task_input: TaskInput, ctx: ExecContext, clock: Clock, started: int
) -> TaskOutput:
    rejected = isinstance(exc, SchemaInvalidError | SchemaVersionUnsupportedError)
    now = clock.now()
    elapsed = max(0, clock.monotonic_ms() - started)
    error = error_object_from_exception(
        exc,
        actor=ACTOR,
        attempt_no=0 if rejected else ctx.attempt_no,
        occurred_at=now,
        correlation_id=task_input.correlation_id,
    )
    return TaskOutput(
        status=OutputStatus.REJECTED if rejected else OutputStatus.FAILED,
        payload=None,
        output_refs=(),
        quality_score=None,
        confidence=None,
        validation_results=(),
        duration=elapsed,
        resource_usage=ResourceUsage(
            cpu_ms=elapsed,
            peak_rss_bytes=0,
            tokens_in=0,
            tokens_out=0,
            tokens_cached_in=0,
            llm_calls=0,
            provider_calls=0,
            render_ms=elapsed,
            cost_estimate_micros=0,
            currency=task_input.resource_budget.currency,
            cost_entry_ids=(),
        ),
        error=error,
        next_action=NextAction(
            type=NextActionType.RETRY if exc.retryable else NextActionType.STOP,
            wait_reason=None,
            escalation_level=(EscalationLevel.L2 if exc.error_class.value == "PERMANENT" else None)
            if not exc.retryable
            else None,
            reason=exc.code,
        ),
        downstream_agent=None,
        timestamp=now,
    )
