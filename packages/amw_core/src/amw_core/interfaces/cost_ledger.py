"""Cost ledger interface (04 section 5.14 ``cost_ledger``; 09 sections 5-6; 3A slice spec 5).

Append-only: one row per paid call, ``figure_kind = ESTIMATE`` at call time; a ``VERIFIED`` row
points to its estimate through ``estimate_entry_id``; nothing is ever updated or deleted
(09 section 13). A replayed write with the same ``(idempotency_key, figure_kind)`` is a no-op that
returns the stored row (09 section 5). Money is integer micros + ``currency``. Implementation: L1.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from amw_core.enums import BillingMode, CostFigureKind, CostOperation, CostUnitKind
from amw_core.ids import (
    AttemptId,
    ChannelId,
    CostEntryId,
    ExecutorId,
    IdempotencyKey,
    JobId,
    OrgId,
    TaskId,
)
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class NewCostEntry:
    """Columns of 04 section 5.14 filled as 09 section 5 describes (none added)."""

    provider: str
    operation: CostOperation
    amount_micros: int
    currency: str
    figure_kind: CostFigureKind
    occurred_at: datetime
    job_id: JobId | None = None
    task_id: TaskId | None = None
    attempt_id: AttemptId | None = None
    channel_id: ChannelId | None = None
    agent_id: ExecutorId | None = None
    model: str | None = None
    billing_mode: BillingMode | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached_in: int | None = None
    tokens_cache_write_in: int | None = None
    """CCR-037: prompt-cache write tokens."""
    chars_in: int | None = None
    """CCR-037: input characters of an LLM/TTS call (Devanagari token ratio)."""
    language: str | None = None
    """CCR-037: BCP 47 language of the call."""
    units: Decimal | None = None
    unit_kind: CostUnitKind | None = None
    fx_rate: Decimal | None = None
    fx_source: str | None = None
    price_ref: str | None = None
    estimate_entry_id: CostEntryId | None = None
    verification_ref: str | None = None
    idempotency_key: IdempotencyKey | None = None


@dataclass(frozen=True, slots=True)
class CostEntry:
    id: CostEntryId
    org_id: OrgId
    entry: NewCostEntry


@dataclass(frozen=True, slots=True)
class CostTotals:
    """09 section 6.1: a total is ESTIMATE until every row has a VERIFIED partner."""

    estimate_micros: int
    verified_micros: int
    effective_micros: int
    """Per call: the VERIFIED amount where one exists, else the ESTIMATE (09 section 3.3)."""
    rows: int
    verified_rows: int
    currency: str


@runtime_checkable
class CostLedger(Protocol):
    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        """Append one row (E3 runs after it, see ``BudgetGuard.after_call``). ``amount_micros < 0``
        or a missing price/FX reference -> ``ConfigInvalidError`` (fail closed, 09 section 13)."""
        ...

    def get(self, tx: TenantTransaction, entry_id: CostEntryId) -> CostEntry | None: ...

    def for_job(self, tx: TenantTransaction, job_id: JobId) -> Sequence[CostEntry]:
        """Rows of one job (cost-per-stage report, 09 section 12)."""
        ...

    def for_task(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[CostEntry]: ...

    def job_totals(self, tx: TenantTransaction, job_id: JobId) -> CostTotals: ...
