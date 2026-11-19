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

Cost is never under-counted (ADR-007 2.8, D10). Every ``before`` registers a PENDING hold of the
worst case. ``after`` settles it with the real cost. A failure is settled by ``failed``: a PROVEN
non-delivery (connect failure, 4xx rejection) releases the hold; anything else (timeout, 5xx, broken
connection, unparsable 2xx) is an UNKNOWN outcome and is kept fail-closed: the worst case is
recorded as an ESTIMATE row (``BudgetCallGuard``) or counted (``CapOnlyCallGuard``) until the owner
reconciles it against the provider's own usage (``reconcile``: a VERIFIED row that supersedes the
estimate, 09 section 6). Each paid attempt of one idempotency key has its OWN ledger key (attempt 0
is the key itself, attempt n a derived key), so a retry after a billed-but-unusable response is
recorded as a second charge instead of replaying the first as a no-op.

``CapOnlyCallGuard`` has no database: it enforces the same cap over an in-process counter for the
live smoke script, which has no job.
"""

import hashlib
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Protocol, final, runtime_checkable

from amw_adapters.common import CallUsage
from amw_adapters.real.authorisation import (
    ProviderAuthorisation,
    VerifiedGrant,
    verify_authorisation,
)
from amw_core.cost.ledger import amount_in, effective_rows
from amw_core.enums import CostFigureKind, CostOperation
from amw_core.errors import BudgetExhaustedError, ConfigInvalidError, InputInvalidError
from amw_core.exec_context import ExecContext
from amw_core.ids import ExecutorId, idempotency_key_of
from amw_core.interfaces.budget_guard import BudgetGuard, CallCheck
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostEntry, CostLedger, NewCostEntry
from amw_core.interfaces.tenancy_context import TenancyContext


@dataclass(frozen=True, slots=True)
class PlannedCall:
    """What the adapter is about to send: the worst-case cost in integer micros."""

    provider: str
    operation: str
    worst_case_micros: int
    currency: str
    idempotency_key: str
    model: str | None = None
    price_ref: str | None = None


@runtime_checkable
class CallGuard(Protocol):
    @property
    def authorisation(self) -> ProviderAuthorisation: ...

    def check_authorisation(self, *, provider: str, currency: str) -> VerifiedGrant: ...

    def before(self, call: PlannedCall) -> None:
        """Verify the token, refuse over the cap, hold the worst case (before any request)."""
        ...

    def after(self, usage: CallUsage) -> None:
        """Settle the hold with the real cost of a response (integer micros, ESTIMATE)."""
        ...

    def failed(self, idempotency_key: str, *, delivered: bool | None) -> None:
        """Settle the hold of a failed call: ``delivered=False`` is PROVEN non-delivery (release);
        anything else keeps the worst case (unknown outcome, fail closed). No-op if nothing is
        pending for the key."""
        ...


def delivery_of(error: BaseException) -> bool | None:
    """``False`` only when the HTTP layer proved the request was not delivered or was rejected."""
    details = getattr(error, "details", None)
    if isinstance(details, dict) and details.get("delivery") == "not_delivered":
        return False
    return None


def require_guard(guard: CallGuard, *, provider: str, currency: str) -> CallGuard:
    """A real adapter accepts only a guard of one of the two concrete classes below (no duck
    typing, no subclass) whose preflight authorisation verifies NOW for ITS provider and ITS price
    currency (``CONFIG_INVALID`` otherwise). Every call verifies it again."""
    if type(guard) not in (BudgetCallGuard, CapOnlyCallGuard):
        raise ConfigInvalidError("a real adapter needs a BudgetCallGuard or CapOnlyCallGuard")
    guard.check_authorisation(provider=provider, currency=currency)
    return guard


def attempt_key(base: str, attempt: int) -> str:
    """Ledger key of paid attempt ``attempt`` of one idempotency key (valid ``idk_`` + 64 hex)."""
    if attempt == 0:
        return base
    digest = hashlib.sha256(f"{base}|attempt|{attempt}".encode()).hexdigest()
    return f"idk_{digest}"


def _now() -> datetime:
    return datetime.now(UTC)


def _check_planned(grant: VerifiedGrant, call: PlannedCall) -> None:
    if call.provider != grant.provider or call.currency != grant.currency:
        raise ConfigInvalidError("call is outside the preflight authorisation")
    if call.worst_case_micros < 0:
        raise InputInvalidError("worst_case_micros is >= 0")


def _refuse_cap(
    call: PlannedCall, spent: int, held: int, cap: int, extra: dict[str, object]
) -> None:
    if spent + held + call.worst_case_micros > cap:
        raise BudgetExhaustedError(
            "the call could push the video above its hard cap (refused before the request)",
            provider=call.provider,
            details={
                "spent_micros": spent,
                "held_micros": held,
                "worst_case_micros": call.worst_case_micros,
                "per_video_cap_micros": cap,
                **extra,
            },
        )


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


@dataclass(frozen=True, slots=True)
class _Pending:
    call: PlannedCall
    ledger_key: str


_UNKNOWN_OP_PREFIX: Final = "held"


@final
class BudgetCallGuard:
    def __init__(
        self,
        authorisation: ProviderAuthorisation,
        *,
        budget: BudgetGuard,
        ledger: CostLedger,
        tenancy: TenancyContext,
        clock: Clock,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._auth = authorisation
        self._budget, self._ledger, self._tenancy, self._clock = budget, ledger, tenancy, clock
        self._now = now
        self._lock = threading.Lock()
        self._pending: dict[tuple[str, str], _Pending] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("BudgetCallGuard cannot be subclassed")

    @property
    def authorisation(self) -> ProviderAuthorisation:
        return self._auth

    def check_authorisation(self, *, provider: str, currency: str) -> VerifiedGrant:
        return verify_authorisation(self._auth, self._now(), provider=provider, currency=currency)

    @staticmethod
    def _scope() -> CallScope:
        scope = _SCOPE.get()
        if scope is None:
            raise ConfigInvalidError("a real provider call needs a call_scope (job and task)")
        return scope

    def _grant(self, provider: str, currency: str, ctx: ExecContext) -> VerifiedGrant:
        grant = self.check_authorisation(provider=provider, currency=currency)
        if grant.org_id != ctx.org_id or grant.job_id != ctx.job_id:
            raise ConfigInvalidError(
                "the preflight authorisation is bound to another org or job",
                details={"job_id": ctx.job_id},
            )
        return grant

    def before(self, call: PlannedCall) -> None:
        ctx = self._scope().ctx
        grant = self._grant(call.provider, call.currency, ctx)
        _check_planned(grant, call)
        with self._tenancy.transaction(ctx.tenant) as tx, self._lock:
            rows = list(self._ledger.for_job(tx, ctx.job_id))
            spent = sum(amount_in(row, grant.currency) for row in effective_rows(rows))
            held = sum(
                p.call.worst_case_micros
                for (job, _k), p in self._pending.items()
                if job == ctx.job_id
            )
            _refuse_cap(call, spent, held, grant.per_video_cap_micros, {"job_id": ctx.job_id})
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
            taken = {str(r.entry.idempotency_key) for r in rows if r.entry.idempotency_key}
            taken |= {p.ledger_key for p in self._pending.values()}
            attempt = 0
            while attempt_key(call.idempotency_key, attempt) in taken:
                attempt += 1
            self._pending[(ctx.job_id, call.idempotency_key)] = _Pending(
                call, attempt_key(call.idempotency_key, attempt)
            )

    def after(self, usage: CallUsage) -> None:
        scope = self._scope()
        ctx = scope.ctx
        self._grant(usage.provider, usage.currency, ctx)
        with self._lock:
            pending = self._pending.pop((ctx.job_id, usage.idempotency_key), None)
        ledger_key = pending.ledger_key if pending else usage.idempotency_key
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
                    idempotency_key=idempotency_key_of(ledger_key),
                ),
            )
            self._budget.after_call(tx, entry)

    def failed(self, idempotency_key: str, *, delivered: bool | None) -> None:
        scope = self._scope()
        ctx = scope.ctx
        with self._lock:
            pending = self._pending.pop((ctx.job_id, idempotency_key), None)
        if pending is None or delivered is False:
            return  # nothing held, or PROVEN non-delivery: the hold is released
        call = pending.call
        with self._tenancy.transaction(ctx.tenant) as tx:
            entry = self._ledger.record(
                tx,
                NewCostEntry(
                    provider=call.provider,
                    operation=CostOperation(call.operation),
                    amount_micros=call.worst_case_micros,
                    currency=call.currency,
                    figure_kind=CostFigureKind.ESTIMATE,
                    occurred_at=self._clock.now(),
                    job_id=ctx.job_id,
                    task_id=ctx.task_id,
                    attempt_id=ctx.attempt_id,
                    channel_id=ctx.channel_id,
                    agent_id=scope.agent_id,
                    model=call.model,
                    price_ref=call.price_ref,
                    idempotency_key=idempotency_key_of(pending.ledger_key),
                ),
            )
            self._budget.after_call(tx, entry)

    def reconcile(self, held: CostEntry, *, actual_micros: int, verification_ref: str) -> CostEntry:
        """Owner reconciliation of an unknown-outcome hold with the provider's own usage: a
        VERIFIED row pointing at the held ESTIMATE (amount 0 if the provider billed nothing)."""
        ctx = self._scope().ctx
        e = held.entry
        with self._tenancy.transaction(ctx.tenant) as tx:
            return self._ledger.record(
                tx,
                NewCostEntry(
                    provider=e.provider, operation=e.operation, amount_micros=actual_micros,
                    currency=e.currency, figure_kind=CostFigureKind.VERIFIED,
                    occurred_at=self._clock.now(), job_id=e.job_id, task_id=e.task_id,
                    attempt_id=e.attempt_id, channel_id=e.channel_id, model=e.model,
                    price_ref=e.price_ref, estimate_entry_id=held.id,
                    verification_ref=verification_ref,
                    idempotency_key=e.idempotency_key,
                ),
            )  # fmt: skip


@final
class CapOnlyCallGuard:
    """The per-video hard stop over an in-process counter (no database, no job): for the live
    smoke script. Thread-safe; ``spent_micros`` is the sum of the recorded real costs and
    ``held_micros`` the worst case of calls in flight or of unknown outcome (until reconciled)."""

    def __init__(
        self,
        authorisation: ProviderAuthorisation,
        *,
        spent_micros: int = 0,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._auth = authorisation
        self._spent = spent_micros
        self._now = now
        self._lock = threading.Lock()
        self._pending: dict[str, int] = {}
        self._unknown: dict[str, int] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("CapOnlyCallGuard cannot be subclassed")

    @property
    def authorisation(self) -> ProviderAuthorisation:
        return self._auth

    @property
    def spent_micros(self) -> int:
        return self._spent

    @property
    def held_micros(self) -> int:
        return sum(self._pending.values()) + sum(self._unknown.values())

    def check_authorisation(self, *, provider: str, currency: str) -> VerifiedGrant:
        return verify_authorisation(self._auth, self._now(), provider=provider, currency=currency)

    def before(self, call: PlannedCall) -> None:
        grant = self.check_authorisation(provider=call.provider, currency=call.currency)
        _check_planned(grant, call)
        with self._lock:
            _refuse_cap(call, self._spent, self.held_micros, grant.per_video_cap_micros, {})
            self._pending[call.idempotency_key] = call.worst_case_micros

    def after(self, usage: CallUsage) -> None:
        self.check_authorisation(provider=usage.provider, currency=usage.currency)
        with self._lock:
            self._pending.pop(usage.idempotency_key, None)
            self._spent += usage.amount_micros

    def failed(self, idempotency_key: str, *, delivered: bool | None) -> None:
        with self._lock:
            held = self._pending.pop(idempotency_key, None)
            if held is not None and delivered is not False:
                n = sum(1 for k in self._unknown if k.startswith(idempotency_key))
                self._unknown[f"{idempotency_key}#{n}"] = held

    def reconcile(self, idempotency_key: str, *, actual_micros: int) -> None:
        """Owner reconciliation of every unknown-outcome hold of this key."""
        with self._lock:
            for k in [k for k in self._unknown if k.startswith(idempotency_key)]:
                del self._unknown[k]
            self._spent += actual_micros
