"""PostgreSQL cost ledger and budget guard: append-only ledger, replay, VERIFIED rules, the
human-only budget trigger, E1/E2/E3 on real tables, 27 section 9 test 4, tenant isolation."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from amw_core.audit.pg import PgAuditLog
from amw_core.budget_guard import BudgetGuardCore
from amw_core.budget_guard.pg import PgBudgetBackend
from amw_core.cost.pg import PgCostLedger
from amw_core.enums import (
    BudgetPeriod,
    BudgetScopeKind,
    BudgetState,
    CostFigureKind,
    CostOperation,
    CostUnitKind,
    ReservationStatus,
)
from amw_core.errors import (
    BudgetExhaustedError,
    IdempotencyConflictError,
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import BUDGET, CHANNEL, USER, ActorRef, make_idempotency_key
from amw_core.interfaces.budget_guard import Budget, CallCheck
from amw_core.interfaces.cost_ledger import CostLedger, NewCostEntry
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy import PgTenancy, connection_of, translate_db_error
from tests.core_services.support import T0, FixedClock, budget, settings
from tests.core_services_db.conftest import Work, make_task, make_user, make_work
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
ORCH = ActorRef("agent_01")
M = 1_000_000


def _e(work: Work, micros: int, **kw: object) -> NewCostEntry:
    base = NewCostEntry(
        provider="llm_provider",
        operation=CostOperation.LLM_COMPLETION,
        amount_micros=micros,
        currency="INR",
        figure_kind=CostFigureKind.ESTIMATE,
        occurred_at=T0,
        job_id=work.job_id,
        task_id=work.task_id,
        attempt_id=work.attempt_id,
        model="model-mid",
        tokens_in=10,
        tokens_out=5,
        units=Decimal("1.5"),
        unit_kind=CostUnitKind.ITEMS,
        price_ref="pricing.v1",
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _raw(tx: Any, stmt: str, params: Any = None) -> Any:
    try:
        return connection_of(tx).execute(stmt, params)
    except psycopg.Error as exc:
        raise translate_db_error(exc) from exc


def test_is_a_cost_ledger() -> None:
    assert isinstance(PgCostLedger(), CostLedger)


def test_record_replay_verified_and_totals(
    tenancy: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    led = PgCostLedger()
    ctx = TenantContext(tenant_a.org_id, ORCH)
    key = make_idempotency_key(tenant_a.org_id, "llm.call", [work_a.task_id, "draft", 1])
    with tenancy.transaction(ctx) as tx:
        est = led.record(tx, _e(work_a, 1_000, idempotency_key=key))
        assert led.get(tx, est.id) == est
        again = led.record(
            tx, _e(work_a, 1_000, idempotency_key=key, occurred_at=T0.replace(minute=9))
        )
        assert again.id == est.id
        with pytest.raises(IdempotencyConflictError):
            led.record(tx, _e(work_a, 2_000, idempotency_key=key))
        ver = led.record(
            tx,
            _e(
                work_a,
                1_100,
                figure_kind=CostFigureKind.VERIFIED,
                price_ref=None,
                estimate_entry_id=est.id,
                verification_ref="usage-1",
            ),
        )
        with pytest.raises(InputInvalidError):
            led.record(
                tx,
                _e(
                    work_a,
                    1,
                    figure_kind=CostFigureKind.VERIFIED,
                    price_ref=None,
                    estimate_entry_id=est.id,
                    verification_ref="u2",
                ),
            )
        with pytest.raises(InputInvalidError):
            led.record(
                tx,
                _e(
                    work_a,
                    1,
                    figure_kind=CostFigureKind.VERIFIED,
                    price_ref=None,
                    estimate_entry_id=ver.id,
                    verification_ref="u3",
                ),
            )
        t = led.job_totals(tx, work_a.job_id)
        assert (t.estimate_micros, t.verified_micros, t.effective_micros) == (1_000, 1_100, 1_100)
        assert [r.id for r in led.for_task(tx, work_a.task_id)] == [est.id, ver.id]
        assert led.query(tx, provider="nobody") == []
        assert led.get(tx, ver.id).entry.units == Decimal("1.5")  # type: ignore[union-attr]


@pytest.mark.security
def test_ledger_is_append_only(tenancy: PgTenancy, tenant_a: Tenant, work_a: Work) -> None:
    ctx = TenantContext(tenant_a.org_id, ORCH)
    with tenancy.transaction(ctx) as tx:
        PgCostLedger().record(tx, _e(work_a, 5))
    for stmt in ("UPDATE cost_ledger SET amount_micros = 0", "DELETE FROM cost_ledger"):
        with pytest.raises(PermissionDeniedError), tenancy.transaction(ctx) as tx:
            _raw(tx, stmt)


def test_db_constraints_are_the_second_line(admin: Any, tenant_a: Tenant, work_a: Work) -> None:
    from amw_core.ids import new_uuid7

    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute(
            "INSERT INTO cost_ledger (id, org_id, provider, operation, amount_micros, currency,"
            " figure_kind, occurred_at) VALUES (%s, %s, 'p', 'llm.completion', 5, 'INR',"
            " 'ESTIMATE', now())",
            (new_uuid7(), tenant_a.org_uuid),
        )  # paid ESTIMATE without price_ref


@pytest.mark.tenancy
def test_cost_rows_are_invisible_to_another_tenant(
    tenancy: PgTenancy, tenant_a: Tenant, tenant_b: Tenant, work_a: Work
) -> None:
    led = PgCostLedger()
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        row = led.record(tx, _e(work_a, 5))
    with tenancy.transaction(TenantContext(tenant_b.org_id, ORCH)) as tx:
        assert led.get(tx, row.id) is None
        assert led.for_job(tx, work_a.job_id) == []
    with (
        pytest.raises(psycopg.errors.ForeignKeyViolation),
        tenancy.transaction(TenantContext(tenant_b.org_id, ORCH)) as tx,
    ):
        connection_of(tx).execute(
            "INSERT INTO cost_ledger (id, org_id, job_id, provider, operation, amount_micros,"
            " currency, figure_kind, occurred_at) VALUES (gen_random_uuid(), %s, %s, 'p',"
            " 'llm.completion', 0, 'INR', 'ESTIMATE', now())",
            (tenant_b.org_uuid, __import__("amw_core.ids").ids.JOB.to_uuid(work_a.job_id)),
        )  # tenant-composite FK: B's row cannot point at A's job


# ---- budgets ---------------------------------------------------------------------------------
def _guard(clock: FixedClock | None = None) -> tuple[BudgetGuardCore, PgBudgetBackend]:
    backend = PgBudgetBackend()
    return BudgetGuardCore(backend, settings(), clock or FixedClock(), PgAuditLog()), backend


def _owner_budgets(tenancy: PgTenancy, tenant: Tenant, owner: str, *budgets: Budget) -> None:
    backend = PgBudgetBackend()
    with tenancy.transaction(TenantContext(tenant.org_id, ActorRef(owner))) as tx:
        for b in budgets:
            backend.create_budget(tx, b)


@pytest.mark.security
def test_only_a_human_creates_or_changes_budgets(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant
) -> None:
    owner = make_user(admin)
    b = budget(tenant_a.org_id, BudgetPeriod.PILOT_TOTAL, 1000)
    with (
        pytest.raises(PermissionDeniedError),
        tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx,
    ):
        PgBudgetBackend().create_budget(tx, b)
    _owner_budgets(tenancy, tenant_a, owner, b)
    ctx = TenantContext(tenant_a.org_id, ORCH)
    uid = BUDGET.to_uuid(b.id)
    for stmt in (
        "UPDATE budgets SET limit_minor = 999999 WHERE id = %s",
        "UPDATE budgets SET state = 'DISABLED' WHERE id = %s",
        "UPDATE budgets SET currency = 'USD' WHERE id = %s",
    ):
        with pytest.raises(PermissionDeniedError), tenancy.transaction(ctx) as tx:
            _raw(tx, stmt, (uid,))
    with tenancy.transaction(ctx) as tx:  # S4 may suspend
        _raw(tx, "UPDATE budgets SET state = 'SUSPENDED_EXCEEDED' WHERE id = %s", (uid,))
    with pytest.raises(PermissionDeniedError), tenancy.transaction(ctx) as tx:
        _raw(tx, "UPDATE budgets SET state = 'ACTIVE' WHERE id = %s", (uid,))  # PILOT: human only
    with admin.transaction():
        admin.execute("SELECT set_config('app.user_id', %s, true)", (str(USER.to_uuid(owner)),))
        with pytest.raises(psycopg.errors.CheckViolation), admin.transaction():
            admin.execute(
                "INSERT INTO budgets (id, org_id, scope_kind, scope_key, period, limit_minor,"
                " currency, soft_limit_ratio, state) VALUES (gen_random_uuid(), %s, 'PROVIDER',"
                " NULL, 'PILOT_TOTAL', 1, 'INR', 0.5, 'ACTIVE')",
                (tenant_a.org_uuid,),
            )


def test_b8_breach_on_real_tables(admin: Any, tenancy: PgTenancy, tenant_a: Tenant) -> None:
    """27 section 9 test 4 on PostgreSQL: a budget breach stops further paid calls."""
    owner = make_user(admin)
    video = budget(tenant_a.org_id, BudgetPeriod.PER_VIDEO, 1000)  # 10 rupees
    pilot = budget(tenant_a.org_id, BudgetPeriod.PILOT_TOTAL, 100_000)
    prov = budget(
        tenant_a.org_id,
        BudgetPeriod.PILOT_TOTAL,
        100_000,
        scope_kind=BudgetScopeKind.PROVIDER,
        scope_key="llm_provider",
    )
    _owner_budgets(tenancy, tenant_a, owner, video, pilot, prov)
    guard, backend = _guard()
    ledger = PgCostLedger()
    work = make_work(admin, tenant_a)
    ctx = TenantContext(tenant_a.org_id, ActorRef("svc_s04"))
    paid = 0
    stopped = False
    task, att = work.task_id, work.attempt_id
    for _ in range(6):
        with tenancy.transaction(ctx) as tx:
            if not guard.reserve(tx, task, 3 * M, "INR").granted:
                stopped = True
                break
            guard.check_call(tx, CallCheck(task, work.job_id, "llm_provider", 3 * M, "INR"))
            row = ledger.record(tx, _e(replace(work, task_id=task, attempt_id=att), 3 * M))
            guard.after_call(tx, row)
            guard.consume(tx, task)
            paid += 1
        task, att = make_task(admin, tenant_a, work.job_id)
    assert stopped
    assert paid == 3
    with tenancy.transaction(ctx) as tx:
        status = guard.status(tx, video.id, work.job_id)
        assert status.committed_micros == 9 * M
        assert status.budget.state is BudgetState.ACTIVE
        assert {r.status for r in backend.reservations(tx)} == {ReservationStatus.CONSUMED}
        with pytest.raises(BudgetExhaustedError):
            guard.check_call(tx, CallCheck(task, work.job_id, "llm_provider", 1, "INR"))
        guard.check_provider_gate(tx, "llm_provider")
        with pytest.raises(BudgetExhaustedError):
            guard.check_provider_gate(tx, "tts_provider")


def test_e3_suspends_and_owner_raises_the_limit(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant
) -> None:
    owner = make_user(admin)
    pilot = budget(tenant_a.org_id, BudgetPeriod.PILOT_TOTAL, 200)
    _owner_budgets(tenancy, tenant_a, owner, pilot)
    guard, backend = _guard()
    work = make_work(admin, tenant_a)
    ctx = TenantContext(tenant_a.org_id, ActorRef("svc_s04"))
    with tenancy.transaction(ctx) as tx:
        assert guard.reserve(tx, work.task_id, 2 * M, "INR").granted
        row = PgCostLedger().record(tx, _e(work, 2 * M))
        (changed,) = guard.after_call(tx, row)
        assert changed.state is BudgetState.SUSPENDED_EXCEEDED
        guard.release(tx, work.task_id)
    other, _ = make_task(admin, tenant_a, work.job_id)
    with tenancy.transaction(ctx) as tx:
        assert not guard.reserve(tx, other, 1, "INR").granted
        with pytest.raises(PermissionDeniedError):
            guard.set_limit(tx, pilot.id, 10_000, "agent cannot")
    with tenancy.transaction(TenantContext(tenant_a.org_id, ActorRef(owner))) as tx:
        after = guard.set_limit(tx, pilot.id, 10_000, "owner raised the pilot")
        assert after.state is BudgetState.ACTIVE
    with tenancy.transaction(ctx) as tx:
        assert guard.reserve(tx, other, 1, "INR").granted
        released = {r.status for r in backend.reservations(tx, task_id=work.task_id)}
        assert released == {ReservationStatus.RELEASED}


@pytest.mark.tenancy
def test_budget_rows_never_span_tenants(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    owner = make_user(admin)
    pilot = budget(tenant_a.org_id, BudgetPeriod.PILOT_TOTAL, 200)
    _owner_budgets(tenancy, tenant_a, owner, pilot)
    work = make_work(admin, tenant_a)
    guard, backend = _guard()
    with tenancy.transaction(TenantContext(tenant_b.org_id, ORCH)) as tx:
        assert backend.budgets(tx) == []
        assert backend.get_budget(tx, pilot.id) is None
        with pytest.raises(MissingDependencyError):
            guard.reserve(tx, work.task_id, 1, "INR")
        with pytest.raises(MissingDependencyError):
            backend.job_scope(tx, work.job_id)
        assert backend.tenant_timezone(tx) == "Asia/Kolkata"


def test_scope_mapping_round_trip(admin: Any, tenancy: PgTenancy, tenant_a: Tenant) -> None:
    owner = make_user(admin)
    wsp = budget(
        tenant_a.org_id,
        BudgetPeriod.PILOT_TOTAL,
        1,
        scope_kind=BudgetScopeKind.WORKSPACE,
        scope_id=tenant_a.workspace_id,
    )
    _owner_budgets(tenancy, tenant_a, owner, wsp)
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        (stored,) = PgBudgetBackend().budgets(tx)
        assert stored.budget == wsp
    assert CHANNEL.prefix.value == "chn"
