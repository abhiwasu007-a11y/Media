"""``SystemFunctions`` on PostgreSQL (04 section 3.6): identifier-only cross-tenant reads.

Each call runs on a connection of its own (``amw_app``, no tenant context) and is logged with the
caller's actor. Thresholds are configuration passed at construction (07 section 4.2 breaker keys,
07 section 6 dwell limits), never literals.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg

from amw_core.enums import CircuitState, TaskState, WaitReason
from amw_core.errors import CATALOGUE, InputInvalidError
from amw_core.ids import ORG, QUEUE_ITEM, TASK, ActorRef, is_actor_ref
from amw_core.interfaces.system_functions import (
    BreakerKey,
    BreakerState,
    DueResume,
    DueTask,
    ExpiredLease,
    StuckTask,
)
from amw_core.tenancy import ConnectionFactory, translate_db_error

_log = logging.getLogger("amw_core.system_functions")


@dataclass(frozen=True, slots=True)
class BreakerConfig:
    """``breaker.<provider>.<operation_class>.*`` (07 section 4.2)."""

    window_ms: int
    min_calls: int
    failure_ratio: Decimal
    consecutive_failures: int
    open_ms: int
    open_ms_max: int
    half_open_successes_to_close: int


@dataclass(frozen=True, slots=True)
class DwellLimits:
    """07 section 6: ``VALIDATING`` too long; ``FAILED`` without a DLQ row."""

    validating_ms: int
    failed_without_dlq_ms: int


class PgSystemFunctions:
    def __init__(
        self,
        connections: ConnectionFactory,
        *,
        breaker_config: Callable[[BreakerKey], BreakerConfig],
        dwell: DwellLimits,
    ) -> None:
        self._connections = connections
        self._breaker_config = breaker_config
        self._dwell = dwell

    def _call(self, caller: ActorRef, name: str, sql: str, params: Sequence[Any]) -> list[Any]:
        if not is_actor_ref(caller):
            raise InputInvalidError("system function caller must be an actor reference")
        try:
            with self._connections() as conn, conn.transaction():
                rows = conn.execute(sql.encode(), params).fetchall()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        _log.info(name, extra={"actor": caller, "rows": len(rows), "system_function": True})
        return list(rows)

    @staticmethod
    def _limit(limit: int) -> int:
        if limit < 1:
            raise InputInvalidError("limit must be positive")
        return limit

    def due_retries(self, caller: ActorRef, limit: int) -> Sequence[DueTask]:
        rows = self._call(
            caller,
            "amw_due_retries",
            "SELECT org_id, task_id FROM amw_due_retries(%s)",
            (self._limit(limit),),
        )
        return [DueTask(ORG.from_uuid(o), TASK.from_uuid(t)) for o, t in rows]

    def due_resumes(self, caller: ActorRef, limit: int) -> Sequence[DueResume]:
        rows = self._call(
            caller,
            "amw_due_resumes",
            "SELECT org_id, task_id, wait_reason FROM amw_due_resumes(%s)",
            (self._limit(limit),),
        )
        return [DueResume(ORG.from_uuid(o), TASK.from_uuid(t), WaitReason(w)) for o, t, w in rows]

    def expired_leases(self, caller: ActorRef, limit: int) -> Sequence[ExpiredLease]:
        rows = self._call(
            caller,
            "amw_expired_leases",
            "SELECT org_id, task_id, queue_item_id FROM amw_expired_leases(%s)",
            (self._limit(limit),),
        )
        return [
            ExpiredLease(ORG.from_uuid(o), TASK.from_uuid(t), QUEUE_ITEM.from_uuid(q))
            for o, t, q in rows
        ]

    def stuck_tasks(self, caller: ActorRef, limit: int) -> Sequence[StuckTask]:
        rows = self._call(
            caller,
            "amw_stuck_tasks",
            "SELECT org_id, task_id, state FROM amw_stuck_tasks(%s, %s, %s)",
            (self._limit(limit), self._dwell.validating_ms, self._dwell.failed_without_dlq_ms),
        )
        return [StuckTask(ORG.from_uuid(o), TASK.from_uuid(t), TaskState(s)) for o, t, s in rows]

    def breaker_record(
        self, caller: ActorRef, key: BreakerKey, succeeded: bool, error_code: str | None
    ) -> BreakerState:
        if succeeded and error_code is not None:
            raise InputInvalidError("a success carries no error code")
        if not succeeded and error_code not in CATALOGUE:
            raise InputInvalidError("a failure carries its 07 error code")
        counted = error_code is not None and CATALOGUE[error_code].breaker_counts
        cfg = self._breaker_config(key)
        rows = self._call(
            caller,
            "amw_breaker_record",
            "SELECT state, open_until FROM amw_breaker_record(%s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, %s)",
            (
                key.provider,
                key.operation_class,
                key.credential_scope,
                succeeded,
                counted,
                error_code,
                cfg.window_ms,
                cfg.min_calls,
                cfg.failure_ratio,
                cfg.consecutive_failures,
                cfg.open_ms,
                cfg.open_ms_max,
                cfg.half_open_successes_to_close,
            ),
        )
        state, open_until = rows[0]
        return BreakerState(key, CircuitState(state), open_until)
