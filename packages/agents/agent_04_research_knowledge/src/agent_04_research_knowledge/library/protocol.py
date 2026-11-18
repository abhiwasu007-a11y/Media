"""``KnowledgeLibrary``: the Protocol of the package's only database access (blueprint 13).

Every method takes a ``TenantScope`` and applies explicit ``org_id`` and ``channel_id``
predicates (RLS is the second line). The in-memory implementation and the PostgreSQL
implementation (``library/sql.py``, lane L1a schema) are both held to the same contract tests.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

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
from amw_core.enums import KnowledgeSourceStatus


@runtime_checkable
class KnowledgeLibrary(Protocol):
    def collections_for_channel(self, scope: TenantScope) -> Sequence[CollectionView]: ...

    def get_source(self, scope: TenantScope, source_id: str) -> SourceView | None:
        """``None`` for an unknown source and for a source of another org or channel (no oracle)."""
        ...

    def search(self, scope: TenantScope, request: SearchRequest) -> Sequence[ChunkHit]:
        """Read-only. Filters (6.6 step 2): org, channel, ``collection_id`` in the request,
        ``ingest_version`` equal to the source's current one, source ``INDEXED``, ownership not
        ``UNKNOWN``. Ordered by ``rank`` descending, then chunk id; at most ``request.limit``."""
        ...

    def load_chunks(self, scope: TenantScope, chunk_ids: Sequence[str]) -> Sequence[ChunkRow]:
        """Rows of this org and channel only; unknown or foreign ids are silently absent."""
        ...

    def approval(self, scope: TenantScope, approval_id: str) -> ApprovalView | None:
        """Read-only ``approvals`` lookup for the release rule (kind, state, subject, org)."""
        ...

    def released_chunk_ids(
        self, scope: TenantScope, approval_id: str, collection_id: str
    ) -> frozenset[str]: ...

    # --- ingestion (agent_04.knowledge_ingest) ---
    def set_source_status(
        self,
        scope: TenantScope,
        source_id: str,
        status: KnowledgeSourceStatus,
        ingest_version: int | None = None,
        reliability_score: float | None = None,
    ) -> SourceView:
        """``InputInvalidError`` for an unknown source in this org and channel."""
        ...

    def insert_chunks(self, scope: TenantScope, chunks: Sequence[ChunkRow]) -> IngestWrite:
        """Insert-only: ``UNIQUE (org, source, ingest_version, chunk_no)`` makes a replayed row a
        no-op (counted in ``skipped_existing``); an old ``ingest_version`` is never updated."""
        ...

    def chunk_count(self, scope: TenantScope, source_id: str, ingest_version: int) -> int: ...
