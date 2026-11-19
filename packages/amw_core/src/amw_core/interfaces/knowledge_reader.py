"""Read-only view of the knowledge library for verification (04 5.10; CCR-130, ticket P4-17).

Source and chunk text is loaded by code, never by a model. Every method takes the tenant
transaction; implementations filter ``org_id`` and ``channel_id`` (RLS is the second line).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from amw_core.ids import ChannelId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class SourceText:
    """One library source of the task's own org and channel."""

    citation_ref: str
    kind: str
    """Citation kind as the agent names it (chunk, reference snapshot, ...)."""
    text: str
    content_sha256: str
    """Chunk ``body_sha256`` or reference snapshot hash (CCR-053)."""
    reliability_tier: str | None
    restricted: bool
    """The source sits in a restricted ("our method") collection (FIN-R12, Q26)."""


@runtime_checkable
class KnowledgeReader(Protocol):
    def get_source(
        self, tx: TenantTransaction, channel_id: ChannelId, citation_ref: str
    ) -> SourceText | None:
        """A source of the tx org and ``channel_id``, else ``None``. A ref of another tenant is
        ``CrossTenantRefError``, never ``None`` (no existence oracle)."""
        ...

    def search(
        self, tx: TenantTransaction, channel_id: ChannelId, query: str, top_k: int
    ) -> Sequence[SourceText]:
        """Full-text search over the channel library (ADR-013 2.4); never restricted collections."""
        ...
