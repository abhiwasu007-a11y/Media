"""Owner instruction evidence store (04 section 5.16 ``owner_instruction_evidence``; 03 section
11.6 rule 6; CCR-010, decision D5).

**The store verifies.** ``verify_recorded`` and ``confirm`` fetch the owner's event through the
store's own ``SessionEventSource`` and run ``amw_core.owner_evidence_verifier.verify_owner_event``
themselves; no method accepts a verification result, an event or a check list from a caller.
A human record (approval step, editorial contribution, HUMAN score, compliance override) may
reference only a ``CONFIRMED`` row. Rows are append-only except the forward changes
``PENDING_VERIFICATION -> VERIFIED -> CONFIRMED`` or ``-> REFUSED``, each setting its columns once.

**Limitation:** the real session-store adapter is ticket 3A-13; until then only the in-memory
fake exists, and 3A approvals recorded through it are not production-verified.
Implementation (S7 -> 01): lanes; memory fake ``amw_core.testing.memory.MemoryOwnerEvidenceStore``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from amw_core.enums import EvidenceRecordKind, EvidenceState, QualityDimension
from amw_core.ids import OrgId, WireId
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_verifier import NewEvidence, SessionEvent, SessionEventSource

__all__ = [
    "EvidenceRecord",
    "NewEvidence",
    "OwnerEvidenceStore",
    "SessionEvent",
    "SessionEventSource",
]


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    id: WireId
    org_id: OrgId
    evidence: NewEvidence
    state: EvidenceState
    evidence_sha256: str
    event_verified_at: datetime | None = None
    verifier_result: Mapping[str, bool] = field(default_factory=dict)
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

    def verify_recorded(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        request_created_at: datetime,
        now: datetime,
    ) -> EvidenceRecord:
        """``PENDING_VERIFICATION -> VERIFIED`` or ``-> REFUSED``, decided by the store: it
        fetches the row's event through its own source and runs the check (review code and
        decision mandatory; superseded evidence ordering from ``supersedes_id``).
        ``request_created_at`` is ``approvals.created_at`` of the row's approval, read by the
        caller in the same transaction. Unfetchable event -> ``MissingDependencyError`` (the row
        stays pending)."""
        ...

    def confirm(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        session_id: str,
        event_uuid: str,
        quote: str,
        now: datetime,
    ) -> EvidenceRecord:
        """``VERIFIED -> CONFIRMED``. The store fetches the event through its own source and
        runs the same check: a second, distinct, later owner event with the same review code and
        the same decision. Unfetchable -> ``MissingDependencyError``; a failed check ->
        ``PermissionDeniedError`` (``details.checks``). The state is unchanged on any error."""
        ...

    def authorise_human_score(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        subject_kind: str,
        subject_id: WireId,
        dimension: QualityDimension,
        points: int,
    ) -> None:
        """The DB human-row trigger for a HUMAN ``quality_scores`` row (CCR-060): the evidence is
        ``CONFIRMED``, kind ``HUMAN_SCORE``, same subject, and ``points`` is an integer equal to
        ``claimed_scores[dimension]``; else ``PermissionDeniedError``."""
        ...

    def authorise_content(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        record_kind: EvidenceRecordKind,
        subject_kind: str,
        subject_id: WireId,
        text: str,
    ) -> None:
        """The trigger for a CONTENT record (e.g. ``editorial_contributions.description``, a topic
        title): ``CONFIRMED``, same kind and subject, ``text`` a non-empty verbatim substring of
        the evidence quote; else ``PermissionDeniedError``."""
        ...

    def refuse(self, tx: TenantTransaction, evidence_id: WireId, reason: str) -> EvidenceRecord:
        """``PENDING_VERIFICATION`` / ``VERIFIED`` -> ``REFUSED``; a refused row backs nothing."""
        ...

    def get(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceRecord | None: ...

    def for_subject(
        self, tx: TenantTransaction, subject_kind: str, subject_id: WireId
    ) -> Sequence[EvidenceRecord]: ...
