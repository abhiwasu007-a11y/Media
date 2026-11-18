"""Checkpoint store interface (04 section 5.7 ``checkpoints``; 03 sections 11.3 T09 / T15;
07 section 10: resume from the latest checkpoint without redoing completed side effects).

A checkpoint row points to its state blob (``state_ref`` + ``state_sha256``, written write-once
through ``BlobStorage`` first) and lists ``completed_effects``: idempotency keys already done in
this task. ``write`` assigns the next ``seq`` per task and moves ``is_latest`` (partial UNIQUE).
Checkpoints are never updated in place otherwise. Implementation: lane L1;
``amw_core.testing.memory.MemoryCheckpointStore`` is an in-memory fake.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from amw_core.ids import AttemptId, CheckpointId, IdempotencyKey, OrgId, TaskId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class NewCheckpoint:
    task_id: TaskId
    attempt_id: AttemptId
    step_key: str
    """Agent-defined resume point."""
    state_ref: str
    state_sha256: str
    completed_effects: tuple[IdempotencyKey, ...]
    progress_ratio: Decimal | None = None
    """numeric(4,3), 0-1."""


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    id: CheckpointId
    org_id: OrgId
    seq: int
    is_latest: bool
    created_at: datetime
    checkpoint: NewCheckpoint


@runtime_checkable
class CheckpointStore(Protocol):
    def write(
        self, tx: TenantTransaction, checkpoint: NewCheckpoint, now: datetime
    ) -> CheckpointRecord:
        """Insert with ``seq = last + 1`` and ``is_latest = true``; clears the previous latest.
        ``progress_ratio`` outside 0-1 -> ``InputInvalidError``."""
        ...

    def latest(self, tx: TenantTransaction, task_id: TaskId) -> CheckpointRecord | None:
        """The resume checkpoint (``tasks.resume_checkpoint_id`` at T15)."""
        ...

    def get(
        self, tx: TenantTransaction, checkpoint_id: CheckpointId
    ) -> CheckpointRecord | None: ...

    def list_for_task(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[CheckpointRecord]:
        """Every checkpoint of the task in ``seq`` order."""
        ...
