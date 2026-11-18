"""PostgreSQL ``BudgetBackend`` (04 section 5.14 ``budgets``, ``budget_reservations``; jobs and
tasks of 04 section 5.3 for the job scope). Every query filters ``org_id`` explicitly (RLS is the
second line). ``budgets(lock=True)`` takes ``FOR UPDATE`` in id order, so concurrent E1 / E3
evaluations of one tenant serialise and never deadlock."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from amw_core.budget_guard.core import JobScope, StoredBudget
from amw_core.cost.pg import PgCostLedger
from amw_core.enums import BudgetPeriod, BudgetScopeKind, BudgetState, ReservationStatus
from amw_core.errors import MissingDependencyError
from amw_core.ids import (
    BUDGET,
    CHANNEL,
    JOB,
    ORG,
    RESERVATION,
    TASK,
    WORKSPACE,
    BudgetId,
    JobId,
    TaskId,
)
from amw_core.interfaces.budget_guard import Budget, Reservation
from amw_core.interfaces.cost_ledger import CostEntry
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

_B_COLS = (
    "id, scope_kind, scope_id, scope_key, period, limit_minor, currency, soft_limit_ratio, state,"
    " non_critical_suspend, updated_at, row_version"
)
_R_COLS = "id, budget_id, task_id, amount_micros, currency, status, released_at"


def _scope_wire(kind: BudgetScopeKind, value: uuid.UUID | None) -> str | None:
    if value is None:
        return None
    if kind is BudgetScopeKind.WORKSPACE:
        return WORKSPACE.from_uuid(value)
    if kind is BudgetScopeKind.CHANNEL:
        return CHANNEL.from_uuid(value)
    return str(value)


def _scope_uuid(kind: BudgetScopeKind, wire: str | None) -> uuid.UUID | None:
    if wire is None:
        return None
    if kind is BudgetScopeKind.WORKSPACE:
        return WORKSPACE.to_uuid(wire)
    if kind is BudgetScopeKind.CHANNEL:
        return CHANNEL.to_uuid(wire)
    return uuid.UUID(wire)


class PgBudgetBackend:
    def __init__(self, ledger: PgCostLedger | None = None) -> None:
        self._ledger = ledger or PgCostLedger()

    @staticmethod
    def _exec(tx: TenantTransaction, query: str, params: Sequence[Any]) -> list[tuple[Any, ...]]:
        try:
            cur = connection_of(tx).execute(query.encode(), params)
            return cur.fetchall() if cur.description else []
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc

    @staticmethod
    def _budget(tx: TenantTransaction, row: tuple[Any, ...]) -> StoredBudget:
        (bid, kind, scope_id, scope_key, period, limit_minor, currency, ratio, state, ncs,
         updated_at, version) = row  # fmt: skip
        k = BudgetScopeKind(kind)
        return StoredBudget(
            Budget(
                id=BUDGET.from_uuid(bid),
                org_id=tx.context.org_id,
                scope_kind=k,
                scope_id=_scope_wire(k, scope_id),
                scope_key=scope_key,
                period=BudgetPeriod(period),
                limit_minor=int(limit_minor),
                currency=str(currency),
                soft_limit_ratio=Decimal(ratio),
                state=BudgetState(state),
                non_critical_suspend=bool(ncs),
            ),
            updated_at,
            int(version),
        )

    def create_budget(self, tx: TenantTransaction, budget: Budget) -> None:
        """Owner / Finance creates a budget (the DB trigger refuses a non-human actor)."""
        self._exec(
            tx,
            "INSERT INTO budgets (id, org_id, scope_kind, scope_id, scope_key, period, limit_minor,"
            " currency, soft_limit_ratio, state, non_critical_suspend)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                BUDGET.to_uuid(budget.id),
                org_uuid_of(tx),
                str(budget.scope_kind),
                _scope_uuid(budget.scope_kind, budget.scope_id),
                budget.scope_key,
                str(budget.period),
                budget.limit_minor,
                budget.currency,
                budget.soft_limit_ratio,
                str(budget.state),
                budget.non_critical_suspend,
            ),
        )

    def budgets(self, tx: TenantTransaction, lock: bool = False) -> Sequence[StoredBudget]:
        rows = self._exec(
            tx,
            f"SELECT {_B_COLS} FROM budgets WHERE org_id = %s ORDER BY id"  # noqa: S608
            + (" FOR UPDATE" if lock else ""),
            (org_uuid_of(tx),),
        )
        return [self._budget(tx, r) for r in rows]

    def get_budget(
        self, tx: TenantTransaction, budget_id: BudgetId, lock: bool = False
    ) -> StoredBudget | None:
        rows = self._exec(
            tx,
            f"SELECT {_B_COLS} FROM budgets WHERE org_id = %s AND id = %s"  # noqa: S608
            + (" FOR UPDATE" if lock else ""),
            (org_uuid_of(tx), BUDGET.to_uuid(budget_id)),
        )
        return self._budget(tx, rows[0]) if rows else None

    def save_budget(self, tx: TenantTransaction, budget: Budget, now: datetime) -> None:
        self._exec(
            tx,
            "UPDATE budgets SET state = %s, limit_minor = %s WHERE org_id = %s AND id = %s",
            (str(budget.state), budget.limit_minor, org_uuid_of(tx), BUDGET.to_uuid(budget.id)),
        )

    @staticmethod
    def _reservation(row: tuple[Any, ...]) -> Reservation:
        rid, bid, tid, amount, currency, status, released_at = row
        return Reservation(
            id=RESERVATION.from_uuid(rid),
            budget_id=BUDGET.from_uuid(bid),
            task_id=TASK.from_uuid(tid),
            amount_micros=int(amount),
            currency=str(currency),
            status=ReservationStatus(status),
            released_at=released_at,
        )

    def reservations(
        self,
        tx: TenantTransaction,
        *,
        task_id: TaskId | None = None,
        budget_id: BudgetId | None = None,
        status: ReservationStatus | None = None,
    ) -> Sequence[Reservation]:
        clauses = ["org_id = %s"]
        params: list[Any] = [org_uuid_of(tx)]
        if task_id is not None:
            clauses.append("task_id = %s")
            params.append(TASK.to_uuid(task_id))
        if budget_id is not None:
            clauses.append("budget_id = %s")
            params.append(BUDGET.to_uuid(budget_id))
        if status is not None:
            clauses.append("status = %s")
            params.append(str(status))
        rows = self._exec(
            tx,
            f"SELECT {_R_COLS} FROM budget_reservations WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY id",
            params,
        )
        return [self._reservation(r) for r in rows]

    def insert_reservation(self, tx: TenantTransaction, reservation: Reservation) -> None:
        r = reservation
        self._exec(
            tx,
            f"INSERT INTO budget_reservations (org_id, {_R_COLS})"  # noqa: S608
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                org_uuid_of(tx),
                RESERVATION.to_uuid(r.id),
                BUDGET.to_uuid(r.budget_id),
                TASK.to_uuid(r.task_id),
                r.amount_micros,
                r.currency,
                str(r.status),
                r.released_at,
            ),
        )

    def update_reservation(self, tx: TenantTransaction, reservation: Reservation) -> None:
        self._exec(
            tx,
            "UPDATE budget_reservations SET status = %s, released_at = %s"
            " WHERE org_id = %s AND id = %s",
            (
                str(reservation.status),
                reservation.released_at,
                org_uuid_of(tx),
                RESERVATION.to_uuid(reservation.id),
            ),
        )

    def ledger_rows(
        self,
        tx: TenantTransaction,
        *,
        job_id: JobId | None = None,
        task_id: TaskId | None = None,
        provider: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Sequence[CostEntry]:
        return self._ledger.query(
            tx, job_id=job_id, task_id=task_id, provider=provider, since=since, until=until
        )

    def job_scope(self, tx: TenantTransaction, job_id: JobId) -> JobScope:
        rows = self._exec(
            tx,
            "SELECT workspace_id, channel_id, production_type_key FROM jobs"
            " WHERE org_id = %s AND id = %s",
            (org_uuid_of(tx), JOB.to_uuid(job_id)),
        )
        if not rows:
            raise MissingDependencyError("job not found in this tenant")
        wsp, chn, ptk = rows[0]
        return JobScope(
            job_id=job_id,
            workspace_id=WORKSPACE.from_uuid(wsp) if wsp else None,
            channel_id=CHANNEL.from_uuid(chn) if chn else None,
            production_type_key=ptk,
        )

    def task_job(self, tx: TenantTransaction, task_id: TaskId) -> JobId:
        rows = self._exec(
            tx,
            "SELECT job_id FROM tasks WHERE org_id = %s AND id = %s",
            (org_uuid_of(tx), TASK.to_uuid(task_id)),
        )
        if not rows:
            raise MissingDependencyError("task not found in this tenant")
        return JOB.from_uuid(rows[0][0])

    def tenant_timezone(self, tx: TenantTransaction) -> str | None:
        rows = self._exec(
            tx,
            "SELECT display_timezone FROM organisations WHERE id = %s",
            (ORG.to_uuid(tx.context.org_id),),
        )
        return str(rows[0][0]) if rows else None

    def new_reservation_id(self) -> str:
        return RESERVATION.new()
