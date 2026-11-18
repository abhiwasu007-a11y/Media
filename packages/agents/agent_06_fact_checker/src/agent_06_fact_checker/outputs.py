"""Task Output assembly shared by both steps (03 5; blueprint 8.1, 8.4, 18)."""

import io
from collections.abc import Mapping, Sequence
from typing import Any

from agent_06_fact_checker.hashing import canonical_json, sha256_hex
from agent_06_fact_checker.models import Verdict
from agent_06_fact_checker.runtime import RunContext, UsageTotals
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.error import error_object_from_exception
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
    EscalationLevel,
    NextActionType,
    OutputRefKind,
    OutputStatus,
    WaitReason,
)
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
from amw_core.interfaces import BlobStorage, Clock, TenantContext

_REJECTED = (
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    InputInvalidError,
    TenantMismatchError,
    CrossTenantRefError,
    TenantInactiveError,
    MissingDependencyError,
)


def check(
    check_id: str,
    ok: bool,
    message: str,
    *,
    blocking: bool = True,
    rule_id: str | None = None,
    gate: bool = False,
    measured: bool | int | float | str | None = None,
    threshold: bool | int | float | str | None = None,
    warn_instead: bool = False,
    skipped: bool = False,
) -> ValidationResult:
    """One ``validation_results`` entry (blueprint 8.4). ``warn_instead``: a failed non-blocking
    check is ``WARN``; ``skipped`` is only for a precondition that is false."""
    if skipped:
        verdict, blocking = CheckVerdict.SKIPPED, False
    elif ok:
        verdict = CheckVerdict.PASS
    elif warn_instead:
        verdict, blocking = CheckVerdict.WARN, False
    else:
        verdict = CheckVerdict.FAIL
    return ValidationResult(
        check_id=check_id,
        kind=CheckKind.DETERMINISTIC,
        verdict=verdict,
        blocking=blocking,
        rule_id=rule_id,
        measured=measured,
        threshold=threshold,
        message=message[:2000],
        gate=gate,
        remedy_stage_id=None,
    )


def next_action_for(verdict: Verdict, failed_checks: Sequence[str]) -> NextAction:
    """Advisory only (03 5.3): routing is the orchestrator's, by the stage's ``on_fail``."""
    if verdict is Verdict.NEEDS_HUMAN_REVIEW:
        return NextAction(
            type=NextActionType.ESCALATE,
            wait_reason=None,
            escalation_level=EscalationLevel.L1,
            reason="NEEDS_HUMAN_REVIEW: SENSITIVE_CLAIM approval",
        )
    if verdict is Verdict.BLOCKED:
        return NextAction(
            type=NextActionType.CONTINUE,
            wait_reason=None,
            escalation_level=None,
            reason="gate FAILED: " + ",".join(failed_checks),
        )
    return NextAction(
        type=NextActionType.CONTINUE, wait_reason=None, escalation_level=None, reason="ALLOWED"
    )


def resource_usage(usage: UsageTotals) -> ResourceUsage:
    """``cpu_ms`` and ``peak_rss_bytes`` are measured by the worker, not by the step."""
    return ResourceUsage(
        cpu_ms=0,
        peak_rss_bytes=0,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        tokens_cached_in=usage.tokens_cached_in,
        llm_calls=usage.llm_calls,
        provider_calls=usage.llm_calls,
        cost_estimate_micros=usage.cost_micros,
        currency=usage.currency,
        cost_entry_ids=tuple(usage.cost_entry_ids),
    )


def write_blob(
    blobs: BlobStorage,
    tenant: TenantContext,
    task: TaskInput,
    ctx: RunContext,
    name: str,
    doc: Any,
) -> OutputRef:
    """Write-once ``artifacts/<name>`` of this attempt (03 8.2); equal bytes are reused."""
    body = canonical_json(doc).encode("utf-8")
    path = f"{task.job_id}/tasks/{task.task_id}/attempts/{ctx.attempt_id}/artifacts/{name}"
    uri = blobs.blob_uri(tenant, "jobs", path)
    head = blobs.head(tenant, uri)
    if not head.exists:
        blobs.put(tenant, uri, io.BytesIO(body))
    elif head.sha256 != sha256_hex(body):
        raise InputInvalidError("an artifact of this attempt exists with different content")
    return OutputRef(
        uri=uri,
        kind=OutputRefKind.DATA,
        sha256=sha256_hex(body),
        size_bytes=len(body),
        media_type="application/json",
    )


def success_output(
    *,
    clock: Clock,
    started_ms: int,
    schema: str,
    doc: Mapping[str, Any],
    refs: Sequence[OutputRef],
    results: Sequence[ValidationResult],
    usage: UsageTotals,
    next_action: NextAction,
) -> TaskOutput:
    return TaskOutput(
        status=OutputStatus.SUCCEEDED,
        payload=PayloadObject(
            payload_schema=schema, payload_schema_version="1.0.0", data=dict(doc)
        ),
        output_refs=tuple(refs),
        quality_score=None,
        confidence=None,
        validation_results=tuple(results),
        duration=max(0, clock.monotonic_ms() - started_ms),
        resource_usage=resource_usage(usage),
        error=None,
        next_action=next_action,
        downstream_agent=None,
        timestamp=clock.now(),
    )


def error_output(
    exc: AmwError,
    *,
    task: TaskInput,
    clock: Clock,
    started_ms: int,
    usage: UsageTotals,
    attempt_no: int,
    validated: bool,
) -> TaskOutput:
    """Map a typed exception to ``REJECTED`` (input never accepted), ``SUSPENDED`` (budget) or
    ``FAILED`` (blueprint 18). Retryable infrastructure errors are not mapped here: the worker
    owns retry and the exception propagates (``validated`` False means nothing was read)."""
    suspended = isinstance(exc, BudgetExhaustedError)
    rejected = isinstance(exc, _REJECTED) and not validated
    status = (
        OutputStatus.SUSPENDED
        if suspended
        else OutputStatus.REJECTED
        if rejected
        else OutputStatus.FAILED
    )
    error = error_object_from_exception(
        exc,
        actor="agent_06",
        attempt_no=0 if rejected else attempt_no,
        occurred_at=clock.now(),
        correlation_id=task.correlation_id,
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
        duration=max(0, clock.monotonic_ms() - started_ms),
        resource_usage=resource_usage(usage),
        error=error,
        next_action=action,
        downstream_agent=None,
        timestamp=clock.now(),
    )


__all__ = [
    "check",
    "error_output",
    "next_action_for",
    "resource_usage",
    "success_output",
    "write_blob",
]
