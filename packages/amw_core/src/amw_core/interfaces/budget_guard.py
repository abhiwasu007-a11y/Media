"""Budget guard interface (S4; 09 sections 2-4 and 8; 04 section 5.14 ``budgets``,
``budget_reservations``; 3A slice spec section 5).

Three enforcement points (09 section 2): E1 admission at T03 (``reserve``), E2 before every paid
call (``check_call``), E3 after the ledger write (``after_call``). Fail closed: a paid task with no
``ACTIVE`` applicable budget is refused; no automatic spend increase ever (rule 8, B6).
``committed = sum(ledger: VERIFIED else ESTIMATE) + sum(HELD reservations)`` (09 section 3.3).

Pending CCRs: the provider start gate (09 section 8) needs ``budget_scope_kind = PROVIDER``
(CCR-3A-5) and the pilot budget needs ``budget_period = PILOT_TOTAL`` (CCR-3A-4); neither value
exists in GLOSSARY yet, so ``check_provider_gate`` is specified but cannot be backed by rows until
they are applied. Implementation: lane L1.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from amw_core.enums import BudgetPeriod, BudgetScopeKind, BudgetState, ReservationStatus
from amw_core.ids import BudgetId, JobId, OrgId, ReservationId, TaskId
from amw_core.interfaces.cost_ledger import CostEntry
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class Budget:
    id: BudgetId
    org_id: OrgId
    scope_kind: BudgetScopeKind
    scope_id: str | None
    scope_key: str | None
    period: BudgetPeriod
    limit_minor: int
    currency: str
    soft_limit_ratio: float
    state: BudgetState
    non_critical_suspend: bool


@dataclass(frozen=True, slots=True)
class Reservation:
    id: ReservationId
    budget_id: BudgetId
    task_id: TaskId
    amount_micros: int
    currency: str
    status: ReservationStatus
    released_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReservationOutcome:
    """E1 result: all-or-nothing over every applicable budget (09 section 3.4)."""

    granted: bool
    reservations: tuple[Reservation, ...]
    refused_budget_ids: tuple[BudgetId, ...]
    """Budgets that could not cover the hold (task goes to T05, ``AWAITING_BUDGET``)."""


@dataclass(frozen=True, slots=True)
class CallCheck:
    """E2 input: the worst-case cost of the next paid call (ADR-007 section 2.8)."""

    task_id: TaskId
    job_id: JobId
    provider: str
    estimated_cost_micros: int
    currency: str
    tokens_in: int | None = None
    tokens_out: int | None = None


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    budget: Budget
    committed_micros: int
    remaining_micros: int
    soft_limit_reached: bool


@runtime_checkable
class BudgetGuard(Protocol):
    def applicable_budgets(self, tx: TenantTransaction, job_id: JobId) -> Sequence[Budget]:
        """Budgets in scope for the job (org, workspace, channel, production type)."""
        ...

    def reserve(
        self, tx: TenantTransaction, task_id: TaskId, amount_micros: int, currency: str
    ) -> ReservationOutcome:
        """E1 / T03: hold ``resource_budget.max_cost_micros`` on every applicable budget.
        A retry of the same task reuses its HELD reservations (never reserves twice)."""
        ...

    def check_call(self, tx: TenantTransaction, check: CallCheck) -> None:
        """E2: raise ``BudgetExhaustedError`` (SUSPEND ``AWAITING_BUDGET``, no attempt consumed)
        if the call would exceed the task's HELD reservation or a budget is not ``ACTIVE``."""
        ...

    def check_provider_gate(self, tx: TenantTransaction, provider: str) -> None:
        """09 section 8.1-8.2: raise ``BudgetExhaustedError`` before any network request if the
        owner has not acknowledged a provider limit (pending CCR-3A-5)."""
        ...

    def after_call(self, tx: TenantTransaction, entry: CostEntry) -> Sequence[Budget]:
        """E3: after a ledger write, set ``SUSPENDED_EXCEEDED`` on every budget whose committed
        amount reached its limit; returns the budgets that changed (B5 notice is the caller's)."""
        ...

    def consume(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[Reservation]:
        """T08: HELD -> CONSUMED; the unused part returns to remaining."""
        ...

    def release(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[Reservation]:
        """T11 / T14 / T19: HELD -> RELEASED (``released_at`` set); incurred cost stays."""
        ...

    def status(self, tx: TenantTransaction, budget_id: BudgetId) -> BudgetStatus: ...
