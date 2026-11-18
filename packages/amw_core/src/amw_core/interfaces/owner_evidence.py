"""Owner instruction evidence (04 section 5.16 ``owner_instruction_evidence``; 03 section 11.6
rule 6; CCR-010, decision D5).

The operator tool (``sys_operator``) supplies only the session and event identifiers and the
decision it read; code fetches the event from the platform's session event store
(``SessionEventSource``) and verifies it. The operator's own text is never evidence. A human
record (approval step, editorial contribution, HUMAN score, compliance override) may reference
only a ``CONFIRMED`` row. Rows are append-only except the forward state changes
``PENDING_VERIFICATION -> VERIFIED -> CONFIRMED`` or ``-> REFUSED``, each setting its columns
once. Implementation (S7 -> 01 and the verifier): lanes; the memory fake is
``amw_core.testing.memory.MemoryOwnerEvidenceStore``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    InstructionSourceKind,
)
from amw_core.ids import ActorRef, ApprovalId, JobId, OrgId, UserId, WireId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """A transcript event as the platform's session event store returns it."""

    session_id: str
    event_uuid: str
    role: str
    is_synthetic: bool
    inbound_origin: str
    content: str
    timestamp: datetime


@runtime_checkable
class SessionEventSource(Protocol):
    def fetch(self, session_id: str, event_uuid: str) -> SessionEvent | None:
        """The event, or ``None`` if it cannot be fetched (the evidence then stays pending)."""
        ...


@dataclass(frozen=True, slots=True)
class NewEvidence:
    """Columns the operator supplies; the quote and timestamp are copied from the fetched event."""

    record_kind: EvidenceRecordKind
    subject_kind: str
    subject_id: WireId
    source_kind: InstructionSourceKind
    session_id: str
    event_uuid: str
    quote: str
    message_at: datetime
    recorded_by: ActorRef
    on_behalf_of: UserId
    job_id: JobId | None = None
    approval_id: ApprovalId | None = None
    step_no: int | None = None
    review_code: str | None = None
    parsed_decision: ApprovalStepState | None = None
    supersedes_id: WireId | None = None


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    id: WireId
    org_id: OrgId
    evidence: NewEvidence
    state: EvidenceState
    evidence_sha256: str
    event_verified_at: datetime | None = None
    verifier_result: Mapping[str, Any] = field(default_factory=dict)
    confirmation_event_uuid: str | None = None
    confirmation_quote: str | None = None
    confirmation_message_at: datetime | None = None
    refused_reason: str | None = None


@runtime_checkable
class OwnerEvidenceStore(Protocol):
    def record(self, tx: TenantTransaction, evidence: NewEvidence) -> EvidenceRecord:
        """Insert ``PENDING_VERIFICATION`` (a non-``OWNER_CHAT_MESSAGE`` source must go straight
        to ``refuse``). A second live row for the same ``(event_uuid, record_kind, subject_kind,
        subject_id)`` is ``IdempotencyConflictError`` (replay key)."""
        ...

    def mark_verified(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        verifier_result: Mapping[str, Any],
        at: datetime,
    ) -> EvidenceRecord:
        """``PENDING_VERIFICATION -> VERIFIED`` after the code check passed."""
        ...

    def confirm(
        self, tx: TenantTransaction, evidence_id: WireId, confirmation: SessionEvent
    ) -> EvidenceRecord:
        """``VERIFIED -> CONFIRMED`` with a second verified owner event later than the first."""
        ...

    def refuse(self, tx: TenantTransaction, evidence_id: WireId, reason: str) -> EvidenceRecord:
        """``PENDING_VERIFICATION`` / ``VERIFIED`` -> ``REFUSED``; a refused row backs nothing."""
        ...

    def get(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceRecord | None: ...

    def for_subject(
        self, tx: TenantTransaction, subject_kind: str, subject_id: WireId
    ) -> Sequence[EvidenceRecord]: ...
