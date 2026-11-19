"""The one entry-point guard of every Agent 16 task type (03 section 1 rule 5, CCR-203).

``run(task_input, ctx)`` of each stage calls :func:`run_guarded`: the context and the Task Input
must name the same agent, org, job and task (19.1 layer 1, ``TENANT_MISMATCH`` before any step
runs); every failure is **returned** as a Task Output (``FAILED``, ``REJECTED`` for a schema
failure, ``SUSPENDED`` for a refused budget) and never raised past ``run``; the error output
reports the cost really incurred so far (never a silent 0, 09 section 3).
"""

import hashlib
import io
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from agent_16_compliance_qa.judge.client import CallMeter
from agent_16_compliance_qa.output import BlobRef, Usage
from amw_core.contracts.error import error_object_from_exception, violation
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import NextAction, ResourceUsage, TaskOutput
from amw_core.enums import EscalationLevel, NextActionType, OutputStatus, WaitReason
from amw_core.errors import (
    AgentCrashError,
    AmwError,
    BudgetExhaustedError,
    IdempotencyConflictError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    TenantMismatchError,
)
from amw_core.exec_context import ExecContext
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext

_LOG = logging.getLogger(__name__)


def check_ctx(task_input: TaskInput, ctx: ExecContext, agent_id: str) -> None:
    """Agent, org, job and task of the context equal those of the Task Input, else
    ``PERMANENT.TENANT_MISMATCH`` (19.1 layer 1; the same rule as agents 04 to 09)."""
    if task_input.agent_id != agent_id:
        raise TenantMismatchError(f"task is not addressed to {agent_id}")
    if (
        str(ctx.org_id) != task_input.org_id
        or str(ctx.job_id) != task_input.job_id
        or str(ctx.task_id) != task_input.task_id
    ):
        raise TenantMismatchError("execution context does not match the Task Input")


def classify(exc: BaseException) -> AmwError:
    """One typed exception to one 07 code; anything else is ``AGENT.CRASH`` (retryable)."""
    if isinstance(exc, AmwError):
        return exc
    if isinstance(exc, ValidationError):
        return SchemaInvalidError(
            "a payload does not match its schema",
            details={"violations": [violation("model", "", "payload does not match its schema")]},
        )
    return AgentCrashError("unhandled exception in agent_16", details={"type": type(exc).__name__})


@dataclass(slots=True)
class Spend:
    """What this attempt has really spent so far. The stage points ``meter`` at its call meter as
    soon as it exists, so an error output reports the cost incurred up to the failure."""

    meter: CallMeter | None = None

    @property
    def usage(self) -> Usage:
        m = self.meter
        if m is None:
            return Usage()
        return Usage(
            tokens_in=m.tokens_in,
            tokens_out=m.tokens_out,
            tokens_cached_in=m.tokens_cached_in,
            llm_calls=m.calls,
            cost_micros=m.spent_micros,
            cost_entry_ids=tuple(m.cost_entry_ids),
        )


def usage_to_resource(usage: Usage, currency: str) -> ResourceUsage:
    return ResourceUsage(
        cpu_ms=0,
        peak_rss_bytes=0,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        tokens_cached_in=usage.tokens_cached_in,
        llm_calls=usage.llm_calls,
        provider_calls=usage.llm_calls,
        cost_estimate_micros=usage.cost_micros,
        currency=currency,
        cost_entry_ids=usage.cost_entry_ids,
    )


def failure_output(
    exc: AmwError,
    *,
    actor: str,
    ctx: ExecContext | None,
    task_input: TaskInput,
    usage: Usage,
    now: datetime,
) -> TaskOutput:
    """``FAILED`` (``REJECTED`` for a payload that fails its schema, 03 section 7.2) with the real
    cost incurred so far; a refused budget is ``SUSPENDED`` with ``AWAITING_BUDGET``."""
    currency = task_input.resource_budget.currency
    rejected = isinstance(exc, SchemaInvalidError | SchemaVersionUnsupportedError)
    attempt_no = 0 if rejected else (ctx.attempt_no if ctx else task_input.retry_count + 1)
    error = error_object_from_exception(
        exc,
        actor=actor,
        attempt_no=attempt_no,
        occurred_at=now,
        correlation_id=task_input.correlation_id,
    )
    resource = usage_to_resource(usage, currency)
    if isinstance(exc, BudgetExhaustedError):
        return TaskOutput(
            status=OutputStatus.SUSPENDED,
            payload=None,
            output_refs=(),
            quality_score=None,
            confidence=None,
            validation_results=(),
            duration=0,
            resource_usage=resource,
            error=error,
            next_action=NextAction(
                type=NextActionType.WAIT,
                wait_reason=WaitReason.AWAITING_BUDGET,
                escalation_level=None,
                reason=WaitReason.AWAITING_BUDGET.value,
            ),
            downstream_agent=None,
            timestamp=now,
        )
    return TaskOutput(
        status=OutputStatus.REJECTED if rejected else OutputStatus.FAILED,
        payload=None,
        output_refs=(),
        quality_score=None,
        confidence=None,
        validation_results=(),
        duration=0,
        resource_usage=resource,
        error=error,
        next_action=NextAction(
            type=NextActionType.RETRY if exc.retryable else NextActionType.STOP,
            wait_reason=None,
            escalation_level=EscalationLevel.L2
            if exc.error_class.value == "PERMANENT" and not exc.retryable
            else None,
            reason=exc.code,
        ),
        downstream_agent=None,
        timestamp=now,
    )


def run_guarded(
    *,
    agent_id: str,
    actor: str,
    task_input: TaskInput,
    ctx: ExecContext,
    spend: Spend,
    now: Callable[[], datetime],
    body: Callable[[], TaskOutput],
    event: str,
) -> TaskOutput:
    """``check_ctx`` then ``body``; every exception becomes a returned failure output."""
    spend.meter = None
    checked: ExecContext | None = None
    try:
        check_ctx(task_input, ctx, agent_id)
        checked = ctx
        return body()
    except Exception as raw:
        exc = classify(raw)
        _LOG.warning(
            event,
            extra={
                "org_id": task_input.org_id,
                "correlation_id": task_input.correlation_id,
                "job_id": task_input.job_id,
                "task_id": task_input.task_id,
                "actor": actor,
                "code": exc.code,
            },
        )
        return failure_output(
            exc,
            actor=actor,
            ctx=checked,
            task_input=task_input,
            usage=spend.usage,
            now=now(),
        )


def put_artifact_once(
    storage: BlobStorage, tc: TenantContext, uri: BlobUri, payload: Mapping[str, Any]
) -> BlobRef:
    """Write-once task artifact (03 section 8.2): equal bytes are reused (a retried write), a
    different document at the same URI is ``IDEMPOTENCY_CONFLICT``, never an overwrite."""
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    head = storage.head(tc, uri)
    if head.exists:
        if head.sha256 != sha:
            raise IdempotencyConflictError("a different report blob already exists for this task")
        return BlobRef(uri=str(uri), sha256=sha, size_bytes=len(data))
    info = storage.put(tc, uri, io.BytesIO(data))
    return BlobRef(uri=str(info.uri), sha256=info.sha256, size_bytes=info.size_bytes)
