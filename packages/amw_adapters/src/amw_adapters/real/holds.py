"""Owner runbook support: list and reconcile the held calls of a job (PROVIDERS.md section 5).

A HELD CALL is the ledger row ``BudgetCallGuard.failed`` writes when a paid request ended with an
UNKNOWN outcome (timeout, 5xx, broken connection, unparsable 2xx): an ESTIMATE of the worst case,
no token / character / unit measurement, and no VERIFIED partner yet. It counts against the
per-video cap, so until the owner reconciles it against the provider's own usage figure the video
stays blocked at the cap. Reconciling appends a VERIFIED row (09 section 6) that supersedes the
estimate: ``actual_micros = 0`` when the provider billed nothing, else the billed amount.

``list_held`` and ``reconcile_held`` take the tenancy, so they run on the memory services in tests
and on PostgreSQL through ``scripts/list_held_calls.py`` / ``scripts/reconcile_held_call.py``.
No key, no network: the owner reads the amount in the provider's console.
"""

import argparse
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from amw_core.cost.ledger import effective_rows
from amw_core.enums import CostFigureKind
from amw_core.errors import AmwError, InputInvalidError
from amw_core.ids import COST_ENTRY, JOB, ORG, ActorRef, CostEntryId, JobId
from amw_core.interfaces.cost_ledger import CostEntry, CostLedger, NewCostEntry
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext, TenantTransaction

DEFAULT_DSN_ENV = "AMW_DATABASE_URL"
DEFAULT_ROLE = "amw_app"
DEFAULT_OPERATOR = "sys_operator"


def is_hold_row(entry: NewCostEntry) -> bool:
    """The shape ``BudgetCallGuard.failed`` writes: a paid ESTIMATE that carries no measurement
    (a settled call always has token counts, characters or units)."""
    return (
        entry.figure_kind is CostFigureKind.ESTIMATE
        and entry.amount_micros > 0
        and entry.idempotency_key is not None
        and entry.tokens_in is None
        and entry.tokens_out is None
        and entry.tokens_cached_in is None
        and entry.tokens_cache_write_in is None
        and entry.chars_in is None
        and entry.units is None
    )


@dataclass(frozen=True, slots=True)
class HeldCall:
    entry_id: CostEntryId
    job_id: JobId | None
    provider: str
    operation: str
    model: str | None
    amount_micros: int
    currency: str
    occurred_at: datetime
    idempotency_key: str


def held_calls(rows: Sequence[CostEntry]) -> list[HeldCall]:
    """The unreconciled holds among ``rows`` (a job's ledger rows), oldest first."""
    live = {r.id for r in effective_rows(rows) if r.entry.figure_kind is CostFigureKind.ESTIMATE}
    return [
        HeldCall(
            entry_id=r.id,
            job_id=r.entry.job_id,
            provider=r.entry.provider,
            operation=str(r.entry.operation),
            model=r.entry.model,
            amount_micros=r.entry.amount_micros,
            currency=r.entry.currency,
            occurred_at=r.entry.occurred_at,
            idempotency_key=str(r.entry.idempotency_key),
        )
        for r in sorted(rows, key=lambda x: x.entry.occurred_at)
        if r.id in live and is_hold_row(r.entry)
    ]


def list_held(
    ledger: CostLedger, tenancy: TenancyContext, tenant: TenantContext, job_id: JobId
) -> list[HeldCall]:
    with tenancy.transaction(tenant) as tx:
        return held_calls(list(ledger.for_job(tx, job_id)))


def verified_row_for(
    held: CostEntry, *, actual_micros: int, verification_ref: str, occurred_at: datetime
) -> NewCostEntry:
    """The VERIFIED row that supersedes the held ESTIMATE ``held`` (same keys, same task)."""
    if not is_hold_row(held.entry):
        raise InputInvalidError(
            "that ledger row is not a held call (it is a settled or verified row)"
        )
    if isinstance(actual_micros, bool) or not isinstance(actual_micros, int) or actual_micros < 0:
        raise InputInvalidError(
            "actual_micros is an integer >= 0 (0 = the provider billed nothing)"
        )
    if not verification_ref.strip():
        raise InputInvalidError("verification_ref is required (where the owner read the figure)")
    e = held.entry
    return NewCostEntry(
        provider=e.provider, operation=e.operation, amount_micros=actual_micros,
        currency=e.currency, figure_kind=CostFigureKind.VERIFIED, occurred_at=occurred_at,
        job_id=e.job_id, task_id=e.task_id, attempt_id=e.attempt_id, channel_id=e.channel_id,
        model=e.model, price_ref=e.price_ref, estimate_entry_id=held.id,
        verification_ref=verification_ref.strip(), idempotency_key=e.idempotency_key,
    )  # fmt: skip


def _require_open(ledger: CostLedger, tx: TenantTransaction, held: CostEntry) -> None:
    if held.entry.job_id is None:
        return
    if any(r.entry.estimate_entry_id == held.id for r in ledger.for_job(tx, held.entry.job_id)):
        raise InputInvalidError("that held call is already reconciled (it has its VERIFIED row)")


def reconcile_held(
    ledger: CostLedger,
    tenancy: TenancyContext,
    tenant: TenantContext,
    entry_id: CostEntryId,
    *,
    actual_micros: int,
    verification_ref: str,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CostEntry:
    """Append the VERIFIED row for the held call ``entry_id``. A second reconcile of the same
    hold is refused (``INPUT.INVALID``: it already has its VERIFIED row)."""
    with tenancy.transaction(tenant) as tx:
        held = ledger.get(tx, entry_id)
        if held is None:
            raise InputInvalidError("no such ledger row in this organisation")
        _require_open(ledger, tx, held)
        row = verified_row_for(
            held, actual_micros=actual_micros, verification_ref=verification_ref, occurred_at=now()
        )
        return ledger.record(tx, row)


# ---- command-line entry points (thin scripts call these) ---------------------------------------


def _tenant(org_id: str, operator: str) -> TenantContext:
    return TenantContext(ORG.validate(org_id), ActorRef(operator))


def _open_pg(dsn_env: str, role: str, environ: dict[str, str]) -> tuple[CostLedger, TenancyContext]:
    from amw_core.cost.pg import PgCostLedger
    from amw_core.tenancy import PgTenancy, dsn_connection_factory

    dsn = environ.get(dsn_env)
    if not dsn:
        raise InputInvalidError(f"environment variable {dsn_env} (database connection) is not set")
    return PgCostLedger(), PgTenancy(dsn_connection_factory(dsn, role=role))


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--org-id", required=True, help="organisation id (org_...)")
    parser.add_argument(
        "--dsn-env", default=DEFAULT_DSN_ENV, help="NAME of the env var with the DSN"
    )
    parser.add_argument("--role", default=DEFAULT_ROLE)
    parser.add_argument(
        "--operator", default=DEFAULT_OPERATOR, help="actor reference of the operator"
    )


Services = tuple[CostLedger, TenancyContext]


def list_main(
    argv: Sequence[str] | None = None,
    *,
    services: Services | None = None,
    out: Callable[[str], None] = print,
    environ: dict[str, str] | None = None,
) -> int:
    """``scripts/list_held_calls.py``: exit 0 (listed, even if none), 2 refused (bad input)."""
    parser = argparse.ArgumentParser(description="List the unreconciled held calls of a job.")
    _common(parser)
    parser.add_argument("--job-id", required=True, help="job id (job_...)")
    args = parser.parse_args(argv)
    try:
        ledger, tenancy = services or _open_pg(args.dsn_env, args.role, dict(environ or os.environ))
        held = list_held(
            ledger, tenancy, _tenant(args.org_id, args.operator), JOB.validate(args.job_id)
        )
    except (AmwError, ValueError) as exc:
        out(f"refused: {exc}")
        return 2
    if not held:
        out("no held calls")
        return 0
    out("entry_id | provider | operation | model | amount_micros | currency | recorded_at | key")
    for h in held:
        out(
            f"{h.entry_id} | {h.provider} | {h.operation} | {h.model or '-'} | "
            f"{h.amount_micros} | {h.currency} | {h.occurred_at.isoformat()} | {h.idempotency_key}"
        )
    out(f"{len(held)} held call(s), {sum(h.amount_micros for h in held)} micros held")
    return 0


def reconcile_main(
    argv: Sequence[str] | None = None,
    *,
    services: Services | None = None,
    out: Callable[[str], None] = print,
    environ: dict[str, str] | None = None,
) -> int:
    """``scripts/reconcile_held_call.py``: prints what it would write; writes only with
    ``--apply``. Exit 0 ok, 2 refused (bad input, not a held call, already reconciled)."""
    parser = argparse.ArgumentParser(
        description="Reconcile one held call with the provider's usage."
    )
    _common(parser)
    parser.add_argument("--entry-id", required=True, help="entry_id printed by list_held_calls")
    parser.add_argument("--actual-micros", required=True, type=int, help="billed amount, 0 if none")
    parser.add_argument("--verification-ref", required=True, help="where the figure was read")
    parser.add_argument("--apply", action="store_true", help="write the VERIFIED row")
    args = parser.parse_args(argv)
    try:
        ledger, tenancy = services or _open_pg(args.dsn_env, args.role, dict(environ or os.environ))
        tenant = _tenant(args.org_id, args.operator)
        entry_id = COST_ENTRY.validate(args.entry_id)
        with tenancy.transaction(tenant) as tx:
            held = ledger.get(tx, entry_id)
            if held is not None:
                _require_open(ledger, tx, held)
        if held is None:
            raise InputInvalidError("no such ledger row in this organisation")
        row = verified_row_for(
            held, actual_micros=args.actual_micros, verification_ref=args.verification_ref,
            occurred_at=datetime.now(UTC),
        )  # fmt: skip
        if row.amount_micros > held.entry.amount_micros:
            out(
                f"warning: actual {row.amount_micros} is ABOVE the held worst case "
                f"{held.entry.amount_micros}; check the figure"
            )
        out(
            f"{'applying' if args.apply else 'dry run'}: {held.entry.provider} {entry_id} "
            f"held {held.entry.amount_micros} -> verified {row.amount_micros} {row.currency}"
        )
        if not args.apply:
            out("nothing written; repeat with --apply to record it")
            return 0
        reconcile_held(
            ledger, tenancy, tenant, entry_id,
            actual_micros=args.actual_micros, verification_ref=args.verification_ref,
        )  # fmt: skip
    except (AmwError, ValueError) as exc:
        out(f"refused: {exc}")
        return 2
    out("recorded: the hold is replaced by the VERIFIED row")
    return 0
