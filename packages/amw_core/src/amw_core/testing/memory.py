"""In-memory fakes: transaction, idempotency, checkpoint and owner-evidence stores.

They follow the interface docstrings exactly and partition every row by the transaction's
``org_id`` (a fake tenant boundary). Not for production use.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from amw_core.enums import (
    EvidenceRecordKind,
    EvidenceState,
    IdempotencyStatus,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.errors import (
    IdempotencyConflictError,
    InputInvalidError,
    InvalidTransitionError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import (
    CHECKPOINT,
    NEVER_EXPIRING_SCOPE_PREFIXES,
    OWNER_EVIDENCE,
    CheckpointId,
    IdempotencyKey,
    OrgId,
    TaskId,
    WireId,
    idempotency_key_of,
    is_idempotency_scope,
)
from amw_core.interfaces.checkpoint_store import CheckpointRecord, NewCheckpoint
from amw_core.interfaces.idempotency_store import BeginAction, BeginDecision, IdempotencyRecord
from amw_core.interfaces.owner_evidence import EvidenceRecord
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_core.owner_evidence_verifier import (
    CONFIRMATION,
    RECORD,
    EventUnavailable,
    NewEvidence,
    Refusal,
    SessionEvent,
    SessionEventSource,
    Verified,
    VerifierPolicy,
    evidence_sha256,
    verify_owner_event,
)


@dataclass(frozen=True, slots=True)
class MemoryTransaction:
    """A ``TenantTransaction`` stand-in: only carries the tenant context."""

    context: TenantContext


class MemoryIdempotencyStore:
    def __init__(self, default_retention: timedelta | None = None) -> None:
        self._rows: dict[tuple[OrgId, IdempotencyKey], IdempotencyRecord] = {}
        self._retention = default_retention

    def begin(
        self,
        tx: TenantTransaction,
        key: IdempotencyKey,
        scope: str,
        request_sha256: str,
        task_id: TaskId | None,
        now: datetime,
        lock_ms: int,
    ) -> BeginDecision:
        idempotency_key_of(key)
        if not is_idempotency_scope(scope):
            raise InputInvalidError(f"unknown idempotency scope {scope!r} (03 section 9.2)")
        org = tx.context.org_id
        locked_until = now + timedelta(milliseconds=lock_ms)
        row = self._rows.get((org, key))
        if row is None:
            never = scope.startswith(NEVER_EXPIRING_SCOPE_PREFIXES)
            expires = None if never or self._retention is None else now + self._retention
            row = IdempotencyRecord(
                org_id=org,
                key=key,
                scope=scope,
                request_sha256=request_sha256,
                status=IdempotencyStatus.IN_PROGRESS,
                task_id=task_id,
                result_ref=None,
                locked_until=locked_until,
                completed_at=None,
                expires_at=expires,
                created_at=now,
            )
            self._rows[(org, key)] = row
            return BeginDecision(BeginAction.PROCEED, row)
        if row.request_sha256 != request_sha256 and row.status is not IdempotencyStatus.FAILED:
            raise IdempotencyConflictError("same idempotency key, different request hash")
        if row.status is IdempotencyStatus.COMPLETED:
            return BeginDecision(BeginAction.RETURN_STORED, row)
        if row.status is IdempotencyStatus.FAILED:
            row = replace(
                row,
                status=IdempotencyStatus.IN_PROGRESS,
                request_sha256=request_sha256,
                locked_until=locked_until,
            )
            self._rows[(org, key)] = row
            return BeginDecision(BeginAction.PROCEED, row)
        if row.locked_until is not None and row.locked_until < now:
            return BeginDecision(BeginAction.RECONCILE, row)
        return BeginDecision(BeginAction.IN_FLIGHT, row)

    def _require_in_progress(self, tx: TenantTransaction, key: IdempotencyKey) -> IdempotencyRecord:
        row = self._rows.get((tx.context.org_id, key))
        if row is None or row.status is not IdempotencyStatus.IN_PROGRESS:
            raise InvalidTransitionError("idempotency key is not IN_PROGRESS")
        return row

    def complete(
        self, tx: TenantTransaction, key: IdempotencyKey, result_ref: str, now: datetime
    ) -> IdempotencyRecord:
        row = replace(
            self._require_in_progress(tx, key),
            status=IdempotencyStatus.COMPLETED,
            result_ref=result_ref,
            locked_until=None,
            completed_at=now,
        )
        self._rows[(tx.context.org_id, key)] = row
        return row

    def fail(self, tx: TenantTransaction, key: IdempotencyKey, now: datetime) -> IdempotencyRecord:
        row = replace(
            self._require_in_progress(tx, key), status=IdempotencyStatus.FAILED, locked_until=None
        )
        self._rows[(tx.context.org_id, key)] = row
        return row

    def get(self, tx: TenantTransaction, key: IdempotencyKey) -> IdempotencyRecord | None:
        return self._rows.get((tx.context.org_id, key))


class MemoryCheckpointStore:
    def __init__(self) -> None:
        self._rows: dict[OrgId, list[CheckpointRecord]] = {}

    def write(
        self, tx: TenantTransaction, checkpoint: NewCheckpoint, now: datetime
    ) -> CheckpointRecord:
        ratio = checkpoint.progress_ratio
        if ratio is not None and not Decimal(0) <= ratio <= Decimal(1):
            raise InputInvalidError("progress_ratio must be within 0-1")
        rows = self._rows.setdefault(tx.context.org_id, [])
        mine = [r for r in rows if r.checkpoint.task_id == checkpoint.task_id]
        for i, row in enumerate(rows):
            if row.checkpoint.task_id == checkpoint.task_id and row.is_latest:
                rows[i] = replace(row, is_latest=False)
        record = CheckpointRecord(
            id=CHECKPOINT.new(),
            org_id=tx.context.org_id,
            seq=len(mine) + 1,
            is_latest=True,
            created_at=now,
            checkpoint=checkpoint,
        )
        rows.append(record)
        return record

    def latest(self, tx: TenantTransaction, task_id: TaskId) -> CheckpointRecord | None:
        found = [r for r in self.list_for_task(tx, task_id) if r.is_latest]
        return found[0] if found else None

    def get(self, tx: TenantTransaction, checkpoint_id: CheckpointId) -> CheckpointRecord | None:
        return next(
            (r for r in self._rows.get(tx.context.org_id, []) if r.id == checkpoint_id), None
        )

    def list_for_task(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[CheckpointRecord]:
        rows = self._rows.get(tx.context.org_id, [])
        return sorted((r for r in rows if r.checkpoint.task_id == task_id), key=lambda r: r.seq)


class MemorySessionEventSource:
    """In-memory stand-in for the platform session event store (the real one is ticket 3A-13)."""

    def __init__(self, events: Sequence[SessionEvent] = ()) -> None:
        self._events: dict[tuple[str, str], SessionEvent] = {}
        for event in events:
            self.add(event)

    def add(self, event: SessionEvent) -> None:
        self._events[(event.session_id, event.event_uuid)] = event

    def fetch(self, session_id: str, event_uuid: str) -> SessionEvent | None:
        return self._events.get((session_id, event_uuid))


class MemoryOwnerEvidenceStore:
    """Forward-only states; the replay key is unique among non-refused rows (04 section 5.16)."""

    def __init__(self, source: SessionEventSource, policy: VerifierPolicy) -> None:
        self._rows: dict[tuple[OrgId, WireId], EvidenceRecord] = {}
        self._source = source
        self._policy = policy

    def _replay_key(self, org: OrgId, e: NewEvidence) -> tuple[Any, ...]:
        return (org, e.event_uuid, e.record_kind, e.subject_kind, e.subject_id)

    def record(self, tx: TenantTransaction, evidence: NewEvidence) -> EvidenceRecord:
        org = tx.context.org_id
        key = self._replay_key(org, evidence)
        for (row_org, _), row in self._rows.items():
            live = row.state is not EvidenceState.REFUSED
            if row_org == org and live and self._replay_key(org, row.evidence) == key:
                raise IdempotencyConflictError("owner message already backs this record")
        row = EvidenceRecord(
            id=OWNER_EVIDENCE.new(),
            org_id=org,
            evidence=evidence,
            state=EvidenceState.PENDING_VERIFICATION,
            evidence_sha256=evidence_sha256(evidence),
        )
        self._rows[(org, row.id)] = row
        return row

    def _move(
        self, tx: TenantTransaction, evidence_id: WireId, allowed: tuple[EvidenceState, ...]
    ) -> EvidenceRecord:
        row = self._rows.get((tx.context.org_id, evidence_id))
        if row is None or row.state not in allowed:
            raise InvalidTransitionError("evidence state change not allowed")
        return row

    def _check(
        self,
        tx: TenantTransaction,
        row: EvidenceRecord,
        purpose: str,
        event: SessionEvent | None,
        *,
        event_uuid: str,
        quote: str,
        message_at: datetime | None,
        not_before: datetime,
        distinct_from: str | None,
        now: datetime,
    ) -> Verified | Refusal | EventUnavailable:
        outcome = verify_owner_event(
            event,
            evidence=row.evidence,
            evidence_id=row.id,
            purpose=purpose,
            quote=quote,
            message_at=message_at,
            not_before=not_before,
            distinct_from_event_uuid=distinct_from,
            policy=self._policy,
            now=now,
        )
        if isinstance(outcome, Verified):
            if (
                outcome.evidence_id != row.id
                or outcome.event_uuid != event_uuid
                or outcome.bound_sha256 != row.evidence_sha256
                or outcome.purpose != purpose
            ):
                raise InvalidTransitionError("verification is not bound to this evidence row")
            if self._event_backs_other_subject(tx, row, event_uuid):
                return Refusal("one_subject_per_message", (*outcome.checks, ("one_subject", False)))
        return outcome

    def _event_backs_other_subject(
        self, tx: TenantTransaction, row: EvidenceRecord, event_uuid: str
    ) -> bool:
        """One owner message verifies exactly one subject (no multi-subject format exists)."""
        subject = (row.evidence.subject_kind, row.evidence.subject_id)
        for (org, other_id), other in self._rows.items():
            if org != tx.context.org_id or other_id == row.id:
                continue
            if other.state is EvidenceState.REFUSED:
                continue
            uses = {other.evidence.event_uuid, other.confirmation_event_uuid}
            if (
                event_uuid in uses
                and (other.evidence.subject_kind, other.evidence.subject_id) != subject
            ):
                return True
        return False

    def verify_recorded(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        request_created_at: datetime,
        now: datetime,
    ) -> EvidenceRecord:
        row = self._move(tx, evidence_id, (EvidenceState.PENDING_VERIFICATION,))
        e = row.evidence
        if e.source_kind is not InstructionSourceKind.OWNER_CHAT_MESSAGE:
            return self.refuse(tx, evidence_id, "source is not an owner chat message")
        not_before = request_created_at
        if e.supersedes_id is not None:
            older = self._rows.get((tx.context.org_id, e.supersedes_id))
            if older is None:
                raise MissingDependencyError("superseded evidence not found")
            not_before = max(not_before, older.evidence.message_at)
        outcome = self._check(
            tx,
            row,
            RECORD,
            self._source.fetch(e.session_id, e.event_uuid),
            event_uuid=e.event_uuid,
            quote=e.quote,
            message_at=e.message_at,
            not_before=not_before,
            distinct_from=None,
            now=now,
        )
        if isinstance(outcome, EventUnavailable):
            raise MissingDependencyError("owner event cannot be fetched; evidence stays pending")
        if isinstance(outcome, Refusal):
            refused = self.refuse(tx, evidence_id, outcome.reason)
            refused = replace(refused, verifier_result=dict(outcome.checks))
            self._rows[(tx.context.org_id, evidence_id)] = refused
            return refused
        row = replace(
            row,
            state=EvidenceState.VERIFIED,
            event_verified_at=outcome.verified_at,
            verifier_result=dict(outcome.checks),
        )
        self._rows[(tx.context.org_id, evidence_id)] = row
        return row

    def confirm(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        session_id: str,
        event_uuid: str,
        quote: str,
        now: datetime,
    ) -> EvidenceRecord:
        row = self._move(tx, evidence_id, (EvidenceState.VERIFIED,))
        outcome = self._check(
            tx,
            row,
            CONFIRMATION,
            self._source.fetch(session_id, event_uuid),
            event_uuid=event_uuid,
            quote=quote,
            message_at=None,
            not_before=row.evidence.message_at,
            distinct_from=row.evidence.event_uuid,
            now=now,
        )
        if isinstance(outcome, EventUnavailable):
            raise MissingDependencyError("confirmation event cannot be fetched")
        if isinstance(outcome, Refusal):
            raise PermissionDeniedError(outcome.reason, details={"checks": dict(outcome.checks)})
        row = replace(
            row,
            state=EvidenceState.CONFIRMED,
            confirmation_event_uuid=outcome.event_uuid,
            confirmation_quote=quote,
            confirmation_message_at=outcome.event_timestamp,
        )
        self._rows[(tx.context.org_id, evidence_id)] = row
        return row

    def _confirmed(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        record_kind: EvidenceRecordKind,
        subject_kind: str,
        subject_id: WireId,
    ) -> EvidenceRecord:
        row = self._rows.get((tx.context.org_id, evidence_id))
        if (
            row is None
            or row.state is not EvidenceState.CONFIRMED
            or row.evidence.record_kind is not record_kind
            or (row.evidence.subject_kind, row.evidence.subject_id) != (subject_kind, subject_id)
        ):
            raise PermissionDeniedError("no confirmed owner evidence for this human record")
        return row

    def authorise_human_score(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        subject_kind: str,
        subject_id: WireId,
        dimension: QualityDimension,
        points: int,
    ) -> None:
        row = self._confirmed(
            tx, evidence_id, EvidenceRecordKind.HUMAN_SCORE, subject_kind, subject_id
        )
        claimed = dict(row.evidence.claimed_scores)
        if (
            isinstance(points, bool)
            or not isinstance(points, int)
            or claimed.get(dimension) != points
        ):
            raise PermissionDeniedError("score row does not equal the owner's claimed score")

    def authorise_content(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        record_kind: EvidenceRecordKind,
        subject_kind: str,
        subject_id: WireId,
        text: str,
    ) -> None:
        row = self._confirmed(tx, evidence_id, record_kind, subject_kind, subject_id)
        if not text or text not in row.evidence.quote:
            raise PermissionDeniedError("record text is not a verbatim substring of the quote")

    def refuse(self, tx: TenantTransaction, evidence_id: WireId, reason: str) -> EvidenceRecord:
        row = self._move(
            tx, evidence_id, (EvidenceState.PENDING_VERIFICATION, EvidenceState.VERIFIED)
        )
        row = replace(row, state=EvidenceState.REFUSED, refused_reason=reason)
        self._rows[(tx.context.org_id, evidence_id)] = row
        return row

    def get(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceRecord | None:
        return self._rows.get((tx.context.org_id, evidence_id))

    def for_subject(
        self, tx: TenantTransaction, subject_kind: str, subject_id: WireId
    ) -> Sequence[EvidenceRecord]:
        org = tx.context.org_id
        return [
            r
            for (row_org, _), r in self._rows.items()
            if row_org == org
            and r.evidence.subject_kind == subject_kind
            and r.evidence.subject_id == subject_id
        ]
