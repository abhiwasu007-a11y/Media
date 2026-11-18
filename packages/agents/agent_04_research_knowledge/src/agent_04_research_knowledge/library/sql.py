"""PostgreSQL implementation of ``KnowledgeLibrary`` (blueprint 13, 6.6, 19.1).

This module is the only place with SQL text. It is written against 04 section 5.10 and is
**not yet run against a database**: the schema and the tenancy transaction belong to lane L1a, so
until that merges it is tested only through the Protocol contract on the in-memory library and by
static checks of the statements (explicit ``org_id`` and ``channel_id`` predicates, table
allow-list of blueprint 13, no string formatting of values). The runner is opened by the caller
inside ``amw_core.tenancy`` (``SET LOCAL app.org_id``), one short transaction per call.
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any, Protocol

from agent_04_research_knowledge.errors import InputInvalid
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
from agent_04_research_knowledge.library.search import FtsQueryBuilder
from amw_core.enums import (
    ApprovalKind,
    ApprovalState,
    ExtractionMethod,
    KnowledgeSourceKind,
    KnowledgeSourceStatus,
    SourceOwnership,
)
from amw_core.ids import Prefix, format_id, parse_id

ALLOWED_TABLES = frozenset(
    {"knowledge_collections", "knowledge_sources", "knowledge_chunks", "approvals"}
)
"""Tables of blueprint 13 this module may name (``memory_items`` is in ``memory.py``)."""


class SqlRunner(Protocol):
    """A cursor-like handle bound to one open tenant transaction."""

    def rows(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]: ...

    def execute(self, sql: str, params: Mapping[str, Any]) -> int:
        """Number of rows affected."""
        ...


RunnerFactory = Callable[[TenantScope], AbstractContextManager[SqlRunner]]

SELECT_COLLECTIONS = """
SELECT id, collection_key, title, restricted
FROM knowledge_collections
WHERE org_id = %(org_id)s AND channel_id = %(channel_id)s
ORDER BY collection_key
"""

SELECT_SOURCE = """
SELECT id, org_id, channel_id, collection_id, kind, title, author, edition, language, ownership,
       status, ingest_version, encode(content_sha256, 'hex') AS content_sha256, size_bytes,
       release_approval_id, credit_in_description, reliability_score
FROM knowledge_sources
WHERE org_id = %(org_id)s AND channel_id = %(channel_id)s AND id = %(source_id)s
"""

SEARCH = """
SELECT c.id, c.org_id, c.channel_id, c.source_id, c.collection_id, k.collection_key,
       k.restricted, c.chapter, c.page_from, c.page_to, c.language,
       ts_rank_cd(c.search_tsv, q.query) AS rank, encode(c.body_sha256, 'hex') AS body_sha256,
       s.release_approval_id AS source_release_approval_id,
       c.release_approval_id AS chunk_release_approval_id
FROM knowledge_chunks c
JOIN knowledge_sources s ON s.org_id = c.org_id AND s.id = c.source_id
JOIN knowledge_collections k ON k.org_id = c.org_id AND k.id = c.collection_id
CROSS JOIN websearch_to_tsquery(%(ts_config)s::regconfig, %(query)s) AS q(query)
WHERE c.org_id = %(org_id)s AND c.channel_id = %(channel_id)s
  AND s.channel_id = %(channel_id)s AND k.channel_id = %(channel_id)s
  AND c.collection_id = ANY(%(collection_ids)s)
  AND c.ingest_version = s.ingest_version
  AND s.status = 'INDEXED' AND s.ownership <> 'UNKNOWN'
  AND (%(source_ids)s::uuid[] IS NULL OR c.source_id = ANY(%(source_ids)s))
  AND c.search_tsv @@ q.query
ORDER BY rank DESC, c.id
LIMIT %(limit)s
"""

SELECT_CHUNKS = """
SELECT id, org_id, channel_id, source_id, collection_id, ingest_version, chunk_no, chapter,
       section, page_from, page_to, language, body, encode(body_sha256, 'hex') AS body_sha256,
       extraction_method, release_approval_id, token_count
FROM knowledge_chunks
WHERE org_id = %(org_id)s AND channel_id = %(channel_id)s AND id = ANY(%(chunk_ids)s)
"""

SELECT_APPROVAL = """
SELECT id, org_id, kind, state, subject_kind, subject_id, subject_sha256
FROM approvals
WHERE org_id = %(org_id)s AND id = %(approval_id)s
"""

SELECT_RELEASED_CHUNKS = """
SELECT id
FROM knowledge_chunks
WHERE org_id = %(org_id)s AND channel_id = %(channel_id)s
  AND collection_id = %(collection_id)s AND release_approval_id = %(approval_id)s
"""

UPDATE_SOURCE_STATUS = """
UPDATE knowledge_sources
SET status = %(status)s,
    ingest_version = COALESCE(%(ingest_version)s, ingest_version),
    reliability_score = COALESCE(%(reliability_score)s, reliability_score)
WHERE org_id = %(org_id)s AND channel_id = %(channel_id)s AND id = %(source_id)s
"""

INSERT_CHUNK = """
INSERT INTO knowledge_chunks (id, org_id, channel_id, source_id, collection_id, ingest_version,
    chunk_no, extraction_method, release_approval_id, chapter, section, page_from, page_to,
    language, body, body_sha256, search_tsv, token_count)
VALUES (%(id)s, %(org_id)s, %(channel_id)s, %(source_id)s, %(collection_id)s, %(ingest_version)s,
    %(chunk_no)s, %(extraction_method)s, %(release_approval_id)s, %(chapter)s, %(section)s,
    %(page_from)s, %(page_to)s, %(language)s, %(body)s, decode(%(body_sha256)s, 'hex'),
    to_tsvector(%(ts_config)s::regconfig, %(body)s), %(token_count)s)
ON CONFLICT (org_id, source_id, ingest_version, chunk_no) DO NOTHING
"""

COUNT_CHUNKS = """
SELECT count(*) AS n
FROM knowledge_chunks
WHERE org_id = %(org_id)s AND channel_id = %(channel_id)s
  AND source_id = %(source_id)s AND ingest_version = %(ingest_version)s
"""

STATEMENTS: Mapping[str, str] = {
    "collections": SELECT_COLLECTIONS,
    "source": SELECT_SOURCE,
    "search": SEARCH,
    "chunks": SELECT_CHUNKS,
    "approval": SELECT_APPROVAL,
    "released": SELECT_RELEASED_CHUNKS,
    "update_source": UPDATE_SOURCE_STATUS,
    "insert_chunk": INSERT_CHUNK,
    "count": COUNT_CHUNKS,
}


def _uuid(wire: str, prefix: Prefix) -> uuid.UUID:
    return parse_id(wire, prefix)


def _wire(prefix: Prefix, value: Any) -> str:
    return str(format_id(prefix, value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))))


def _opt_wire(prefix: Prefix, value: Any) -> str | None:
    return None if value is None else _wire(prefix, value)


class SqlKnowledgeLibrary:
    """``KnowledgeLibrary`` over a ``SqlRunner`` (one short tenant transaction per call)."""

    def __init__(self, runner: RunnerFactory, fts: FtsQueryBuilder) -> None:
        self._runner = runner
        self._fts = fts

    @staticmethod
    def _base(scope: TenantScope) -> dict[str, Any]:
        return {
            "org_id": _uuid(scope.org_id, Prefix.ORGANISATION),
            "channel_id": _uuid(scope.channel_id, Prefix.CHANNEL),
        }

    def collections_for_channel(self, scope: TenantScope) -> Sequence[CollectionView]:
        with self._runner(scope) as run:
            rows = run.rows(SELECT_COLLECTIONS, self._base(scope))
        return [
            CollectionView(
                _wire(Prefix.KNOWLEDGE_COLLECTION, r["id"]),
                str(r["collection_key"]),
                str(r["title"]),
                bool(r["restricted"]),
            )
            for r in rows
        ]

    def get_source(self, scope: TenantScope, source_id: str) -> SourceView | None:
        params = {**self._base(scope), "source_id": _uuid(source_id, Prefix.KNOWLEDGE_SOURCE)}
        with self._runner(scope) as run:
            rows = run.rows(SELECT_SOURCE, params)
        if not rows:
            return None
        r = rows[0]
        return SourceView(
            source_id=_wire(Prefix.KNOWLEDGE_SOURCE, r["id"]),
            org_id=scope.org_id,
            channel_id=scope.channel_id,
            collection_id=_wire(Prefix.KNOWLEDGE_COLLECTION, r["collection_id"]),
            kind=KnowledgeSourceKind(r["kind"]),
            title=str(r["title"]),
            author=r["author"],
            edition=r["edition"],
            language=str(r["language"]),
            ownership=SourceOwnership(r["ownership"]),
            status=KnowledgeSourceStatus(r["status"]),
            ingest_version=int(r["ingest_version"]),
            content_sha256=str(r["content_sha256"]),
            size_bytes=int(r["size_bytes"]),
            release_approval_id=_opt_wire(Prefix.APPROVAL, r["release_approval_id"]),
            credit_in_description=bool(r["credit_in_description"]),
            reliability_score=None
            if r["reliability_score"] is None
            else float(r["reliability_score"]),
        )

    def search(self, scope: TenantScope, request: SearchRequest) -> Sequence[ChunkHit]:
        query = self._fts.build(request.language, request.text)
        if not query.text or not request.collection_ids or request.limit < 1:
            return []
        params: dict[str, Any] = {
            **self._base(scope),
            "ts_config": query.config,
            "query": query.text,
            "collection_ids": [
                _uuid(c, Prefix.KNOWLEDGE_COLLECTION) for c in request.collection_ids
            ],
            "source_ids": (
                None
                if request.source_ids is None
                else [_uuid(s, Prefix.KNOWLEDGE_SOURCE) for s in request.source_ids]
            ),
            "limit": request.limit,
        }
        with self._runner(scope) as run:
            rows = run.rows(SEARCH, params)
        return [
            ChunkHit(
                chunk_id=_wire(Prefix.KNOWLEDGE_CHUNK, r["id"]),
                org_id=scope.org_id,
                channel_id=scope.channel_id,
                source_id=_wire(Prefix.KNOWLEDGE_SOURCE, r["source_id"]),
                collection_id=_wire(Prefix.KNOWLEDGE_COLLECTION, r["collection_id"]),
                collection_key=str(r["collection_key"]),
                collection_restricted=bool(r["restricted"]),
                chapter=r["chapter"],
                page_from=r["page_from"],
                page_to=r["page_to"],
                language=str(r["language"]),
                rank=float(r["rank"]),
                body_sha256=str(r["body_sha256"]),
                source_release_approval_id=_opt_wire(
                    Prefix.APPROVAL, r["source_release_approval_id"]
                ),
                chunk_release_approval_id=_opt_wire(
                    Prefix.APPROVAL, r["chunk_release_approval_id"]
                ),
            )
            for r in rows
        ]

    def load_chunks(self, scope: TenantScope, chunk_ids: Sequence[str]) -> Sequence[ChunkRow]:
        if not chunk_ids:
            return []
        params = {
            **self._base(scope),
            "chunk_ids": [_uuid(c, Prefix.KNOWLEDGE_CHUNK) for c in chunk_ids],
        }
        with self._runner(scope) as run:
            rows = run.rows(SELECT_CHUNKS, params)
        return [
            ChunkRow(
                chunk_id=_wire(Prefix.KNOWLEDGE_CHUNK, r["id"]),
                org_id=scope.org_id,
                channel_id=scope.channel_id,
                source_id=_wire(Prefix.KNOWLEDGE_SOURCE, r["source_id"]),
                collection_id=_wire(Prefix.KNOWLEDGE_COLLECTION, r["collection_id"]),
                ingest_version=int(r["ingest_version"]),
                chunk_no=int(r["chunk_no"]),
                chapter=r["chapter"],
                section=r["section"],
                page_from=r["page_from"],
                page_to=r["page_to"],
                language=str(r["language"]),
                body=str(r["body"]),
                body_sha256=str(r["body_sha256"]),
                extraction_method=ExtractionMethod(r["extraction_method"]),
                release_approval_id=_opt_wire(Prefix.APPROVAL, r["release_approval_id"]),
                token_count=r["token_count"],
            )
            for r in rows
        ]

    def approval(self, scope: TenantScope, approval_id: str) -> ApprovalView | None:
        params = {
            "org_id": _uuid(scope.org_id, Prefix.ORGANISATION),
            "approval_id": _uuid(approval_id, Prefix.APPROVAL),
        }
        with self._runner(scope) as run:
            rows = run.rows(SELECT_APPROVAL, params)
        if not rows:
            return None
        r = rows[0]
        return ApprovalView(
            approval_id=_wire(Prefix.APPROVAL, r["id"]),
            org_id=_wire(Prefix.ORGANISATION, r["org_id"]),
            kind=ApprovalKind(r["kind"]),
            state=ApprovalState(r["state"]),
            subject_kind=r["subject_kind"],
            subject_id=None if r["subject_id"] is None else str(r["subject_id"]),
            subject_sha256=r["subject_sha256"],
        )

    def released_chunk_ids(
        self, scope: TenantScope, approval_id: str, collection_id: str
    ) -> frozenset[str]:
        params = {
            **self._base(scope),
            "approval_id": _uuid(approval_id, Prefix.APPROVAL),
            "collection_id": _uuid(collection_id, Prefix.KNOWLEDGE_COLLECTION),
        }
        with self._runner(scope) as run:
            rows = run.rows(SELECT_RELEASED_CHUNKS, params)
        return frozenset(_wire(Prefix.KNOWLEDGE_CHUNK, r["id"]) for r in rows)

    def set_source_status(
        self,
        scope: TenantScope,
        source_id: str,
        status: KnowledgeSourceStatus,
        ingest_version: int | None = None,
        reliability_score: float | None = None,
    ) -> SourceView:
        params = {
            **self._base(scope),
            "source_id": _uuid(source_id, Prefix.KNOWLEDGE_SOURCE),
            "status": status.value,
            "ingest_version": ingest_version,
            "reliability_score": reliability_score,
        }
        with self._runner(scope) as run:
            if run.execute(UPDATE_SOURCE_STATUS, params) != 1:
                raise InputInvalid("unknown source")
        source = self.get_source(scope, source_id)
        if source is None:  # pragma: no cover - the update just matched the row
            raise InputInvalid("unknown source")
        return source

    def insert_chunks(self, scope: TenantScope, chunks: Sequence[ChunkRow]) -> IngestWrite:
        written = 0
        with self._runner(scope) as run:
            for chunk in chunks:
                query = self._fts.build(chunk.language, "")
                params = {
                    **self._base(scope),
                    "id": _uuid(chunk.chunk_id, Prefix.KNOWLEDGE_CHUNK),
                    "source_id": _uuid(chunk.source_id, Prefix.KNOWLEDGE_SOURCE),
                    "collection_id": _uuid(chunk.collection_id, Prefix.KNOWLEDGE_COLLECTION),
                    "ingest_version": chunk.ingest_version,
                    "chunk_no": chunk.chunk_no,
                    "extraction_method": chunk.extraction_method.value,
                    "release_approval_id": (
                        None
                        if chunk.release_approval_id is None
                        else _uuid(chunk.release_approval_id, Prefix.APPROVAL)
                    ),
                    "chapter": chunk.chapter,
                    "section": chunk.section,
                    "page_from": chunk.page_from,
                    "page_to": chunk.page_to,
                    "language": chunk.language,
                    "body": chunk.body,
                    "body_sha256": chunk.body_sha256,
                    "ts_config": query.config,
                    "token_count": chunk.token_count,
                }
                written += run.execute(INSERT_CHUNK, params)
        return IngestWrite(written, len(chunks) - written)

    def chunk_count(self, scope: TenantScope, source_id: str, ingest_version: int) -> int:
        params = {
            **self._base(scope),
            "source_id": _uuid(source_id, Prefix.KNOWLEDGE_SOURCE),
            "ingest_version": ingest_version,
        }
        with self._runner(scope) as run:
            rows = run.rows(COUNT_CHUNKS, params)
        return int(rows[0]["n"]) if rows else 0
