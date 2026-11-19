"""In-memory fakes: transaction, idempotency and checkpoint stores (owner evidence:
``amw_core.owner_evidence_fake``).

They follow the interface docstrings exactly and partition every row by the transaction's
``org_id`` (a fake tenant boundary). Not for production use.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from amw_core.enums import (
    IdempotencyStatus,
)
from amw_core.errors import (
    IdempotencyConflictError,
    InputInvalidError,
    InvalidTransitionError,
)
from amw_core.ids import (
    CHECKPOINT,
    NEVER_EXPIRING_SCOPE_PREFIXES,
    CheckpointId,
    IdempotencyKey,
    OrgId,
    TaskId,
    idempotency_key_of,
    is_idempotency_scope,
)
from amw_core.interfaces.checkpoint_store import CheckpointRecord, NewCheckpoint
from amw_core.interfaces.idempotency_store import BeginAction, BeginDecision, IdempotencyRecord
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction


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
            row = replace(row, locked_until=locked_until)  # the reconciler holds the key now
            self._rows[(org, key)] = row
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
