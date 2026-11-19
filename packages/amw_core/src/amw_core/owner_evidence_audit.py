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
to change after ``CHANGES_REQUESTED`` is an editorial contribution): REQUIRES REVIEW (CCR-191;
owner or integrator: confirm or name another family). The audit details carry identifiers, the
state and the names of failed checks only: never the owner's quote.

Not audited (nothing was recorded): an event that cannot be fetched (the evidence stays pending).
A confirmation attempt that is refused (failed check, replay on a final row, event already used
by another record) leaves the row unchanged but is audited with the existing ``record_refused``
verb and ``details.attempt = "confirmation"`` (PROPOSED CCR-191: 03 names no verb for it; the
verb is reused, none is invented). ``AuditedEvidenceFlow.confirm`` RETURNS a ``ConfirmationResult``
for such an attempt instead of raising, because an exception rolls the caller's tenant
transaction back together with the audit row; an unfetchable event still raises (nothing was
decided, nothing is audited).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from amw_core.enums import ActorKind, EvidenceRecordKind, EvidenceState
from amw_core.errors import (
    IdempotencyConflictError,
    InputInvalidError,
    InvalidTransitionError,
    PermissionDeniedError,
)
from amw_core.ids import ActorRef, Prefix, SystemActor, WireId, prefix_of
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
OPERATOR_REFUSAL_REASONS: Final = frozenset({"source_owner_chat", "operator_refused"})
"""The closed set of reasons the operator tool may give for an attempt it refuses itself; any other
text (it could carry the owner's quote) is replaced by ``operator_refused``."""
_REASON_CODE: Final = re.compile(r"[a-z][a-z0-9_]{0,47}")
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


SUBJECT_KINDS: Final = frozenset(p.name.lower() for p in Prefix)
"""The closed set of ``subject_kind`` values the audit keeps (the entity names of GLOSSARY 2.2);
free text in that column (it is operator input) becomes ``other``."""


def _closed_subject_kind(value: str) -> str:
    return value if value in SUBJECT_KINDS else "other"


def _wire_id_or_none(value: str) -> str | None:
    try:
        prefix_of(value)
    except InputInvalidError:
        return None
    return value


@dataclass(frozen=True, slots=True)
class ConfirmationRefusal:
    reason: str
    failed_checks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    """Outcome of ``AuditedEvidenceFlow.confirm``: ``record`` is the row after the attempt; a
    refused attempt (``refusal`` set) changed nothing but was audited."""

    record: EvidenceRecord
    refusal: ConfirmationRefusal | None = None

    @property
    def confirmed(self) -> bool:
        return self.refusal is None and self.record.state is EvidenceState.CONFIRMED

    def require_confirmed(self) -> EvidenceRecord:
        """The confirmed record, or ``PermissionDeniedError`` for a refused attempt (raise this
        only after the tenant transaction has committed, so the audit row survives)."""
        if self.refusal is not None or not self.confirmed:
            reason = self.refusal.reason if self.refusal else "not_confirmed"
            raise PermissionDeniedError(reason, details={"refusal": reason})
        return self.record


def operator_reason(reason: str | None) -> str:
    """A closed reason code for an operator-refused row (never free text)."""
    return reason if reason in OPERATOR_REFUSAL_REASONS else "operator_refused"


def _safe_code(value: str | None) -> str:
    """A verifier check name or reason code only: anything that is not an identifier-shaped code
    is dropped from the audit details."""
    return value if value is not None and _REASON_CODE.fullmatch(value) else "unspecified"


def audit_entry(
    row: EvidenceRecord,
    now: datetime,
    *,
    action_state: EvidenceState | None = None,
    attempt: str | None = None,
    failed_checks: tuple[str, ...] | None = None,
    reason: str | None = None,
) -> NewAuditEntry:
    e = row.evidence
    details: dict[str, Any] = {
        "evidence_id": row.id,
        "evidence_sha256": row.evidence_sha256,
        "record_kind": e.record_kind.value,
        "subject_kind": _closed_subject_kind(e.subject_kind),
        "state": row.state.value,
        "approval_channel": "OWNER_CHAT_OPERATOR",
    }
    subject_id = _wire_id_or_none(e.subject_id)
    if subject_id is not None:
        details["subject_id"] = subject_id
    if e.approval_id is not None:
        details["approval_id"] = e.approval_id
    if e.step_no is not None:
        details["step_no"] = e.step_no
    if row.state is EvidenceState.REFUSED or action_state is EvidenceState.REFUSED:
        why = reason or row.refused_reason or (failed_checks[0] if failed_checks else None)
        details["refused_reason"] = _safe_code(why)
        names = failed_checks
        if names is None:
            names = tuple(sorted(k for k, ok in row.verifier_result.items() if not ok))
        details["failed_checks"] = [_safe_code(n) for n in names]
    if attempt is not None:
        details["attempt"] = attempt
    return NewAuditEntry(
        actor_kind=ActorKind.SYSTEM,
        actor_ref=ActorRef(SystemActor.OPERATOR.value),
        authority=AUTHORITY,
        action=audit_action(e.record_kind, action_state or row.state),
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
        if state is EvidenceState.REFUSED:
            refused_reason = operator_reason(refused_reason)
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
    ) -> ConfirmationResult:
        try:
            row = self._verifier.confirm(tx, evidence_id, session_id, event_uuid, quote, now)
        except (PermissionDeniedError, InvalidTransitionError, IdempotencyConflictError) as exc:
            return self._refused_confirmation(tx, evidence_id, exc, now)
        return ConfirmationResult(self._audited(tx, row, now))

    def _refused_confirmation(
        self, tx: TenantTransaction, evidence_id: WireId, exc: Exception, now: datetime
    ) -> ConfirmationResult:
        """A refused confirmation attempt is audited and RETURNED, not raised: raising would roll
        the caller's tenant transaction back and take the audit row with it. The record is
        unchanged (still ``VERIFIED``, or already final). ``require_confirmed`` raises after the
        transaction has committed."""
        row = self._db.get(self._operator, tx, evidence_id)
        if row is None:
            raise exc
        checks = exc.details.get("checks") if isinstance(exc, PermissionDeniedError) else None
        if isinstance(checks, dict):
            failed = tuple(sorted(k for k, ok in checks.items() if not ok))
            reason = _safe_code(exc.args[0] if exc.args else None)
        elif isinstance(exc, InvalidTransitionError):
            failed, reason = ("not_verified",), "not_verified"
        elif isinstance(exc, IdempotencyConflictError):
            failed, reason = ("event_conflict",), "event_conflict"
        else:
            failed, reason = ("mac_invalid",), "mac_invalid"
        self._audit.append(
            tx,
            audit_entry(
                row,
                now,
                action_state=EvidenceState.REFUSED,
                attempt="confirmation",
                failed_checks=failed,
                reason=reason,
            ),
        )
        return ConfirmationResult(row, ConfirmationRefusal(reason, failed))
