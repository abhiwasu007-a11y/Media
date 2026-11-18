"""Step outcome to ``amw.task_output`` 1.0.0 (blueprint 8.1, 18, 03 section 5).

``quality_score`` and ``confidence`` are null (scored by Agent 16). The success rule of 03 section
5.3 holds because ``s05_script`` / ``s05_shorts`` are not gate stages: no result carries ``gate``.
"""

from datetime import datetime

from agent_05_scriptwriter.contracts import ShortsAdaptationResult
from agent_05_scriptwriter.protocols import StepContext
from agent_05_scriptwriter.steps.common import StepOutcome
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.error import error_object_from_exception
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
)
from amw_core.enums import (
    EscalationLevel,
    NextActionType,
    OutputRefKind,
    OutputStatus,
    WaitReason,
)


def build_task_output(
    outcome: StepOutcome,
    ctx: StepContext,
    *,
    now: datetime,
    duration_ms: int,
    attempt_no: int,
    currency: str = "USD",
) -> TaskOutput:
    shorts = isinstance(outcome.result, ShortsAdaptationResult)
    schema = "agent_05.shorts_adaptation.output" if shorts else "agent_05.script_draft.output"
    status = OutputStatus(outcome.status)
    records = outcome.records
    usage = ResourceUsage(
        cpu_ms=0,
        peak_rss_bytes=0,
        tokens_in=sum(r.tokens_in for r in records),
        tokens_out=sum(r.tokens_out for r in records),
        tokens_cached_in=sum(r.tokens_cached_in for r in records),
        llm_calls=len(records),
        provider_calls=len(records),
        cost_estimate_micros=sum(r.amount_micros for r in records),
        currency=currency,
        cost_entry_ids=tuple(r.cost_entry_id for r in records),
    )
    payload = (
        PayloadObject(
            payload_schema=schema,
            payload_schema_version="1.0.0",
            data=outcome.result.model_dump(mode="json"),
        )
        if outcome.result is not None
        else None
    )
    refs: tuple[OutputRef, ...] = ()
    if outcome.saved is not None and outcome.document_bytes is not None:
        refs = (
            OutputRef(
                uri=outcome.saved.uri,
                kind=OutputRefKind.SCRIPT,
                sha256=outcome.saved.sha256,
                size_bytes=len(outcome.document_bytes),
                media_type="application/json",
            ),
        )
    error = (
        error_object_from_exception(
            outcome.error,
            actor=ctx.actor,
            attempt_no=attempt_no,
            occurred_at=now,
            correlation_id=ctx.correlation_id,
        )
        if outcome.error is not None
        else None
    )
    if status is OutputStatus.SUCCEEDED:
        action = NextAction(
            type=NextActionType.CONTINUE, wait_reason=None, escalation_level=None, reason="done"
        )
    elif status is OutputStatus.SUSPENDED:
        action = NextAction(
            type=NextActionType.WAIT,
            wait_reason=WaitReason(outcome.wait_reason or "DRAIN"),
            escalation_level=None,
            reason="suspended at a checkpoint",
        )
    elif outcome.error is not None and outcome.error.retryable:
        action = NextAction(
            type=NextActionType.RETRY,
            wait_reason=None,
            escalation_level=None,
            reason="retryable error",
        )
    else:
        action = NextAction(
            type=NextActionType.ESCALATE,
            wait_reason=None,
            escalation_level=EscalationLevel.L2,
            reason="permanent error",
        )
    return TaskOutput(
        status=status,
        payload=payload,
        output_refs=refs,
        quality_score=None,
        confidence=None,
        validation_results=tuple(r.to_validation_result() for r in outcome.validation_results),
        duration=duration_ms,
        resource_usage=usage,
        error=error,
        next_action=action,
        downstream_agent=None,
        timestamp=now,
    )
