"""In-memory ``KnowledgeLibrary`` (tests, development): same filters as the SQL contract.

Full-text matching emulates ``websearch_to_tsquery`` AND semantics: every query term must occur
in the chunk. Rank is a deterministic stand-in for ``ts_rank_cd``. Rows are partitioned by org
and channel exactly as the explicit SQL predicates do.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import replace

from agent_04_research_knowledge.errors import InputInvalid
from agent_04_research_knowledge.guards.copy_guard import normalise
from agent_04_research_knowledge.guards.restricted import ApprovalView
from agent_04_research_knowledge.library.models import (
    ChunkHit,
    ChunkRow,
    CollectionView,
    IngestWrite,
    SearchRequest,
    SourceView,
    TenantScope,
)
from amw_core.enums import KnowledgeSourceStatus, SourceOwnership


def fts_terms(text: str, language: str) -> list[str]:
    """Lower-cased word tokens; English gets a plural-stripping stand-in for stemming."""
    words = normalise(text)
    if language.split("-", 1)[0].lower() == "en":
        words = [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words]
    return words


class InMemoryKnowledgeLibrary:
    def __init__(self) -> None:
        self._collections: dict[tuple[str, str, str], CollectionView] = {}
        self._sources: dict[tuple[str, str], SourceView] = {}
        self._chunks: dict[str, ChunkRow] = {}
        self._approvals: dict[tuple[str, str], ApprovalView] = {}
        self.search_calls = 0

    # ---- seeding (test and development helpers; not part of the Protocol) ----
    def add_collection(self, org_id: str, channel_id: str, view: CollectionView) -> None:
        self._collections[(org_id, channel_id, view.collection_id)] = view

    def add_source(self, source: SourceView) -> None:
        self._sources[(source.org_id, source.source_id)] = source

    def add_chunk(self, chunk: ChunkRow) -> None:
        self._chunks[chunk.chunk_id] = chunk

    def add_approval(self, approval: ApprovalView) -> None:
        self._approvals[(approval.org_id, approval.approval_id)] = approval

    # ---- KnowledgeLibrary ----
    def collections_for_channel(self, scope: TenantScope) -> Sequence[CollectionView]:
        return sorted(
            (
                v
                for (o, c, _), v in self._collections.items()
                if (o, c) == (scope.org_id, scope.channel_id)
            ),
            key=lambda v: v.collection_key,
        )

    def get_source(self, scope: TenantScope, source_id: str) -> SourceView | None:
        source = self._sources.get((scope.org_id, source_id))
        if source is None or source.channel_id != scope.channel_id:
            return None
        return source

    def _collection(self, scope: TenantScope, collection_id: str) -> CollectionView | None:
        return self._collections.get((scope.org_id, scope.channel_id, collection_id))

    def search(self, scope: TenantScope, request: SearchRequest) -> Sequence[ChunkHit]:
        self.search_calls += 1
        terms = fts_terms(request.text, request.language)
        if not terms or request.limit < 1:
            return []
        hits: list[ChunkHit] = []
        for chunk in self._chunks.values():
            if (chunk.org_id, chunk.channel_id) != (scope.org_id, scope.channel_id):
                continue
            if chunk.collection_id not in request.collection_ids:
                continue
            source = self.get_source(scope, chunk.source_id)
            collection = self._collection(scope, chunk.collection_id)
            if source is None or collection is None:
                continue
            if (
                source.status is not KnowledgeSourceStatus.INDEXED
                or source.ownership is SourceOwnership.UNKNOWN
                or chunk.ingest_version != source.ingest_version
            ):
                continue
            if request.source_ids is not None and chunk.source_id not in request.source_ids:
                continue
            counts = Counter(fts_terms(chunk.body, chunk.language))
            if any(counts[t] == 0 for t in terms):
                continue
            total = sum(counts.values()) or 1
            rank = len(set(terms)) + sum(counts[t] for t in terms) / total
            hits.append(
                ChunkHit(
                    chunk_id=chunk.chunk_id,
                    org_id=chunk.org_id,
                    channel_id=chunk.channel_id,
                    source_id=chunk.source_id,
                    collection_id=chunk.collection_id,
                    collection_key=collection.collection_key,
                    collection_restricted=collection.restricted,
                    chapter=chunk.chapter,
                    page_from=chunk.page_from,
                    page_to=chunk.page_to,
                    language=chunk.language,
                    rank=rank,
                    body_sha256=chunk.body_sha256,
                    source_release_approval_id=source.release_approval_id,
                    chunk_release_approval_id=chunk.release_approval_id,
                )
            )
        hits.sort(key=lambda h: (-h.rank, h.chunk_id))
        return hits[: request.limit]

    def load_chunks(self, scope: TenantScope, chunk_ids: Sequence[str]) -> Sequence[ChunkRow]:
        rows = [self._chunks[c] for c in chunk_ids if c in self._chunks]
        return [r for r in rows if (r.org_id, r.channel_id) == (scope.org_id, scope.channel_id)]

    def approval(self, scope: TenantScope, approval_id: str) -> ApprovalView | None:
        return self._approvals.get((scope.org_id, approval_id))

    def released_chunk_ids(
        self, scope: TenantScope, approval_id: str, collection_id: str
    ) -> frozenset[str]:
        return frozenset(
            c.chunk_id
            for c in self._chunks.values()
            if (c.org_id, c.channel_id) == (scope.org_id, scope.channel_id)
            and c.collection_id == collection_id
            and c.release_approval_id == approval_id
        )

    def set_source_status(
        self,
        scope: TenantScope,
        source_id: str,
        status: KnowledgeSourceStatus,
        ingest_version: int | None = None,
        reliability_score: float | None = None,
    ) -> SourceView:
        source = self.get_source(scope, source_id)
        if source is None:
            raise InputInvalid("unknown source")
        updated = replace(
            source,
            status=status,
            ingest_version=source.ingest_version if ingest_version is None else ingest_version,
            reliability_score=(
                source.reliability_score if reliability_score is None else reliability_score
            ),
        )
        self._sources[(scope.org_id, source_id)] = updated
        return updated

    def insert_chunks(self, scope: TenantScope, chunks: Sequence[ChunkRow]) -> IngestWrite:
        written = skipped = 0
        keys = {
            (c.org_id, c.source_id, c.ingest_version, c.chunk_no) for c in self._chunks.values()
        }
        for chunk in chunks:
            if (chunk.org_id, chunk.channel_id) != (scope.org_id, scope.channel_id):
                raise InputInvalid("chunk does not belong to the tenant scope")
            key = (chunk.org_id, chunk.source_id, chunk.ingest_version, chunk.chunk_no)
            if key in keys:
                skipped += 1
                continue
            keys.add(key)
            self._chunks[chunk.chunk_id] = chunk
            written += 1
        return IngestWrite(written, skipped)

    def chunk_count(self, scope: TenantScope, source_id: str, ingest_version: int) -> int:
        return sum(
            1
            for c in self._chunks.values()
            if (c.org_id, c.channel_id, c.source_id, c.ingest_version)
            == (scope.org_id, scope.channel_id, source_id, ingest_version)
        )
