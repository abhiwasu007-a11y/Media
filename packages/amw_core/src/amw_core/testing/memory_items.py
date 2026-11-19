"""In-memory ``MemoryItems`` fake (CCR-130, ticket P4-17): per-org isolation, idempotent by key."""

from amw_core.enums import MemoryScope
from amw_core.errors import IdempotencyConflictError, InputInvalidError
from amw_core.ids import ChannelId, OrgId, Prefix, new_id
from amw_core.interfaces.memory_items import MemoryItem, StoredMemoryItem
from amw_core.interfaces.tenancy_context import TenantTransaction

type _Key = tuple[OrgId, MemoryScope, ChannelId | None, str]


class InMemoryMemoryItems:
    def __init__(self) -> None:
        self._rows: dict[_Key, StoredMemoryItem] = {}

    def put(self, tx: TenantTransaction, item: MemoryItem) -> StoredMemoryItem:
        problems = item.problems()
        if problems:
            raise InputInvalidError("invalid memory item", details={"problems": list(problems)})
        key = (tx.context.org_id, item.scope, item.channel_id, item.key)
        old = self._rows.get(key)
        if old is None:
            stored = StoredMemoryItem(id=new_id(Prefix.MEMORY_ITEM), item=item)
            self._rows[key] = stored
            return stored
        if old.item.value_sha256 != item.value_sha256:
            raise IdempotencyConflictError("memory key exists with a different value")
        return old

    def get(
        self, tx: TenantTransaction, scope: MemoryScope, channel_id: ChannelId | None, key: str
    ) -> StoredMemoryItem | None:
        return self._rows.get((tx.context.org_id, scope, channel_id, key))

    def list_for_scope(
        self, tx: TenantTransaction, scope: MemoryScope, channel_id: ChannelId | None
    ) -> list[StoredMemoryItem]:
        org = tx.context.org_id
        rows = [
            r for (o, s, c, _), r in self._rows.items() if (o, s, c) == (org, scope, channel_id)
        ]
        return sorted(rows, key=lambda r: r.item.key)
