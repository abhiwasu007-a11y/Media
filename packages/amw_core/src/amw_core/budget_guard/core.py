"""S4 budget guard logic (09 sections 2-4 and 8; 3A slice spec section 5), backend-agnostic.

``BudgetGuardCore`` implements the ``BudgetGuard`` Protocol over a ``BudgetBackend`` (in-memory or
PostgreSQL). Everything here is deterministic code; no model call.

**Committed amount.** 09 section 3.3 defines ``committed = sum(ledger, VERIFIED else ESTIMATE) +
sum(HELD reservations)``. Taken literally, the spend of a running task is counted twice (once in
the ledger and again inside its own HELD reservation), which would suspend a budget mid-task even
when the task stays inside the amount admitted for it, and would contradict 09 section 3.4 step 2
("the difference returns to remaining" at CONSUMED) and B2. This implementation therefore counts
each HELD reservation net of the spend already recorded for its task in the budget's scope:
``committed = sum(ledger) + sum over HELD of max(0, hold - task spend)``. It is never lower than
the literal sum of spend and never lower than the literal formula minus that double count. Filed
as an open contract question (lane L1b report).

**PER_VIDEO / PER_JOB** budgets apply per job: the ledger rows and holds of that job only.
**PILOT_TOTAL** never resets. **DAY / MONTH** follow the tenant time zone; a suspended DAY/MONTH
budget returns to ACTIVE only when the period has rolled over since it was suspended (B6).
**PROVIDER** budgets are the start gate (09 section 8) and cap the provider's spend; they are not
reserved at T03 (the provider of a task is known only at call time).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from amw_core.config import AmwSettings
from amw_core.cost.ledger import amount_in, effective_rows
from amw_core.enums import ActorKind, BudgetPeriod, BudgetScopeKind, BudgetState, ReservationStatus
from amw_core.errors import (
    BudgetExhaustedError,
    ConfigInvalidError,
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import (
    ActorRef,
    BudgetId,
    ChannelId,
    JobId,
    TaskId,
    WorkspaceId,
)
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.budget_guard import (
    Budget,
    BudgetStatus,
    CallCheck,
    Reservation,
    ReservationOutcome,
)
from amw_core.interfaces.cost_ledger import CostEntry
from amw_core.interfaces.tenancy_context import TenantTransaction

_MICROS_PER_MINOR = (1_000_000, 100_000, 10_000, 1_000, 100, 10, 1)
"""Micros per minor unit by ISO 4217 exponent 0-6."""
PER_ITEM_PERIODS = frozenset({BudgetPeriod.PER_VIDEO, BudgetPeriod.PER_JOB})
ROLLING_PERIODS = frozenset({BudgetPeriod.DAY, BudgetPeriod.MONTH})
AUTHORITY_SYSTEM = "svc_s04.budget_guard"
"""``audit_log.authority`` of S4's own enforcement entries (09 section 2)."""
AUTHORITY_HUMAN = "budget.limit_owner"
"""Authority of an owner / Finance budget action. The permission key is REQUIRES REVIEW (09
section 13: GLOSSARY permission list); this value names the policy, not a permission."""


@dataclass(frozen=True, slots=True)
class JobScope:
    """What decides which budgets apply to a job (04 section 5.3 ``jobs`` columns)."""

    job_id: JobId
    workspace_id: WorkspaceId | None
    channel_id: ChannelId | None
    production_type_key: str | None


@dataclass(frozen=True, slots=True)
class StoredBudget:
    budget: Budget
    updated_at: datetime
    row_version: int = 1


class BudgetBackend(Protocol):
    """Storage operations the guard needs; every call runs in the caller's tenant transaction."""

    def budgets(self, tx: TenantTransaction, lock: bool = False) -> Sequence[StoredBudget]: ...

    def get_budget(
        self, tx: TenantTransaction, budget_id: BudgetId, lock: bool = False
    ) -> StoredBudget | None: ...

    def save_budget(self, tx: TenantTransaction, budget: Budget, now: datetime) -> None: ...

    def reservations(
        self,
        tx: TenantTransaction,
        *,
        task_id: TaskId | None = None,
        budget_id: BudgetId | None = None,
        status: ReservationStatus | None = None,
    ) -> Sequence[Reservation]: ...

    def insert_reservation(self, tx: TenantTransaction, reservation: Reservation) -> None: ...

    def update_reservation(self, tx: TenantTransaction, reservation: Reservation) -> None: ...

    def ledger_rows(
        self,
        tx: TenantTransaction,
        *,
        job_id: JobId | None = None,
        task_id: TaskId | None = None,
        provider: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Sequence[CostEntry]: ...

    def job_scope(self, tx: TenantTransaction, job_id: JobId) -> JobScope: ...

    def task_job(self, tx: TenantTransaction, task_id: TaskId) -> JobId: ...

    def tenant_timezone(self, tx: TenantTransaction) -> str | None: ...

    def new_reservation_id(self) -> str: ...


def actor_kind_of(actor: str) -> ActorKind:
    if actor.startswith("usr_"):
        return ActorKind.HUMAN
    if actor.startswith("agent_"):
        return ActorKind.AGENT
    if actor.startswith("svc_"):
        return ActorKind.SERVICE
    return ActorKind.SYSTEM


def limit_micros(budget: Budget, settings: AmwSettings) -> int:
    """``limit_minor`` converted to micros (GLOSSARY section 3); unknown exponent fails closed."""
    exp = settings.finance.currency_minor_exponent.get(budget.currency)
    if exp is None or not 0 <= exp <= 6:
        raise ConfigInvalidError(
            "no minor-unit exponent configured for the budget currency",
            details={"currency": budget.currency},
        )
    return budget.limit_minor * _MICROS_PER_MINOR[exp]


def period_bounds(
    period: BudgetPeriod, now: datetime, tz_name: str | None
) -> tuple[datetime | None, datetime | None]:
    """[start, end) of the current DAY / MONTH in the tenant zone; ``(None, None)`` otherwise."""
    if period not in ROLLING_PERIODS:
        return None, None
    if not tz_name:
        raise ConfigInvalidError("DAY/MONTH budgets need the tenant time zone")
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError, ValueError:
        raise ConfigInvalidError("unknown tenant time zone", details={"tz": tz_name}) from None
    local = now.astimezone(zone)
    if period is BudgetPeriod.DAY:
        start = datetime(local.year, local.month, local.day, tzinfo=zone)
        nxt = local.date() + timedelta(days=1)
        end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=zone)
    else:
        start = datetime(local.year, local.month, 1, tzinfo=zone)
        year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
        end = datetime(year, month, 1, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


class BudgetGuardCore:
    """``BudgetGuard`` (E1 ``reserve``, E2 ``check_call`` / ``check_provider_gate``, E3
    ``after_call``, ``consume``, ``release``, ``status``) plus the audited owner actions."""

    def __init__(
        self,
        backend: BudgetBackend,
        settings: AmwSettings,
        clock: ClockLike,
        audit: AuditLog | None = None,
    ) -> None:
        self._b = backend
        self._settings = settings
        self._clock = clock
        self._audit = audit

    # ---- scope -------------------------------------------------------------------------------
    @staticmethod
    def _applies_to_job(budget: Budget, scope: JobScope) -> bool:
        match budget.scope_kind:
            case BudgetScopeKind.ORG:
                return True
            case BudgetScopeKind.WORKSPACE:
                return budget.scope_id is not None and budget.scope_id == scope.workspace_id
            case BudgetScopeKind.CHANNEL:
                return budget.scope_id is not None and budget.scope_id == scope.channel_id
            case BudgetScopeKind.PRODUCTION_TYPE:
                return (
                    budget.scope_key is not None and budget.scope_key == scope.production_type_key
                )
            case _:
                return False

    def applicable_budgets(self, tx: TenantTransaction, job_id: JobId) -> Sequence[Budget]:
        scope = self._b.job_scope(tx, job_id)
        return [s.budget for s in self._b.budgets(tx) if self._applies_to_job(s.budget, scope)]

    def _row_in_scope(self, tx: TenantTransaction, budget: Budget, row: CostEntry) -> bool:
        e = row.entry
        if budget.scope_kind is BudgetScopeKind.ORG:
            return True
        if budget.scope_kind is BudgetScopeKind.PROVIDER:
            return e.provider == budget.scope_key
        if budget.scope_kind is BudgetScopeKind.CHANNEL and e.channel_id is not None:
            return e.channel_id == budget.scope_id
        if e.job_id is None:
            return False
        return self._applies_to_job(budget, self._b.job_scope(tx, e.job_id))

    def _committed(
        self, tx: TenantTransaction, budget: Budget, job_id: JobId | None, now: datetime
    ) -> int:
        if budget.period in PER_ITEM_PERIODS and job_id is None:
            raise InputInvalidError("a PER_VIDEO / PER_JOB budget is evaluated for one job")
        start, end = period_bounds(budget.period, now, self._tz(tx, budget))
        per_item_job = job_id if budget.period in PER_ITEM_PERIODS else None
        rows = self._b.ledger_rows(
            tx,
            job_id=per_item_job,
            provider=budget.scope_key if budget.scope_kind is BudgetScopeKind.PROVIDER else None,
            since=start,
            until=end,
        )
        in_scope = [r for r in effective_rows(rows) if self._row_in_scope(tx, budget, r)]
        spend_by_task: dict[TaskId, int] = {}
        total = 0
        for row in in_scope:
            amount = amount_in(row, budget.currency)
            total += amount
            if row.entry.task_id is not None:
                spend_by_task[row.entry.task_id] = spend_by_task.get(row.entry.task_id, 0) + amount
        for hold in self._b.reservations(tx, budget_id=budget.id, status=ReservationStatus.HELD):
            if per_item_job is not None and self._b.task_job(tx, hold.task_id) != per_item_job:
                continue
            total += max(0, hold.amount_micros - spend_by_task.get(hold.task_id, 0))
        return total

    def _tz(self, tx: TenantTransaction, budget: Budget) -> str | None:
        return self._b.tenant_timezone(tx) if budget.period in ROLLING_PERIODS else None

    def _effective_state(
        self, tx: TenantTransaction, stored: StoredBudget, now: datetime
    ) -> BudgetState:
        """B6 period roll-over for DAY/MONTH: suspended in an earlier period -> ACTIVE again."""
        b = stored.budget
        if b.state is BudgetState.SUSPENDED_EXCEEDED and b.period in ROLLING_PERIODS:
            start, _ = period_bounds(b.period, now, self._tz(tx, b))
            if start is not None and stored.updated_at < start:
                reactivated = replace(b, state=BudgetState.ACTIVE)
                self._b.save_budget(tx, reactivated, now)
                self._write_audit(
                    tx, "budget.period_rolled_over", b, {"from": str(b.state), "to": "ACTIVE"}, now
                )
                return BudgetState.ACTIVE
        return b.state

    # ---- E1 ----------------------------------------------------------------------------------
    def reserve(
        self, tx: TenantTransaction, task_id: TaskId, amount_micros: int, currency: str
    ) -> ReservationOutcome:
        if amount_micros < 0:
            raise InputInvalidError("a reservation amount is >= 0")
        held = self._b.reservations(tx, task_id=task_id, status=ReservationStatus.HELD)
        if held:
            return ReservationOutcome(True, tuple(held), ())  # 09 section 3.4 step 4
        if amount_micros == 0:
            return ReservationOutcome(True, (), ())  # B4: non-paid work is never blocked
        now = self._clock.now()
        job_id = self._b.task_job(tx, task_id)
        scope = self._b.job_scope(tx, job_id)
        stored = sorted(
            (s for s in self._b.budgets(tx, lock=True) if self._applies_to_job(s.budget, scope)),
            key=lambda s: s.budget.id,
        )
        enforced = []
        refused: list[BudgetId] = []
        for s in stored:
            state = self._effective_state(tx, s, now)
            if state is BudgetState.DISABLED:
                continue
            budget = replace(s.budget, state=state)
            if budget.currency != currency:
                raise ConfigInvalidError(
                    "reservation currency differs from the budget currency",
                    details={"budget_currency": budget.currency, "currency": currency},
                )
            enforced.append(budget)
            if state is not BudgetState.ACTIVE:
                refused.append(budget.id)
                continue
            limit = limit_micros(budget, self._settings)
            committed = self._committed(tx, budget, job_id, now)
            if committed >= limit:
                self._suspend(tx, budget, committed, limit, "E1", job_id, now)
                refused.append(budget.id)
            elif limit - committed < amount_micros:
                refused.append(budget.id)
        if not enforced:
            # fail closed (09 section 3.2): a paid task with no ACTIVE applicable budget
            return ReservationOutcome(False, (), tuple(s.budget.id for s in stored))
        if refused:
            return ReservationOutcome(False, (), tuple(refused))
        made = []
        for budget in enforced:
            reservation = Reservation(
                id=self._b.new_reservation_id(),  # type: ignore[arg-type]
                budget_id=budget.id,
                task_id=task_id,
                amount_micros=amount_micros,
                currency=currency,
                status=ReservationStatus.HELD,
                released_at=None,
            )
            self._b.insert_reservation(tx, reservation)
            made.append(reservation)
        return ReservationOutcome(True, tuple(made), ())

    # ---- E2 ----------------------------------------------------------------------------------
    def check_provider_gate(self, tx: TenantTransaction, provider: str) -> None:
        now = self._clock.now()
        for s in self._b.budgets(tx):
            b = s.budget
            if (
                b.scope_kind is BudgetScopeKind.PROVIDER
                and b.scope_key == provider
                and self._effective_state(tx, s, now) is BudgetState.ACTIVE
            ):
                return
        raise BudgetExhaustedError(
            "no ACTIVE provider limit acknowledged for this provider (09 section 8.2)",
            provider=provider,
        )

    def check_call(self, tx: TenantTransaction, check: CallCheck) -> None:
        if check.estimated_cost_micros < 0:
            raise InputInvalidError("estimated_cost_micros is >= 0")
        self.check_provider_gate(tx, check.provider)
        if self._b.task_job(tx, check.task_id) != check.job_id:
            raise InputInvalidError("CallCheck task does not belong to its job")
        held = self._b.reservations(tx, task_id=check.task_id, status=ReservationStatus.HELD)
        if check.estimated_cost_micros == 0:
            return
        if not held:
            raise BudgetExhaustedError("paid call without a HELD reservation (E1 not passed)")
        spent_rows = effective_rows(self._b.ledger_rows(tx, task_id=check.task_id))
        for hold in held:
            if hold.currency != check.currency:
                raise ConfigInvalidError("call currency differs from the reservation currency")
            spent = sum(amount_in(r, hold.currency) for r in spent_rows)
            if spent + check.estimated_cost_micros > hold.amount_micros:
                raise BudgetExhaustedError(
                    "the call would exceed the task's HELD reservation (B2)",
                    provider=check.provider,
                    details={"budget_id": hold.budget_id},
                )

    # ---- E3 ----------------------------------------------------------------------------------
    def after_call(self, tx: TenantTransaction, entry: CostEntry) -> Sequence[Budget]:
        now = self._clock.now()
        job_id = entry.entry.job_id
        scope = self._b.job_scope(tx, job_id) if job_id is not None else None
        changed: list[Budget] = []
        for s in sorted(self._b.budgets(tx, lock=True), key=lambda s: s.budget.id):
            b = s.budget
            if b.scope_kind is BudgetScopeKind.PROVIDER:
                relevant = b.scope_key == entry.entry.provider
            elif scope is not None:
                relevant = self._applies_to_job(b, scope)
            else:  # a row without a job (e.g. an eval run) counts against org-wide totals only
                relevant = b.scope_kind is BudgetScopeKind.ORG and b.period not in PER_ITEM_PERIODS
            if not relevant or self._effective_state(tx, s, now) is not BudgetState.ACTIVE:
                continue
            limit = limit_micros(b, self._settings)
            committed = self._committed(tx, b, job_id, now)
            if committed >= limit:
                changed.append(self._suspend(tx, b, committed, limit, "E3", job_id, now))
        return changed

    def _suspend(
        self,
        tx: TenantTransaction,
        budget: Budget,
        committed: int,
        limit: int,
        point: str,
        job_id: JobId | None,
        now: datetime,
    ) -> Budget:
        suspended = replace(budget, state=BudgetState.SUSPENDED_EXCEEDED)
        self._b.save_budget(tx, suspended, now)
        details: dict[str, str | int | None] = {
            "from": str(budget.state),
            "to": str(BudgetState.SUSPENDED_EXCEEDED),
            "enforcement_point": point,
            "committed_micros": committed,
            "limit_micros": limit,
            "job_id": job_id,
        }
        self._write_audit(tx, "budget.suspended", budget, details, now, job_id)
        return suspended

    # ---- T08 / T11 / T14 / T19 ----------------------------------------------------------------
    def _close(
        self, tx: TenantTransaction, task_id: TaskId, status: ReservationStatus
    ) -> Sequence[Reservation]:
        now = self._clock.now()
        out = []
        for hold in self._b.reservations(tx, task_id=task_id, status=ReservationStatus.HELD):
            closed = replace(
                hold,
                status=status,
                released_at=now if status is ReservationStatus.RELEASED else None,
            )
            self._b.update_reservation(tx, closed)
            out.append(closed)
        return out

    def consume(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[Reservation]:
        return self._close(tx, task_id, ReservationStatus.CONSUMED)

    def release(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[Reservation]:
        return self._close(tx, task_id, ReservationStatus.RELEASED)

    # ---- status --------------------------------------------------------------------------------
    def status(
        self, tx: TenantTransaction, budget_id: BudgetId, job_id: JobId | None = None
    ) -> BudgetStatus:
        """``job_id`` is required for PER_VIDEO / PER_JOB budgets (their amount is per job)."""
        stored = self._b.get_budget(tx, budget_id)
        if stored is None:
            raise MissingDependencyError("budget not found")
        now = self._clock.now()
        budget = replace(stored.budget, state=self._effective_state(tx, stored, now))
        limit = limit_micros(budget, self._settings)
        committed = self._committed(tx, budget, job_id, now)
        soft = Decimal(committed) >= Decimal(limit) * budget.soft_limit_ratio
        return BudgetStatus(
            budget=budget,
            committed_micros=committed,
            remaining_micros=limit - committed,
            soft_limit_reached=soft and limit > 0,
        )

    def provider_limit_warnings(self, tx: TenantTransaction) -> list[tuple[BudgetId, BudgetId]]:
        """09 section 8.3: internal budgets whose limit is above a provider limit (same currency);
        a warning, never a block. Returns ``(internal budget, provider budget)`` pairs."""
        budgets = [s.budget for s in self._b.budgets(tx)]
        providers = [b for b in budgets if b.scope_kind is BudgetScopeKind.PROVIDER]
        out = []
        for b in budgets:
            if b.scope_kind is BudgetScopeKind.PROVIDER or b.state is BudgetState.DISABLED:
                continue
            for p in providers:
                if p.currency == b.currency and b.limit_minor > p.limit_minor:
                    out.append((b.id, p.id))
        return out

    # ---- owner / Finance actions (B6: never automatic) ----------------------------------------
    def _require_human(self, tx: TenantTransaction) -> ActorRef:
        actor = tx.context.actor
        if actor_kind_of(actor) is not ActorKind.HUMAN:
            raise PermissionDeniedError("budget limits are changed only by a human (rule 8)")
        return actor

    def set_limit(
        self, tx: TenantTransaction, budget_id: BudgetId, limit_minor: int, reason: str
    ) -> Budget:
        """Owner/Finance raises or lowers ``limit_minor``; a suspended budget becomes ACTIVE only
        if the new limit covers what is committed. Audited with before/after."""
        self._require_human(tx)
        if limit_minor < 0 or not reason.strip():
            raise InputInvalidError("limit_minor >= 0 and a reason are required")
        stored = self._b.get_budget(tx, budget_id, lock=True)
        if stored is None:
            raise MissingDependencyError("budget not found")
        now = self._clock.now()
        before = stored.budget
        after = replace(before, limit_minor=limit_minor)
        if (
            before.state is BudgetState.SUSPENDED_EXCEEDED
            and before.period not in PER_ITEM_PERIODS
            and self._committed(tx, after, None, now) < limit_micros(after, self._settings)
        ):
            after = replace(after, state=BudgetState.ACTIVE)
        self._b.save_budget(tx, after, now)
        self._write_audit(
            tx,
            "budget.limit_changed",
            before,
            {
                "before_limit_minor": before.limit_minor,
                "after_limit_minor": after.limit_minor,
                "before_state": str(before.state),
                "after_state": str(after.state),
                "reason": reason.strip(),
            },
            now,
        )
        return after

    def release_suspension(self, tx: TenantTransaction, budget_id: BudgetId, reason: str) -> Budget:
        """Owner/Finance releases a ``SUSPENDED_EXCEEDED`` budget (B6, audited); resume of the
        waiting tasks then re-runs E1 through T15."""
        self._require_human(tx)
        if not reason.strip():
            raise InputInvalidError("a reason is required")
        stored = self._b.get_budget(tx, budget_id, lock=True)
        if stored is None:
            raise MissingDependencyError("budget not found")
        if stored.budget.state is not BudgetState.SUSPENDED_EXCEEDED:
            raise InputInvalidError("budget is not suspended")
        now = self._clock.now()
        after = replace(stored.budget, state=BudgetState.ACTIVE)
        self._b.save_budget(tx, after, now)
        self._write_audit(
            tx,
            "budget.released",
            stored.budget,
            {"from": "SUSPENDED_EXCEEDED", "to": "ACTIVE", "reason": reason.strip()},
            now,
        )
        return after

    def _write_audit(
        self,
        tx: TenantTransaction,
        action: str,
        budget: Budget,
        details: dict[str, str | int | None],
        now: datetime,
        job_id: JobId | None = None,
    ) -> None:
        if self._audit is None:
            return
        actor = tx.context.actor
        self._audit.append(
            tx,
            NewAuditEntry(
                actor_kind=actor_kind_of(actor),
                actor_ref=actor,
                authority=AUTHORITY_HUMAN
                if actor_kind_of(actor) is ActorKind.HUMAN
                else AUTHORITY_SYSTEM,
                action=action,
                target_kind="BUDGET",
                target_id=budget.id,
                occurred_at=now,
                job_id=job_id,
                correlation_id=tx.context.correlation_id,
                details={k: v for k, v in details.items() if v is not None},
            ),
        )


class ClockLike(Protocol):
    def now(self) -> datetime: ...


def budgets_by_id(items: Iterable[StoredBudget]) -> dict[BudgetId, StoredBudget]:
    return {s.budget.id: s for s in items}
