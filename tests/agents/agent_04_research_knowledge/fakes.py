"""In-memory fakes for the Agent 04 tests (Protocols of amw_core; no network, no database)."""

import hashlib
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from agent_04_research_knowledge.guards.tenant import ChannelRecord
from amw_adapters.common import CallUsage, FakeEngine
from amw_adapters.llm.protocol import OPERATION_COMPLETION, LlmRequest, LlmResponse
from amw_core.enums import BillingMode, CostFigureKind
from amw_core.errors import (
    BudgetExhaustedError,
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    TenantInactiveError,
    TenantMismatchError,
)
from amw_core.ids import COST_ENTRY, AuditEntryId, OrgId
from amw_core.interfaces import (
    AuditEntry,
    BlobHead,
    BlobInfo,
    BlobUri,
    Budget,
    CallCheck,
    ChainVerification,
    CostEntry,
    NewAuditEntry,
    NewCostEntry,
    TenantContext,
    TenantTransaction,
)
from amw_core.testing.memory import MemoryTransaction


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2030, 1, 1, tzinfo=UTC)
        self._mono = 0

    def now(self) -> datetime:
        return self._now

    def monotonic_ms(self) -> int:
        self._mono += 5
        return self._mono


class FakeTenancy:
    def __init__(self) -> None:
        self.inactive: set[str] = set()

    @contextmanager
    def transaction(self, context: TenantContext) -> Iterator[TenantTransaction]:
        if context.org_id in self.inactive:
            raise TenantInactiveError("inactive")
        yield MemoryTransaction(context)

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        if tx.context.org_id != org_id:
            raise TenantMismatchError("mismatch")

    def cache_key(self, org_id: OrgId, area: str, key: str) -> str:
        return f"amw:{org_id}:{area}:{key}"


class MemoryBlobStorage:
    """Write-once blobs partitioned by org; the URI owner is checked against the context."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.puts = 0

    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        return BlobUri(f"amw-blob://{context.org_id}/{area}/{path}")

    def _check(self, context: TenantContext, uri: str) -> None:
        owner = uri.split("://", 1)[1].split("/", 1)[0]
        if owner != context.org_id:
            raise CrossTenantRefError("uri of another tenant")

    def put(self, context: TenantContext, uri: BlobUri, stream: Any) -> BlobInfo:
        self._check(context, uri)
        if uri in self.blobs:
            raise InputInvalidError("write-once path exists")
        data = stream.read()
        self.blobs[uri] = data
        self.puts += 1
        return BlobInfo(uri, hashlib.sha256(data).hexdigest(), len(data))

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        self._check(context, uri)
        if uri not in self.blobs:
            raise MissingDependencyError("absent")
        if hashlib.sha256(self.blobs[uri]).hexdigest() != expected_sha256:
            raise CorruptedOutputError("hash mismatch")
        yield self.blobs[uri]

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        self._check(context, uri)
        data = self.blobs.get(uri)
        if data is None:
            return BlobHead(False, None, None)
        return BlobHead(True, hashlib.sha256(data).hexdigest(), len(data))

    def list_prefix(self, context: TenantContext, org_id: OrgId, area: str) -> Iterable[BlobInfo]:
        return []


class FakeBudget:
    def __init__(self) -> None:
        self.exhausted_after: int | None = None
        self.checks = 0

    def check_call(self, tx: TenantTransaction, check: CallCheck) -> None:
        self.checks += 1
        if self.exhausted_after is not None and self.checks > self.exhausted_after:
            raise BudgetExhaustedError("budget exhausted")

    def after_call(self, tx: TenantTransaction, entry: CostEntry) -> Sequence[Budget]:
        return []

    def applicable_budgets(self, tx: TenantTransaction, job_id: Any) -> Sequence[Budget]:
        return []

    def reserve(
        self, tx: TenantTransaction, task_id: Any, amount_micros: int, currency: str
    ) -> Any:
        raise NotImplementedError

    def check_provider_gate(self, tx: TenantTransaction, provider: str) -> None:
        return None

    def consume(self, tx: TenantTransaction, task_id: Any) -> Sequence[Any]:
        return []

    def release(self, tx: TenantTransaction, task_id: Any) -> Sequence[Any]:
        return []

    def status(self, tx: TenantTransaction, budget_id: Any) -> Any:
        raise NotImplementedError


class FakeLedger:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], CostEntry] = {}

    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        key = (entry.idempotency_key or "", entry.figure_kind.value)
        if entry.idempotency_key and key in self.rows:
            return self.rows[key]
        row = CostEntry(COST_ENTRY.new(), tx.context.org_id, entry)
        self.rows[key if entry.idempotency_key else (str(len(self.rows)), "x")] = row
        return row

    def get(self, tx: TenantTransaction, entry_id: Any) -> CostEntry | None:
        return next((r for r in self.rows.values() if r.id == entry_id), None)

    def for_job(self, tx: TenantTransaction, job_id: Any) -> Sequence[CostEntry]:
        return list(self.rows.values())

    def for_task(self, tx: TenantTransaction, task_id: Any) -> Sequence[CostEntry]:
        return list(self.rows.values())

    def job_totals(self, tx: TenantTransaction, job_id: Any) -> Any:
        raise NotImplementedError


class FakeAuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(self, tx: TenantTransaction, entry: NewAuditEntry) -> AuditEntry:
        row = AuditEntry(
            AuditEntryId(f"aud_{len(self.entries)}"),
            tx.context.org_id,
            len(self.entries) + 1,
            entry,
            b"",
            b"",
        )
        self.entries.append(row)
        return row

    def verify_chain(self, tx: TenantTransaction) -> ChainVerification:
        return ChainVerification(True, len(self.entries), None)

    def export(
        self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None
    ) -> Iterator[AuditEntry]:
        return iter(self.entries)


class FakeDirectory:
    def __init__(self) -> None:
        self.active = True
        self.channels: dict[tuple[str, str], ChannelRecord] = {}
        self.workspaces: dict[tuple[str, str], str] = {}

    def tenant_active(self, org_id: str) -> bool:
        return self.active

    def channel(self, org_id: str, channel_id: str) -> ChannelRecord | None:
        return self.channels.get((org_id, channel_id))

    def workspace_id(self, org_id: str, project_id: str) -> str | None:
        return self.workspaces.get((org_id, project_id))


class ScriptedLlm:
    """``LlmAdapter`` with idempotency and failure injection from ``FakeEngine``; the reply text
    comes from ``responder(request)``."""

    provider = "fake_llm"

    def __init__(
        self, responder: Callable[[LlmRequest], str], engine: FakeEngine | None = None
    ) -> None:
        self.responder = responder
        self.engine = engine or FakeEngine("llm")
        self.requests: list[LlmRequest] = []

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        def build(digest: str, fixture: dict[str, Any] | None) -> LlmResponse:
            self.requests.append(request)
            text = self.responder(request)
            usage = CallUsage(
                provider="fake_llm",
                operation=OPERATION_COMPLETION,
                model=request.model,
                billing_mode=BillingMode.STANDARD,
                tokens_in=100,
                tokens_out=50,
                tokens_cached_in=0,
                amount_micros=300,
                currency="USD",
                figure_kind=CostFigureKind.ESTIMATE,
                price_ref="fake-pricing-v0",
                idempotency_key=idempotency_key,
            )
            return LlmResponse(text=text, stop_reason="end_turn", usage=usage)

        return self.engine.run(OPERATION_COMPLETION, idempotency_key, request, build, LlmResponse)

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> Any:
        raise NotImplementedError
