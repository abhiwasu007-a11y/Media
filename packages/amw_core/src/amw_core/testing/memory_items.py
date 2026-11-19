"""In-memory ``MemoryItems`` fake (CCR-130, ticket P4-17): per-org isolation, scoped to the
requester's task / project / channel, idempotent by hash, expired rows never returned."""

from datetime import datetime

from amw_core.enums import MemoryScope
from amw_core.errors import IdempotencyConflictError, InputInvalidError
from amw_core.ids import OrgId, Prefix, new_id
from amw_core.interfaces.memory_items import (
    MemoryItem,
    MemoryRequester,
    StoredMemoryItem,
    owner_id_of,
)
from amw_core.interfaces.tenancy_context import TenantTransaction

type _Key = tuple[OrgId, MemoryScope, str, str]


class InMemoryMemoryItems:
    def __init__(self) -> None:
        self._rows: dict[_Key, StoredMemoryItem] = {}

    def put(self, tx: TenantTransaction, item: MemoryItem) -> StoredMemoryItem:
        problems = item.problems()
        owner = owner_id_of(item)
        if problems or owner is None:
            raise InputInvalidError("invalid memory item", details={"problems": list(problems)})
        key = (tx.context.org_id, item.scope, owner, item.key)
        old = self._rows.get(key)
        if old is None:
            stored = StoredMemoryItem(id=new_id(Prefix.MEMORY_ITEM), item=item)
            self._rows[key] = stored
            return stored
        if old.item.value_sha256 != item.value_sha256:
            raise IdempotencyConflictError("memory key exists with a different value")
        return old

    def get(
        self,
        tx: TenantTransaction,
        requester: MemoryRequester,
        scope: MemoryScope,
        key: str,
        now: datetime,
    ) -> StoredMemoryItem | None:
        owner = requester.owner_of(scope)
        if owner is None:
            return None
        row = self._rows.get((tx.context.org_id, scope, owner, key))
        return row if row is not None and _live(row, now) else None

    def list_for_scope(
        self, tx: TenantTransaction, requester: MemoryRequester, scope: MemoryScope, now: datetime
    ) -> list[StoredMemoryItem]:
        owner = requester.owner_of(scope)
        if owner is None:
            return []
        org = tx.context.org_id
        rows = [
            r
            for (o, s, w, _), r in self._rows.items()
            if (o, s, w) == (org, scope, owner) and _live(r, now)
        ]
        return sorted(rows, key=lambda r: r.item.key)


def _live(row: StoredMemoryItem, now: datetime) -> bool:
    expires = row.item.expires_at
    return expires is None or expires > now
