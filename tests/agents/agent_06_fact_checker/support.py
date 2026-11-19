"""In-memory fakes and builders for the Agent 06 tests (no network, no paid call)."""

import io
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from agent_06_fact_checker.config import FactCheckSettings, LlmStepSettings
from agent_06_fact_checker.hashing import canonical_json, claims_sha256, sha256_hex
from agent_06_fact_checker.models import (
    CitationKind,
    ExtractedClaim,
    Relation,
    Verdict,
    VerifiedClaim,
)
from agent_06_fact_checker.ports import CitationRow, SourceText
from agent_06_fact_checker.prompts import PromptDoc, parse_prompt_doc
from agent_06_fact_checker.rulepack import FinLexicon, RulePack, load_provisional_finance_lexicon
from amw_adapters.common import CallUsage
from amw_adapters.llm.protocol import LlmRequest, LlmResponse
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import CostOperation
from amw_core.errors import (
    BudgetExhaustedError,
    CorruptedOutputError,
    CrossTenantRefError,
    IdempotencyConflictError,
    InputInvalidError,
    MissingDependencyError,
    TenantMismatchError,
)
from amw_core.exec_context import ExecContext
from amw_core.ids import (
    ActorRef,
    AttemptId,
    AuditEntryId,
    ChannelId,
    CorrelationId,
    CostEntryId,
    JobId,
    OrgId,
    Prefix,
    TaskId,
    new_id,
)
from amw_core.interfaces import (
    AuditEntry,
    BlobHead,
    BlobInfo,
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
from amw_core.testing.memory import MemoryCheckpointStore, MemoryTransaction

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs" / "v4"
PROMPTS = DOCS / "prompts" / "agent_06_fact_checker"
ORG = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f"
OTHER_ORG = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e90"
CHANNEL = "chn_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8ea1"
JOB = "job_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e91"
TASK = "tsk_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e92"
PROJECT = "prj_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e93"
COR = "cor_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e94"
ATT = "att_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e95"
SCRIPT = "scr_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f"
IDK = "idk_" + "ab" * 32
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)

# Test lexicon only (the 13 5.4 examples). Production lists are rule-pack data (REQUIRES REVIEW).
TEST_MARKERS = {"en": ("will", "should", "likely to", "target", "next move", "again", "repeat")}


def make_settings(**over: Any) -> FactCheckSettings:
    llm = LlmStepSettings(
        model="test-model",
        temperature=0.0,
        max_output_tokens=4000,
        timeout_ms=60000,
        cost_budget_micros=1000,
        cache_system_prompt=True,
        currency="USD",
    )
    base: dict[str, Any] = {
        "config_version": "test-1",
        "extraction_llm": llm,
        "verification_llm": llm,
        "extract_max_chars_per_call": 12000,
        "price_data_lag_days": 30,
        "referral_patterns": [r"\bcode[:=]\s?[A-Z0-9]{4,}\b"],
        "min_tier_for_verified": "C_SECONDARY",
        "tier_order": ["A_PRIMARY", "B_PUBLISHED", "C_SECONDARY", "D_UNVERIFIED"],
        "unranked_tier": "D_UNVERIFIED",
        "max_window_chars": 600,
        "max_passages_per_claim": 3,
        "search_top_k_per_claim": 3,
        "max_span_chars": 400,
        "max_claims_per_call": 8,
        "max_digest_claims": 10,
        "rounding_match": True,
        "conflict_min_shared_tokens": 2,
        "conflict_max_pairs": 20,
        "conflict_stop_words": {"en": ["the", "a", "of", "is", "in", "on", "for", "to"]},
        "conflict_opposites": {"en": [["rises", "falls"], ["above", "below"]]},
        "conflict_negations": {"en": ["not", "never", "no"]},
        "advice_words": {"en": ["buy", "sell", "hold"]},
    }
    base.update(over)
    return FactCheckSettings.model_validate(base)


class FixedClock:
    def __init__(self) -> None:
        self._ms = 0

    def now(self) -> datetime:
        return NOW

    def monotonic_ms(self) -> int:
        self._ms += 5
        return self._ms


class FakeTenancy:
    @contextmanager
    def transaction(self, context: TenantContext) -> Iterator[TenantTransaction]:
        yield MemoryTransaction(context)

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        if tx.context.org_id != org_id:
            raise TenantMismatchError("org mismatch")

    def cache_key(self, org_id: str, area: str, key: str) -> str:
        return f"amw:{org_id}:{area}:{key}"


class MemoryBlobs:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        return BlobUri(f"amw-blob://{context.org_id}/{area}/{path}")

    def put(self, context: TenantContext, uri: BlobUri, stream: Any) -> BlobInfo:
        if uri in self.data:
            raise InputInvalidError("write-once")
        body = stream.read()
        self.data[uri] = body
        return BlobInfo(uri, sha256_hex(body), len(body))

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        if uri not in self.data:
            raise MissingDependencyError("absent")
        if sha256_hex(self.data[uri]) != expected_sha256:
            raise CorruptedOutputError("hash")
        yield self.data[uri]

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        body = self.data.get(uri)
        return BlobHead(body is not None, None if body is None else sha256_hex(body), None)

    def list_prefix(self, context: TenantContext, org_id: str, area: str) -> list[BlobInfo]:
        return []


class FakeBudget:
    def __init__(self, *, refuse: bool = False) -> None:
        self.refuse = refuse
        self.checks: list[CallCheck] = []

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


class FakeLedger:
    def __init__(self) -> None:
        self.rows: list[CostEntry] = []

    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        row = CostEntry(CostEntryId(new_id(Prefix.COST_ENTRY)), tx.context.org_id, entry)
        self.rows.append(row)
        return row

    def get(self, tx: TenantTransaction, entry_id: str) -> CostEntry | None:
        return None

    def for_job(self, tx: TenantTransaction, job_id: str) -> Sequence[CostEntry]:
        return self.rows

    def for_task(self, tx: TenantTransaction, task_id: str) -> Sequence[CostEntry]:
        return self.rows

    def job_totals(self, tx: TenantTransaction, job_id: str) -> CostTotals:
        raise NotImplementedError


class MemoryAudit:
    def __init__(self) -> None:
        self.entries: list[NewAuditEntry] = []

    def append(self, tx: TenantTransaction, entry: NewAuditEntry) -> AuditEntry:
        self.entries.append(entry)
        raise_if_secret(entry)
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

    def export(
        self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None
    ) -> Any:
        raise NotImplementedError


def raise_if_secret(entry: NewAuditEntry) -> None:
    text = json.dumps(dict(entry.details), default=str)
    assert "quote" not in text  # audit rows carry ids and counts only


class MemoryClaims:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, str]] = {}
        self.ids: dict[str, str] = {}
        self.status: dict[str, VerifiedClaim] = {}
        self.citations: list[CitationRow] = []
        self.status_task: dict[str, str] = {}
        self.owned_override: frozenset[str] | None = None
        self.verdicts: dict[str, Verdict] = {}

    def insert_claims(
        self,
        tx: TenantTransaction,
        *,
        script_id: str,
        task_id: TaskId,
        claims: Sequence[ExtractedClaim],
    ) -> Mapping[str, str]:
        key = (script_id, task_id)
        if key not in self.rows:
            self.rows[key] = {c.local_id: new_id(Prefix.CLAIM) for c in claims}
            self.ids.update(dict.fromkeys(self.rows[key].values(), script_id))
        return self.rows[key]

    def owned_claim_ids(
        self, tx: TenantTransaction, *, script_id: str, claim_ids: Sequence[str]
    ) -> frozenset[str]:
        if self.owned_override is not None:
            return self.owned_override
        return frozenset(claim_ids)

    def extraction_verdicts(
        self, tx: TenantTransaction, *, script_id: str, claim_ids: Sequence[str]
    ) -> Mapping[str, Verdict]:
        return {i: self.verdicts[i] for i in claim_ids if i in self.verdicts}

    def register_extraction(self, claims: Sequence[Mapping[str, Any]]) -> None:
        """What the stored ``claims`` rows hold (the code-recomputed extraction verdicts)."""
        for c in claims:
            self.verdicts[c["claim_id"]] = Verdict(c["extraction_verdict"])

    def update_status(
        self, tx: TenantTransaction, *, task_id: TaskId, results: Sequence[VerifiedClaim]
    ) -> None:
        for r in results:
            other = self.status_task.get(r.claim_id)
            if other is not None and other != task_id:
                raise IdempotencyConflictError("claim changed by another task")
            self.status_task[r.claim_id] = task_id
            self.status[r.claim_id] = r

    def insert_citations(self, tx: TenantTransaction, rows: Sequence[CitationRow]) -> None:
        for row in rows:
            if row not in self.citations:
                self.citations.append(row)


class MemoryScripts:
    def __init__(self, sha: str | None) -> None:
        self.sha = sha

    def content_sha256(
        self, tx: TenantTransaction, *, script_id: str, script_version: int
    ) -> str | None:
        return self.sha


class MemoryKnowledge:
    def __init__(self, sources: Sequence[SourceText] = (), foreign: Sequence[str] = ()) -> None:
        self.sources = {s.citation_ref: s for s in sources}
        self.foreign = set(foreign)
        self.searches = 0

    def get_source(
        self, tx: TenantTransaction, channel_id: str, citation_ref: str
    ) -> SourceText | None:
        if citation_ref in self.foreign:
            raise CrossTenantRefError("foreign")
        return self.sources.get(citation_ref)

    def search(
        self, tx: TenantTransaction, channel_id: str, query: str, top_k: int
    ) -> Sequence[SourceText]:
        self.searches += 1
        return [s for s in self.sources.values() if not s.restricted][:top_k]


def source(
    ref: str, text: str, *, tier: str | None = "B_PUBLISHED", restricted: bool = False
) -> SourceText:
    return SourceText(ref, CitationKind.KNOWLEDGE_CHUNK, text, sha256_hex(text), tier, restricted)


class StaticPacks:
    """Rule-pack records; the finance pack carries the provisional baseline lexicon data file."""

    def __init__(
        self,
        markers: Mapping[str, tuple[str, ...]] | None = None,
        lexicon: FinLexicon | None = None,
    ) -> None:
        base_markers, base_lexicon = load_provisional_finance_lexicon()
        self.markers = base_markers if markers is None else markers
        self.lexicon = base_lexicon if lexicon is None else lexicon
        self.missing: set[str] = set()

    def resolve(self, key: str) -> RulePack:
        if key in self.missing:
            raise MissingDependencyError("pack")
        finance = key == "rp.finance_sebi_in"
        return RulePack(
            key=key,
            version=1,
            text=f"[rules of {key}]",
            rules_sha256="0" * 64,
            markers=self.markers if finance else {},
            lexicon=self.lexicon if finance else None,
        )


class FixedRanges:
    """Last bar dates of the charts (the required D0 lookup); a missing entry is unknown."""

    def __init__(self, ends: Mapping[str, date | None] | None = None) -> None:
        self.ends = dict(ends or {})

    def range_end(self, ref_id: str) -> date | None:
        return self.ends.get(ref_id)


def ranges_for(case_input: Mapping[str, Any]) -> FixedRanges:
    """Dataset charts carry a precomputed age: give the lookup a consistent last bar date."""
    ends: dict[str, date | None] = {}
    for ref in case_input.get("chart_data_refs", []):
        age = ref.get("data_age_vs_lag")
        if age == "OLDER_THAN_LAG":
            ends[ref["ref_id"]] = date(2025, 1, 1)
        elif age == "WITHIN_LAG":
            ends[ref["ref_id"]] = NOW.date() - timedelta(days=5)
    return FixedRanges(ends)


class DocPrompts:
    """Loads the real prompt files of ``docs/v4/prompts`` (their sha256 is the registry value)."""

    def load(self, prompt_id: str) -> PromptDoc:
        name = prompt_id.split("/", 1)[1]
        return parse_prompt_doc(prompt_id, (PROMPTS / f"{name}.md").read_bytes())


class RecordedLlm:
    """Replays recorded model responses in call order; never calls anything."""

    provider = "fake_llm"

    def __init__(self, texts: Sequence[str]) -> None:
        self.texts = list(texts)
        self.requests: list[LlmRequest] = []
        self.keys: list[str] = []

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        self.requests.append(request)
        self.keys.append(idempotency_key)
        text = self.texts.pop(0)
        usage = CallUsage(
            provider="fake_llm",
            operation=CostOperation.LLM_COMPLETION,
            model=request.model,
            tokens_in=100,
            tokens_out=50,
            tokens_cached_in=0,
            amount_micros=300,
            currency="USD",
            idempotency_key=idempotency_key,
        )
        return LlmResponse(usage=usage, text=text, stop_reason="end_turn")

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> Any:
        raise NotImplementedError

    @property
    def calls(self) -> int:
        return len(self.requests)


@dataclass
class World:
    """Everything a step needs, wired with fakes."""

    llm: RecordedLlm
    blobs: MemoryBlobs = field(default_factory=MemoryBlobs)
    budget: FakeBudget = field(default_factory=FakeBudget)
    ledger: FakeLedger = field(default_factory=FakeLedger)
    audit: MemoryAudit = field(default_factory=MemoryAudit)
    claims: MemoryClaims = field(default_factory=MemoryClaims)
    checkpoints: MemoryCheckpointStore = field(default_factory=MemoryCheckpointStore)
    tenancy: FakeTenancy = field(default_factory=FakeTenancy)
    clock: FixedClock = field(default_factory=FixedClock)


def task_input(
    schema: str,
    data: Mapping[str, Any],
    *,
    version: str = "1.0.0",
    script_sha: str | None = None,
    org: str = ORG,
    max_llm_calls: int | None = 20,
    retry_count: int = 0,
) -> TaskInput:
    refs: list[dict[str, Any]] = []
    if script_sha is not None:
        refs.append(
            {
                "uri": f"amw-blob://{org}/jobs/x/script.json",
                "purpose": "PRIOR_OUTPUT",
                "sha256": script_sha,
                "schema": "agent_05.script_draft.output",
            }
        )
    budget: dict[str, Any] = {"max_cost_micros": 500000, "currency": "USD", "max_wall_ms": 60000}
    if max_llm_calls is not None:
        budget["max_llm_calls"] = max_llm_calls
    return TaskInput.model_validate(
        {
            "org_id": org,
            "job_id": JOB,
            "task_id": TASK,
            "project_id": PROJECT,
            "channel_id": CHANNEL,
            "agent_id": "agent_06",
            "source_agent": "agent_01",
            "priority": "NORMAL",
            "deadline": None,
            "context_refs": refs,
            "resource_budget": budget,
            "payload": {
                "payload_schema": schema,
                "payload_schema_version": version,
                "data": dict(data),
            },
            "correlation_id": COR,
            "idempotency_key": IDK,
            "retry_count": retry_count,
            "schema_version": "1.0.0",
        }
    )


def with_claims_hash(data: dict[str, Any]) -> dict[str, Any]:
    data["claims_sha256"] = claims_sha256(data["claims"])
    return data


def js(value: Any) -> str:
    return canonical_json(value)


def bytes_stream(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)


__all__ = ["Relation"]


SCRIPT_SHA = "11" * 32


def extraction_step(world: World, packs: StaticPacks | None = None, **kw: Any) -> Any:
    from agent_06_fact_checker.extraction_step import ClaimExtractionStep

    return ClaimExtractionStep(
        llm=world.llm,
        budget=world.budget,
        ledger=world.ledger,
        tenancy=world.tenancy,
        clock=world.clock,
        blobs=world.blobs,
        checkpoints=world.checkpoints,
        audit=world.audit,
        claims=world.claims,
        scripts=kw.pop("scripts", MemoryScripts(SCRIPT_SHA)),
        chart_ranges=kw.pop("chart_ranges", FixedRanges()),
        rule_packs=packs or StaticPacks(),
        prompts=DocPrompts(),
        settings=kw.pop("settings", make_settings()),
        **kw,
    )


def _scripts(kw: dict[str, Any]) -> Any:
    sha = kw.pop("script_sha", SCRIPT_SHA)
    return kw.pop("scripts", None) or MemoryScripts(sha)


def verification_step(world: World, knowledge: MemoryKnowledge, **kw: Any) -> Any:
    from agent_06_fact_checker.verification_step import ClaimVerificationStep

    return ClaimVerificationStep(
        llm=world.llm,
        budget=world.budget,
        ledger=world.ledger,
        tenancy=world.tenancy,
        clock=world.clock,
        blobs=world.blobs,
        checkpoints=world.checkpoints,
        audit=world.audit,
        claims=world.claims,
        scripts=_scripts(kw),
        knowledge=knowledge,
        prompts=DocPrompts(),
        settings=kw.pop("settings", make_settings()),
        **kw,
    )


def run_context(stage: str = "s06_claims", iteration: int = 0) -> ExecContext:
    """The worker context (CCR-203): tenant, ids, attempt, stage and iteration."""
    return ExecContext(
        tenant=TenantContext(
            org_id=OrgId(ORG), actor=ActorRef("agent_06"), correlation_id=CorrelationId(COR)
        ),
        job_id=JobId(JOB),
        task_id=TaskId(TASK),
        attempt_id=AttemptId(ATT),
        channel_id=ChannelId(CHANNEL),
        attempt_no=1,
        stage_id=stage,
        iteration=iteration,
    )
