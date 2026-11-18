"""Knowledge collections (04 section 5.10 ``knowledge_collections``, CCR-011; prefix ``kcl``).

Per-channel collections with a ``restricted`` flag: restricted material is used only when a
``KNOWLEDGE_RELEASE`` approval covers it (04 section 5.16 release rule; FIN-R12, Q26). Sources
and chunks carry ``collection_id``. Every call is tenant-scoped and channel-filtered.
Implementation: lane of Agent 04 / L1.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from amw_core.ids import ChannelId, OrgId, WireId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class NewKnowledgeCollection:
    channel_id: ChannelId
    collection_key: str
    """``^[a-z0-9_]{2,48}$``, unique per channel."""
    title: str
    restricted: bool = False
    description: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeCollection:
    id: WireId
    org_id: OrgId
    collection: NewKnowledgeCollection


@runtime_checkable
class KnowledgeCollections(Protocol):
    def create(
        self, tx: TenantTransaction, collection: NewKnowledgeCollection
    ) -> KnowledgeCollection:
        """``InputInvalidError`` for a bad key; ``IdempotencyConflictError`` if the key exists in
        the channel with different fields."""
        ...

    def get(self, tx: TenantTransaction, collection_id: WireId) -> KnowledgeCollection | None: ...

    def by_key(
        self, tx: TenantTransaction, channel_id: ChannelId, collection_key: str
    ) -> KnowledgeCollection | None: ...

    def list_for_channel(
        self, tx: TenantTransaction, channel_id: ChannelId
    ) -> Sequence[KnowledgeCollection]: ...
