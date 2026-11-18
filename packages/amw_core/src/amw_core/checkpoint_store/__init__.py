"""PostgreSQL ``CheckpointStore`` (04 section 5.7 ``checkpoints``; 07 section 10).

``write`` serialises per task with a transaction advisory lock, clears the previous ``is_latest``
and inserts ``seq = last + 1`` with ``is_latest = true`` (the partial UNIQUE index guarantees one
latest row). The state blob is written write-once through ``BlobStorage`` before this call; the
row stores its URI and SHA-256. Nothing else is ever updated.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from amw_core.errors import InputInvalidError
from amw_core.ids import (
    ATTEMPT,
    CHECKPOINT,
    TASK,
    CheckpointId,
    IdempotencyKey,
    TaskId,
    idempotency_key_of,
)
from amw_core.interfaces.checkpoint_store import CheckpointRecord, NewCheckpoint
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

_COLS = (
    "id, task_id, attempt_id, seq, step_key, state_ref, state_sha256, completed_effects,"
    " progress_ratio, is_latest, created_at"
)


class PgCheckpointStore:
    def _exec(self, tx: TenantTransaction, query: str, params: Sequence[Any]) -> list[Any]:
        try:
            cur = connection_of(tx).execute(query.encode(), params)
            return cur.fetchall() if cur.description else []
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc

    def _record(self, tx: TenantTransaction, row: Sequence[Any]) -> CheckpointRecord:
        cid, task, att, seq, step, ref, sha, effects, ratio, latest, created = row
        return CheckpointRecord(
            id=CHECKPOINT.from_uuid(cid),
            org_id=tx.context.org_id,
            seq=int(seq),
            is_latest=bool(latest),
            created_at=created,
            checkpoint=NewCheckpoint(
                task_id=TASK.from_uuid(task),
                attempt_id=ATTEMPT.from_uuid(att),
                step_key=step,
                state_ref=ref,
                state_sha256=bytes(sha).hex(),
                completed_effects=tuple(IdempotencyKey(e) for e in effects),
                progress_ratio=Decimal(ratio) if ratio is not None else None,
            ),
        )

    def write(
        self, tx: TenantTransaction, checkpoint: NewCheckpoint, now: datetime
    ) -> CheckpointRecord:
        ratio = checkpoint.progress_ratio
        if ratio is not None and not Decimal(0) <= ratio <= Decimal(1):
            raise InputInvalidError("progress_ratio must be within 0-1")
        if len(checkpoint.state_sha256) != 64:
            raise InputInvalidError("state_sha256 must be 64 hex characters")
        for key in checkpoint.completed_effects:
            idempotency_key_of(key)
        org = org_uuid_of(tx)
        task = TASK.to_uuid(checkpoint.task_id)
        self._exec(
            tx, "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"ckp:{org}:{task}",)
        )
        last = self._exec(
            tx,
            "SELECT coalesce(max(seq), 0) FROM checkpoints WHERE org_id = %s AND task_id = %s",
            (org, task),
        )
        seq = int(last[0][0]) + 1
        self._exec(
            tx,
            "UPDATE checkpoints SET is_latest = false"
            " WHERE org_id = %s AND task_id = %s AND is_latest",
            (org, task),
        )
        new_id = CHECKPOINT.new()
        rows = self._exec(
            tx,
            f"INSERT INTO checkpoints (org_id, {_COLS})"  # noqa: S608
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)"
            f" RETURNING {_COLS}",
            (
                org,
                CHECKPOINT.to_uuid(new_id),
                task,
                ATTEMPT.to_uuid(checkpoint.attempt_id),
                seq,
                checkpoint.step_key,
                checkpoint.state_ref,
                bytes.fromhex(checkpoint.state_sha256),
                list(checkpoint.completed_effects),
                ratio,
                now,
            ),
        )
        return self._record(tx, rows[0])

    def latest(self, tx: TenantTransaction, task_id: TaskId) -> CheckpointRecord | None:
        rows = self._exec(
            tx,
            f"SELECT {_COLS} FROM checkpoints"  # noqa: S608
            " WHERE org_id = %s AND task_id = %s AND is_latest",
            (org_uuid_of(tx), TASK.to_uuid(task_id)),
        )
        return self._record(tx, rows[0]) if rows else None

    def get(self, tx: TenantTransaction, checkpoint_id: CheckpointId) -> CheckpointRecord | None:
        rows = self._exec(
            tx,
            f"SELECT {_COLS} FROM checkpoints WHERE org_id = %s AND id = %s",  # noqa: S608
            (org_uuid_of(tx), CHECKPOINT.to_uuid(checkpoint_id)),
        )
        return self._record(tx, rows[0]) if rows else None

    def list_for_task(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[CheckpointRecord]:
        rows = self._exec(
            tx,
            f"SELECT {_COLS} FROM checkpoints"  # noqa: S608
            " WHERE org_id = %s AND task_id = %s ORDER BY seq",
            (org_uuid_of(tx), TASK.to_uuid(task_id)),
        )
        return [self._record(tx, r) for r in rows]


__all__ = ["PgCheckpointStore"]
