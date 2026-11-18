"""Views and requests of the knowledge library (04 section 5.10, blueprint 10.3, 10.9, 13).

``TenantScope`` carries ``org_id`` and ``channel_id``, always taken from the validated task
input, never from a model, a prompt or a passage (19.1 layer 1).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from amw_core.enums import (
    ExtractionMethod,
    KnowledgeSourceKind,
    KnowledgeSourceStatus,
    SourceOwnership,
)


@dataclass(frozen=True, slots=True)
class TenantScope:
    org_id: str
    channel_id: str
    actor: str = "agent_04"


@dataclass(frozen=True, slots=True)
class CollectionView:
    collection_id: str
    collection_key: str
    title: str
    restricted: bool


@dataclass(frozen=True, slots=True)
class SourceView:
    source_id: str
    org_id: str
    channel_id: str
    collection_id: str
    kind: KnowledgeSourceKind
    title: str
    author: str | None
    edition: str | None
    language: str
    ownership: SourceOwnership
    status: KnowledgeSourceStatus
    ingest_version: int
    content_sha256: str
    size_bytes: int
    release_approval_id: str | None = None
    credit_in_description: bool = True
    reliability_score: float | None = None


@dataclass(frozen=True, slots=True)
class ChunkRow:
    """One ``knowledge_chunks`` row. ``body`` is confidential: never logged (NFR-6)."""

    chunk_id: str
    org_id: str
    channel_id: str
    source_id: str
    collection_id: str
    ingest_version: int
    chunk_no: int
    chapter: str | None
    section: str | None
    page_from: int | None
    page_to: int | None
    language: str
    body: str
    body_sha256: str
    extraction_method: ExtractionMethod = ExtractionMethod.TEXT_LAYER
    release_approval_id: str | None = None
    token_count: int | None = None

    def __repr__(self) -> str:  # never leak the body through a repr in a log or an error
        return f"ChunkRow({self.chunk_id}, source={self.source_id}, no={self.chunk_no})"


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """One full-text query. ``collection_ids`` is the already-gated allowed set (D-4, D-6)."""

    text: str
    language: str
    collection_ids: frozenset[str]
    limit: int
    source_ids: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """Search result: citation metadata and rank, never the body (10.3)."""

    chunk_id: str
    org_id: str
    channel_id: str
    source_id: str
    collection_id: str
    collection_key: str
    collection_restricted: bool
    chapter: str | None
    page_from: int | None
    page_to: int | None
    language: str
    rank: float
    body_sha256: str
    source_release_approval_id: str | None
    chunk_release_approval_id: str | None


@dataclass(frozen=True, slots=True)
class IngestWrite:
    """Result of writing a source's chunks for one ``ingest_version``."""

    written: int
    skipped_existing: int


ChunkRows = Sequence[ChunkRow]
