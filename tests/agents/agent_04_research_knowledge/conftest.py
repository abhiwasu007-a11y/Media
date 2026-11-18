"""World builder for the Agent 04 tests: one tenant, one channel, a seeded library, fake adapters."""
# ruff: noqa: E501

import hashlib
import json
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agent_04_research_knowledge.guards.restricted import ApprovalView
from agent_04_research_knowledge.guards.tenant import ChannelRecord
from agent_04_research_knowledge.library.memory import InMemoryKnowledgeLibrary
from agent_04_research_knowledge.library.models import ChunkRow, CollectionView, SourceView
from agent_04_research_knowledge.memory import InMemoryMemoryItems, PackMemory
from agent_04_research_knowledge.prompts import PromptLoader, RulePackText, StaticRulePacks
from agent_04_research_knowledge.settings import ResearchSettings
from agent_04_research_knowledge.steps.research_pack import (
    ResearchPackStep,
    ResolverFactory,
    StepDeps,
    task_key,
)
from amw_adapters.llm.protocol import LlmRequest
from amw_adapters.web_fetch.fake import FakeWebFetchAdapter
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import (
    ApprovalKind,
    ApprovalState,
    KnowledgeSourceKind,
    KnowledgeSourceStatus,
    RulePackScope,
    SourceOwnership,
)
from amw_core.ids import (
    ATTEMPT,
    CHANNEL,
    CORRELATION,
    JOB,
    ORG,
    PROJECT,
    TASK,
    Prefix,
    new_id,
)
from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore
from tests.agents.agent_04_research_knowledge.fakes import (
    FakeAuditLog,
    FakeBudget,
    FakeDirectory,
    FakeLedger,
    FakeTenancy,
    FixedClock,
    MemoryBlobStorage,
    ScriptedLlm,
)

PROMPTS = Path(__file__).resolve().parents[3] / "docs" / "v4" / "prompts"
BODY_1 = "A stop loss closes a position once price reaches a chosen level against it. Traders often move the level away, which removes the protection."
BODY_2 = "Position sizing converts risk into a quantity of units. The stop distance sets how many units fit inside the risk limit."


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("test attempted a network connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def flat_settings() -> dict[str, Any]:
    step = {
        "model_tier": "MID",
        "model": "model-test",
        "temperature": 0.0,
        "max_output_tokens": 4000,
        "timeout_ms": 60000,
        "cost_budget_micros": 1000,
        "cache_system_prompt": True,
    }
    flat: dict[str, Any] = {
        "research.plan.max_concepts": 6,
        "research.plan.max_queries_per_concept": 3,
        "research.retrieval.top_k_per_concept": 4,
        "research.retrieval.candidate_pool_per_query": 12,
        "research.retrieval.max_chunks_per_source_per_concept": 2,
        "research.retrieval.statement_timeout_ms": 5000,
        "research.retrieval.text_search_configs": {"en": "english", "mr": "simple"},
        "research.retrieval.default_text_search_config": "simple",
        "research.notes.max_note_chars": 300,
        "research.notes.max_notes_per_passage": 3,
        "research.notes.max_passages_per_call": 3,
        "research.notes.max_repair_rounds": 1,
        "research.copy_guard.max_verbatim_words": 6,
        "research.copy_guard.max_overlap_ratio": 0.5,
        "research.copy_guard.ngram_n": 3,
        "research.reliability.tier_scores": {
            "A_PRIMARY": 0.9,
            "B_PUBLISHED": 0.7,
            "C_SECONDARY": 0.5,
            "D_UNVERIFIED": 0.2,
        },
        "research.reliability.domain_classes": {
            "gov.example": "OFFICIAL",
            "news.example": "REPUTABLE_SECONDARY",
        },
        "research.external.allowlist": [],
        "research.external.max_bytes": 100000,
        "research.external.timeout_ms": 5000,
        "research.external.max_redirects": 3,
        "research.external.passage_target_chars": 400,
        "research.ingest.chunk_target_chars": 300,
        "research.ingest.chunk_overlap_chars": 30,
        "research.ingest.min_page_chars": 20,
        "research.ingest.max_nonprintable_ratio": 0.2,
        "research.ingest.qa_sample_size": 2,
        "research.ingest.qa_seed": 7,
        "research.memory.project_ttl_ms": 86_400_000,
        "research.min_tier_for_factual": "C_SECONDARY",
        "research.inline_payload_max_bytes": 500_000,
        "llm.agent_04.caps.default_max_llm_calls": 20,
    }
    for name in ("plan", "notes"):
        for k, v in step.items():
            flat[f"llm.agent_04.research_pack.{name}.{k}"] = v
    return flat


def make_settings(**overrides: Any) -> ResearchSettings:
    return ResearchSettings.from_flat({**flat_settings(), **overrides})


def plan_json(concepts: int = 2, **extra: Any) -> str:
    items = []
    labels = [
        ("stop-loss", "stop loss", ["DEFINITION", "COMMON_MISTAKE"]),
        ("position sizing", "position sizing", ["MECHANISM"]),
    ]
    for i in range(concepts):
        label, query, needs = labels[i % 2]
        items.append(
            {
                "concept_id": f"c{i + 1:02d}",
                "label": label,
                "label_en": label,
                "kind": "CORE_CONCEPT",
                "rationale": "needed",
                "evidence_needs": needs,
                "time_reference": "TIMELESS",
                "queries": [{"text": query, "language": "en", "purpose": "PRIMARY"}],
                "wants_method_material": False,
                "closes_gap_ids": [],
                "target_collection_keys": [],
            }
        )
    doc = {"concepts": items, "out_of_scope_notes": [], "refusal": None, **extra}
    return json.dumps(doc)


def user_payload(request: LlmRequest) -> dict[str, Any]:
    text = request.messages[0].content
    body = text.split("<input_data>\n", 1)[1].split("\n</input_data>", 1)[0]
    parsed: dict[str, Any] = json.loads(body.replace("<\\/", "</"))
    return parsed


def default_responder(request: LlmRequest) -> str:
    payload = user_payload(request)
    if "topic_title" in payload:
        return plan_json()
    notes = []
    assess = []
    for i, p in enumerate(payload["passages"], start=1):
        relevant = any(w in p["text"].lower() for w in ("stop", "position"))
        assess.append(
            {
                "passage_id": p["passage_id"],
                "relevance": "RELEVANT" if relevant else "IRRELEVANT",
                "reason": "checked",
            }
        )
        if relevant:
            kind = payload["concept"]["evidence_needs"][0]
            notes.append(
                {
                    "note_ref": f"n{i}",
                    "passage_id": p["passage_id"],
                    "statement_kind": kind,
                    "note": "An advance order limits the loss of a trade at a level set beforehand.",
                    "time_reference_kind": "TIMELESS",
                    "instruments": [],
                    "numbers_in_note": [],
                    "clarity": "CLEAR",
                    "forward_looking": False,
                }
            )
    return json.dumps(
        {"assessments": assess, "notes": notes, "excluded_statements": [], "refusal": None}
    )


@dataclass
class World:
    org: str
    channel: str
    project: str
    job: str
    task: str
    library: InMemoryKnowledgeLibrary
    storage: MemoryBlobStorage
    llm: ScriptedLlm
    web: FakeWebFetchAdapter
    budget: FakeBudget
    ledger: FakeLedger
    audit: FakeAuditLog
    tenancy: FakeTenancy
    directory: FakeDirectory
    checkpoints: MemoryCheckpointStore
    idempotency: MemoryIdempotencyStore
    memory_items: InMemoryMemoryItems
    settings: ResearchSettings
    deps: StepDeps
    collections: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    chunks: list[str] = field(default_factory=list)

    def step(self) -> ResearchPackStep:
        return ResearchPackStep(self.deps)

    def data(self, **over: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "topic": {
                "title": "What a stop-loss is",
                "brief": None,
                "angle": None,
                "language": "en-IN",
                "video_kind": "GENERAL",
                "course_chapter_pointer": None,
            },
            "channel_category": "finance",
            "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
            "library_scope": {"collection_keys": None},
            "owner_references": [],
            "revision": None,
        }
        base.update(over)
        return base

    def task_input(self, data: dict[str, Any] | None = None, **over: Any) -> TaskInput:
        data = data if data is not None else self.data()
        doc: dict[str, Any] = {
            "org_id": self.org,
            "job_id": self.job,
            "task_id": self.task,
            "project_id": self.project,
            "channel_id": self.channel,
            "agent_id": "agent_04",
            "source_agent": "agent_01",
            "priority": "NORMAL",
            "deadline": None,
            "context_refs": [],
            "resource_budget": {
                "max_cost_micros": 1_000_000,
                "currency": "USD",
                "max_wall_ms": 600000,
                "max_llm_calls": 20,
            },
            "payload": {
                "payload_schema": "agent_04.research_pack.input",
                "payload_schema_version": "1.0.0",
                "data": data,
            },
            "correlation_id": new_id(Prefix.CORRELATION),
            "idempotency_key": str(task_key(self.org, self.job, 0)),
            "retry_count": 0,
            "schema_version": "1.0.0",
        }
        doc.update(over)
        return TaskInput.model_validate(doc)

    def add_chunk(
        self,
        body: str,
        *,
        source: str | None = None,
        collection: str = "general_trading",
        chunk_release: str | None = None,
        no: int | None = None,
    ) -> str:
        src = source or self.sources[collection]
        cid = new_id(Prefix.KNOWLEDGE_CHUNK)
        self.library.add_chunk(
            ChunkRow(
                cid,
                self.org,
                self.channel,
                src,
                self.collections[collection],
                1,
                no or len(self.chunks) + 1,
                "Chapter 1",
                None,
                3,
                4,
                "en",
                body,
                hashlib.sha256(body.encode()).hexdigest(),
                release_approval_id=chunk_release,
            )
        )
        self.chunks.append(cid)
        return cid

    def add_source(self, collection: str, **over: Any) -> str:
        sid = new_id(Prefix.KNOWLEDGE_SOURCE)
        fields: dict[str, Any] = {
            "source_id": sid,
            "org_id": self.org,
            "channel_id": self.channel,
            "collection_id": self.collections[collection],
            "kind": KnowledgeSourceKind.BOOK,
            "title": "Invented Trading Primer",
            "author": "A. Writer",
            "edition": "1",
            "language": "en",
            "ownership": SourceOwnership.OWNED_COPY,
            "status": KnowledgeSourceStatus.INDEXED,
            "ingest_version": 1,
            "content_sha256": "ab" * 32,
            "size_bytes": 10,
        }
        fields.update(over)
        self.library.add_source(SourceView(**fields))
        self.sources.setdefault(collection, sid)
        return sid


def build_world(responder: Callable[[LlmRequest], str] = default_responder) -> World:
    org, channel = str(ORG.new()), str(CHANNEL.new())
    project, job, task = str(PROJECT.new()), str(JOB.new()), str(TASK.new())
    library = InMemoryKnowledgeLibrary()
    storage, tenancy = MemoryBlobStorage(), FakeTenancy()
    directory = FakeDirectory()
    directory.channels[(org, channel)] = ChannelRecord(org, channel, True)
    directory.workspaces[(org, project)] = "wsp_x"
    settings = make_settings()
    packs = StaticRulePacks(
        {
            "rp.youtube_general": RulePackText(
                "rp.youtube_general",
                RulePackScope.PLATFORM,
                "1",
                "PLATFORM RULES: YTG-R9 source use.",
            ),
            "rp.finance_sebi_in": RulePackText(
                "rp.finance_sebi_in", RulePackScope.PLATFORM, "3", "PLATFORM RULES: FIN-R1..R13."
            ),
        }
    )
    llm = ScriptedLlm(responder)
    web = FakeWebFetchAdapter(allowed_hosts=frozenset({"example.org", "gov.example"}))
    budget, ledger, audit = FakeBudget(), FakeLedger(), FakeAuditLog()
    checkpoints, idem, memory_items = (
        MemoryCheckpointStore(),
        MemoryIdempotencyStore(),
        InMemoryMemoryItems(),
    )
    deps = StepDeps(
        llm=llm,
        web=web,
        library=library,
        directory=directory,
        tenancy=tenancy,
        storage=storage,
        checkpoints=checkpoints,
        idempotency=idem,
        budget=budget,
        ledger=ledger,
        audit=audit,
        clock=FixedClock(),
        settings=settings,
        prompts=PromptLoader(PROMPTS, packs),
        memory=PackMemory(memory_items, 86_400_000),
        resolver_factory=ResolverFactory(library, storage),
    )
    world = World(
        org,
        channel,
        project,
        job,
        task,
        library,
        storage,
        llm,
        web,
        budget,
        ledger,
        audit,
        tenancy,
        directory,
        checkpoints,
        idem,
        memory_items,
        settings,
        deps,
    )
    for key, restricted in (("general_trading", False), ("owner_method", True)):
        cid = new_id(Prefix.KNOWLEDGE_COLLECTION)
        library.add_collection(org, channel, CollectionView(cid, key, key, restricted))
        world.collections[key] = cid
    world.add_source("general_trading")
    world.add_chunk(BODY_1)
    world.add_chunk(BODY_2)
    return world


@pytest.fixture
def world() -> World:
    return build_world()


def approval(world: World, **over: Any) -> ApprovalView:
    fields: dict[str, Any] = {
        "approval_id": new_id(Prefix.APPROVAL),
        "org_id": world.org,
        "kind": ApprovalKind.KNOWLEDGE_RELEASE,
        "state": ApprovalState.APPROVED,
    }
    fields.update(over)
    view = ApprovalView(**fields)
    world.library.add_approval(view)
    return view


_ = ATTEMPT, CORRELATION


def make_run(world: World, log_name: str = "amw.agent_04") -> Any:
    """A ``RunInfo`` for direct step tests (audit rows are kept in ``run.audit.rows``)."""
    from agent_04_research_knowledge.library.models import TenantScope
    from agent_04_research_knowledge.observability import EventLogger, LogContext
    from agent_04_research_knowledge.runtime import CallCounter, RunInfo
    from amw_core.interfaces import TenantContext

    class ListAudit:
        def __init__(self) -> None:
            self.rows: list[tuple[str, str, str | None, dict[str, Any]]] = []

        def record(
            self, action: str, target_kind: str, target_id: str | None, details: Any
        ) -> None:
            self.rows.append((action, target_kind, target_id, dict(details)))

    ctx = TenantContext(world.org, "agent_04", None)  # type: ignore[arg-type]
    return RunInfo(
        context=ctx,
        scope=TenantScope(world.org, world.channel),
        job_id=world.job,  # type: ignore[arg-type]
        task_id=world.task,  # type: ignore[arg-type]
        attempt_id=ATTEMPT.new(),
        currency="USD",
        log=EventLogger(LogContext(world.org, None, world.job, world.task, None)),
        audit=ListAudit(),
        counter=CallCounter(20),
    )
