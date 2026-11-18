"""Task Output builders shared by both stages (03 section 5; blueprint 8, 18).

A failed *gate* is not an error: ``s07_master`` returns SUCCEEDED with gate results (03 5.3 rule 4).
Typed exceptions map one to one onto the 07 section 2 codes (F-28).
"""

import hashlib
import logging
from collections.abc import Sequence
from datetime import datetime

from pydantic import ValidationError

from agent_07_voice_production.context import AGENT_ID, ExecContext
from amw_core.contracts.common import AmwModel, PayloadObject
from amw_core.contracts.error import error_object_from_exception
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
    AgentCrashError,
    AmwError,
    BudgetExhaustedError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
)

log = logging.getLogger("agent_07")


def log_event(event: str, ctx: ExecContext, **fields: str | int | float | bool | None) -> None:
    """Structured log line: IDs, hashes, counts and check IDs only (NFR-5). Callers never pass
    script text, spoken text, consent data or a provider voice reference."""
    log.info(
        event,
        extra={
            "org_id": str(ctx.org_id),
            "correlation_id": str(ctx.correlation_id),
            "job_id": str(ctx.job_id),
            "task_id": str(ctx.task_id),
            "attempt_id": str(ctx.attempt_id),
            "actor": AGENT_ID,
            **fields,
        },
    )


def result(
    check_id: str,
    verdict: CheckVerdict,
    message: str,
    *,
    blocking: bool = False,
    kind: CheckKind = CheckKind.DETERMINISTIC,
    measured: bool | int | float | str | None = None,
    threshold: bool | int | float | str | None = None,
    unit: str | None = None,
    gate: bool = False,
    remedy_stage_id: str | None = None,
) -> ValidationResult:
    """A WARN or SKIPPED result is never blocking (03 5.3 rule 5)."""
    return ValidationResult(
        check_id=check_id,
        kind=kind,
        verdict=verdict,
        blocking=blocking and verdict not in (CheckVerdict.WARN, CheckVerdict.SKIPPED),
        measured=measured,
        threshold=threshold,
        unit=unit,
        message=message,
        gate=gate,
        remedy_stage_id=remedy_stage_id if gate and verdict is CheckVerdict.FAIL else None,
    )


def output_ref(uri: str, kind: OutputRefKind, sha256: str, size: int, media_type: str) -> OutputRef:
    return OutputRef(uri=uri, kind=kind, sha256=sha256, size_bytes=size, media_type=media_type)


def usage(
    *,
    provider_calls: int,
    cost_micros: int,
    currency: str,
    cost_entry_ids: Sequence[str],
    cpu_ms: int = 0,
) -> ResourceUsage:
    return ResourceUsage(
        cpu_ms=cpu_ms,
        peak_rss_bytes=0,
        tokens_in=0,
        tokens_out=0,
        tokens_cached_in=0,
        llm_calls=0,
        provider_calls=provider_calls,
        cost_estimate_micros=cost_micros,
        currency=currency,
        cost_entry_ids=tuple(cost_entry_ids),
    )


def success(
    *,
    payload_schema: str,
    payload: AmwModel,
    refs: Sequence[OutputRef],
    results: Sequence[ValidationResult],
    resource: ResourceUsage,
    duration_ms: int,
    now: datetime,
    reason: str = "",
    downstream: str | None = None,
) -> TaskOutput:
    return TaskOutput(
        status=OutputStatus.SUCCEEDED,
        payload=PayloadObject(
            payload_schema=payload_schema, payload_schema_version="1.0.0", data=payload.to_doc()
        ),
        output_refs=tuple(refs),
        quality_score=None,
        confidence=None,
        validation_results=tuple(results),
        duration=duration_ms,
        resource_usage=resource,
        error=None,
        next_action=NextAction(
            type=NextActionType.CONTINUE, wait_reason=None, escalation_level=None, reason=reason
        ),
        downstream_agent=downstream,
        timestamp=now,
    )


def suspended(
    *,
    wait_reason: WaitReason,
    resource: ResourceUsage,
    duration_ms: int,
    now: datetime,
    refs: Sequence[OutputRef] = (),
    exc: AmwError | None = None,
    ctx: ExecContext | None = None,
) -> TaskOutput:
    error = None
    if exc is not None and ctx is not None:
        error = error_object_from_exception(
            exc,
            actor=AGENT_ID,
            attempt_no=ctx.attempt_no,
            occurred_at=now,
            correlation_id=str(ctx.correlation_id),
        )
    return TaskOutput(
        status=OutputStatus.SUSPENDED,
        payload=None,
        output_refs=tuple(refs),
        quality_score=None,
        confidence=None,
        validation_results=(),
        duration=duration_ms,
        resource_usage=resource,
        error=error,
        next_action=NextAction(
            type=NextActionType.WAIT,
            wait_reason=wait_reason,
            escalation_level=None,
            reason=wait_reason.value,
        ),
        downstream_agent=None,
        timestamp=now,
    )


def failed(
    exc: AmwError,
    *,
    ctx: ExecContext | None,
    correlation_id: str,
    resource: ResourceUsage,
    duration_ms: int,
    now: datetime,
    attempt_no: int,
) -> TaskOutput:
    """FAILED, or REJECTED for a payload that fails its schema (03 section 7.2, attempt_no 0)."""
    rejected = isinstance(exc, SchemaInvalidError | SchemaVersionUnsupportedError)
    error = error_object_from_exception(
        exc,
        actor=AGENT_ID,
        attempt_no=0 if rejected else attempt_no,
        occurred_at=now,
        correlation_id=correlation_id,
    )
    escalation = EscalationLevel.L2 if exc.error_class.value == "PERMANENT" else None
    return TaskOutput(
        status=OutputStatus.REJECTED if rejected else OutputStatus.FAILED,
        payload=None,
        output_refs=(),
        quality_score=None,
        confidence=None,
        validation_results=(),
        duration=duration_ms,
        resource_usage=resource,
        error=error,
        next_action=NextAction(
            type=NextActionType.RETRY if exc.retryable else NextActionType.STOP,
            wait_reason=None,
            escalation_level=escalation if not exc.retryable else None,
            reason=exc.code,
        ),
        downstream_agent=None,
        timestamp=now,
    )


def classify(exc: BaseException) -> AmwError:
    """F-28: one typed exception to one 07 code; anything else is ``AGENT.CRASH`` (retryable)."""
    if isinstance(exc, AmwError):
        return exc
    if isinstance(exc, ValidationError):
        return SchemaInvalidError(
            "a payload does not match its schema",
            details={"violations": [{"path": "", "keyword": "model", "message": str(exc)[:300]}]},
        )
    return AgentCrashError("unhandled exception in agent_07", details={"type": type(exc).__name__})


def is_budget(exc: AmwError) -> bool:
    return isinstance(exc, BudgetExhaustedError)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
