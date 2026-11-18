"""S2: LibraryRetriever and CandidateRanker (blueprint 6.6, 10.3; ADR-013 section 2.4).

Retrieval is read-only and idempotent. Filters run in the library query (org, channel,
collection, current ingest version, source status, ownership) and the restricted-collection gate
runs again on the candidate list and on the loaded rows before any text reaches the model.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_04_research_knowledge.errors import CrossTenantRef
from agent_04_research_knowledge.guards.restricted import (
    ApprovalLookup,
    ApprovalView,
    ChunkMeta,
    RestrictedCollectionGate,
    TopicFlags,
)
from agent_04_research_knowledge.library.models import (
    ChunkHit,
    CollectionView,
    SearchRequest,
    TenantScope,
)
from agent_04_research_knowledge.library.protocol import KnowledgeLibrary
from agent_04_research_knowledge.models.plan import PlannedConcept
from agent_04_research_knowledge.runtime import RunInfo
from amw_core.enums import VideoKind

SECURITY_EVENT = "security.cross_tenant_ref"


@dataclass(frozen=True, slots=True)
class RetrievalLimits:
    top_k: int
    max_per_source: int
    pool: int
    """chunks fetched per query before the diversity cap and the top-k cut."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """A chunk that passed every filter and the gate; no text (the body is loaded lazily)."""

    chunk_id: str
    source_id: str
    collection_id: str
    collection_key: str
    chapter: str | None
    page_from: int | None
    page_to: int | None
    language: str
    rank: float
    body_sha256: str
    method_labelled: bool
    release_approval_id: str | None
    meta: ChunkMeta


@dataclass(frozen=True, slots=True)
class Passage:
    """Passage text lives in memory only for the notes call (never persisted, never logged)."""

    chunk_id: str
    text: str
    language: str

    def __repr__(self) -> str:
        return f"Passage({self.chunk_id})"


@dataclass
class RetrievalResult:
    concept_id: str
    candidates: list[Candidate] = field(default_factory=list)
    restricted_blocked: dict[str, int] = field(default_factory=dict)
    """collection key to the number of relevant restricted chunks the gate held back."""
    gate_denied: dict[str, int] = field(default_factory=dict)
    """gate reason to count."""


class _LibraryApprovals:
    def __init__(self, library: KnowledgeLibrary, scope: TenantScope) -> None:
        self._library, self._scope = library, scope

    def approval(self, approval_id: str) -> ApprovalView | None:
        return self._library.approval(self._scope, approval_id)

    def released_chunk_ids(self, approval_id: str, collection_id: str) -> frozenset[str]:
        return self._library.released_chunk_ids(self._scope, approval_id, collection_id)


def allowed_collections(
    collections: Sequence[CollectionView],
    scope_keys: Sequence[str] | None,
    concept: PlannedConcept,
    video_kind: VideoKind,
) -> frozenset[str]:
    """D-4: the channel's collections within the request scope. A restricted collection is
    searched only for a method topic and only for a concept that asks for method material."""
    method = video_kind is VideoKind.METHOD_TOPIC and concept.wants_method_material
    chosen = []
    for c in collections:
        if scope_keys is not None and c.collection_key not in scope_keys:
            continue
        if (
            concept.target_collection_keys
            and c.collection_key not in concept.target_collection_keys
        ):
            continue
        if c.restricted and not method:
            continue
        chosen.append(c.collection_id)
    return frozenset(chosen)


class LibraryRetriever:
    def __init__(
        self, library: KnowledgeLibrary, gate: RestrictedCollectionGate | None = None
    ) -> None:
        self._library = library
        self._gate = gate or RestrictedCollectionGate()

    def _security_event(self, run: RunInfo) -> None:
        run.log.error(SECURITY_EVENT)
        run.audit.record(SECURITY_EVENT, "task", run.task_id, {"org_id": run.context.org_id})

    def _meta(self, hit: ChunkHit) -> ChunkMeta:
        return ChunkMeta(
            chunk_id=hit.chunk_id,
            org_id=hit.org_id,
            collection_id=hit.collection_id,
            collection_key=hit.collection_key,
            collection_restricted=hit.collection_restricted,
            source_id=hit.source_id,
            source_release_approval_id=hit.source_release_approval_id,
            chunk_release_approval_id=hit.chunk_release_approval_id,
        )

    def retrieve(
        self,
        run: RunInfo,
        concept: PlannedConcept,
        allowed: frozenset[str],
        topic: TopicFlags,
        limits: RetrievalLimits,
        source_ids: frozenset[str] | None = None,
    ) -> RetrievalResult:
        scope = run.scope
        result = RetrievalResult(concept.concept_id)
        best: dict[str, ChunkHit] = {}
        for query in concept.queries:
            request = SearchRequest(query.text, query.language, allowed, limits.pool, source_ids)
            for hit in self._library.search(scope, request):
                if (hit.org_id, hit.channel_id) != (scope.org_id, scope.channel_id):
                    self._security_event(run)
                    raise CrossTenantRef("search returned a row of another tenant")
                if hit.chunk_id not in best or hit.rank > best[hit.chunk_id].rank:
                    best[hit.chunk_id] = hit
        lookup: ApprovalLookup = _LibraryApprovals(self._library, scope)
        kept: list[Candidate] = []
        for hit in sorted(best.values(), key=lambda h: (-h.rank, h.chunk_id)):
            meta = self._meta(hit)
            try:
                decision = self._gate.evaluate(meta, topic, lookup)
            except CrossTenantRef:
                self._security_event(run)
                raise
            if meta.collection_restricted:
                run.audit.record(
                    "knowledge.gate_decision",
                    "knowledge_chunk",
                    hit.chunk_id,
                    {
                        "allowed": decision.allowed,
                        "reason": decision.reason.value if decision.reason else None,
                        "approval_id": decision.release_approval_id,
                    },
                )
            if not decision.allowed:
                if decision.reason is not None:
                    key = decision.reason.value
                    result.gate_denied[key] = result.gate_denied.get(key, 0) + 1
                if decision.restricted_pending:
                    result.restricted_blocked[hit.collection_key] = (
                        result.restricted_blocked.get(hit.collection_key, 0) + 1
                    )
                continue
            kept.append(
                Candidate(
                    chunk_id=hit.chunk_id,
                    source_id=hit.source_id,
                    collection_id=hit.collection_id,
                    collection_key=hit.collection_key,
                    chapter=hit.chapter,
                    page_from=hit.page_from,
                    page_to=hit.page_to,
                    language=hit.language,
                    rank=hit.rank,
                    body_sha256=hit.body_sha256,
                    method_labelled=decision.method_labelled,
                    release_approval_id=decision.release_approval_id,
                    meta=meta,
                )
            )
        result.candidates = rank_candidates(kept, limits)
        run.audit.record(
            "knowledge.retrieve",
            "task",
            run.task_id,
            {
                "concept_id": concept.concept_id,
                "collection_keys": sorted({c.collection_key for c in result.candidates}),
                "candidates": len(result.candidates),
                "restricted_blocked": sum(result.restricted_blocked.values()),
                "chunk_ids": [c.chunk_id for c in result.candidates],
            },
        )
        run.log.info(
            "research.retrieve",
            concept_id=concept.concept_id,
            candidates=len(result.candidates),
            restricted_blocked=sum(result.restricted_blocked.values()),
        )
        return result

    def load_passages(
        self, run: RunInfo, candidates: Sequence[Candidate], topic: TopicFlags
    ) -> list[Passage]:
        """Load text just before the notes call; defence in depth (10.3, 19.1 control 1).

        A row of another org or channel raises ``CrossTenantRef``; a row whose hash differs from
        the candidate's is dropped; the gate is evaluated once more.
        """
        scope = run.scope
        by_id = {c.chunk_id: c for c in candidates}
        rows = self._library.load_chunks(scope, [c.chunk_id for c in candidates])
        lookup: ApprovalLookup = _LibraryApprovals(self._library, scope)
        out: list[Passage] = []
        for row in rows:
            if (row.org_id, row.channel_id) != (scope.org_id, scope.channel_id):
                self._security_event(run)
                raise CrossTenantRef("loaded row of another tenant")
            cand = by_id.get(row.chunk_id)
            if cand is None or row.collection_id != cand.collection_id:
                continue
            actual = hashlib.sha256(row.body.encode("utf-8")).hexdigest()
            if actual != row.body_sha256 or row.body_sha256 != cand.body_sha256:
                run.log.warning("research.chunk_hash_changed", chunk_id=row.chunk_id)
                continue
            try:
                decision = self._gate.evaluate(cand.meta, topic, lookup)
            except CrossTenantRef:
                self._security_event(run)
                raise
            if not decision.allowed:
                continue
            out.append(Passage(row.chunk_id, row.body, row.language))
        order = {c.chunk_id: i for i, c in enumerate(candidates)}
        out.sort(key=lambda p: order[p.chunk_id])
        return out


def rank_candidates(candidates: Sequence[Candidate], limits: RetrievalLimits) -> list[Candidate]:
    """CandidateRanker (6.6 steps 3 and 4): relevance order only (never page or chapter order),
    at most ``max_per_source`` per source, then the top ``top_k``."""
    ordered = sorted(candidates, key=lambda c: (-c.rank, c.chunk_id))
    per_source: dict[str, int] = {}
    kept: list[Candidate] = []
    for cand in ordered:
        if per_source.get(cand.source_id, 0) >= limits.max_per_source:
            continue
        per_source[cand.source_id] = per_source.get(cand.source_id, 0) + 1
        kept.append(cand)
        if len(kept) >= limits.top_k:
            break
    return kept
