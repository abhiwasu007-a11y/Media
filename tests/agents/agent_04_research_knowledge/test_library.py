"""Knowledge library Protocol contract, retrieval and SQL statement checks (blueprint 6.6, 10.3, 13)."""
# ruff: noqa: E501, PT018

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import pytest

from agent_04_research_knowledge.errors import CrossTenantRef, InputInvalid
from agent_04_research_knowledge.guards.restricted import ChunkMeta, TopicFlags
from agent_04_research_knowledge.library import sql as sqlmod
from agent_04_research_knowledge.library.memory import InMemoryKnowledgeLibrary
from agent_04_research_knowledge.library.models import (
    ChunkRow,
    CollectionView,
    SearchRequest,
    TenantScope,
)
from agent_04_research_knowledge.library.protocol import KnowledgeLibrary
from agent_04_research_knowledge.library.search import FtsQueryBuilder
from agent_04_research_knowledge.models.plan import PlannedConcept
from agent_04_research_knowledge.steps.retrieve import (
    Candidate,
    LibraryRetriever,
    RetrievalLimits,
    allowed_collections,
    rank_candidates,
)
from amw_core.enums import KnowledgeSourceStatus, SourceOwnership, VideoKind
from tests.agents.agent_04_research_knowledge.conftest import (
    BODY_1,
    approval,
    build_world,
    make_run,
)

pytestmark = pytest.mark.unit
LIMITS = RetrievalLimits(top_k=4, max_per_source=2, pool=12)
GENERAL = TopicFlags(VideoKind.GENERAL, "t")
METHOD = TopicFlags(VideoKind.METHOD_TOPIC, "t")


def concept(
    query: str = "stop loss", method: bool = False, targets: tuple[str, ...] = ()
) -> PlannedConcept:
    return PlannedConcept.model_validate(
        {
            "concept_id": "c01",
            "label": "x",
            "label_en": "x",
            "kind": "CORE_CONCEPT",
            "rationale": "r",
            "evidence_needs": ["DEFINITION"],
            "time_reference": "TIMELESS",
            "queries": [{"text": query, "language": "en", "purpose": "PRIMARY"}],
            "wants_method_material": method,
            "closes_gap_ids": [],
            "target_collection_keys": list(targets),
        }
    )


# ---- Protocol contract (run on every KnowledgeLibrary implementation) ------------------------
def contract_checks(make: Callable[[], Any]) -> None:
    w = make()
    lib: KnowledgeLibrary = w.library
    scope = TenantScope(w.org, w.channel)
    allowed = frozenset(w.collections.values())
    hits = lib.search(scope, SearchRequest("stop loss", "en", allowed, 10))
    assert [h.chunk_id for h in hits] == [w.chunks[0]]
    assert all(h.org_id == w.org and h.channel_id == w.channel for h in hits)
    assert lib.search(scope, SearchRequest("stop loss", "en", frozenset(), 10)) == []
    assert lib.search(scope, SearchRequest("stop loss", "en", allowed, 0)) == []
    foreign = TenantScope(w.org, "chn_other")
    assert lib.search(foreign, SearchRequest("stop loss", "en", allowed, 10)) == []
    assert lib.get_source(foreign, next(iter(w.sources.values()))) is None
    rows = lib.load_chunks(scope, [w.chunks[0], "kch_missing"])
    assert [r.chunk_id for r in rows] == [w.chunks[0]]
    assert lib.load_chunks(foreign, [w.chunks[0]]) == []
    row = ChunkRow(
        "kch_new",
        w.org,
        w.channel,
        next(iter(w.sources.values())),
        w.collections["general_trading"],
        2,
        1,
        None,
        None,
        None,
        None,
        "en",
        "text",
        "00" * 32,
    )
    first = lib.insert_chunks(scope, [row])
    again = lib.insert_chunks(scope, [row])
    assert (first.written, first.skipped_existing) == (1, 0)
    assert (again.written, again.skipped_existing) == (0, 1)
    assert lib.chunk_count(scope, row.source_id, 2) == 1


def test_inmemory_satisfies_contract() -> None:
    assert isinstance(InMemoryKnowledgeLibrary(), KnowledgeLibrary)
    contract_checks(build_world)


def test_search_filters_status_ownership_version_and_source_ids() -> None:
    w = build_world()
    scope = TenantScope(w.org, w.channel)
    allowed = frozenset(w.collections.values())
    retired = w.add_source("general_trading", status=KnowledgeSourceStatus.RETIRED)
    failed = w.add_source("general_trading", status=KnowledgeSourceStatus.FAILED)
    unknown = w.add_source("general_trading", ownership=SourceOwnership.UNKNOWN)
    old = w.add_source("general_trading", ingest_version=2)
    for src in (retired, failed, unknown, old):
        w.add_chunk(BODY_1, source=src)
    ids = {
        h.chunk_id for h in w.library.search(scope, SearchRequest("stop loss", "en", allowed, 20))
    }
    assert ids == {w.chunks[0]}  # none of the filtered sources, nor the stale ingest_version
    only = frozenset({retired})
    assert not w.library.search(scope, SearchRequest("stop loss", "en", allowed, 20, only))


def test_two_orgs_same_text_returns_only_own() -> None:
    a, b = build_world(), build_world()
    a.library._chunks.update(b.library._chunks)
    a.library._sources.update(b.library._sources)
    a.library._collections.update(b.library._collections)
    scope = TenantScope(a.org, a.channel)
    hits = a.library.search(
        scope,
        SearchRequest(
            "stop loss",
            "en",
            frozenset(a.collections.values()) | frozenset(b.collections.values()),
            20,
        ),
    )
    assert hits and all(h.org_id == a.org for h in hits)
    assert not a.library.search(
        TenantScope(a.org, b.channel),
        SearchRequest("stop loss", "en", frozenset(b.collections.values()), 5),
    )


# ---- retriever -------------------------------------------------------------------------------
def test_retrieve_basic_audit_and_no_text() -> None:
    w = build_world()
    run = make_run(w)
    res = LibraryRetriever(w.library).retrieve(
        run,
        concept(),
        allowed_collections(
            w.library.collections_for_channel(run.scope), None, concept(), VideoKind.GENERAL
        ),
        GENERAL,
        LIMITS,
    )
    assert [c.chunk_id for c in res.candidates] == [w.chunks[0]]
    assert res.restricted_blocked == {}
    actions = [a[0] for a in run.audit.rows]
    assert actions == ["knowledge.retrieve"]
    assert BODY_1 not in repr(run.audit.rows) and BODY_1 not in repr(res)


def test_allowed_collections_rules() -> None:
    w = build_world()
    cols = w.library.collections_for_channel(make_run(w).scope)
    general = w.collections["general_trading"]
    method_id = w.collections["owner_method"]
    assert allowed_collections(cols, None, concept(), VideoKind.GENERAL) == {general}
    assert allowed_collections(cols, None, concept(method=True), VideoKind.GENERAL) == {general}
    assert allowed_collections(cols, None, concept(), VideoKind.METHOD_TOPIC) == {general}
    assert allowed_collections(cols, None, concept(method=True), VideoKind.METHOD_TOPIC) == {
        general,
        method_id,
    }
    assert allowed_collections(
        cols, ["owner_method"], concept(method=True), VideoKind.METHOD_TOPIC
    ) == {method_id}
    assert allowed_collections(
        cols, None, concept(targets=("general_trading",)), VideoKind.GENERAL
    ) == {general}


def test_restricted_chunk_gate_pending_released_and_general() -> None:
    w = build_world()
    run = make_run(w)
    src = w.add_source("owner_method")
    w.add_chunk(
        "Method note about the zone entry rule for stop loss placement.",
        source=src,
        collection="owner_method",
    )
    cols = w.library.collections_for_channel(run.scope)
    retriever = LibraryRetriever(w.library)
    method_concept = concept(method=True)
    allowed = allowed_collections(cols, None, method_concept, VideoKind.METHOD_TOPIC)
    res = retriever.retrieve(run, method_concept, allowed, METHOD, LIMITS)
    assert res.restricted_blocked == {"owner_method": 1} and res.gate_denied == {
        "RELEASE_MISSING": 1
    }
    assert all(not c.method_labelled for c in res.candidates)
    # release at source level: now allowed and labelled
    apr = approval(w)
    w.library._sources[(w.org, src)] = __import__("dataclasses").replace(
        w.library._sources[(w.org, src)], release_approval_id=apr.approval_id
    )
    res = retriever.retrieve(run, method_concept, allowed, METHOD, LIMITS)
    assert any(
        c.method_labelled and c.release_approval_id == apr.approval_id for c in res.candidates
    )
    # a general topic never sees it, even released
    general_allowed = allowed_collections(cols, None, method_concept, VideoKind.GENERAL)
    res = retriever.retrieve(run, method_concept, general_allowed, GENERAL, LIMITS)
    assert all(c.collection_key != "owner_method" for c in res.candidates)
    assert res.restricted_blocked == {}
    gate_rows = [a for a in run.audit.rows if a[0] == "knowledge.gate_decision"]
    assert gate_rows and all("approval_id" in a[3] for a in gate_rows)


def test_cross_tenant_rows_raise_and_emit_event() -> None:
    w = build_world()

    class Leaky(InMemoryKnowledgeLibrary):
        def search(self, scope, request):  # type: ignore[no-untyped-def]
            hits = super().search(scope, request)
            from dataclasses import replace

            return [replace(h, org_id="org_other") for h in hits]

    leaky = Leaky()
    leaky.__dict__.update(w.library.__dict__)
    run = make_run(w)
    with pytest.raises(CrossTenantRef):
        LibraryRetriever(leaky).retrieve(
            run, concept(), frozenset(w.collections.values()), GENERAL, LIMITS
        )
    assert any(a[0] == "security.cross_tenant_ref" for a in run.audit.rows)


def test_load_passages_hash_change_and_foreign_rows() -> None:
    w = build_world()
    run = make_run(w)
    retriever = LibraryRetriever(w.library)
    res = retriever.retrieve(run, concept(), frozenset(w.collections.values()), GENERAL, LIMITS)
    passages = retriever.load_passages(run, res.candidates, GENERAL)
    assert [p.chunk_id for p in passages] == [res.candidates[0].chunk_id] and passages[
        0
    ].text == BODY_1
    assert BODY_1 not in repr(passages[0])
    from dataclasses import replace

    row = w.library._chunks[w.chunks[0]]
    w.library._chunks[w.chunks[0]] = replace(row, body=BODY_1 + " changed")
    assert retriever.load_passages(run, res.candidates, GENERAL) == []
    w.library._chunks[w.chunks[0]] = replace(row, org_id="org_other")

    class Foreign(InMemoryKnowledgeLibrary):
        def load_chunks(self, scope, chunk_ids):  # type: ignore[no-untyped-def]
            return [r for r in self._chunks.values() if r.chunk_id in chunk_ids]

    foreign = Foreign()
    foreign.__dict__.update(w.library.__dict__)
    with pytest.raises(CrossTenantRef):
        LibraryRetriever(foreign).load_passages(run, res.candidates, GENERAL)


def _cand(i: int, src: str, rank: float) -> Candidate:
    meta = ChunkMeta(f"kch_{i}", "org_x", "kcl", "k", False, src)
    return Candidate(
        f"kch_{i}", src, "kcl", "k", None, None, None, "en", rank, "h", False, None, meta
    )


def test_rank_candidates_diversity_cap_and_relevance_order() -> None:
    cands = [_cand(i, "S1", 10 - i) for i in range(6)] + [
        _cand(10 + i, "S2", 1 + i) for i in range(2)
    ]
    kept = rank_candidates(cands, RetrievalLimits(4, 2, 12))
    by_source: dict[str, int] = {}
    for c in kept:
        by_source[c.source_id] = by_source.get(c.source_id, 0) + 1
    assert by_source == {"S1": 2, "S2": 2}
    assert [c.rank for c in kept] == sorted(
        (c.rank for c in kept), reverse=True
    )  # relevance, not page


def test_fts_query_builder() -> None:
    b = FtsQueryBuilder({"en": "english"}, "simple")
    assert b.build("en-IN", "stop\x00 loss").config == "english"
    assert b.build("mr", "x").config == "simple"
    assert len(b.build("en", "a" * 500).text) == 120
    with pytest.raises(Exception, match="configuration"):
        FtsQueryBuilder({"en": "english; drop"}, "simple")


# ---- SQL module: static checks and mapping through a recording runner ------------------------
def test_sql_statements_are_tenant_scoped_and_allow_listed() -> None:
    tables = {"knowledge_collections", "knowledge_sources", "knowledge_chunks", "approvals"}
    for name, stmt in sqlmod.STATEMENTS.items():
        used = set(re.findall(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([a-z_]+)\b(?!\()", stmt))
        assert used <= tables, (name, used)
        assert "%(org_id)s" in stmt, name
        assert not re.search(r"\{|f\"|\+ ", stmt)
        if name != "approval":
            assert ("channel_id = %(channel_id)s" in stmt) or "%(channel_id)s" in stmt, name
            if name != "insert_chunk":
                assert "channel_id = %(channel_id)s" in stmt, name
    assert tables == sqlmod.ALLOWED_TABLES
    assert "ingest_version = s.ingest_version" in sqlmod.SEARCH
    assert "s.status = 'INDEXED'" in sqlmod.SEARCH and "s.ownership <> 'UNKNOWN'" in sqlmod.SEARCH


class RecordingRunner:
    def __init__(self, rows: Sequence[Mapping[str, Any]] = (), affected: int = 1) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []
        self._rows, self._affected = rows, affected

    def rows(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        self.calls.append((sql, params))
        return self._rows

    def execute(self, sql: str, params: Mapping[str, Any]) -> int:
        self.calls.append((sql, params))
        return self._affected


def make_sql_lib(runner: RecordingRunner) -> sqlmod.SqlKnowledgeLibrary:
    @contextmanager
    def factory(scope: TenantScope) -> Iterator[RecordingRunner]:
        yield runner

    return sqlmod.SqlKnowledgeLibrary(factory, FtsQueryBuilder({"en": "english"}, "simple"))


def test_sql_library_parameters_and_mapping() -> None:
    from amw_core.ids import CHANNEL, ORG, Prefix, new_id

    org, ch = str(ORG.new()), str(CHANNEL.new())
    scope = TenantScope(org, ch)
    kcl, ksr, kch = (
        new_id(Prefix.KNOWLEDGE_COLLECTION),
        new_id(Prefix.KNOWLEDGE_SOURCE),
        new_id(Prefix.KNOWLEDGE_CHUNK),
    )
    import uuid

    row = {
        "id": uuid.UUID(kch.split("_", 1)[1]),
        "source_id": uuid.UUID(ksr.split("_", 1)[1]),
        "collection_id": uuid.UUID(kcl.split("_", 1)[1]),
        "collection_key": "k",
        "restricted": True,
        "chapter": None,
        "page_from": 1,
        "page_to": 2,
        "language": "en",
        "rank": 0.5,
        "body_sha256": "ab",
        "source_release_approval_id": None,
        "chunk_release_approval_id": None,
    }
    runner = RecordingRunner([row])
    lib = make_sql_lib(runner)
    hits = lib.search(
        scope, SearchRequest("stop loss", "en", frozenset({kcl}), 5, frozenset({ksr}))
    )
    sql, params = runner.calls[0]
    assert sql == sqlmod.SEARCH and params["ts_config"] == "english" and params["limit"] == 5
    assert params["org_id"] == uuid.UUID(org.split("_", 1)[1]) and params[
        "channel_id"
    ] == uuid.UUID(ch.split("_", 1)[1])
    assert hits[0].chunk_id == kch and hits[0].collection_restricted and hits[0].org_id == org
    assert lib.search(scope, SearchRequest("", "en", frozenset({kcl}), 5)) == []
    assert lib.load_chunks(scope, []) == []
    runner2 = RecordingRunner(affected=0)
    with pytest.raises(InputInvalid):
        make_sql_lib(runner2).set_source_status(scope, ksr, KnowledgeSourceStatus.FAILED)
    assert make_sql_lib(RecordingRunner(affected=1)).insert_chunks(scope, []).written == 0
    cv = CollectionView(kcl, "k", "t", False)
    assert cv.collection_key == "k"
