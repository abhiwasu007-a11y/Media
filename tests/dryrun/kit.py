"""Shared fakes of the PLUMBING dry-run world (no network, no paid call, no database inside
agents: the graph runner owns the database records).

One local-disk blob store is shared by every agent, so each stage reads exactly the bytes the
upstream stage wrote (hash-verified), as in production. Everything else an agent needs inside
its own process (tenancy transaction, idempotency, checkpoints, its private ledger copy) is an
in-memory fake from the agents' own test support or ``amw_core.testing``.
"""

import hashlib
import io
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amw_core.contracts import OutputRef, TaskOutput
from amw_core.errors import BudgetExhaustedError, TenantMismatchError
from amw_core.ids import AuditEntryId, CostEntryId, Prefix, TaskId, new_id
from amw_core.interfaces import (
    AuditEntry,
    BlobUri,
    Budget,
    BudgetStatus,
    CallCheck,
    CostEntry,
    CostTotals,
    NewAuditEntry,
    NewCostEntry,
    Reservation,
    ReservationOutcome,
    TenantContext,
    TenantTransaction,
)
from amw_core.storage.local import LocalDiskStorage
from amw_core.testing.memory import MemoryTransaction

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "v4"
PROMPTS = DOCS / "prompts"
PLUMBING = "PLUMBING TEST - NOT QUALITY"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(doc: object) -> bytes:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


class WallClock:
    """Real UTC time (the market-hours guard and the data-lag checks read it)."""

    def __init__(self, fixed: datetime | None = None) -> None:
        self._fixed = fixed
        self._mono = 0

    def now(self) -> datetime:
        return self._fixed or datetime.now(UTC)

    def monotonic_ms(self) -> int:
        self._mono += 5
        return self._mono


class MemTenancy:
    @contextmanager
    def transaction(self, context: TenantContext) -> Iterator[TenantTransaction]:
        yield MemoryTransaction(context)

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        if tx.context.org_id != org_id:
            raise TenantMismatchError("org mismatch")

    def cache_key(self, org_id: str, area: str, key: str) -> str:
        return f"amw:{org_id}:{area}:{key}"


class AllowBudget:
    """Agent-internal budget port: the REAL E1/E2 checks run in the graph runner and in the
    metering adapter wrapper (``amw_orchestrator.metering``) against PostgreSQL."""

    def __init__(self) -> None:
        self.checks: list[CallCheck] = []
        self.refuse = False

    def applicable_budgets(self, tx: TenantTransaction, job_id: str) -> Sequence[Budget]:
        return []

    def reserve(
        self, tx: TenantTransaction, task_id: TaskId, amount_micros: int, currency: str
    ) -> ReservationOutcome:
        return ReservationOutcome(True, (), ())

    def check_call(self, tx: TenantTransaction, check: CallCheck) -> None:
        self.checks.append(check)
        if self.refuse:
            raise BudgetExhaustedError("budget")

    def check_provider_gate(self, tx: TenantTransaction, provider: str) -> None:
        return None

    def after_call(self, tx: TenantTransaction, entry: CostEntry) -> Sequence[Budget]:
        return []

    def consume(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[Reservation]:
        return []

    def release(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[Reservation]:
        return []

    def status(self, tx: TenantTransaction, budget_id: str) -> BudgetStatus:
        raise NotImplementedError


class MirrorLedger:
    """Agent-internal copy of the ledger rows (the authoritative rows are written to
    PostgreSQL by the metering wrapper, one per adapter call)."""

    def __init__(self) -> None:
        self.rows: list[CostEntry] = []

    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        row = CostEntry(CostEntryId(new_id(Prefix.COST_ENTRY)), tx.context.org_id, entry)
        self.rows.append(row)
        return row

    def get(self, tx: TenantTransaction, entry_id: str) -> CostEntry | None:
        return next((r for r in self.rows if r.id == entry_id), None)

    def for_job(self, tx: TenantTransaction, job_id: str) -> Sequence[CostEntry]:
        return [r for r in self.rows if r.entry.job_id == job_id]

    def for_task(self, tx: TenantTransaction, task_id: str) -> Sequence[CostEntry]:
        return [r for r in self.rows if r.entry.task_id == task_id]

    def job_totals(self, tx: TenantTransaction, job_id: str) -> CostTotals:
        rows = self.for_job(tx, job_id)
        total = sum(r.entry.amount_micros for r in rows)
        return CostTotals(total, 0, total, len(rows), 0, "USD")


class ListAudit:
    def __init__(self) -> None:
        self.entries: list[NewAuditEntry] = []

    def append(self, tx: TenantTransaction, entry: NewAuditEntry) -> AuditEntry:
        self.entries.append(entry)
        return AuditEntry(
            AuditEntryId(new_id(Prefix.AUDIT_ENTRY)),
            tx.context.org_id,
            len(self.entries),
            entry,
            b"",
            b"",
        )

    def verify_chain(self, tx: TenantTransaction) -> Any:
        raise NotImplementedError

    def export(self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None) -> Any:
        raise NotImplementedError


@dataclass
class Blobs:
    """The shared store plus convenience helpers (every write is write-once)."""

    storage: LocalDiskStorage
    org_id: str
    seeded: dict[str, str] = field(default_factory=dict)

    @property
    def ctx(self) -> TenantContext:
        return TenantContext(self.org_id, "sys_operator")  # type: ignore[arg-type]

    def put_bytes(self, area: str, path: str, data: bytes) -> tuple[str, str]:
        uri = self.storage.blob_uri(self.ctx, area, path)
        head = self.storage.head(self.ctx, uri)
        if head.exists:
            return uri, head.sha256 or ""
        info = self.storage.put(self.ctx, uri, io.BytesIO(data))
        self.seeded[uri] = info.sha256
        return uri, info.sha256

    def put_json(self, area: str, path: str, doc: object) -> tuple[str, str]:
        return self.put_bytes(area, path, json.dumps(doc, ensure_ascii=False).encode())

    def read(self, uri: str, sha: str | None = None) -> bytes:
        if sha is None:
            sha = self.storage.head(self.ctx, BlobUri(uri)).sha256 or ""
        return b"".join(self.storage.get(self.ctx, BlobUri(uri), sha))

    def read_json(self, uri: str, sha: str | None = None) -> Any:
        return json.loads(self.read(uri, sha))

    def local_path(self, uri: str) -> Path:
        from amw_core.storage.local import parse_uri

        parsed = parse_uri(uri)
        return self.storage._path(parsed)


def data_of(out: TaskOutput) -> dict[str, Any]:
    assert out.payload is not None, "upstream output has no payload"
    return dict(out.payload.data)


def ref_ending(out: TaskOutput, suffix: str) -> OutputRef:
    for ref in out.output_refs:
        if ref.uri.endswith(suffix):
            return ref
    raise KeyError(f"no output ref ending with {suffix}: {[r.uri for r in out.output_refs]}")


def as_mapping(value: object) -> Mapping[str, Any]:
    assert isinstance(value, Mapping)
    return value


def banner_png(width: int, height: int, title: str, subtitle: str = "") -> bytes:
    """Full-frame RGBA overlay: an opaque PLUMBING band at the top, transparent elsewhere."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    band = max(24, height // 9)
    draw.rectangle((0, 0, width, band), fill=(200, 20, 20, 235))
    font = ImageFont.load_default(size=max(12, band // 2))
    draw.text((width // 2, band // 2), PLUMBING, fill=(255, 255, 255, 255), font=font, anchor="mm")
    if title:
        small = ImageFont.load_default(size=max(10, band // 3))
        draw.rectangle((0, height - band, width, height), fill=(16, 24, 32, 220))
        draw.text((width // 2, height - band // 2), f"{title} {subtitle}".strip(),
                  fill=(242, 242, 242, 255), font=small, anchor="mm")
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False)
    return out.getvalue()
