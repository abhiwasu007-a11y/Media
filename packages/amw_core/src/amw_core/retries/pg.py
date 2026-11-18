"""PostgreSQL persistence for breakers and dead letters.

* ``PgBreakerFunctions.breaker_record`` is ``SystemFunctions.breaker_record``: it calls
  ``amw_breaker_record`` (migrations 0010 and 0051), the only writer of ``circuit_breakers``, in
  its own short transaction (not bound to a tenant transaction, 04 section 3.6). ``read`` returns
  the shared row (tenants may read platform rows, 04 section 3.5) for the pure ``admit`` check.
* ``PgDeadLetterStore`` writes the T14 row and moves its workflow columns (07 section 5).
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from amw_core.config import AmwSettings
from amw_core.enums import CircuitState, DlqRecoveryStatus, EscalationLevel, FailureClass
from amw_core.errors import MissingDependencyError
from amw_core.ids import (
    APPROVAL,
    ATTEMPT,
    DEAD_LETTER,
    JOB,
    TASK,
    USER,
    ActorRef,
    DeadLetterId,
    IdempotencyKey,
    is_actor_ref,
)
from amw_core.interfaces.system_functions import BreakerKey, BreakerState
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.observability import get_logger
from amw_core.retries.breaker import BreakerRow, counts_as_failure
from amw_core.retries.dlq import AttemptHistoryItem, DeadLetter
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

Connection = psycopg.Connection[tuple[Any, ...]]
_log = get_logger("retries.breaker")


@dataclass(frozen=True, slots=True)
class ProbeAdmission:
    """Outcome of ``amw_breaker_admit``: ``admitted`` is the decision, ``state`` the breaker state
    after it (``HALF_OPEN`` admissions are probes and must be followed by ``breaker_record``)."""

    admitted: bool
    state: BreakerState


class PgBreakerFunctions:
    """``amw_breaker_record`` caller. ``connections`` yields an ``amw_app`` connection."""

    def __init__(
        self, connections: Callable[[], AbstractContextManager[Connection]], settings: AmwSettings
    ) -> None:
        self._connections = connections
        self._settings = settings

    def admit(self, caller: ActorRef, key: BreakerKey) -> ProbeAdmission:
        """Atomic admission before a call (07 section 4.3): at most ``half_open_max_probes``
        concurrent probes while ``HALF_OPEN``, counted in the database under a row lock."""
        if not is_actor_ref(caller):
            raise ValueError("caller must be an actor reference")
        cfg = self._settings.breaker_for(key.provider, key.operation_class)
        try:
            with self._connections() as conn, conn.transaction():
                conn.execute("SELECT set_config('app.actor', %s, true)", (caller,))
                row = conn.execute(
                    "SELECT admitted, state, open_until FROM amw_breaker_admit(%s, %s, %s, %s)",
                    (
                        key.provider,
                        key.operation_class,
                        key.credential_scope,
                        cfg.half_open_max_probes,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        assert row is not None  # noqa: S101 - the function always returns one row
        return ProbeAdmission(bool(row[0]), BreakerState(key, CircuitState(row[1]), row[2]))

    def breaker_record(
        self, caller: ActorRef, key: BreakerKey, succeeded: bool, error_code: str | None
    ) -> BreakerState:
        if not is_actor_ref(caller):
            raise ValueError("caller must be an actor reference")
        cfg = self._settings.breaker_for(key.provider, key.operation_class)
        try:
            with self._connections() as conn, conn.transaction():
                conn.execute("SELECT set_config('app.actor', %s, true)", (caller,))
                row = conn.execute(
                    "SELECT state, open_until FROM amw_breaker_record("
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        key.provider,
                        key.operation_class,
                        key.credential_scope,
                        succeeded,
                        counts_as_failure(error_code),
                        error_code,
                        cfg.window_ms,
                        cfg.min_calls,
                        cfg.failure_ratio,
                        cfg.consecutive_failures,
                        cfg.open_ms,
                        cfg.open_ms_max,
                        cfg.half_open_successes_to_close,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        assert row is not None  # noqa: S101 - the function always returns one row
        state = BreakerState(key=key, state=CircuitState(row[0]), open_until=row[1])
        _log.info(
            "breaker outcome recorded",
            extra={
                "actor": caller,
                "provider": key.provider,
                "operation_class": key.operation_class,
                "breaker_state": str(state.state),
                "error_code": error_code,
            },
        )
        return state

    @staticmethod
    def read(tx: TenantTransaction, key: BreakerKey) -> BreakerRow | None:
        """The breaker row as visible in a tenant transaction (platform rows are readable)."""
        try:
            row = (
                connection_of(tx)
                .execute(
                    "SELECT state, window_started_at, window_calls, window_failures,"
                    " consecutive_failures, opened_at, open_until, open_count,"
                    " half_open_in_flight, last_error_code FROM circuit_breakers"
                    " WHERE provider = %s AND operation_class = %s AND credential_scope = %s",
                    (key.provider, key.operation_class, key.credential_scope),
                )
                .fetchone()
            )
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        if row is None:
            return None
        return BreakerRow(
            key=key,
            state=CircuitState(row[0]),
            window_started_at=row[1],
            window_calls=row[2],
            window_failures=row[3],
            consecutive_failures=row[4],
            opened_at=row[5],
            open_until=row[6],
            open_count=row[7],
            half_open_in_flight=row[8],
            last_error_code=row[9],
        )


_DLQ_COLS = (
    "task_id, job_id, failure_class, error_code, reason, error, payload_ref, payload_sha256,"
    " retry_history, traceback_ref, last_attempt_id, last_run_at, recovery_status,"
    " escalation_level, replay_count, replay_approval_id, triaged_by, root_cause_note, resolved_at"
)


def _history(raw: Any) -> tuple[AttemptHistoryItem, ...]:
    items = []
    for h in raw:
        items.append(
            AttemptHistoryItem(
                attempt_no=int(h["attempt_no"]),
                started_at=datetime.fromisoformat(h["started_at"]),
                ended_at=datetime.fromisoformat(h["ended_at"]) if h["ended_at"] else None,
                worker_id=h["worker_id"],
                error_code=h["error_code"],
            )
        )
    return tuple(items)


class PgDeadLetterStore:
    """``dead_letter`` rows. Fields that are not columns (idempotency key / scope, estimated
    cost) are filled on read from ``tasks`` (key, ``task.<task_type>``, ``resource_budget``)."""

    @staticmethod
    def _exec(tx: TenantTransaction, query: str, params: Any) -> list[tuple[Any, ...]]:
        try:
            cur = connection_of(tx).execute(query.encode(), params)
            return cur.fetchall() if cur.description else []
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc

    def insert(self, tx: TenantTransaction, item: DeadLetter) -> DeadLetterId:
        dlq_id = DEAD_LETTER.new()
        self._exec(
            tx,
            f"INSERT INTO dead_letter (id, org_id, {_DLQ_COLS})"  # noqa: S608
            " VALUES (" + ", ".join(["%s"] * 21) + ")",
            (
                DEAD_LETTER.to_uuid(dlq_id),
                org_uuid_of(tx),
                TASK.to_uuid(item.task_id),
                JOB.to_uuid(item.job_id),
                str(item.failure_class),
                item.error_code,
                item.reason,
                Jsonb(dict(item.error)),
                item.payload_ref,
                bytes.fromhex(item.payload_sha256),
                Jsonb([h.to_json() for h in item.retry_history]),
                item.traceback_ref,
                ATTEMPT.to_uuid(item.last_attempt_id) if item.last_attempt_id else None,
                item.last_run_at,
                str(item.recovery_status),
                str(item.escalation_level),
                item.replay_count,
                APPROVAL.to_uuid(item.replay_approval_id) if item.replay_approval_id else None,
                USER.to_uuid(item.triaged_by) if item.triaged_by else None,
                item.root_cause_note,
                item.resolved_at,
            ),
        )
        return dlq_id

    def get(self, tx: TenantTransaction, dlq_id: DeadLetterId) -> DeadLetter:
        rows = self._exec(
            tx,
            f"SELECT {', '.join('d.' + c.strip() for c in _DLQ_COLS.split(','))},"  # noqa: S608
            " t.idempotency_key, t.task_type, (t.resource_budget->>'max_cost_micros')::bigint"
            " FROM dead_letter d JOIN tasks t ON t.org_id = d.org_id AND t.id = d.task_id"
            " WHERE d.org_id = %s AND d.id = %s",
            (org_uuid_of(tx), DEAD_LETTER.to_uuid(dlq_id)),
        )
        if not rows:
            raise MissingDependencyError("dead-letter row not found")
        r = rows[0]
        return DeadLetter(
            task_id=TASK.from_uuid(r[0]),
            job_id=JOB.from_uuid(r[1]),
            failure_class=FailureClass(r[2]),
            error_code=r[3],
            reason=r[4],
            error=r[5],
            payload_ref=r[6],
            payload_sha256=bytes(r[7]).hex(),
            retry_history=_history(r[8]),
            traceback_ref=r[9],
            last_attempt_id=ATTEMPT.from_uuid(r[10]) if r[10] else None,
            last_run_at=r[11],
            recovery_status=DlqRecoveryStatus(r[12]),
            escalation_level=EscalationLevel(r[13]),
            replay_count=int(r[14]),
            replay_approval_id=APPROVAL.from_uuid(r[15]) if r[15] else None,
            triaged_by=USER.from_uuid(r[16]) if r[16] else None,
            root_cause_note=r[17],
            resolved_at=r[18],
            idempotency_key=IdempotencyKey(r[19]),
            idempotency_scope=f"task.{r[20]}",
            estimated_cost_micros=int(r[21] or 0),
        )

    def save(self, tx: TenantTransaction, dlq_id: DeadLetterId, item: DeadLetter) -> None:
        """Persist the workflow columns after a ``amw_core.retries.dlq`` step."""
        self._exec(
            tx,
            "UPDATE dead_letter SET recovery_status = %s, replay_count = %s,"
            " replay_approval_id = %s, triaged_by = %s, root_cause_note = %s, resolved_at = %s"
            " WHERE org_id = %s AND id = %s",
            (
                str(item.recovery_status),
                item.replay_count,
                APPROVAL.to_uuid(item.replay_approval_id) if item.replay_approval_id else None,
                USER.to_uuid(item.triaged_by) if item.triaged_by else None,
                item.root_cause_note,
                item.resolved_at,
                org_uuid_of(tx),
                DEAD_LETTER.to_uuid(dlq_id),
            ),
        )

    @staticmethod
    def with_effect_scope(item: DeadLetter, scope: str, key: IdempotencyKey) -> DeadLetter:
        """The side-effect scope / key of the task's external effect (e.g. ``delivery.file``),
        which decides approval and reconciliation (07 section 5.2 steps 5-6)."""
        return replace(item, idempotency_scope=scope, idempotency_key=key)
