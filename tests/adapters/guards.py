"""Test guards. A token is minted here the way the preflight does (tests are the only other
caller of ``mint_provider_authorisation``); real tokens come only from ``run_preflight``."""

from collections.abc import Iterator
from contextlib import contextmanager

from amw_adapters.real.authorisation import ProviderAuthorisation, mint_provider_authorisation
from amw_adapters.real.guard import BudgetCallGuard, CapOnlyCallGuard
from amw_core.enums import BudgetPeriod, BudgetScopeKind
from amw_core.errors import CrossTenantRefError
from amw_core.exec_context import ExecContext
from amw_core.ids import ATTEMPT, ActorRef, JobId, OrgId, TaskId
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_core.testing.memory import MemoryTransaction
from tests.core_services.support import World, budget

PER_VIDEO_CAP_MICROS = 5_000_000


def auth(provider: str, cap: int = PER_VIDEO_CAP_MICROS) -> ProviderAuthorisation:
    return mint_provider_authorisation(provider, per_video_cap_micros=cap, currency="USD")


def cap_guard(provider: str, cap: int = PER_VIDEO_CAP_MICROS) -> CapOnlyCallGuard:
    return CapOnlyCallGuard(auth(provider, cap))


# ---- a real BudgetCallGuard over the in-memory L1b services -------------------------------------


class MemoryTenancy:
    @contextmanager
    def transaction(self, context: TenantContext) -> Iterator[TenantTransaction]:
        yield MemoryTransaction(context)

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        if tx.context.org_id != org_id:
            raise CrossTenantRefError("other tenant")

    def cache_key(self, org_id: OrgId, area: str, key: str) -> str:
        return f"amw:{org_id}:{area}:{key}"


class GuardedWorld:
    """One tenant: USD per-video cap of USD 5, pilot budget, and the two provider-limit rows."""

    def __init__(self, providers: tuple[str, ...] = ("anthropic", "elevenlabs")) -> None:
        self.w = World()
        self.w.add_budget(budget(self.w.org, BudgetPeriod.PER_VIDEO, 500, currency="USD"))
        self.w.add_budget(budget(self.w.org, BudgetPeriod.PILOT_TOTAL, 5000, currency="USD"))
        for p in providers:
            self.w.add_budget(
                budget(
                    self.w.org, BudgetPeriod.PILOT_TOTAL, 5000, currency="USD",
                    scope_kind=BudgetScopeKind.PROVIDER, scope_key=p,
                )
            )  # fmt: skip
        self.job: JobId = self.w.job()
        self.task: TaskId = self.w.task(self.job)
        outcome = self.w.guard.reserve(self.w.tx, self.task, PER_VIDEO_CAP_MICROS, "USD")
        assert outcome.granted
        self.ctx = ExecContext(
            tenant=TenantContext(self.w.org, ActorRef("agent_07")),
            job_id=self.job,
            task_id=self.task,
            attempt_id=ATTEMPT.new(),
            channel_id=None,
            attempt_no=1,
        )

    def guard(self, provider: str, cap: int = PER_VIDEO_CAP_MICROS) -> BudgetCallGuard:
        return BudgetCallGuard(
            auth(provider, cap), budget=self.w.guard, ledger=self.w.ledger,
            tenancy=MemoryTenancy(), clock=self.w.clock,
        )  # fmt: skip

    def spend(self, micros: int, provider: str = "anthropic") -> None:
        self.w.spend(self.job, self.task, micros, provider=provider, currency="USD")

    def rows(self) -> list[object]:
        return list(self.w.ledger.for_job(self.w.tx, self.job))
