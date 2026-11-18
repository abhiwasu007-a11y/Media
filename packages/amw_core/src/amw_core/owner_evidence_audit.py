"""Audit verbs of owner-chat evidence (03 section 11.6 rule 6; CCR-121, CCR-131; ticket P4-19).

Every record the operator tool makes from an owner chat message is audited, in the same tenant
transaction as the evidence state change: ``<family>.recorded_from_owner_chat`` when the evidence
is verified, ``<family>.owner_confirmed`` when the owner's second message confirms it, and
``<family>.record_refused`` when it is refused. The family follows the record kind:

========================================================  =====================
``STEP_DECISION``, ``COMPLIANCE_DECISION``,                ``approval``
``KNOWLEDGE_RELEASE_REQUEST``
``CONTRIBUTION``, ``REVISION_NOTE``                        ``editorial_contribution``
``HUMAN_SCORE``                                            ``quality_score``
``OWNER_TOPIC``                                            ``owner_topic``
``DATASET_INTAKE``                                         ``asset_intake``
========================================================  =====================

``REVISION_NOTE`` is not named by 03 rule 6; it is written under ``editorial_contribution`` (what
to change after ``CHANGES_REQUESTED`` is an editorial contribution): REQUIRES REVIEW (owner /
integrator: confirm or name another family). The audit details carry identifiers, the state and
the names of failed checks only: never the owner's quote.

Not audited (nothing was recorded): an event that cannot be fetched (the evidence stays pending)
and a confirmation that fails its check (the row stays ``VERIFIED``; the service raises).
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from amw_core.enums import ActorKind, EvidenceRecordKind, EvidenceState
from amw_core.errors import InvalidTransitionError
from amw_core.ids import ActorRef, SystemActor, WireId
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.owner_evidence import DbSession, EvidenceDatabase, EvidenceRecord
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_service import EvidenceVerifierService
from amw_core.owner_evidence_verifier import NewEvidence

RECORDED: Final = "recorded_from_owner_chat"
CONFIRMED: Final = "owner_confirmed"
REFUSED: Final = "record_refused"
VERBS: Final = (RECORDED, CONFIRMED, REFUSED)

AUDIT_FAMILY: Final[Mapping[EvidenceRecordKind, str]] = {
    EvidenceRecordKind.STEP_DECISION: "approval",
    EvidenceRecordKind.COMPLIANCE_DECISION: "approval",
    EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST: "approval",
    EvidenceRecordKind.CONTRIBUTION: "editorial_contribution",
    EvidenceRecordKind.REVISION_NOTE: "editorial_contribution",
    EvidenceRecordKind.HUMAN_SCORE: "quality_score",
    EvidenceRecordKind.OWNER_TOPIC: "owner_topic",
    EvidenceRecordKind.DATASET_INTAKE: "asset_intake",
}
AUTHORITY: Final = "owner_chat_operator"
"""``audit_log.authority``: the approval channel the record came through (GLOSSARY 6.44)."""
TARGET_KIND: Final = "OWNER_INSTRUCTION_EVIDENCE"

_VERB_OF_STATE: Final[Mapping[EvidenceState, str]] = {
    EvidenceState.VERIFIED: RECORDED,
    EvidenceState.CONFIRMED: CONFIRMED,
    EvidenceState.REFUSED: REFUSED,
}


def audit_action(kind: EvidenceRecordKind, state: EvidenceState) -> str:
    """The dotted audit event for ``kind`` entering ``state``; ``PENDING_VERIFICATION`` has none."""
    verb = _VERB_OF_STATE.get(state)
    if verb is None:
        raise InvalidTransitionError("this evidence state is not audited")
    return f"{AUDIT_FAMILY[kind]}.{verb}"


def audit_entry(row: EvidenceRecord, now: datetime) -> NewAuditEntry:
    e = row.evidence
    details: dict[str, Any] = {
        "evidence_id": row.id,
        "evidence_sha256": row.evidence_sha256,
        "record_kind": e.record_kind.value,
        "subject_kind": e.subject_kind,
        "subject_id": e.subject_id,
        "state": row.state.value,
        "approval_channel": "OWNER_CHAT_OPERATOR",
    }
    if e.approval_id is not None:
        details["approval_id"] = e.approval_id
    if e.step_no is not None:
        details["step_no"] = e.step_no
    if row.state is EvidenceState.REFUSED:
        details["refused_reason"] = row.refused_reason or "unspecified"
        details["failed_checks"] = sorted(k for k, ok in row.verifier_result.items() if not ok)
    return NewAuditEntry(
        actor_kind=ActorKind.SYSTEM,
        actor_ref=ActorRef(SystemActor.OPERATOR.value),
        authority=AUTHORITY,
        action=audit_action(e.record_kind, row.state),
        target_kind=TARGET_KIND,
        target_id=row.id,
        occurred_at=now,
        job_id=e.job_id,
        on_behalf_of=e.on_behalf_of,
        details=details,
    )


class AuditedEvidenceFlow:
    """The operator tool's evidence flow with the audit written in the caller's transaction.

    It composes the operator-side insert, the verifier service and the audit log; it holds no
    verification logic and accepts no verification result (the store verifies).
    """

    def __init__(
        self,
        database: EvidenceDatabase,
        operator: DbSession,
        verifier: EvidenceVerifierService,
        audit: AuditLog,
    ) -> None:
        self._db = database
        self._operator = operator
        self._verifier = verifier
        self._audit = audit

    def _audited(self, tx: TenantTransaction, row: EvidenceRecord, now: datetime) -> EvidenceRecord:
        if row.state in _VERB_OF_STATE:
            self._audit.append(tx, audit_entry(row, now))
        return row

    def record(
        self,
        tx: TenantTransaction,
        evidence: NewEvidence,
        now: datetime,
        *,
        state: EvidenceState = EvidenceState.PENDING_VERIFICATION,
        refused_reason: str | None = None,
    ) -> EvidenceRecord:
        """Operator insert; an attempt the operator already refused (``REFUSED``) is audited."""
        row = self._db.insert_evidence(
            self._operator, tx, evidence, state=state, refused_reason=refused_reason
        )
        return self._audited(tx, row, now)

    def verify(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        anchor: datetime | None,
        now: datetime,
        allowed_stages: frozenset[str] | None = None,
    ) -> EvidenceRecord:
        row = self._verifier.verify_recorded(tx, evidence_id, anchor, now, allowed_stages)
        return self._audited(tx, row, now)

    def confirm(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        session_id: str,
        event_uuid: str,
        quote: str,
        now: datetime,
    ) -> EvidenceRecord:
        row = self._verifier.confirm(tx, evidence_id, session_id, event_uuid, quote, now)
        return self._audited(tx, row, now)
