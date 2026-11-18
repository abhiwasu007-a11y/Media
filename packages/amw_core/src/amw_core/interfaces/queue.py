"""Task queue interface (04 section 5.4 ``task_queue``; ADR-001 option A: own table).

Claiming is cross-tenant (a worker serves every tenant) and goes through the ``SECURITY DEFINER``
function ``amw_queue_claim`` with ``FOR UPDATE SKIP LOCKED`` (04 section 3.6); everything else runs
in the tenant transaction of the transition that causes it (03 section 11.3 side effects).
LISTEN/NOTIFY is a wake-up only; correctness never depends on it (03 section 11.4 step 5).
Implementation: lane L1.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from amw_core.contracts.envelope import Envelope
from amw_core.enums import Capability, Priority, QueueItemStatus, QueueName, ResourceClass
from amw_core.ids import CheckpointId, JobId, OrgId, QueueItemId, TaskId, WorkerId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class NewQueueItem:
    """A ``READY`` row written at T03 / T12 / T15 / T17 with the dispatch envelope."""

    task_id: TaskId
    job_id: JobId
    queue_name: QueueName
    priority: Priority
    resource_class: ResourceClass
    required_capabilities: tuple[Capability, ...]
    scheduled_at: datetime
    envelope: Envelope
    resume_checkpoint_id: CheckpointId | None = None


@dataclass(frozen=True, slots=True)
class QueueItem:
    id: QueueItemId
    org_id: OrgId
    task_id: TaskId
    job_id: JobId
    queue_name: QueueName
    status: QueueItemStatus
    priority: Priority
    resource_class: ResourceClass
    required_capabilities: tuple[Capability, ...]
    scheduled_at: datetime
    claimed_by: WorkerId | None
    lease_expires_at: datetime | None
    envelope: Envelope
    resume_checkpoint_id: CheckpointId | None


@dataclass(frozen=True, slots=True)
class ClaimedItem:
    """One row returned by ``amw_queue_claim`` (04 section 3.6): identifiers and the envelope only.
    The worker then opens a tenant transaction for ``org_id`` before reading anything else."""

    queue_item_id: QueueItemId
    org_id: OrgId
    task_id: TaskId
    envelope: Envelope


@dataclass(frozen=True, slots=True)
class ClaimRequest:
    """What a worker can take (T07 guard: capabilities, admission, resource class)."""

    worker_id: WorkerId
    queue_names: tuple[QueueName, ...]
    capabilities: tuple[Capability, ...]
    resource_classes: tuple[ResourceClass, ...]
    lease_ms: int
    limit: int = 1
    """``n`` of ``amw_queue_claim(worker_id, capabilities[], resource_classes[], n)``."""


@runtime_checkable
class TaskQueue(Protocol):
    def enqueue(self, tx: TenantTransaction, item: NewQueueItem) -> QueueItem:
        """Insert a ``READY`` row; at most one live (READY/CLAIMED) row per task."""
        ...

    def claim(self, request: ClaimRequest) -> Sequence[ClaimedItem]:
        """T07 via ``amw_queue_claim`` (SECURITY DEFINER, ``FOR UPDATE SKIP LOCKED``, fair-share
        order of 05): up to ``limit`` admissible ``READY`` rows (``scheduled_at <= now()``) set to
        ``CLAIMED`` with a lease. Not tied to a tenant transaction; returns identifiers only."""
        ...

    def heartbeat(self, item_id: QueueItemId, worker_id: WorkerId, lease_ms: int) -> datetime:
        """Renew the lease (not a transition); returns the new ``lease_expires_at``.
        ``WorkerLostError`` if the lease is no longer held by this worker."""
        ...

    def mark_done(self, tx: TenantTransaction, item_id: QueueItemId) -> None:
        """Set ``DONE`` (T08, T09, T10, T11, T20 side effect)."""
        ...

    def cancel_for_task(self, tx: TenantTransaction, task_id: TaskId) -> None:
        """Set any live row of the task to ``CANCELLED`` (T19)."""
        ...

    def notify(self, queue_name: QueueName) -> None:
        """Wake listeners after commit (NOTIFY)."""
        ...

    def wait_for_work(self, queue_names: Sequence[QueueName], timeout_ms: int) -> bool:
        """Block until a NOTIFY or the timeout; ``True`` if woken by a NOTIFY."""
        ...
