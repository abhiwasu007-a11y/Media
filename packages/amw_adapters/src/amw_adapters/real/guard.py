"""Call guard: the E2 refusal BEFORE a paid request and the integer-micros record AFTER it.

Every real adapter calls ``guard.before(...)`` with the worst-case cost of the request it is about
to send, and ``guard.after(usage)`` with the real cost of a response that arrived (billed
refusals and unusable audio included). The adapter has no other way to reach the network, so a
real call cannot skip the guard.

``BudgetCallGuard`` runs on the merged L1b services: the per-video hard stop (the cap the
preflight verified, owner ceiling USD 5 per video, D10) over the job's effective ledger spend,
then ``BudgetGuard.check_call`` (provider gate, task reservation, CCR-107 job caps); after the
call ``CostLedger.record`` + ``BudgetGuard.after_call`` (E3). The ledger replays a write with the
same idempotency key and figure kind as a no-op, so an agent that records the same call again
does not count it twice. The job comes from ``call_scope``; a call outside a scope is refused
(fail closed; a ``ContextVar`` is not inherited by threads started elsewhere).

``CapOnlyCallGuard`` has no database: it enforces the same cap over an in-process counter for the
live smoke script, which has no job.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from amw_adapters.common import CallUsage
from amw_adapters.real.authorisation import ProviderAuthorisation
from amw_core.cost.ledger import amount_in, effective_rows
from amw_core.enums import CostFigureKind
from amw_core.errors import BudgetExhaustedError, ConfigInvalidError, InputInvalidError
from amw_core.exec_context import ExecContext
from amw_core.ids import ExecutorId, idempotency_key_of
from amw_core.interfaces.budget_guard import BudgetGuard, CallCheck
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostLedger, NewCostEntry
from amw_core.interfaces.tenancy_context import TenancyContext


@dataclass(frozen=True, slots=True)
class PlannedCall:
    """What the adapter is about to send: the worst-case cost in integer micros."""

    provider: str
    operation: str
    worst_case_micros: int
    currency: str
    idempotency_key: str


@runtime_checkable
class CallGuard(Protocol):
    @property
    def authorisation(self) -> ProviderAuthorisation: ...

    def before(self, call: PlannedCall) -> None:
        """Raise ``BudgetExhaustedError`` (or another typed error) before any request."""
        ...

    def after(self, usage: CallUsage) -> None:
        """Record the real cost of a response (integer micros, ESTIMATE until verified)."""
        ...


def require_guard(guard: CallGuard, *, provider: str, currency: str) -> CallGuard:
    """A real adapter accepts only a guard bound to a preflight authorisation for ITS provider
    and ITS price currency (``CONFIG_INVALID`` otherwise)."""
    auth = getattr(guard, "authorisation", None)
    if not isinstance(auth, ProviderAuthorisation):
        raise ConfigInvalidError("a real adapter needs a guard bound to a preflight authorisation")
    if auth.provider != provider or auth.currency != currency:
        raise ConfigInvalidError(
            "the preflight authorisation is for another provider or currency",
            details={"provider": provider},
        )
    return guard


def _check_planned(auth: ProviderAuthorisation, call: PlannedCall) -> None:
    if call.provider != auth.provider or call.currency != auth.currency:
        raise ConfigInvalidError("call is outside the preflight authorisation")
    if call.worst_case_micros < 0:
        raise InputInvalidError("worst_case_micros is >= 0")


@dataclass(frozen=True, slots=True)
class CallScope:
    ctx: ExecContext
    agent_id: ExecutorId | None = None


_SCOPE: ContextVar[CallScope | None] = ContextVar("amw_real_call_scope", default=None)


@contextmanager
def call_scope(ctx: ExecContext, agent_id: ExecutorId | None = None) -> Iterator[None]:
    """Names the job / task / tenant the real calls inside the block are charged to."""
    token = _SCOPE.set(CallScope(ctx, agent_id))
    try:
        yield
    finally:
        _SCOPE.reset(token)


class BudgetCallGuard:
    def __init__(
        self,
        authorisation: ProviderAuthorisation,
        *,
        budget: BudgetGuard,
        ledger: CostLedger,
        tenancy: TenancyContext,
        clock: Clock,
    ) -> None:
        self._auth = authorisation
        self._budget, self._ledger, self._tenancy, self._clock = budget, ledger, tenancy, clock

    @property
    def authorisation(self) -> ProviderAuthorisation:
        return self._auth

    @staticmethod
    def _scope() -> CallScope:
        scope = _SCOPE.get()
        if scope is None:
            raise ConfigInvalidError("a real provider call needs a call_scope (job and task)")
        return scope

    def before(self, call: PlannedCall) -> None:
        _check_planned(self._auth, call)
        ctx = self._scope().ctx
        with self._tenancy.transaction(ctx.tenant) as tx:
            spent = sum(
                amount_in(row, self._auth.currency)
                for row in effective_rows(self._ledger.for_job(tx, ctx.job_id))
            )
            if spent + call.worst_case_micros > self._auth.per_video_cap_micros:
                raise BudgetExhaustedError(
                    "the call could push the video above its hard cap (refused before the request)",
                    provider=call.provider,
                    details={
                        "job_id": ctx.job_id,
                        "spent_micros": spent,
                        "worst_case_micros": call.worst_case_micros,
                        "per_video_cap_micros": self._auth.per_video_cap_micros,
                    },
                )
            self._budget.check_call(
                tx,
                CallCheck(
                    task_id=ctx.task_id,
                    job_id=ctx.job_id,
                    provider=call.provider,
                    estimated_cost_micros=call.worst_case_micros,
                    currency=call.currency,
                ),
            )

    def after(self, usage: CallUsage) -> None:
        if usage.provider != self._auth.provider or usage.currency != self._auth.currency:
            raise ConfigInvalidError("usage is outside the preflight authorisation")
        scope = self._scope()
        ctx = scope.ctx
        with self._tenancy.transaction(ctx.tenant) as tx:
            entry = self._ledger.record(
                tx,
                NewCostEntry(
                    provider=usage.provider,
                    operation=usage.operation,
                    amount_micros=usage.amount_micros,
                    currency=usage.currency,
                    figure_kind=CostFigureKind.ESTIMATE,
                    occurred_at=self._clock.now(),
                    job_id=ctx.job_id,
                    task_id=ctx.task_id,
                    attempt_id=ctx.attempt_id,
                    channel_id=ctx.channel_id,
                    agent_id=scope.agent_id,
                    model=usage.model,
                    billing_mode=usage.billing_mode,
                    tokens_in=usage.tokens_in,
                    tokens_out=usage.tokens_out,
                    tokens_cached_in=usage.tokens_cached_in,
                    tokens_cache_write_in=usage.tokens_cache_write_in,
                    chars_in=usage.chars_in,
                    language=usage.language,
                    units=None if usage.units is None else Decimal(usage.units),
                    unit_kind=usage.unit_kind,
                    price_ref=usage.price_ref,
                    idempotency_key=idempotency_key_of(usage.idempotency_key),
                ),
            )
            self._budget.after_call(tx, entry)


class CapOnlyCallGuard:
    """The per-video hard stop over an in-process counter (no database, no job): for the live
    smoke script. Thread-safe; ``spent_micros`` is the sum of the recorded real costs."""

    def __init__(self, authorisation: ProviderAuthorisation, *, spent_micros: int = 0) -> None:
        self._auth = authorisation
        self._spent = spent_micros
        self._lock = threading.Lock()

    @property
    def authorisation(self) -> ProviderAuthorisation:
        return self._auth

    @property
    def spent_micros(self) -> int:
        return self._spent

    def before(self, call: PlannedCall) -> None:
        _check_planned(self._auth, call)
        with self._lock:
            if self._spent + call.worst_case_micros > self._auth.per_video_cap_micros:
                raise BudgetExhaustedError(
                    "the call could push the run above its hard cap (refused before the request)",
                    provider=call.provider,
                    details={
                        "spent_micros": self._spent,
                        "worst_case_micros": call.worst_case_micros,
                        "per_video_cap_micros": self._auth.per_video_cap_micros,
                    },
                )

    def after(self, usage: CallUsage) -> None:
        with self._lock:
            self._spent += usage.amount_micros
