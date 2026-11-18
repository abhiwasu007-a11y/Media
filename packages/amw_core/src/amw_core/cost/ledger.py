"""Cost ledger rules (04 section 5.14; 09 sections 3.3, 5, 6) and the in-memory ledger.

Validation (fail closed, 09 section 13): ``amount_micros >= 0``; currency is 3 upper-case letters;
a paid ``ESTIMATE`` names its ``price_ref``; a ``VERIFIED`` row names its ``verification_ref``
and, when it has one, an ``ESTIMATE`` of the same tenant (at most one ``VERIFIED`` per estimate);
an FX rate comes with its source; ``quota_units`` rows carry no money (24 section 6).

Replay: a write whose ``(idempotency_key, figure_kind)`` already exists returns the stored row; the
same key with different content is ``IdempotencyConflictError``.
"""

import re
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal

from amw_core.enums import CostFigureKind, CostUnitKind
from amw_core.errors import ConfigInvalidError, IdempotencyConflictError, InputInvalidError
from amw_core.ids import COST_ENTRY, CostEntryId, JobId, OrgId, TaskId, idempotency_key_of
from amw_core.interfaces.cost_ledger import CostEntry, CostTotals, NewCostEntry
from amw_core.interfaces.tenancy_context import TenantTransaction

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def validate_new_entry(entry: NewCostEntry) -> None:
    if isinstance(entry.amount_micros, bool) or not isinstance(entry.amount_micros, int):
        raise InputInvalidError("amount_micros must be an integer (money is never a float)")
    if entry.amount_micros < 0:
        raise ConfigInvalidError("amount_micros must be >= 0 (04 section 5.14)")
    if not _CURRENCY_RE.fullmatch(entry.currency):
        raise InputInvalidError("currency must be an ISO 4217 code (3 upper-case letters)")
    if entry.occurred_at.tzinfo is None:
        raise InputInvalidError("occurred_at must be timezone-aware")
    if not entry.provider:
        raise InputInvalidError("provider is required")
    for name in (
        "tokens_in",
        "tokens_out",
        "tokens_cached_in",
        "tokens_cache_write_in",
        "chars_in",
    ):
        value = getattr(entry, name)
        if value is not None and value < 0:
            raise InputInvalidError(f"{name} must be >= 0")
    if (entry.units is None) != (entry.unit_kind is None):
        raise InputInvalidError("units and unit_kind go together")
    if entry.units is not None and entry.units < 0:
        raise InputInvalidError("units must be >= 0")
    if entry.unit_kind is CostUnitKind.QUOTA_UNITS and entry.amount_micros != 0:
        raise InputInvalidError("quota_units rows carry amount_micros = 0 (24 section 6)")
    if entry.fx_rate is not None:
        if entry.fx_rate <= 0:
            raise ConfigInvalidError("fx_rate must be positive")
        if not entry.fx_source:
            raise ConfigInvalidError("an fx_rate needs its fx_source (GLOSSARY section 3)")
    if entry.figure_kind is CostFigureKind.ESTIMATE:
        if entry.amount_micros > 0 and not entry.price_ref:
            raise ConfigInvalidError("a paid ESTIMATE needs its price_ref (no price, no call)")
        if entry.estimate_entry_id is not None or entry.verification_ref is not None:
            raise InputInvalidError("only VERIFIED rows carry estimate_entry_id / verification_ref")
    else:
        if not entry.verification_ref:
            raise InputInvalidError("a VERIFIED row needs its verification_ref (09 section 6)")
    if entry.idempotency_key is not None:
        idempotency_key_of(entry.idempotency_key)


def same_content(a: NewCostEntry, b: NewCostEntry) -> bool:
    """Replay comparison: every field except ``occurred_at`` (a retried write may re-stamp it)."""
    return all(
        getattr(a, f.name) == getattr(b, f.name) for f in fields(a) if f.name != "occurred_at"
    )


def effective_rows(rows: Iterable[CostEntry]) -> list[CostEntry]:
    """09 section 3.3: per call, the VERIFIED row where one exists, else the ESTIMATE. A VERIFIED
    row without an estimate (a leak, 09 section 6.3) counts on its own."""
    materialised = list(rows)
    verified_for = {
        r.entry.estimate_entry_id
        for r in materialised
        if r.entry.figure_kind is CostFigureKind.VERIFIED and r.entry.estimate_entry_id is not None
    }
    return [
        r
        for r in materialised
        if r.entry.figure_kind is CostFigureKind.VERIFIED or r.id not in verified_for
    ]


def totals(rows: Sequence[CostEntry], currency_hint: str | None = None) -> CostTotals:
    currencies = {r.entry.currency for r in rows}
    if len(currencies) > 1:
        raise ConfigInvalidError(
            "rows in more than one currency; convert with a recorded fx_rate first",
            details={"currencies": sorted(currencies)},
        )
    currency = next(iter(currencies), currency_hint or "")
    estimates = [r for r in rows if r.entry.figure_kind is CostFigureKind.ESTIMATE]
    verified = [r for r in rows if r.entry.figure_kind is CostFigureKind.VERIFIED]
    verified_ids = {r.entry.estimate_entry_id for r in verified}
    return CostTotals(
        estimate_micros=sum(r.entry.amount_micros for r in estimates),
        verified_micros=sum(r.entry.amount_micros for r in verified),
        effective_micros=sum(r.entry.amount_micros for r in effective_rows(rows)),
        rows=len(estimates) + sum(1 for r in verified if r.entry.estimate_entry_id is None),
        verified_rows=sum(1 for r in estimates if r.id in verified_ids)
        + sum(1 for r in verified if r.entry.estimate_entry_id is None),
        currency=currency,
    )


def figure_kind_label(t: CostTotals) -> str:
    """09 section 6.1: "ESTIMATE" until every call has a VERIFIED partner."""
    if t.rows == 0 or t.verified_rows == 0:
        return "ESTIMATE"
    if t.verified_rows >= t.rows:
        return "VERIFIED"
    return f"partly verified ({t.verified_rows} of {t.rows} rows)"


@dataclass(frozen=True, slots=True)
class LeakFlag:
    """09 section 6.3: a VERIFIED amount with no matching ESTIMATE (missed call)."""

    entry_id: CostEntryId
    provider: str
    amount_micros: int


class MemoryCostLedger:
    """``CostLedger`` kept in memory, partitioned by the transaction's org (tests)."""

    def __init__(self) -> None:
        self._rows: dict[OrgId, list[CostEntry]] = {}
        self._lock = threading.Lock()

    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        validate_new_entry(entry)
        org = tx.context.org_id
        with self._lock:
            rows = self._rows.setdefault(org, [])
            if entry.idempotency_key is not None:
                for row in rows:
                    e = row.entry
                    if (
                        e.idempotency_key == entry.idempotency_key
                        and e.figure_kind is entry.figure_kind
                    ):
                        if not same_content(e, entry):
                            raise IdempotencyConflictError("ledger replay with different content")
                        return row
            if entry.estimate_entry_id is not None:
                target = next((r for r in rows if r.id == entry.estimate_entry_id), None)
                if target is None or target.entry.figure_kind is not CostFigureKind.ESTIMATE:
                    raise InputInvalidError("estimate_entry_id must point to an ESTIMATE row")
                if any(r.entry.estimate_entry_id == entry.estimate_entry_id for r in rows):
                    raise InputInvalidError("that ESTIMATE already has a VERIFIED row")
            row = CostEntry(id=COST_ENTRY.new(), org_id=org, entry=entry)
            rows.append(row)
            return row

    def get(self, tx: TenantTransaction, entry_id: CostEntryId) -> CostEntry | None:
        return next((r for r in self._rows.get(tx.context.org_id, []) if r.id == entry_id), None)

    def for_job(self, tx: TenantTransaction, job_id: JobId) -> Sequence[CostEntry]:
        return [r for r in self._rows.get(tx.context.org_id, []) if r.entry.job_id == job_id]

    def for_task(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[CostEntry]:
        return [r for r in self._rows.get(tx.context.org_id, []) if r.entry.task_id == task_id]

    def job_totals(self, tx: TenantTransaction, job_id: JobId) -> CostTotals:
        return totals(self.for_job(tx, job_id))

    def all_rows(self, tx: TenantTransaction) -> Sequence[CostEntry]:
        """Every row of the tenant (budget scopes, the JSON export)."""
        return list(self._rows.get(tx.context.org_id, []))

    def leaks(self, tx: TenantTransaction) -> list[LeakFlag]:
        return [
            LeakFlag(r.id, r.entry.provider, r.entry.amount_micros)
            for r in self.all_rows(tx)
            if r.entry.figure_kind is CostFigureKind.VERIFIED and r.entry.estimate_entry_id is None
        ]


def amount_in(row: CostEntry, currency: str) -> int:
    """The row's amount in ``currency`` micros: same currency as is; otherwise the recorded
    ``fx_rate`` (row currency -> ``currency``), rounded up so a budget is never under-counted.
    A missing rate is a refusal, not a guess (09 section 3.3)."""
    if row.entry.currency == currency:
        return row.entry.amount_micros
    if row.entry.fx_rate is None:
        raise ConfigInvalidError(
            "ledger row in another currency has no fx_rate",
            details={"row_currency": row.entry.currency, "currency": currency},
        )
    value = Decimal(row.entry.amount_micros) * row.entry.fx_rate
    return int(value.to_integral_value(rounding="ROUND_CEILING"))
