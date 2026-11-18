"""Checkpoint IO: the state blob is written write-once first, then the ``checkpoints`` row
(blueprint 10 section 16; 07 sections 8, 10; F-14). State holds IDs, keys, hashes and URIs only."""

from collections.abc import Sequence
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel

from agent_10_video_editor.canonical import sha256_hex
from agent_10_video_editor.scope import TenantScope
from amw_core.ids import AttemptId, IdempotencyKey, TaskId
from amw_core.interfaces.checkpoint_store import CheckpointStore, NewCheckpoint
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext

S = TypeVar("S", bound=BaseModel)


class CheckpointIO:
    def __init__(
        self,
        *,
        scope: TenantScope,
        tenancy: TenancyContext,
        store: CheckpointStore,
        clock: Clock,
        context: TenantContext,
        job_id: str,
        task_id: str,
        attempt_id: str,
    ) -> None:
        self._scope = scope
        self._tenancy = tenancy
        self._store = store
        self._clock = clock
        self._context = context
        self._job = job_id
        self._task = task_id
        self._attempt = attempt_id

    def write(
        self,
        step_key: str,
        state: BaseModel,
        effects: Sequence[str] = (),
        progress: Decimal | None = None,
    ) -> None:
        data = state.model_dump_json().encode()
        path = (
            f"{self._job}/tasks/{self._task}/attempts/{self._attempt}/checkpoints/"
            f"{step_key}-{sha256_hex(data)[:16]}.json"
        )
        info = self._scope.put_bytes(self._scope.uri("jobs", path), data)
        with self._tenancy.transaction(self._context) as tx:
            self._store.write(
                tx,
                NewCheckpoint(
                    task_id=TaskId(self._task),
                    attempt_id=AttemptId(self._attempt),
                    step_key=step_key,
                    state_ref=info.uri,
                    state_sha256=info.sha256,
                    completed_effects=tuple(IdempotencyKey(e) for e in effects),
                    progress_ratio=progress,
                ),
                self._clock.now(),
            )

    def latest(self, model: type[S], step_prefix: str) -> tuple[S, tuple[str, ...]] | None:
        """The latest checkpoint of THIS task, only if its step belongs to ``step_prefix``."""
        with self._tenancy.transaction(self._context) as tx:
            record = self._store.latest(tx, TaskId(self._task))
        if record is None or not record.checkpoint.step_key.startswith(step_prefix):
            return None
        raw = self._scope.read_bytes(record.checkpoint.state_ref, record.checkpoint.state_sha256)
        return model.model_validate_json(raw), tuple(record.checkpoint.completed_effects)
