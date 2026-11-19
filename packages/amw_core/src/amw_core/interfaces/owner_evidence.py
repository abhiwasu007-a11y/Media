"""Owner instruction evidence: the database surface of 04 sections 3.1 / 3.6a / 5.16 (CCR-100,
CCR-101) as a Protocol, and the records it returns.

Provenance is enforced by **database roles**, not by any actor the caller names:

* ``amw_operator`` (the operator tool) may only insert evidence in ``PENDING_VERIFICATION`` or
  ``REFUSED`` with every verification, confirmation and MAC column empty, and call
  ``human_record_apply`` (``amw_human_record_apply``) for a ``CONFIRMED`` row with a valid MAC;
* ``amw_verifier`` (the evidence verifier component) alone calls ``mark_verified`` /
  ``mark_confirmed`` / ``refuse``; the definer functions (owner ``amw_verifier_fn``) stamp the
  keyed ``evidence_mac`` (HMAC-SHA256, ``mac_key_version``) with a key no role can read;
* every consumer re-checks ``mac_valid`` (``amw_evidence_mac_valid``).

Identity comes from the connection's role (``session_user`` / ``current_user``), never from
``app.actor`` or ``TenantContext.actor``. A shared superuser can still bypass this; the MAC makes
such a change detectable (08; defence in depth). Lane L1a implements the PostgreSQL roles,
functions and triggers; ``amw_core.owner_evidence_fake.FakeEvidenceDatabase`` models them in
memory. The verification itself (fetch the event, run 03 section 11.6 rule 7) is
``amw_core.owner_evidence_service.EvidenceVerifierService``.

**Session record (3A-13 / WS-08):** the real source is
``amw_adapters.session_record.ClaudeSessionJsonlSource`` (wired by
``amw_core.owner_evidence_real``); approvals recorded through the in-memory fake are TEST
fixtures (dry run only). Residual risks: ``docs/v4/runtime/EVIDENCE_PATH.md``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from amw_core.enums import ApprovalStepState, EvidenceRecordKind, EvidenceState, QualityDimension
from amw_core.ids import OrgId, UserId, WireId
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_verifier import NewEvidence, SessionEvent, SessionEventSource

__all__ = [
    "DbRole",
    "DbSession",
    "EvidenceDatabase",
    "EvidenceRecord",
    "HumanRecord",
    "NewEvidence",
    "SessionEvent",
    "SessionEventSource",
]


class DbRole(StrEnum):
    """Login roles of 04 section 3.1 that touch owner evidence (CCR-100)."""

    APP = "amw_app"
    OPERATOR = "amw_operator"
    VERIFIER = "amw_verifier"


@runtime_checkable
class DbSession(Protocol):
    """An authenticated database connection; ``role`` is its ``session_user``."""

    @property
    def role(self) -> DbRole: ...


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
    evidence_mac: bytes | None = None
    mac_key_version: int | None = None


@dataclass(frozen=True, slots=True)
class HumanRecord:
    """One human row written by ``amw_human_record_apply`` (``approval_channel =
    OWNER_CHAT_OPERATOR``, ``recorded_by = sys_operator``, ``evidence_id``)."""

    evidence_id: WireId
    org_id: OrgId
    record_kind: EvidenceRecordKind
    subject_kind: str
    subject_id: WireId
    decided_by: UserId
    decision: ApprovalStepState | None = None
    target_stage_id: str | None = None
    text: str | None = None
    scores: tuple[tuple[QualityDimension, int], ...] = ()


@runtime_checkable
class EvidenceDatabase(Protocol):
    """``owner_instruction_evidence`` and the 04 section 3.6a functions. Every method checks the
    session's role; a wrong role is ``PermissionDeniedError``."""

    def insert_evidence(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence: NewEvidence,
        *,
        state: EvidenceState = EvidenceState.PENDING_VERIFICATION,
        refused_reason: str | None = None,
        verifier_result: Mapping[str, bool] | None = None,
        event_verified_at: datetime | None = None,
        confirmation_event_uuid: str | None = None,
        evidence_mac: bytes | None = None,
        mac_key_version: int | None = None,
    ) -> EvidenceRecord:
        """``amw_operator`` only; ``state`` ``PENDING_VERIFICATION`` (or ``REFUSED`` with a
        reason) and every verification / confirmation / MAC column ``None`` (INSERT CHECK +
        trigger). Keys: one live row per ``event_uuid``; an event that confirms another row can
        never be a row's event (CCR-101)."""
        ...

    def mark_verified(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        verifier_result: Mapping[str, bool],
        at: datetime,
    ) -> EvidenceRecord:
        """``amw_evidence_mark_verified``: ``amw_verifier`` only, from ``PENDING_VERIFICATION``,
        owner-chat sources only; stamps ``evidence_mac``."""
        ...

    def mark_confirmed(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        confirmation_event_uuid: str,
        confirmation_quote: str,
        confirmation_message_at: datetime,
        verifier_result: Mapping[str, bool],
    ) -> EvidenceRecord:
        """``amw_evidence_mark_confirmed``: ``amw_verifier`` only, from ``VERIFIED`` with a valid
        MAC; the confirmation event is unique and never another row's event; new MAC."""
        ...

    def refuse(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        reason: str,
        verifier_result: Mapping[str, bool],
    ) -> EvidenceRecord:
        """``amw_evidence_refuse``: ``amw_verifier`` only, ``PENDING_VERIFICATION`` / ``VERIFIED``
        -> ``REFUSED``."""
        ...

    def mac_valid(self, session: DbSession, tx: TenantTransaction, evidence_id: WireId) -> bool:
        """``amw_evidence_mac_valid``: any of the three roles; never returns the key."""
        ...

    def human_record_apply(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        text: str | None = None,
    ) -> HumanRecord:
        """``amw_human_record_apply``: ``amw_operator`` only; a ``CONFIRMED`` row with a valid
        MAC; writes exactly the one human row the evidence names (scores from
        ``claimed_scores``; a CONTENT text must be a verbatim substring of the quote), once."""
        ...

    def get(
        self, session: DbSession, tx: TenantTransaction, evidence_id: WireId
    ) -> EvidenceRecord | None: ...

    def for_subject(
        self, session: DbSession, tx: TenantTransaction, subject_kind: str, subject_id: WireId
    ) -> Sequence[EvidenceRecord]: ...
