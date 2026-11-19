"""``memory_items`` access (04 section 5.10; CCR-130, ticket P4-17; prefix ``mem``).

One Protocol over the table so agents never write their own SQL for it. Every call takes the
tenant transaction; ``org_id`` comes from it, never from the caller (27 section 7.3 rule 3).
Retrieval filters the narrowest scope chain of the requesting task (04 5.10 rule 1).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from amw_core.enums import MemoryScope
from amw_core.ids import ActorRef, ChannelId, JobId, TaskId, WireId
from amw_core.interfaces.tenancy_context import TenantTransaction

EXPIRY_REQUIRED_SCOPES = frozenset({MemoryScope.WORKING, MemoryScope.TASK, MemoryScope.PROJECT})
"""04 5.10 CHECK: ``expires_at`` is required for these scopes."""


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """A ``memory_items`` row without the org (taken from the transaction)."""

    scope: MemoryScope
    workspace_id: WireId
    key: str
    provenance_ref: str
    created_by: ActorRef
    value_sha256: str
    """Idempotency fingerprint of the stored value (the same key with another hash conflicts)."""
    value: object | None = None
    value_ref: str | None = None
    """Exactly one of ``value`` / ``value_ref`` (04 5.10 CHECK)."""
    channel_id: ChannelId | None = None
    project_id: WireId | None = None
    job_id: JobId | None = None
    task_id: TaskId | None = None
    expires_at: datetime | None = None
    review_after: datetime | None = None
    confidence: str | None = None
    """``numeric(4,3)`` as text, never a float."""

    def problems(self) -> tuple[str, ...]:
        """The 04 5.10 CHECK constraints this row would violate (empty = valid)."""
        found: list[str] = []
        if (self.value is None) == (self.value_ref is None):
            found.append("exactly one of value / value_ref")
        if self.scope in EXPIRY_REQUIRED_SCOPES and self.expires_at is None:
            found.append("expires_at is required for this scope")
        if self.scope in {MemoryScope.CHANNEL, MemoryScope.LONG_TERM} and self.channel_id is None:
            found.append("channel_id is required for this scope")
        if self.scope is MemoryScope.PROJECT and self.project_id is None:
            found.append("project_id is required for PROJECT")
        if self.scope in {MemoryScope.TASK, MemoryScope.WORKING} and (
            self.job_id is None or self.task_id is None
        ):
            found.append("job_id and task_id are required for this scope")
        return tuple(found)


@dataclass(frozen=True, slots=True)
class StoredMemoryItem:
    id: WireId
    item: MemoryItem


@runtime_checkable
class MemoryItems(Protocol):
    def put(self, tx: TenantTransaction, item: MemoryItem) -> StoredMemoryItem:
        """Insert. The same ``(scope, channel, key)`` with the same ``value_sha256`` returns the
        stored row; another hash is ``IdempotencyConflictError``; a row that breaks the 04 5.10
        constraints (``MemoryItem.problems``) is ``InputInvalidError``."""
        ...

    def get(
        self, tx: TenantTransaction, scope: MemoryScope, channel_id: ChannelId | None, key: str
    ) -> StoredMemoryItem | None:
        """The live (not superseded, not expired) row of the tx org, else ``None``."""
        ...

    def list_for_scope(
        self, tx: TenantTransaction, scope: MemoryScope, channel_id: ChannelId | None
    ) -> Sequence[StoredMemoryItem]: ...
