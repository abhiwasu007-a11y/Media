"""In-memory fakes for the ports of agent 11 (no network, no database)."""

import hashlib
import json
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent_11_thumbnail_design.config import Agent11Settings
from agent_11_thumbnail_design.models import Brief, Promise, SubjectHint
from agent_11_thumbnail_design.ports import (
    BrandKitView,
    FontRef,
    LedgerRow,
    NewImageAsset,
    NewLedgerRow,
    OwnerAsset,
    RegisteredAsset,
    ScriptView,
)
from agent_11_thumbnail_design.subject_options import AssetFacts
from amw_adapters.common import CallUsage
from amw_adapters.llm.protocol import LlmRequest, LlmResponse, TokenCount
from amw_core.enums import (
    BillingMode,
    CostOperation,
)
from amw_core.errors import BudgetExhaustedError, CrossTenantRefError, MissingDependencyError
from amw_core.ids import AuditEntryId, Prefix, new_id
from amw_core.interfaces.audit_log import AuditEntry, ChainVerification, NewAuditEntry
from amw_core.interfaces.budget_guard import (
    Budget,
    BudgetStatus,
    CallCheck,
    Reservation,
    ReservationOutcome,
)
from amw_core.interfaces.cost_ledger import CostEntry, NewCostEntry
from amw_core.interfaces.storage import BlobHead, BlobInfo, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_core.testing.memory import MemoryTransaction

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self._ms = 0

    def now(self) -> datetime:
        return NOW

    def monotonic_ms(self) -> int:
        self._ms += 5
        return self._ms


class FakeTenancy:
    def __init__(self) -> None:
        self.opened = 0

    @contextmanager
    def transaction(self, context: TenantContext) -> Iterator[TenantTransaction]:
        self.opened += 1
        yield MemoryTransaction(context)

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        if tx.context.org_id != org_id:
            raise CrossTenantRefError("other tenant")

    def cache_key(self, org_id: str, area: str, key: str) -> str:
        return f"amw:{org_id}:{area}:{key}"


class FakeStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        return BlobUri(f"amw-blob://{context.org_id}/{area}/{path}")

    def _check(self, context: TenantContext, uri: str) -> None:
        owner = uri.split("://", 1)[1].split("/", 1)[0]
        if owner not in (context.org_id, "platform"):
            raise CrossTenantRefError("blob of another tenant")

    def put(self, context: TenantContext, uri: BlobUri, stream: Any) -> BlobInfo:
        self._check(context, uri)
        if uri in self.blobs:
            raise AssertionError("write-once violated")
        data = stream.read()
        self.blobs[uri] = data
        return BlobInfo(uri, hashlib.sha256(data).hexdigest(), len(data))

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        self._check(context, uri)
        if uri not in self.blobs:
            raise MissingDependencyError("absent")
        yield self.blobs[uri]

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        self._check(context, uri)
        data = self.blobs.get(uri)
        return BlobHead(
            data is not None,
            hashlib.sha256(data).hexdigest() if data else None,
            len(data) if data else None,
        )

    def list_prefix(self, context: TenantContext, org_id: Any, area: str) -> Iterable[BlobInfo]:
        return []


class FakeBudget:
    def __init__(self, *, grant: bool = True) -> None:
        self.grant = grant
        self.checks = 0
        self.after = 0

    def applicable_budgets(self, tx: TenantTransaction, job_id: Any) -> Sequence[Budget]:
        return []

    def reserve(
        self, tx: TenantTransaction, task_id: Any, amount_micros: int, currency: str
    ) -> ReservationOutcome:
        return ReservationOutcome(self.grant, (), ())

    def check_call(self, tx: TenantTransaction, check: CallCheck) -> None:
        self.checks += 1
        if not self.grant:
            raise BudgetExhaustedError("no budget")

    def check_provider_gate(self, tx: TenantTransaction, provider: str) -> None: ...

    def after_call(self, tx: TenantTransaction, entry: CostEntry) -> Sequence[Budget]:
        self.after += 1
        return []

    def consume(self, tx: TenantTransaction, task_id: Any) -> Sequence[Reservation]:
        return []

    def release(self, tx: TenantTransaction, task_id: Any) -> Sequence[Reservation]:
        return []

    def status(self, tx: TenantTransaction, budget_id: Any) -> BudgetStatus:
        raise NotImplementedError


class FakeCosts:
    def __init__(self) -> None:
        self.rows: list[CostEntry] = []

    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        row = CostEntry(new_id(Prefix.COST_ENTRY), tx.context.org_id, entry)  # type: ignore[arg-type]
        self.rows.append(row)
        return row

    def get(self, tx: TenantTransaction, entry_id: Any) -> CostEntry | None:
        return None

    def for_job(self, tx: TenantTransaction, job_id: Any) -> Sequence[CostEntry]:
        return self.rows

    def for_task(self, tx: TenantTransaction, task_id: Any) -> Sequence[CostEntry]:
        return self.rows

    def job_totals(self, tx: TenantTransaction, job_id: Any) -> Any:
        raise NotImplementedError


class FakeAudit:
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

    def verify_chain(self, tx: TenantTransaction) -> ChainVerification:
        return ChainVerification(True, len(self.entries), None)

    def export(
        self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None
    ) -> Iterator[AuditEntry]:
        return iter(())


class ScriptedLlm:
    """An LlmAdapter that replays prepared answers in order (no network)."""

    provider = "fake"

    def __init__(self, answers: Sequence[str | Exception]) -> None:
        self.answers = list(answers)
        self.requests: list[LlmRequest] = []
        self.keys: list[str] = []

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        self.requests.append(request)
        self.keys.append(idempotency_key)
        ans = self.answers.pop(0)
        if isinstance(ans, Exception):
            raise ans
        usage = CallUsage(
            provider="fake",
            operation=CostOperation.LLM_COMPLETION,
            model=request.model,
            billing_mode=BillingMode.STANDARD,
            tokens_in=100,
            tokens_out=50,
            tokens_cached_in=0,
            tokens_cache_write_in=0,
            chars_in=10,
            language=request.language,
            amount_micros=350,
            currency="USD",
            price_ref="fake-price",
            idempotency_key=idempotency_key,
        )
        return LlmResponse(text=ans, stop_reason="end_turn", usage=usage)

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> TokenCount:
        raise NotImplementedError


@dataclass
class FakeRepo:
    script: ScriptView
    category: str
    kit: BrandKitView | None
    default_font_ref: FontRef | None
    assets: list[OwnerAsset] = field(default_factory=list)
    hints: list[SubjectHint] = field(default_factory=list)
    previous: dict[str, Any] | None = None
    registered: dict[tuple[str, str], RegisteredAsset] = field(default_factory=dict)
    images: dict[str, str] = field(default_factory=dict)
    ledger: list[LedgerRow] = field(default_factory=list)
    ledger_inserts: list[NewLedgerRow] = field(default_factory=list)
    image_inserts: list[NewImageAsset] = field(default_factory=list)

    def script_view(self, tx: TenantTransaction, uri: str, sha256: str) -> ScriptView:
        return self.script

    def channel_category(self, tx: TenantTransaction, channel_id: str) -> str:
        return self.category

    def brand_kit(self, tx: TenantTransaction, uri: str, sha256: str) -> BrandKitView | None:
        return self.kit

    def default_font(self, tx: TenantTransaction) -> FontRef | None:
        return self.default_font_ref

    def owner_assets(self, tx: TenantTransaction, uris: Sequence[str]) -> list[OwnerAsset]:
        return [a for a in self.assets if a.uri in uris]

    def subject_hints(self, tx: TenantTransaction, uri: str, sha256: str) -> list[SubjectHint]:
        return self.hints

    def previous_manifest(
        self, tx: TenantTransaction, uri: str, sha256: str
    ) -> dict[str, Any] | None:
        return self.previous

    def registered_assets(
        self, tx: TenantTransaction, keys: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], RegisteredAsset]:
        return {k: v for k, v in self.registered.items() if k in keys}

    def licence_id_code_generated(self, tx: TenantTransaction) -> str:
        return "lic_selfgrant"

    def insert_image_asset(self, tx: TenantTransaction, row: NewImageAsset) -> str:
        if row.content_sha256 not in self.images:
            self.images[row.content_sha256] = new_id(Prefix.ASSET)
            self.image_inserts.append(row)
        return self.images[row.content_sha256]

    def insert_ledger_row(self, tx: TenantTransaction, row: NewLedgerRow) -> None:
        if not any(
            r.asset_id == row.asset_id and r.usage_kind == row.usage_kind and r.job_id == row.job_id
            for r in self.ledger
        ):
            self.ledger.append(LedgerRow(row.asset_id, row.usage_kind, row.job_id, False))
            self.ledger_inserts.append(row)

    def ledger_rows(self, tx: TenantTransaction, job_id: str) -> list[LedgerRow]:
        return [r for r in self.ledger if r.job_id == job_id]


def settings(**over: Any) -> Agent11Settings:
    flat: dict[str, Any] = {
        "agent_11.canvas.width_px": 1920,
        "agent_11.canvas.height_px": 1080,
        "agent_11.output.format": "png",
        "agent_11.output.max_bytes": 50_000_000,
        "agent_11.text.max_words": 6,
        "agent_11.text.max_chars": 40,
        "agent_11.text.max_options": 8,
        "agent_11.text.min_font_px": 48,
        "agent_11.text.max_font_px": 200,
        "agent_11.text.font_step_px": 8,
        "agent_11.layout.safe_margin_permille": 30,
        "agent_11.layout.reserved_corner": "bottom_right",
        "agent_11.legibility.min_contrast_ratio": 4.5,
        "agent_11.distinct.min_hash_distance_bits": 1,
        "agent_11.asset.min_width_px": 1280,
        "agent_11.asset.min_height_px": 720,
        "agent_11.llm.enabled": True,
        "agent_11.llm.max_rationale_chars": 160,
        "llm.agent_11.thumbnail_variants.concepts.model_tier": "MID",
        "llm.agent_11.thumbnail_variants.concepts.temperature": 0.0,
        "llm.agent_11.thumbnail_variants.concepts.max_output_tokens": 1500,
        "llm.agent_11.thumbnail_variants.concepts.timeout_ms": 60000,
        "llm.agent_11.thumbnail_variants.concepts.cost_budget_micros": 100000,
        "llm.agent_11.thumbnail_variants.concepts.cache_system_prompt": True,
        "llm.tiers.MID.model": "model-mid",
        "llm.tiers.MID.price_in_micros_per_token": 3,
        "llm.tiers.MID.price_out_micros_per_token": 15,
        "llm.tiers.MID.currency": "USD",
    }
    for k, v in over.items():
        flat[k.replace("__", ".")] = v
    return Agent11Settings.load(flat)


def promise_en() -> tuple[Promise, Brief]:
    return (
        Promise(
            promise_statement="You will learn how to read a trend from price structure.",
            promise_key_terms=("trend", "price structure"),
            working_title_local="How to read a trend from price structure",
        ),
        Brief(
            subject_idea="outline of level steps",
            text_idea_local="Read the trend",
            must_not_promise=("profit", "secret"),
        ),
    )


def asset_facts(sha: str = "a1", **over: Any) -> AssetFacts:
    base: dict[str, Any] = {
        "sha": sha,
        "label": f"owner image {sha}",
        "kind": "IMAGE",
        "status": "ACTIVE",
        "source_type": "OWNER_MADE",
        "licence_state": "ACTIVE",
        "covers_monetized": True,
        "expired": False,
        "channel_allowed": True,
        "width_px": 1920,
        "height_px": 1080,
        "depicts_real_person": False,
        "release_ref": False,
        "data_age_vs_lag": "NOT_APPLICABLE",
        "label_free": False,
        "direction_balanced": False,
    }
    base.update(over)
    return AssetFacts(**base)


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)
