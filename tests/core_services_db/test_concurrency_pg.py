"""20-way concurrency on real PostgreSQL (PR #44 review M2, M3, m1): budget E1 / E2 and breaker
probe admission, plus the breaker SQL against the pure model on random sequences."""

import random
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from amw_core.audit.pg import PgAuditLog
from amw_core.budget_guard import BudgetGuardCore
from amw_core.budget_guard.pg import PgBudgetBackend
from amw_core.config import BreakerSettings
from amw_core.cost.pg import PgCostLedger
from amw_core.enums import (
    BudgetPeriod,
    BudgetScopeKind,
    CircuitState,
    CostFigureKind,
    CostOperation,
    ReservationStatus,
)
from amw_core.errors import BudgetExhaustedError
from amw_core.ids import ActorRef, make_idempotency_key
from amw_core.interfaces.budget_guard import Budget, CallCheck
from amw_core.interfaces.cost_ledger import NewCostEntry
from amw_core.interfaces.system_functions import BreakerKey
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.retries.breaker import BreakerRow, admit, new_row, record
from amw_core.retries.pg import PgBreakerFunctions
from amw_core.tenancy import PgTenancy, dsn_connection_factory
from tests.core_services.support import T0, FixedClock, budget, settings
from tests.core_services_db.conftest import Work, make_task, make_user, make_work
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
M = 1_000_000
S4 = ActorRef("svc_s04")
ADAPTER = ActorRef("agent_05")
N = 20


def run_threads(fn: Callable[[int], Any]) -> tuple[list[Any], list[BaseException]]:
    """Run ``fn(i)`` on ``N`` threads released together by a barrier."""
    results: list[Any] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(N)

    def worker(i: int) -> None:
        try:
            barrier.wait(timeout=30)
            results.append(fn(i))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results, errors


def _guard() -> BudgetGuardCore:
    return BudgetGuardCore(PgBudgetBackend(), settings(), FixedClock(), PgAuditLog())


def _owner_budgets(tenancy: PgTenancy, tenant: Tenant, admin: Any, *budgets: Budget) -> None:
    owner = make_user(admin)
    with tenancy.transaction(TenantContext(tenant.org_id, ActorRef(owner))) as tx:
        for b in budgets:
            PgBudgetBackend().create_budget(tx, b)


def _entry(work: Work, micros: int, key: str | None = None) -> NewCostEntry:
    return NewCostEntry(
        provider="llm_provider",
        operation=CostOperation.LLM_COMPLETION,
        amount_micros=micros,
        currency="INR",
        figure_kind=CostFigureKind.ESTIMATE,
        occurred_at=T0,
        job_id=work.job_id,
        task_id=work.task_id,
        attempt_id=work.attempt_id,
        price_ref="pricing.v1",
        idempotency_key=key,  # type: ignore[arg-type]
    )


def _provider_budget(tenant: Tenant) -> Budget:
    return budget(
        tenant.org_id,
        BudgetPeriod.PILOT_TOTAL,
        100_000,
        scope_kind=BudgetScopeKind.PROVIDER,
        scope_key="llm_provider",
    )


def test_e2_twenty_parallel_calls_stay_inside_the_hold(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant
) -> None:
    """M2: hold 3 rupees, 20 workers each check + record a 1-rupee call in one transaction:
    exactly 3 pass and the ledger holds exactly 3 rupees."""
    _owner_budgets(
        tenancy,
        tenant_a,
        admin,
        budget(tenant_a.org_id, BudgetPeriod.PILOT_TOTAL, 100_000),
        _provider_budget(tenant_a),
    )
    work = make_work(admin, tenant_a)
    ctx = TenantContext(tenant_a.org_id, S4)
    with tenancy.transaction(ctx) as tx:
        assert _guard().reserve(tx, work.task_id, 3 * M, "INR").granted

    def call(i: int) -> bool:
        with tenancy.transaction(ctx) as tx:
            _guard().check_call(tx, CallCheck(work.task_id, work.job_id, "llm_provider", M, "INR"))
            time.sleep(0.05)  # the window in which an unlocked check would let everyone through
            key = make_idempotency_key(tenant_a.org_id, "llm.call", [str(i)])
            PgCostLedger().record(tx, _entry(work, M, key))
        return True

    passed, errors = run_threads(call)
    assert len(passed) == 3
    assert len(errors) == N - 3
    assert all(isinstance(e, BudgetExhaustedError) for e in errors)
    total = admin.execute(
        "SELECT sum(amount_micros) FROM cost_ledger WHERE org_id = %s", (tenant_a.org_uuid,)
    ).fetchone()
    assert total == (3 * M,)


def test_e1_twenty_parallel_reservations_never_exceed_the_limit(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant
) -> None:
    _owner_budgets(
        tenancy, tenant_a, admin, budget(tenant_a.org_id, BudgetPeriod.PILOT_TOTAL, 1000)
    )
    job = make_work(admin, tenant_a).job_id
    tasks = [make_task(admin, tenant_a, job)[0] for _ in range(N)]
    ctx = TenantContext(tenant_a.org_id, S4)

    def reserve(i: int) -> bool:
        with tenancy.transaction(ctx) as tx:
            return _guard().reserve(tx, tasks[i], 1_500_000, "INR").granted

    granted, errors = run_threads(reserve)
    assert errors == []
    assert sum(granted) == 6  # 10 rupees / 1.5
    with tenancy.transaction(ctx) as tx:
        held = PgBudgetBackend().reservations(tx, status=ReservationStatus.HELD)
    assert sum(h.amount_micros for h in held) == 9 * M


def test_e1_twenty_parallel_reservations_of_one_task_make_one_hold(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant
) -> None:
    """m1: the loser of the race reuses the HELD row (09 3.4 step 4), no raw UniqueViolation."""
    _owner_budgets(
        tenancy, tenant_a, admin, budget(tenant_a.org_id, BudgetPeriod.PILOT_TOTAL, 1000)
    )
    work = make_work(admin, tenant_a)
    ctx = TenantContext(tenant_a.org_id, S4)

    def reserve(_: int) -> bool:
        with tenancy.transaction(ctx) as tx:
            return _guard().reserve(tx, work.task_id, M, "INR").granted

    granted, errors = run_threads(reserve)
    assert errors == []
    assert all(granted)
    with tenancy.transaction(ctx) as tx:
        held = PgBudgetBackend().reservations(tx, status=ReservationStatus.HELD)
    assert len(held) == 1


def test_per_video_breach_stops_only_that_job_on_postgresql(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant
) -> None:
    """M4 / CCR-107 with two jobs: job A reaches its per-video cap, job B and the shared row
    are untouched."""
    video = budget(tenant_a.org_id, BudgetPeriod.PER_VIDEO, 300)  # 3 rupees
    _owner_budgets(
        tenancy,
        tenant_a,
        admin,
        video,
        budget(tenant_a.org_id, BudgetPeriod.PILOT_TOTAL, 100_000),
        _provider_budget(tenant_a),
    )
    a, b = make_work(admin, tenant_a), make_work(admin, tenant_a)
    ctx = TenantContext(tenant_a.org_id, S4)
    guard, ledger = _guard(), PgCostLedger()
    with tenancy.transaction(ctx) as tx:
        assert guard.reserve(tx, a.task_id, 3 * M, "INR").granted
        guard.check_call(tx, CallCheck(a.task_id, a.job_id, "llm_provider", 3 * M, "INR"))
        guard.after_call(tx, ledger.record(tx, _entry(a, 3 * M)))
    with tenancy.transaction(ctx) as tx:
        extra, _ = make_task(admin, tenant_a, a.job_id)
        assert not guard.reserve(tx, extra, 1, "INR").granted  # job A: no new paid task
        with pytest.raises(BudgetExhaustedError):
            guard.check_call(tx, CallCheck(a.task_id, a.job_id, "llm_provider", 1, "INR"))
        assert guard.status(tx, video.id, a.job_id).budget.state.value == "ACTIVE"
        assert guard.reserve(tx, b.task_id, 2 * M, "INR").granted  # job B is unaffected
        guard.check_call(tx, CallCheck(b.task_id, b.job_id, "llm_provider", 2 * M, "INR"))


# ---- breaker ---------------------------------------------------------------------------------
def _fns(pg_dsn: str, **cfg: int | None) -> PgBreakerFunctions:
    base = {"open_ms": 100, "open_ms_max": 400, "half_open_probe_timeout_ms": 5_000}
    breaker = BreakerSettings(**(base | cfg))
    s = settings().model_copy(update={"breaker_default": breaker})
    return PgBreakerFunctions(dsn_connection_factory(pg_dsn, role="amw_app"), s)


def _open_breaker(fns: PgBreakerFunctions, key: BreakerKey) -> None:
    for _ in range(5):
        fns.breaker_record(ADAPTER, key, False, "TEMPORARY.NETWORK")
    time.sleep(0.25)  # past open_until: the next admission is the first probe


@pytest.mark.parametrize("max_probes", [1, 3])
def test_half_open_admits_exactly_max_probes_of_twenty_workers(
    pg_dsn: str, tenant_a: Tenant, max_probes: int
) -> None:
    """M3: the probe count is kept under the row lock, so concurrent workers cannot over-admit."""
    fns = _fns(pg_dsn, half_open_max_probes=max_probes)
    key = BreakerKey(f"llm_probe_{max_probes}", "llm.completion", "platform")
    _open_breaker(fns, key)
    outcomes, errors = run_threads(lambda _: fns.admit(ADAPTER, key))
    assert errors == []
    assert sum(1 for o in outcomes if o.admitted) == max_probes
    assert {o.state.state for o in outcomes} == {CircuitState.HALF_OPEN}
    # a finished probe (even an uncounted failure) frees exactly one slot
    fns.breaker_record(ADAPTER, key, False, "PERMANENT.INPUT_INVALID")
    again = fns.admit(ADAPTER, key)
    assert again.admitted
    assert not fns.admit(ADAPTER, key).admitted


def test_closed_breaker_admits_everyone_and_open_admits_nobody(
    pg_dsn: str, tenant_a: Tenant
) -> None:
    fns = _fns(pg_dsn, open_ms=5_000, open_ms_max=10_000)
    key = BreakerKey("llm_probe_closed", "llm.completion", "platform")
    outcomes, errors = run_threads(lambda _: fns.admit(ADAPTER, key))
    assert errors == []
    assert all(o.admitted and o.state.state is CircuitState.CLOSED for o in outcomes)
    for _ in range(5):
        fns.breaker_record(ADAPTER, key, False, "TEMPORARY.NETWORK")
    outcomes, errors = run_threads(lambda _: fns.admit(ADAPTER, key))
    assert errors == []
    assert not any(o.admitted for o in outcomes)


def test_twenty_parallel_counted_failures_open_once(pg_dsn: str, tenant_a: Tenant) -> None:
    fns = _fns(pg_dsn, open_ms=5_000, open_ms_max=10_000)
    key = BreakerKey("llm_parallel_fail", "llm.completion", "platform")
    _, errors = run_threads(lambda _: fns.breaker_record(ADAPTER, key, False, "TEMPORARY.NETWORK"))
    assert errors == []
    with dsn_connection_factory(pg_dsn, role="amw_app")() as conn:
        row = conn.execute(
            "SELECT state, open_count FROM circuit_breakers WHERE provider = %s", (key.provider,)
        ).fetchone()
    assert row == ("OPEN", 1)


_COLS = (
    "state, window_calls, window_failures, consecutive_failures, open_count,"
    " half_open_in_flight, opened_at IS NOT NULL, last_error_code, open_until,"
    " half_open_probe_until"
)


def _pure_view(row: BreakerRow) -> tuple[Any, ...]:
    return (
        row.state.value,
        row.window_calls,
        row.window_failures,
        row.consecutive_failures,
        row.open_count,
        row.half_open_in_flight,
        row.opened_at is not None,
        row.last_error_code,
    )


def _sync_clock_columns(pure: BreakerRow, stored: tuple[Any, ...]) -> BreakerRow:
    """The stored time columns are SQL ``now()``; the pure model is given the same instants, so
    the two never disagree about which side of a boundary a step falls on."""
    return replace(pure, open_until=stored[8], half_open_probe_until=stored[9])


@pytest.mark.parametrize("seed", range(1, 9))
def test_breaker_sql_matches_the_pure_model(pg_dsn: str, admin: Any, seed: int) -> None:
    """Random sequences of outcomes, admissions, waits and lease expiries: every column of the row
    equals the pure model after each step. Deterministic: the clock is never slept on. The open
    period and the probe lease are long (minutes); "wait" and "lease expiry" move the stored
    deadline into the past with a superuser UPDATE, so no step lands near a time boundary (the old
    version slept 150 ms against Python and SQL clocks and failed on that race)."""
    cfg = BreakerSettings(
        window_ms=600_000,
        min_calls=3,
        failure_ratio=0.5,
        consecutive_failures=4,
        open_ms=600_000,
        open_ms_max=1_200_000,
        half_open_max_probes=2,
        half_open_successes_to_close=2,
        half_open_probe_timeout_ms=600_000,
    )
    fns = PgBreakerFunctions(
        dsn_connection_factory(pg_dsn, role="amw_app"),
        settings().model_copy(update={"breaker_default": cfg}),
    )
    key = BreakerKey(f"llm_parity_{seed}", "llm.completion", "platform")
    rng = random.Random(seed)  # noqa: S311 - deterministic test data
    pure = new_row(key, datetime.now(UTC))
    codes = ["TEMPORARY.NETWORK", "TEMPORARY.UPSTREAM_5XX", "PERMANENT.INPUT_INVALID"]
    probes: list[bool | None] = []  # admission flag of the calls in flight (any order)
    seen: set[tuple[str, str]] = set()
    for step in range(120):
        op = rng.choice(["ok", "ok", "fail", "fail", "neutral", "admit", "admit", "wait", "lease"])
        before = pure.state.value
        now = datetime.now(UTC)
        if op == "wait":
            admin.execute(
                "UPDATE circuit_breakers SET open_until = now() - interval '1 second'"
                " WHERE provider = %s AND state = 'OPEN'",
                (key.provider,),
            )
        elif op == "lease":
            admin.execute(
                "UPDATE circuit_breakers SET half_open_probe_until = now() - interval '1 second'"
                " WHERE provider = %s AND half_open_probe_until IS NOT NULL",
                (key.provider,),
            )
        elif op == "admit":
            admission = admit(pure, now, cfg)
            got = fns.admit(ADAPTER, key)
            assert got.admitted is admission.allowed, (seed, step, op)
            assert got.probe is admission.probe, (seed, step, op)
            pure = admission.row
            if got.admitted:
                probes.append(got.probe)
        else:
            flag = probes.pop(rng.randrange(len(probes))) if probes else None
            code = {"ok": None, "fail": rng.choice(codes[:2]), "neutral": codes[2]}[op]
            pure = record(pure, op == "ok", code, now, cfg, probe=flag)
            fns.breaker_record(ADAPTER, key, op == "ok", code, probe=flag)
        stored = admin.execute(
            f"SELECT {_COLS} FROM circuit_breakers WHERE provider = %s",  # noqa: S608
            (key.provider,),
        ).fetchone()
        if stored is None:
            assert pure.state is CircuitState.CLOSED
            continue
        pure = _sync_clock_columns(pure, tuple(stored))
        assert tuple(stored[:8]) == _pure_view(pure), (seed, step, op)
        seen.add((before, pure.state.value))
    assert ("OPEN", "HALF_OPEN") in seen or seed != 1


def test_a_probe_that_never_reports_is_reclaimed_after_its_lease(
    pg_dsn: str, admin: Any, tenant_a: Tenant
) -> None:
    """Re-review N1: crash (or an E2 refusal) after admission must not wedge HALF_OPEN."""
    fns = _fns(pg_dsn, half_open_probe_timeout_ms=300)
    key = BreakerKey("llm_probe_crash", "llm.completion", "platform")
    _open_breaker(fns, key)
    first = fns.admit(ADAPTER, key)  # this worker crashes now: it never records
    assert first.admitted
    assert first.probe
    assert not fns.admit(ADAPTER, key).admitted  # the lease still runs
    time.sleep(0.4)
    again = fns.admit(ADAPTER, key)
    assert again.admitted
    fns.breaker_record(ADAPTER, key, True, None, probe=again.probe)
    closing = fns.admit(ADAPTER, key)
    assert closing.admitted
    fns.breaker_record(ADAPTER, key, True, None, probe=closing.probe)
    assert fns.admit(ADAPTER, key).state.state is CircuitState.CLOSED


def test_a_late_result_of_a_non_probe_call_frees_no_probe_slot(
    pg_dsn: str, admin: Any, tenant_a: Tenant
) -> None:
    """Re-review m-a: a call admitted while CLOSED that ends during HALF_OPEN is not a probe."""
    fns = _fns(pg_dsn, open_ms=5_000, open_ms_max=10_000)
    key = BreakerKey("llm_probe_late", "llm.completion", "platform")
    old_call = fns.admit(ADAPTER, key)  # admitted while CLOSED, still running
    assert old_call.admitted
    assert not old_call.probe
    for _ in range(5):
        fns.breaker_record(ADAPTER, key, False, "TEMPORARY.NETWORK")
    assert not fns.admit(ADAPTER, key).admitted  # OPEN
    admin.execute(
        "UPDATE circuit_breakers SET open_until = now() - interval '1 second' WHERE provider = %s",
        (key.provider,),
    )
    probe = fns.admit(ADAPTER, key)
    assert probe.probe
    assert not fns.admit(ADAPTER, key).admitted  # max 1 probe, in flight
    fns.breaker_record(ADAPTER, key, True, None, probe=old_call.probe)  # the late result
    assert not fns.admit(ADAPTER, key).admitted  # the real probe still holds the slot
    fns.breaker_record(ADAPTER, key, True, None, probe=probe.probe)
    assert fns.admit(ADAPTER, key).admitted  # now it is free
