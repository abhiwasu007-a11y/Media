"""PostgreSQL ``IdempotencyStore`` (03 section 9.1 rule 3; 04 section 5.9 ``idempotency_keys``).

Decision table (identical to ``amw_core.testing.memory.MemoryIdempotencyStore``):
no row -> insert ``IN_PROGRESS`` -> ``PROCEED``; ``COMPLETED`` same hash -> ``RETURN_STORED``;
different hash while ``COMPLETED`` / ``IN_PROGRESS`` -> ``IdempotencyConflictError``;
``IN_PROGRESS`` same hash and ``locked_until`` passed -> ``RECONCILE``; still locked ->
``IN_FLIGHT``; ``FAILED`` -> back to ``IN_PROGRESS`` -> ``PROCEED``.

Concurrency: the insert uses ``ON CONFLICT DO NOTHING`` and every other path reads the row
``FOR UPDATE``, so two attempts racing on one key never both get ``PROCEED``.
"""

from datetime import datetime, timedelta
from typing import Any

import psycopg

from amw_core.enums import IdempotencyStatus
from amw_core.errors import IdempotencyConflictError, InputInvalidError, InvalidTransitionError
from amw_core.ids import (
    NEVER_EXPIRING_SCOPE_PREFIXES,
    TASK,
    IdempotencyKey,
    TaskId,
    idempotency_key_of,
    is_idempotency_scope,
)
from amw_core.interfaces.idempotency_store import BeginAction, BeginDecision, IdempotencyRecord
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

_COLS = (
    "key, scope, request_sha256, status, task_id, result_ref, locked_until, completed_at,"
    " expires_at, created_at"
)


def _sha_bytes(value: str) -> bytes:
    if len(value) != 64:
        raise InputInvalidError("request_sha256 must be 64 hex characters")
    try:
        return bytes.fromhex(value)
    except ValueError:
        raise InputInvalidError("request_sha256 must be hex") from None


class PgIdempotencyStore:
    def __init__(self, default_retention: timedelta | None = None) -> None:
        """``default_retention``: expiry of keys outside ``upload.*`` / ``publish.*`` (04 section 7
        says "with job retention"; the value is REQUIRES REVIEW, so none by default)."""
        self._retention = default_retention

    def _record(self, tx: TenantTransaction, row: tuple[Any, ...]) -> IdempotencyRecord:
        key, scope, sha, status, task, result, locked, completed, expires, created = row
        return IdempotencyRecord(
            org_id=tx.context.org_id,
            key=IdempotencyKey(key),
            scope=scope,
            request_sha256=bytes(sha).hex(),
            status=IdempotencyStatus(status),
            task_id=TASK.from_uuid(task) if task else None,
            result_ref=result,
            locked_until=locked,
            completed_at=completed,
            expires_at=expires,
            created_at=created,
        )

    def _row(self, tx: TenantTransaction, key: str, lock: bool) -> IdempotencyRecord | None:
        try:
            row = (
                connection_of(tx)
                .execute(
                    f"SELECT {_COLS} FROM idempotency_keys WHERE org_id = %s AND key = %s"  # noqa: S608
                    + (" FOR UPDATE" if lock else ""),
                    (org_uuid_of(tx), key),
                )
                .fetchone()
            )
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        return None if row is None else self._record(tx, row)

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
        sha = _sha_bytes(request_sha256)
        locked_until = now + timedelta(milliseconds=lock_ms)
        never = scope.startswith(NEVER_EXPIRING_SCOPE_PREFIXES)
        expires = None if never or self._retention is None else now + self._retention
        conn = connection_of(tx)
        org = org_uuid_of(tx)
        try:
            inserted = conn.execute(
                "INSERT INTO idempotency_keys (org_id, key, scope, request_sha256, status, task_id,"
                " locked_until, expires_at, created_at)"
                " VALUES (%s, %s, %s, %s, 'IN_PROGRESS', %s, %s, %s, %s)"
                " ON CONFLICT (org_id, key) DO NOTHING",
                (
                    org,
                    key,
                    scope,
                    sha,
                    TASK.to_uuid(task_id) if task_id else None,
                    locked_until,
                    expires,
                    now,
                ),
            ).rowcount
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        row = self._row(tx, key, lock=True)
        assert row is not None  # noqa: S101 - inserted or present
        if inserted == 1:
            return BeginDecision(BeginAction.PROCEED, row)
        if row.request_sha256 != request_sha256 and row.status is not IdempotencyStatus.FAILED:
            raise IdempotencyConflictError("same idempotency key, different request hash")
        if row.status is IdempotencyStatus.COMPLETED:
            return BeginDecision(BeginAction.RETURN_STORED, row)
        if row.status is IdempotencyStatus.FAILED:
            self._update(
                tx,
                key,
                "status = 'IN_PROGRESS', request_sha256 = %s, locked_until = %s",
                (sha, locked_until),
            )
            refreshed = self._row(tx, key, lock=False)
            assert refreshed is not None  # noqa: S101
            return BeginDecision(BeginAction.PROCEED, refreshed)
        if row.locked_until is not None and row.locked_until < now:
            # The reconciler holds the key from now on: renew the lock so that the next caller
            # gets IN_FLIGHT, not a second RECONCILE (PR #44 review m9).
            self._update(tx, key, "locked_until = %s", (locked_until,))
            renewed = self._row(tx, key, lock=False)
            assert renewed is not None  # noqa: S101
            return BeginDecision(BeginAction.RECONCILE, renewed)
        return BeginDecision(BeginAction.IN_FLIGHT, row)

    def _update(self, tx: TenantTransaction, key: str, sets: str, params: tuple[Any, ...]) -> None:
        try:
            connection_of(tx).execute(
                f"UPDATE idempotency_keys SET {sets} WHERE org_id = %s AND key = %s".encode(),  # noqa: S608
                (*params, org_uuid_of(tx), key),
            )
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc

    def _require_in_progress(self, tx: TenantTransaction, key: IdempotencyKey) -> None:
        row = self._row(tx, key, lock=True)
        if row is None or row.status is not IdempotencyStatus.IN_PROGRESS:
            raise InvalidTransitionError("idempotency key is not IN_PROGRESS")

    def complete(
        self, tx: TenantTransaction, key: IdempotencyKey, result_ref: str, now: datetime
    ) -> IdempotencyRecord:
        self._require_in_progress(tx, key)
        self._update(
            tx,
            key,
            "status = 'COMPLETED', result_ref = %s, locked_until = NULL, completed_at = %s",
            (result_ref, now),
        )
        row = self._row(tx, key, lock=False)
        assert row is not None  # noqa: S101
        return row

    def fail(self, tx: TenantTransaction, key: IdempotencyKey, now: datetime) -> IdempotencyRecord:
        self._require_in_progress(tx, key)
        self._update(tx, key, "status = 'FAILED', locked_until = NULL", ())
        row = self._row(tx, key, lock=False)
        assert row is not None  # noqa: S101
        return row

    def get(self, tx: TenantTransaction, key: IdempotencyKey) -> IdempotencyRecord | None:
        return self._row(tx, key, lock=False)


__all__ = ["PgIdempotencyStore"]
