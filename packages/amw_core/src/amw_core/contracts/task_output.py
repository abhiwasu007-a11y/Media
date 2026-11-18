"""``amw.task_output`` 1.0.0 (03 section 5)."""

from typing import Annotated, ClassVar, Self

from pydantic import Field, StrictBool, StringConstraints, model_validator

from amw_core.contracts.common import (
    AmwModel,
    CostEntryIdStr,
    Currency,
    ExecutorIdStr,
    NonNegInt,
    PayloadObject,
    Sha256Hex,
    StorageUri,
    UtcTimestamp,
)
from amw_core.contracts.error import ErrorObject
from amw_core.enums import (
    CheckKind,
    CheckVerdict,
    EscalationLevel,
    NextActionType,
    OutputRefKind,
    OutputStatus,
    WaitReason,
)

MeasuredValue = bool | int | float | str | None
StageId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,32}$")]


class OutputRef(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"entity_ref"})

    uri: StorageUri
    kind: OutputRefKind
    sha256: Sha256Hex
    size_bytes: NonNegInt
    media_type: Annotated[str, StringConstraints(max_length=128)]
    entity_ref: StorageUri | None = None


class ValidationResult(AmwModel):
    check_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.-]{3,96}$")]
    kind: CheckKind
    verdict: CheckVerdict
    blocking: StrictBool
    rule_id: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,8}-R[0-9]{1,3}$")] | None = None
    measured: MeasuredValue = None
    threshold: MeasuredValue = None
    unit: Annotated[str, StringConstraints(max_length=16)] | None = None
    message: Annotated[str, StringConstraints(max_length=2000)]
    evidence_ref: StorageUri | None = None
    gate: StrictBool = False
    """True only for a registered blocking gate stage's domain result (03 section 5.3 rule 4)."""
    remedy_stage_id: StageId | None = None
    """Stage the failing gate result names for the REVISE route (24 section 3.3, CCR-002)."""

    @model_validator(mode="after")
    def _result_rules(self) -> Self:
        # Schema allOf (03 section 5.2 / 5.3 rule 5): WARN/SKIPPED never block; a remedy stage
        # is only named by a gate result.
        if self.verdict in (CheckVerdict.WARN, CheckVerdict.SKIPPED) and self.blocking:
            raise ValueError("a WARN or SKIPPED result must have blocking false")
        if self.remedy_stage_id is not None and not self.gate:
            raise ValueError("remedy_stage_id requires gate true")
        return self


class ResourceUsage(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"render_ms"})

    cpu_ms: NonNegInt
    peak_rss_bytes: NonNegInt
    tokens_in: NonNegInt
    tokens_out: NonNegInt
    tokens_cached_in: NonNegInt
    llm_calls: NonNegInt
    provider_calls: NonNegInt
    render_ms: NonNegInt | None = None
    cost_estimate_micros: NonNegInt
    currency: Currency
    cost_entry_ids: tuple[CostEntryIdStr, ...]


class NextAction(AmwModel):
    """Advisory only (03 section 5.3)."""

    type: NextActionType
    wait_reason: WaitReason | None
    escalation_level: EscalationLevel | None
    reason: Annotated[str, StringConstraints(max_length=1000)]


class TaskOutput(AmwModel):
    """No IDs of its own: stored per attempt and transmitted only inside an envelope (5.1)."""

    status: OutputStatus
    payload: PayloadObject | None
    output_refs: Annotated[tuple[OutputRef, ...], Field(max_length=512)]
    quality_score: Annotated[float, Field(strict=True, ge=0, le=100)] | None
    confidence: Annotated[float, Field(strict=True, ge=0, le=1)] | None
    validation_results: Annotated[tuple[ValidationResult, ...], Field(max_length=1024)]
    duration: NonNegInt
    resource_usage: ResourceUsage
    error: ErrorObject | None
    next_action: NextAction
    downstream_agent: ExecutorIdStr | None
    timestamp: UtcTimestamp

    @model_validator(mode="after")
    def _status_rules(self) -> Self:
        status = self.status
        if status is OutputStatus.SUCCEEDED and (self.payload is None or self.error is not None):
            raise ValueError("SUCCEEDED requires a payload and a null error")
        if status in (OutputStatus.FAILED, OutputStatus.REJECTED) and self.error is None:
            raise ValueError(f"{status} requires an error")
        if status is OutputStatus.SUSPENDED and (
            self.next_action.type is not NextActionType.WAIT or self.next_action.wait_reason is None
        ):
            raise ValueError("SUSPENDED requires next_action.type WAIT and a wait_reason")
        if status is OutputStatus.REJECTED:
            # Schema allOf (CCR-057): 03 section 7.2 rejection, section 6 rule 4 (attempt_no 0).
            if self.payload is not None or self.output_refs:
                raise ValueError("REJECTED requires a null payload and empty output_refs")
            if self.error is not None and self.error.attempt_no != 0:
                raise ValueError("REJECTED at validation requires error.attempt_no 0")
        return self


def integrity_failures(output: TaskOutput) -> tuple[ValidationResult, ...]:
    """03 section 5.3 rule 2(b): blocking process-integrity results (``gate`` false) not ``PASS``.

    Any such result makes a reported ``SUCCEEDED`` an ``AGENT.INCOMPLETE_OUTPUT``. Rules 2(a)
    (payload schema) and 2(c) (stored output refs) need the payload registry and storage; the
    orchestrator checks them.
    """
    return tuple(
        r
        for r in output.validation_results
        if r.blocking and not r.gate and r.verdict is not CheckVerdict.PASS
    )


def gate_failures(output: TaskOutput) -> tuple[ValidationResult, ...]:
    """03 section 5.3 rule 4: the gate failed iff a result has gate, blocking and FAIL."""
    return tuple(
        r
        for r in output.validation_results
        if r.gate and r.blocking and r.verdict is CheckVerdict.FAIL
    )


def meets_success_rule_2b(output: TaskOutput) -> bool:
    """``SUCCEEDED`` and no integrity failure; a failed gate still counts as a succeeded task."""
    return output.status is OutputStatus.SUCCEEDED and not integrity_failures(output)


def has_gate_results(output: TaskOutput) -> bool:
    """True if any result claims ``gate``; the orchestrator accepts that only from a stage the
    production type registers as a blocking gate (else rule 2 fails, ``INCOMPLETE_OUTPUT``)."""
    return any(r.gate for r in output.validation_results)
