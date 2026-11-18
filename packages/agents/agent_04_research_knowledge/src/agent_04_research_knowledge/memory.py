"""PackMemory: the ``memory_items`` pointer to the pack blob (blueprint 10.8, 14).

Scope ``PROJECT``, key ``research_pack.<job>.<iteration>``, ``value_ref`` the pack URI. The row is
idempotent by key; ``expires_at`` is mandatory (04 section 5.10 CHECK).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from agent_04_research_knowledge.errors import IdempotencyConflict
from amw_core.enums import MemoryScope


@dataclass(frozen=True, slots=True)
class MemoryItem:
    org_id: str
    scope: MemoryScope
    channel_id: str
    workspace_id: str
    project_id: str
    key: str
    value_ref: str
    provenance_ref: str
    created_by: str
    expires_at: datetime
    value_sha256: str


class MemoryItems(Protocol):
    def put(self, item: MemoryItem) -> MemoryItem:
        """Insert; the same key with the same ``value_sha256`` returns the stored row,
        with another hash raises ``IdempotencyConflict``."""
        ...

    def get(
        self, org_id: str, scope: MemoryScope, channel_id: str, key: str
    ) -> MemoryItem | None: ...


class InMemoryMemoryItems:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str, str], MemoryItem] = {}

    def put(self, item: MemoryItem) -> MemoryItem:
        k = (item.org_id, item.scope.value, item.channel_id, item.key)
        old = self._rows.get(k)
        if old is None:
            self._rows[k] = item
            return item
        if old.value_sha256 != item.value_sha256:
            raise IdempotencyConflict("memory key exists with a different pack")
        return old

    def get(self, org_id: str, scope: MemoryScope, channel_id: str, key: str) -> MemoryItem | None:
        return self._rows.get((org_id, scope.value, channel_id, key))


class PackMemory:
    def __init__(self, items: MemoryItems, project_ttl_ms: int) -> None:
        self._items, self._ttl = items, project_ttl_ms

    def write(
        self,
        *,
        org_id: str,
        channel_id: str,
        workspace_id: str,
        project_id: str,
        job_id: str,
        iteration: int,
        task_id: str,
        pack_uri: str,
        pack_sha256: str,
        now: datetime,
    ) -> MemoryItem:
        return self._items.put(
            MemoryItem(
                org_id=org_id,
                scope=MemoryScope.PROJECT,
                channel_id=channel_id,
                workspace_id=workspace_id,
                project_id=project_id,
                key=f"research_pack.{job_id}.{iteration}",
                value_ref=pack_uri,
                provenance_ref=task_id,
                created_by="agent_04",
                expires_at=now + timedelta(milliseconds=self._ttl),
                value_sha256=pack_sha256,
            )
        )
