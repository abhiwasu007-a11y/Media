"""S4 budget guard: blocking tests for 09 section 4 rules B1-B8, the provider start gate (09 8),
E1 all-or-nothing reservations, E2 per-call checks and E3 breach detection."""

from datetime import timedelta

import pytest

from amw_core.budget_guard import JobScope, period_bounds
from amw_core.config import load_settings
from amw_core.enums import (
    BudgetPeriod,
    BudgetScopeKind,
    BudgetState,
    CostFigureKind,
    CostOperation,
    ErrorDisposition,
    ReservationStatus,
    WaitReason,
)
from amw_core.errors import (
    BudgetExhaustedError,
    ConfigInvalidError,
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import CHANNEL, JOB, ORG, USER, JobId, TaskId
from amw_core.interfaces.budget_guard import BudgetGuard, CallCheck
from amw_core.interfaces.cost_ledger import NewCostEntry
from amw_core.retries import decide_for_error
from tests.core_services.support import T0, World, budget, settings, tx_for

pytestmark = pytest.mark.unit
PROVIDER = "llm_provider"
M = 1_000_000  # micros per rupee; INR minor exponent 2 -> 1 paisa = 10_000 micros


def world(per_video_rupees: int = 10, pilot_rupees: int = 25) -> World:
    w = World()
    w.video = w.add_budget(budget(w.org, BudgetPeriod.PER_VIDEO, per_video_rupees * 100))
    w.pilot = w.add_budget(budget(w.org, BudgetPeriod.PILOT_TOTAL, pilot_rupees * 100))
    w.provider = w.add_budget(
        budget(
            w.org,
            BudgetPeriod.PILOT_TOTAL,
            100_000,
            scope_kind=BudgetScopeKind.PROVIDER,
            scope_key=PROVIDER,
        )
    )
    return w


def check(w: World, job: str, task: str, micros: int) -> None:
    w.guard.check_call(w.tx, CallCheck(task, job, PROVIDER, micros, "INR"))  # type: ignore[arg-type]


def test_is_a_budget_guard() -> None:
    assert isinstance(world().guard, BudgetGuard)


def test_e1_reserves_on_every_applicable_budget() -> None:
    w = world()
    job = w.job()
    task = w.task(job)
    out = w.guard.reserve(w.tx, task, 4 * M, "INR")
    assert out.granted
    assert {r.budget_id for r in out.reservations} == {w.video, w.pilot}
    assert all(r.status is ReservationStatus.HELD for r in out.reservations)
    again = w.guard.reserve(w.tx, task, 4 * M, "INR")  # a retry reuses the hold
    assert again.reservations == out.reservations
    assert len(w.backend.reservations(w.tx, task_id=task)) == 2


def test_e1_is_all_or_nothing() -> None:
    w = world(per_video_rupees=10, pilot_rupees=5)
    task = w.task(w.job())
    out = w.guard.reserve(w.tx, task, 6 * M, "INR")
    assert not out.granted
    assert out.refused_budget_ids == (w.pilot,)
    assert w.backend.reservations(w.tx, task_id=task) == []


# ---- B1 -------------------------------------------------------------------------------------
def test_b1_breach_blocks_new_paid_tasks_and_they_wait_for_budget() -> None:
    w = world(per_video_rupees=100, pilot_rupees=5)
    job = w.job()
    t1 = w.task(job)
    assert w.guard.reserve(w.tx, t1, 5 * M, "INR").granted
    check(w, job, t1, 5 * M)
    w.spend(job, t1, 5 * M)  # pilot committed = limit -> E3 suspends it
    assert w.backend.get_budget(w.tx, w.pilot).budget.state is BudgetState.SUSPENDED_EXCEEDED  # type: ignore[union-attr]
    t2 = w.task(w.job())
    out = w.guard.reserve(w.tx, t2, 1, "INR")
    assert not out.granted
    assert w.pilot in out.refused_budget_ids
    # the orchestrator maps the refusal to RESOURCE.BUDGET_EXHAUSTED: SUSPEND, AWAITING_BUDGET
    decision = decide_for_error(
        BudgetExhaustedError("budget refused"),
        attempt_count=0,
        max_attempts=3,
        class_failures=0,
        now=T0,
        settings=w.cfg,
    )
    assert decision.disposition is ErrorDisposition.SUSPEND
    assert decision.wait_reason is WaitReason.AWAITING_BUDGET
    assert not decision.consumes_attempt


def test_b1_fail_closed_without_an_active_budget() -> None:
    w = World()
    task = w.task(w.job())
    assert not w.guard.reserve(w.tx, task, 1, "INR").granted  # no budget at all
    w.add_budget(budget(w.org, BudgetPeriod.PER_VIDEO, 1000, state=BudgetState.DISABLED))
    assert not w.guard.reserve(w.tx, task, 1, "INR").granted  # DISABLED is not enforcement
    zero = World()
    zero.add_budget(budget(zero.org, BudgetPeriod.PILOT_TOTAL, 0))  # no owner-set limit
    assert not zero.guard.reserve(zero.tx, zero.task(zero.job()), 1, "INR").granted


# ---- B2 -------------------------------------------------------------------------------------
def test_b2_running_task_continues_inside_its_hold_and_e2_stops_the_excess() -> None:
    w = world(per_video_rupees=100, pilot_rupees=10)
    job = w.job()
    task = w.task(job)
    assert w.guard.reserve(w.tx, task, 10 * M, "INR").granted
    check(w, job, task, 6 * M)
    w.spend(job, task, 6 * M)
    other = w.task(w.job())
    assert not w.guard.reserve(w.tx, other, 1, "INR").granted  # hold covers the rest of pilot
    check(w, job, task, 4 * M)  # still inside its own reservation
    w.spend(job, task, 4 * M)
    assert w.backend.get_budget(w.tx, w.pilot).budget.state is BudgetState.SUSPENDED_EXCEEDED  # type: ignore[union-attr]
    with pytest.raises(BudgetExhaustedError) as err:
        check(w, job, task, 1)
    assert err.value.spec.wait_reason is WaitReason.AWAITING_BUDGET


def test_committed_counts_a_running_tasks_spend_once() -> None:
    w = world(per_video_rupees=100, pilot_rupees=10)
    job = w.job()
    task = w.task(job)
    w.guard.reserve(w.tx, task, 8 * M, "INR")
    w.spend(job, task, 3 * M)
    s = w.guard.status(w.tx, w.pilot)
    assert s.committed_micros == 8 * M  # 3 spent + 5 still held, not 3 + 8
    assert s.budget.state is BudgetState.ACTIVE
    w.guard.consume(w.tx, task)
    assert w.guard.status(w.tx, w.pilot).committed_micros == 3 * M  # unused hold returns


def test_e2_requires_a_hold_and_matching_ids() -> None:
    w = world()
    job = w.job()
    task = w.task(job)
    with pytest.raises(BudgetExhaustedError):
        check(w, job, task, 1)
    check(w, job, task, 0)  # B4: no cost, no hold needed
    with pytest.raises(InputInvalidError):
        check(w, w.job(), task, 1)
    with pytest.raises(InputInvalidError):
        check(w, job, task, -1)
    w.guard.reserve(w.tx, task, M, "INR")
    with pytest.raises(ConfigInvalidError):
        w.guard.check_call(w.tx, CallCheck(task, job, PROVIDER, 1, "USD"))


# ---- B3 -------------------------------------------------------------------------------------
def test_b3_completed_work_is_never_deleted() -> None:
    w = world(per_video_rupees=100, pilot_rupees=2)
    job = w.job()
    done = w.task(job)
    w.guard.reserve(w.tx, done, 2 * M, "INR")
    w.spend(job, done, 2 * M)
    w.guard.consume(w.tx, done)
    failing = w.task(job)
    assert not w.guard.reserve(w.tx, failing, M, "INR").granted
    assert len(w.ledger.all_rows(w.tx)) == 1
    assert [r.status for r in w.backend.reservations(w.tx, task_id=done)] == [
        ReservationStatus.CONSUMED
    ] * 2
    released = w.guard.release(w.tx, failing)
    assert released == []
    assert len(w.ledger.all_rows(w.tx)) == 1


def test_release_keeps_incurred_cost() -> None:
    w = world()
    job = w.job()
    task = w.task(job)
    w.guard.reserve(w.tx, task, 5 * M, "INR")
    w.spend(job, task, 2 * M)
    (rel,) = [r for r in w.guard.release(w.tx, task) if r.budget_id == w.pilot]
    assert rel.status is ReservationStatus.RELEASED
    assert rel.released_at == T0
    assert w.guard.status(w.tx, w.pilot).committed_micros == 2 * M


# ---- B4 -------------------------------------------------------------------------------------
def test_b4_non_paid_work_is_not_blocked_by_a_breach() -> None:
    w = world(per_video_rupees=1, pilot_rupees=1)
    job = w.job()
    task = w.task(job)
    w.guard.reserve(w.tx, task, M, "INR")
    w.spend(job, task, M)
    assert w.backend.get_budget(w.tx, w.pilot).budget.state is BudgetState.SUSPENDED_EXCEEDED  # type: ignore[union-attr]
    qc = w.task(job)
    out = w.guard.reserve(w.tx, qc, 0, "INR")
    assert out.granted
    assert out.reservations == ()
    with pytest.raises(InputInvalidError):
        w.guard.reserve(w.tx, qc, -1, "INR")


# ---- B5 -------------------------------------------------------------------------------------
def test_b5_breach_returns_the_changed_budgets_and_is_audited() -> None:
    w = world(per_video_rupees=100, pilot_rupees=3)
    job = w.job()
    task = w.task(job)
    w.guard.reserve(w.tx, task, 3 * M, "INR")
    row = w.ledger.record(w.tx, _entry(w, job, task, 3 * M))
    changed = w.guard.after_call(w.tx, row)
    assert [b.id for b in changed] == [w.pilot]
    assert changed[0].state is BudgetState.SUSPENDED_EXCEEDED
    assert w.guard.after_call(w.tx, row) == []  # already suspended: no second notice
    (audit,) = list(w.audit.export(w.tx))
    assert audit.entry.action == "budget.suspended"
    assert audit.entry.target_id == w.pilot
    assert audit.entry.details["enforcement_point"] == "E3"
    assert audit.entry.details["committed_micros"] == 3 * M
    assert audit.entry.job_id == job
    assert w.audit.verify_chain(w.tx).ok


def _entry(w: World, job: JobId | None, task: TaskId | None, micros: int) -> NewCostEntry:
    return NewCostEntry(
        provider=PROVIDER,
        operation=CostOperation.LLM_COMPLETION,
        amount_micros=micros,
        currency="INR",
        figure_kind=CostFigureKind.ESTIMATE,
        occurred_at=w.clock.now(),
        job_id=job,
        task_id=task,
        price_ref="pricing.v1",
    )


# ---- B6 -------------------------------------------------------------------------------------
def test_b6_resume_only_after_a_human_action() -> None:
    w = world(per_video_rupees=100, pilot_rupees=2)
    job = w.job()
    task = w.task(job)
    w.guard.reserve(w.tx, task, 2 * M, "INR")
    w.spend(job, task, 2 * M)
    w.guard.consume(w.tx, task)
    waiting = w.task(job)
    assert not w.guard.reserve(w.tx, waiting, M, "INR").granted
    w.clock.advance(86_400_000 * 40)  # time alone never resumes a PILOT_TOTAL budget
    assert not w.guard.reserve(w.tx, waiting, M, "INR").granted
    with pytest.raises(PermissionDeniedError):
        w.guard.set_limit(w.tx, w.pilot, 10_000, "raise")
    with pytest.raises(PermissionDeniedError):
        w.guard.release_suspension(w.tx, w.pilot, "release")
    owner = tx_for(w.org, USER.new())
    with pytest.raises(InputInvalidError):
        w.guard.set_limit(owner, w.pilot, 500, " ")
    raised = w.guard.set_limit(owner, w.pilot, 500, "owner raised the pilot limit")
    assert raised.state is BudgetState.ACTIVE
    assert raised.limit_minor == 500
    assert w.guard.reserve(w.tx, waiting, M, "INR").granted  # T15 re-runs E1
    actions = [e.entry.action for e in w.audit.export(w.tx)]
    assert actions == ["budget.suspended", "budget.limit_changed"]
    changed = list(w.audit.export(w.tx))[-1].entry.details
    assert (changed["before_limit_minor"], changed["after_limit_minor"]) == (200, 500)


def test_b6_raise_that_does_not_cover_stays_suspended_and_explicit_release() -> None:
    w = world(per_video_rupees=100, pilot_rupees=2)
    job = w.job()
    task = w.task(job)
    w.guard.reserve(w.tx, task, 2 * M, "INR")
    w.spend(job, task, 2 * M)
    owner = tx_for(w.org, USER.new())
    still = w.guard.set_limit(owner, w.pilot, 200, "same")
    assert still.state is BudgetState.SUSPENDED_EXCEEDED
    released = w.guard.release_suspension(owner, w.pilot, "accept overrun")
    assert released.state is BudgetState.ACTIVE
    with pytest.raises(InputInvalidError):
        w.guard.release_suspension(owner, w.pilot, "again")
    with pytest.raises(InputInvalidError):
        w.guard.release_suspension(owner, w.pilot, "")
    with pytest.raises(MissingDependencyError):
        w.guard.release_suspension(owner, w.video.replace(w.video[-4:], "0000"), "x")  # type: ignore[arg-type]
    with pytest.raises(MissingDependencyError):
        w.guard.set_limit(owner, w.video.replace(w.video[-4:], "0000"), 1, "x")  # type: ignore[arg-type]
    with pytest.raises(MissingDependencyError):
        w.guard.status(w.tx, w.video.replace(w.video[-4:], "0000"))  # type: ignore[arg-type]


def test_b6_day_budget_rolls_over_with_the_period() -> None:
    w = World()
    w.backend.set_timezone(w.tx, "Asia/Kolkata")
    day = w.add_budget(budget(w.org, BudgetPeriod.DAY, 100))  # 1 rupee per day
    job = w.job()
    t1 = w.task(job)
    w.guard.reserve(w.tx, t1, M, "INR")
    w.spend(job, t1, M)
    w.guard.consume(w.tx, t1)
    t2 = w.task(job)
    assert not w.guard.reserve(w.tx, t2, 1, "INR").granted
    w.clock.advance(86_400_000)  # next calendar day in the tenant zone
    assert w.guard.reserve(w.tx, t2, 1, "INR").granted
    assert w.backend.get_budget(w.tx, day).budget.state is BudgetState.ACTIVE  # type: ignore[union-attr]
    assert "budget.period_rolled_over" in [e.entry.action for e in w.audit.export(w.tx)]


# ---- B7 -------------------------------------------------------------------------------------
def test_b7_soft_limit_warns_and_never_blocks() -> None:
    w = world(per_video_rupees=100, pilot_rupees=10)
    job = w.job()
    task = w.task(job)
    w.guard.reserve(w.tx, task, 9 * M, "INR")
    w.spend(job, task, 9 * M)
    s = w.guard.status(w.tx, w.pilot)
    assert s.soft_limit_reached
    assert s.budget.state is BudgetState.ACTIVE
    w.guard.consume(w.tx, task)
    assert w.guard.reserve(w.tx, w.task(job), M // 2, "INR").granted
    assert not w.guard.status(w.tx, w.video, job).soft_limit_reached


# ---- B8 (27 section 9 acceptance test 4) ------------------------------------------------------
def test_b8_a_budget_breach_stops_further_paid_calls() -> None:
    """Paid steps of one video run until the per-video limit is reached; then the next paid
    call and the next paid task are refused, and the task waits with AWAITING_BUDGET."""
    w = world(per_video_rupees=10, pilot_rupees=1000)
    job = w.job()
    calls = 0
    refused: BudgetExhaustedError | None = None
    for _ in range(20):
        task = w.task(job)
        if not w.guard.reserve(w.tx, task, 3 * M, "INR").granted:
            refused = BudgetExhaustedError("E1 refused")
            break
        try:
            check(w, job, task, 3 * M)
        except BudgetExhaustedError as exc:
            refused = exc
            break
        w.spend(job, task, 3 * M)
        calls += 1
        w.guard.consume(w.tx, task)
    assert calls == 3
    assert refused is not None
    assert refused.spec.wait_reason is WaitReason.AWAITING_BUDGET
    paid = sum(r.entry.amount_micros for r in w.ledger.all_rows(w.tx))
    assert paid == 9 * M <= w.guard.status(w.tx, w.video, job).budget.limit_minor * 10_000
    other_video = w.job()  # per-video limits apply per job
    assert w.guard.reserve(w.tx, w.task(other_video), 3 * M, "INR").granted


# ---- provider start gate (09 section 8) -------------------------------------------------------
def test_provider_gate_requires_an_active_acknowledged_limit() -> None:
    w = World()
    w.add_budget(budget(w.org, BudgetPeriod.PILOT_TOTAL, 1000))
    with pytest.raises(BudgetExhaustedError):
        w.guard.check_provider_gate(w.tx, PROVIDER)
    w.add_budget(
        budget(
            w.org,
            BudgetPeriod.PILOT_TOTAL,
            1000,
            scope_kind=BudgetScopeKind.PROVIDER,
            scope_key="tts_provider",
        )
    )
    with pytest.raises(BudgetExhaustedError):
        w.guard.check_provider_gate(w.tx, PROVIDER)
    w.add_budget(
        budget(
            w.org,
            BudgetPeriod.PILOT_TOTAL,
            1000,
            scope_kind=BudgetScopeKind.PROVIDER,
            scope_key=PROVIDER,
            state=BudgetState.DISABLED,
        )
    )
    with pytest.raises(BudgetExhaustedError):
        w.guard.check_provider_gate(w.tx, PROVIDER)
    w.add_budget(
        budget(
            w.org,
            BudgetPeriod.PILOT_TOTAL,
            1000,
            scope_kind=BudgetScopeKind.PROVIDER,
            scope_key=PROVIDER,
        )
    )
    w.guard.check_provider_gate(w.tx, PROVIDER)


def test_provider_limit_is_also_a_cap_and_warnings_flag_higher_internal_limits() -> None:
    w = World()
    w.add_budget(budget(w.org, BudgetPeriod.PER_VIDEO, 100_000))
    prov = w.add_budget(
        budget(
            w.org,
            BudgetPeriod.PILOT_TOTAL,
            200,
            scope_kind=BudgetScopeKind.PROVIDER,
            scope_key=PROVIDER,
        )
    )
    job = w.job()
    task = w.task(job)
    w.guard.reserve(w.tx, task, 5 * M, "INR")
    check(w, job, task, 2 * M)
    w.spend(job, task, 2 * M)
    assert w.backend.get_budget(w.tx, prov).budget.state is BudgetState.SUSPENDED_EXCEEDED  # type: ignore[union-attr]
    with pytest.raises(BudgetExhaustedError):
        check(w, job, task, 1)
    pairs = w.guard.provider_limit_warnings(w.tx)
    assert len(pairs) == 1
    assert pairs[0][1] == prov


def test_spend_without_a_job_counts_against_org_totals_only() -> None:
    w = world(per_video_rupees=1, pilot_rupees=1)
    row = w.ledger.record(w.tx, _entry(w, None, None, M))
    changed = {b.id for b in w.guard.after_call(w.tx, row)}
    assert changed == {w.pilot}


# ---- scopes, units, periods -------------------------------------------------------------------
def test_workspace_channel_and_production_type_scopes() -> None:
    w = World()
    chn = CHANNEL.new()
    job = JOB.new()
    w.backend.add_job(w.tx, JobScope(job, w.workspace, chn, "SHORTS"))
    wsp_b = w.add_budget(
        budget(
            w.org,
            BudgetPeriod.PILOT_TOTAL,
            1000,
            scope_kind=BudgetScopeKind.WORKSPACE,
            scope_id=w.workspace,
        )
    )
    chn_b = w.add_budget(
        budget(
            w.org, BudgetPeriod.PILOT_TOTAL, 1000, scope_kind=BudgetScopeKind.CHANNEL, scope_id=chn
        )
    )
    pt_b = w.add_budget(
        budget(
            w.org,
            BudgetPeriod.PILOT_TOTAL,
            1000,
            scope_kind=BudgetScopeKind.PRODUCTION_TYPE,
            scope_key="SHORTS",
        )
    )
    w.add_budget(
        budget(
            w.org,
            BudgetPeriod.PILOT_TOTAL,
            1000,
            scope_kind=BudgetScopeKind.PRODUCTION_TYPE,
            scope_key="AD_SPOT",
        )
    )
    assert {b.id for b in w.guard.applicable_budgets(w.tx, job)} == {wsp_b, chn_b, pt_b}
    task = w.task(job)
    w.guard.reserve(w.tx, task, M, "INR")
    w.spend(job, task, M)
    for b in (wsp_b, chn_b, pt_b):
        assert w.guard.status(w.tx, b).committed_micros == M


def test_unknown_currency_exponent_and_currency_mismatch_fail_closed() -> None:
    w = World(cfg=load_settings(environ={}))
    w.add_budget(budget(w.org, BudgetPeriod.PILOT_TOTAL, 100))
    with pytest.raises(ConfigInvalidError):
        w.guard.reserve(w.tx, w.task(w.job()), 1, "INR")
    w2 = world()
    with pytest.raises(ConfigInvalidError):
        w2.guard.reserve(w2.tx, w2.task(w2.job()), 1, "USD")


def test_per_video_status_needs_a_job() -> None:
    w = world()
    with pytest.raises(InputInvalidError):
        w.guard.status(w.tx, w.video)


def test_period_bounds() -> None:
    start, end = period_bounds(BudgetPeriod.MONTH, T0, "Asia/Kolkata")
    assert start is not None
    assert end is not None
    assert start.isoformat() == "2025-12-31T18:30:00+00:00"
    assert end.isoformat() == "2026-01-31T18:30:00+00:00"
    dec = T0.replace(month=12, day=20)
    assert period_bounds(BudgetPeriod.MONTH, dec, "UTC")[1].isoformat().startswith("2027-01-01")  # type: ignore[union-attr]
    day = period_bounds(BudgetPeriod.DAY, T0, "UTC")
    assert day[1] - day[0] == timedelta(days=1)  # type: ignore[operator]
    assert period_bounds(BudgetPeriod.PILOT_TOTAL, T0, None) == (None, None)
    with pytest.raises(ConfigInvalidError):
        period_bounds(BudgetPeriod.DAY, T0, None)
    with pytest.raises(ConfigInvalidError):
        period_bounds(BudgetPeriod.DAY, T0, "Mars/Base")


def test_rolling_budget_without_tenant_zone_fails_closed() -> None:
    w = World()
    w.add_budget(budget(w.org, BudgetPeriod.MONTH, 100))
    with pytest.raises(ConfigInvalidError):
        w.guard.reserve(w.tx, w.task(w.job()), 1, "INR")


@pytest.mark.tenancy
def test_budgets_never_span_tenants() -> None:
    w = world()
    other = tx_for(ORG.new())
    with pytest.raises(MissingDependencyError):
        w.guard.reserve(other, w.task(w.job()), 1, "INR")
    with pytest.raises(MissingDependencyError):
        w.guard.status(other, w.pilot)
    assert w.backend.budgets(other) == []


def test_settings_helper_has_exponents() -> None:
    assert settings().finance.currency_minor_exponent["INR"] == 2


def test_per_video_breach_stops_only_that_job_and_never_suspends_the_shared_row() -> None:
    """CCR-107: the per-video cap of job A refuses A's reserve and calls; job B and the row live."""
    w = world(per_video_rupees=3, pilot_rupees=100)
    job_a, job_b = w.job(), w.job()
    task_a, task_b = w.task(job_a), w.task(job_b)
    assert w.guard.reserve(w.tx, task_a, 3 * M, "INR").granted
    check(w, job_a, task_a, 3 * M)
    row = w.ledger.record(w.tx, _entry(w, job_a, task_a, 3 * M))
    assert w.guard.after_call(w.tx, row) == []  # no budget changed state
    assert w.backend.get_budget(w.tx, w.video).budget.state is BudgetState.ACTIVE  # type: ignore[union-attr]
    audits = [a.entry for a in w.audit.export(w.tx)]
    assert [a.action for a in audits] == ["budget.job_cap_reached"]
    assert audits[0].job_id == job_a
    # job A: no new paid task, no further call
    assert not w.guard.reserve(w.tx, w.task(job_a), 1, "INR").granted
    with pytest.raises(BudgetExhaustedError):
        check(w, job_a, task_a, 1)
    # job B is untouched
    assert w.guard.reserve(w.tx, task_b, 2 * M, "INR").granted
    check(w, job_b, task_b, 2 * M)
    assert w.guard.status(w.tx, w.video, job_b).remaining_micros == 1 * M


def test_e2_per_video_cap_refuses_a_call_that_would_cross_it_inside_the_hold() -> None:
    w = world(per_video_rupees=3, pilot_rupees=100)
    job = w.job()
    task = w.task(job)
    other = w.task(job)
    assert w.guard.reserve(w.tx, task, 3 * M, "INR").granted
    w.spend(job, other, 2 * M)  # another task of the job already spent 2 of the 3 rupees
    with pytest.raises(BudgetExhaustedError) as err:
        check(w, job, task, 2 * M)
    assert "per-job cap" in str(err.value)
