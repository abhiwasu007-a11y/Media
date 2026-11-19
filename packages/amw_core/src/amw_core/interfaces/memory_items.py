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
    superseded_by: WireId | None = None
    """A newer row replaced this one (04 5.10 ``superseded_by``); superseded rows are not live."""
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
        if self.scope is MemoryScope.LONG_TERM and not self.provenance_ref.strip():
            found.append("provenance_ref is required for LONG_TERM (04 5.10 rule 3)")
        return tuple(found)


@dataclass(frozen=True, slots=True)
class StoredMemoryItem:
    id: WireId
    item: MemoryItem


@dataclass(frozen=True, slots=True)
class MemoryRequester:
    """Who asks: the narrowest scope chain of the requesting task (04 5.10 rule 1). ``TASK`` /
    ``WORKING`` rows are visible to the same task only, ``PROJECT`` rows to the same project,
    ``CHANNEL`` / ``LONG_TERM`` rows to the same channel; never another channel or project."""

    channel_id: ChannelId | None
    project_id: WireId | None
    job_id: JobId | None
    task_id: TaskId | None

    def may_write(self, item: MemoryItem) -> bool:
        """The item lies inside this requester's own scope (and its job, when both name one)."""
        owner = owner_id_of(item)
        if owner is None or owner != self.owner_of(item.scope):
            return False
        return not (
            item.scope in {MemoryScope.TASK, MemoryScope.WORKING}
            and self.job_id is not None
            and item.job_id != self.job_id
        )

    def owner_of(self, scope: MemoryScope) -> str | None:
        """The id that owns rows of ``scope`` for this requester (``None``: cannot see them)."""
        if scope in {MemoryScope.TASK, MemoryScope.WORKING}:
            return None if self.task_id is None else str(self.task_id)
        if scope is MemoryScope.PROJECT:
            return None if self.project_id is None else str(self.project_id)
        return None if self.channel_id is None else str(self.channel_id)


def owner_id_of(item: MemoryItem) -> str | None:
    """The owner id of a row: its task, project or channel by scope."""
    if item.scope in {MemoryScope.TASK, MemoryScope.WORKING}:
        return None if item.task_id is None else str(item.task_id)
    if item.scope is MemoryScope.PROJECT:
        return None if item.project_id is None else str(item.project_id)
    return None if item.channel_id is None else str(item.channel_id)


@runtime_checkable
class MemoryItems(Protocol):
    def put(
        self, tx: TenantTransaction, requester: MemoryRequester, item: MemoryItem
    ) -> StoredMemoryItem:
        """Insert on behalf of ``requester``. A row outside the requester's own scope (another
        task's TASK / WORKING row, another project's PROJECT row, another channel's CHANNEL /
        LONG_TERM row) is ``PermissionDeniedError``: nothing is written (no memory poisoning);
        the org is always the transaction's. The same ``(scope, owner, key)`` with the same
        ``value_sha256`` returns the stored row (idempotent replay); another hash is
        ``IdempotencyConflictError``; a row that breaks the 04 5.10 constraints
        (``MemoryItem.problems``) is ``InputInvalidError``."""
        ...

    def get(
        self,
        tx: TenantTransaction,
        requester: MemoryRequester,
        scope: MemoryScope,
        key: str,
        now: datetime,
    ) -> StoredMemoryItem | None:
        """The live row (not expired at ``now``) of the tx org that ``requester`` owns for
        ``scope``; a row of another project, task or channel is never returned."""
        ...

    def list_for_scope(
        self, tx: TenantTransaction, requester: MemoryRequester, scope: MemoryScope, now: datetime
    ) -> Sequence[StoredMemoryItem]: ...
