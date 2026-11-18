"""In-memory ``BudgetBackend`` (tests). Rows are partitioned by the transaction's org."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from amw_core.budget_guard.core import JobScope, StoredBudget
from amw_core.cost.ledger import MemoryCostLedger
from amw_core.enums import ReservationStatus
from amw_core.errors import MissingDependencyError
from amw_core.ids import RESERVATION, BudgetId, JobId, OrgId, ReservationId, TaskId
from amw_core.interfaces.budget_guard import Budget, Reservation
from amw_core.interfaces.cost_ledger import CostEntry
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass
class _Tenant:
    budgets: dict[BudgetId, StoredBudget] = field(default_factory=dict)
    reservations: dict[ReservationId, Reservation] = field(default_factory=dict)
    jobs: dict[JobId, JobScope] = field(default_factory=dict)
    tasks: dict[TaskId, JobId] = field(default_factory=dict)
    timezone: str | None = None


class MemoryBudgetBackend:
    def __init__(self, ledger: MemoryCostLedger) -> None:
        self._ledger = ledger
        self._tenants: dict[OrgId, _Tenant] = {}

    def _t(self, tx: TenantTransaction) -> _Tenant:
        return self._tenants.setdefault(tx.context.org_id, _Tenant())

    # --- fixtures (what jobs / tasks / budgets tables hold in PostgreSQL) -------------------------
    def add_budget(self, tx: TenantTransaction, budget: Budget, now: datetime) -> None:
        self._t(tx).budgets[budget.id] = StoredBudget(budget, now)

    def add_job(self, tx: TenantTransaction, scope: JobScope) -> None:
        self._t(tx).jobs[scope.job_id] = scope

    def add_task(self, tx: TenantTransaction, task_id: TaskId, job_id: JobId) -> None:
        self._t(tx).tasks[task_id] = job_id

    def set_timezone(self, tx: TenantTransaction, tz: str) -> None:
        self._t(tx).timezone = tz

    # --- BudgetBackend ----------------------------------------------------------------------------
    def budgets(self, tx: TenantTransaction, lock: bool = False) -> Sequence[StoredBudget]:
        return list(self._t(tx).budgets.values())

    def get_budget(
        self, tx: TenantTransaction, budget_id: BudgetId, lock: bool = False
    ) -> StoredBudget | None:
        return self._t(tx).budgets.get(budget_id)

    def save_budget(self, tx: TenantTransaction, budget: Budget, now: datetime) -> None:
        t = self._t(tx)
        old = t.budgets[budget.id]
        t.budgets[budget.id] = StoredBudget(budget, now, old.row_version + 1)

    def reservations(
        self,
        tx: TenantTransaction,
        *,
        task_id: TaskId | None = None,
        budget_id: BudgetId | None = None,
        status: ReservationStatus | None = None,
        lock: bool = False,
    ) -> Sequence[Reservation]:
        return [
            r
            for r in self._t(tx).reservations.values()
            if (task_id is None or r.task_id == task_id)
            and (budget_id is None or r.budget_id == budget_id)
            and (status is None or r.status is status)
        ]

    def insert_reservation(self, tx: TenantTransaction, reservation: Reservation) -> None:
        self._t(tx).reservations[reservation.id] = reservation

    def update_reservation(self, tx: TenantTransaction, reservation: Reservation) -> None:
        self._t(tx).reservations[reservation.id] = reservation

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
        return [
            r
            for r in self._ledger.all_rows(tx)
            if (job_id is None or r.entry.job_id == job_id)
            and (task_id is None or r.entry.task_id == task_id)
            and (provider is None or r.entry.provider == provider)
            and (since is None or r.entry.occurred_at >= since)
            and (until is None or r.entry.occurred_at < until)
        ]

    def job_scope(self, tx: TenantTransaction, job_id: JobId) -> JobScope:
        try:
            return self._t(tx).jobs[job_id]
        except KeyError:
            raise MissingDependencyError("job not found in this tenant") from None

    def task_job(self, tx: TenantTransaction, task_id: TaskId) -> JobId:
        try:
            return self._t(tx).tasks[task_id]
        except KeyError:
            raise MissingDependencyError("task not found in this tenant") from None

    def tenant_timezone(self, tx: TenantTransaction) -> str | None:
        return self._t(tx).timezone

    def new_reservation_id(self) -> ReservationId:
        return RESERVATION.new()
