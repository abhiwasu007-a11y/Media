"""Owner instruction evidence store (04 section 5.16 ``owner_instruction_evidence``; 03 section
11.6 rule 6; CCR-010, decision D5).

Verification is code-only and lives in ``amw_core.owner_evidence_verifier``: ``mark_verified``
accepts only a sealed ``VerifiedEvidence`` produced by ``verify_owner_event`` for this row, and
``confirm`` fetches the confirmation event through its ``SessionEventSource`` and verifies it
itself; no caller-built event or verifier result is ever trusted. A human record (approval step,
editorial contribution, HUMAN score, compliance override) may reference only a ``CONFIRMED`` row.
Rows are append-only except the forward changes ``PENDING_VERIFICATION -> VERIFIED ->
CONFIRMED`` or ``-> REFUSED``, each setting its columns once.

**Limitation:** the real session-store adapter is ticket 3A-13; until then only the in-memory
fake exists, and 3A approvals recorded through it are not production-verified.
Implementation (S7 -> 01): lanes; memory fake ``amw_core.testing.memory.MemoryOwnerEvidenceStore``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from amw_core.enums import EvidenceState
from amw_core.ids import OrgId, WireId
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_verifier import (
    NewEvidence,
    SessionEvent,
    SessionEventSource,
    VerifiedEvidence,
)

__all__ = [
    "EvidenceRecord",
    "NewEvidence",
    "OwnerEvidenceStore",
    "SessionEvent",
    "SessionEventSource",
    "VerifiedEvidence",
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

    def mark_verified(
        self, tx: TenantTransaction, evidence_id: WireId, verified: VerifiedEvidence
    ) -> EvidenceRecord:
        """``PENDING_VERIFICATION -> VERIFIED``. ``verified`` must come from
        ``verify_recorded_evidence`` for exactly this row (bound by ``evidence_sha256``), else
        ``InvalidTransitionError``; ``verifier_result`` is ``verified.checks``."""
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
        """``VERIFIED -> CONFIRMED``. The store fetches the event through its own
        ``SessionEventSource`` and verifies it with ``verify_confirmation`` (a second, distinct,
        later owner event). Unfetchable -> ``MissingDependencyError``; a failed check ->
        ``PermissionDeniedError`` (``details.checks``). The state is unchanged on any error."""
        ...

    def refuse(self, tx: TenantTransaction, evidence_id: WireId, reason: str) -> EvidenceRecord:
        """``PENDING_VERIFICATION`` / ``VERIFIED`` -> ``REFUSED``; a refused row backs nothing."""
        ...

    def get(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceRecord | None: ...

    def for_subject(
        self, tx: TenantTransaction, subject_kind: str, subject_id: WireId
    ) -> Sequence[EvidenceRecord]: ...
