"""Shared helpers for the lane L1b unit suites (fixed clock, tenants, settings, budgets)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from amw_core.budget_guard import BudgetGuardCore, JobScope, MemoryBudgetBackend
from amw_core.config import AmwSettings, FinanceSettings, load_settings
from amw_core.cost import MemoryCostLedger
from amw_core.enums import (
    BudgetPeriod,
    BudgetScopeKind,
    BudgetState,
    CostFigureKind,
    CostOperation,
)
from amw_core.ids import (
    BUDGET,
    JOB,
    ORG,
    TASK,
    WORKSPACE,
    ActorRef,
    BudgetId,
    JobId,
    OrgId,
    TaskId,
)
from amw_core.interfaces.budget_guard import Budget
from amw_core.interfaces.cost_ledger import NewCostEntry
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.testing.memory import MemoryTransaction

T0 = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
ORCH = ActorRef("agent_01")
S4 = ActorRef("svc_s04")


@dataclass
class FixedClock:
    current: datetime = T0
    mono: int = 0

    def now(self) -> datetime:
        return self.current

    def monotonic_ms(self) -> int:
        return self.mono

    def advance(self, ms: int) -> None:
        self.current += timedelta(milliseconds=ms)
        self.mono += ms


def tx_for(org: OrgId, actor: str = ORCH) -> MemoryTransaction:
    return MemoryTransaction(TenantContext(org, ActorRef(actor)))


def settings(**finance: object) -> AmwSettings:
    """Settings with the INR / USD minor-unit exponents a test needs (test data)."""
    base = load_settings(environ={})
    fin = FinanceSettings(currency_minor_exponent={"INR": 2, "USD": 2}, **finance)  # type: ignore[arg-type,unused-ignore]
    return base.model_copy(update={"finance": fin})


def budget(
    org: OrgId,
    period: BudgetPeriod,
    limit_minor: int,
    *,
    scope_kind: BudgetScopeKind = BudgetScopeKind.ORG,
    scope_id: str | None = None,
    scope_key: str | None = None,
    state: BudgetState = BudgetState.ACTIVE,
    soft: str = "0.800",
    currency: str = "INR",
) -> Budget:
    return Budget(
        id=BUDGET.new(),
        org_id=org,
        scope_kind=scope_kind,
        scope_id=scope_id,
        scope_key=scope_key,
        period=period,
        limit_minor=limit_minor,
        currency=currency,
        soft_limit_ratio=Decimal(soft),
        state=state,
        non_critical_suspend=True,
    )


@dataclass
class World:
    """One tenant with a ledger, budget backend and guard (in memory)."""

    org: OrgId = field(default_factory=ORG.new)
    clock: FixedClock = field(default_factory=FixedClock)
    ledger: MemoryCostLedger = field(default_factory=MemoryCostLedger)
    cfg: AmwSettings = field(default_factory=settings)
    video: BudgetId = field(default_factory=lambda: BudgetId(""))
    pilot: BudgetId = field(default_factory=lambda: BudgetId(""))
    provider: BudgetId = field(default_factory=lambda: BudgetId(""))

    def __post_init__(self) -> None:
        from amw_core.audit import MemoryAuditLog

        self.backend = MemoryBudgetBackend(self.ledger)
        self.audit = MemoryAuditLog()
        self.guard = BudgetGuardCore(self.backend, self.cfg, self.clock, self.audit)
        self.tx = tx_for(self.org)
        self.workspace = WORKSPACE.new()

    def add_budget(self, b: Budget) -> BudgetId:
        self.backend.add_budget(self.tx, b, self.clock.now())
        return b.id

    def job(self, production_type: str = "CHANNEL_LONG_FORM") -> JobId:
        job_id = JOB.new()
        self.backend.add_job(self.tx, JobScope(job_id, self.workspace, None, production_type))
        return job_id

    def task(self, job_id: JobId) -> TaskId:
        task_id = TASK.new()
        self.backend.add_task(self.tx, task_id, job_id)
        return task_id

    def spend(
        self,
        job_id: JobId,
        task_id: TaskId,
        micros: int,
        provider: str = "llm_provider",
        kind: CostFigureKind = CostFigureKind.ESTIMATE,
        currency: str = "INR",
    ) -> NewCostEntry:
        entry = NewCostEntry(
            provider=provider,
            operation=CostOperation.LLM_COMPLETION,
            amount_micros=micros,
            currency=currency,
            figure_kind=kind,
            occurred_at=self.clock.now(),
            job_id=job_id,
            task_id=task_id,
            price_ref="pricing.v1" if kind is CostFigureKind.ESTIMATE else None,
            verification_ref="invoice-1" if kind is CostFigureKind.VERIFIED else None,
        )
        row = self.ledger.record(self.tx, entry)
        self.guard.after_call(self.tx, row)
        return entry
