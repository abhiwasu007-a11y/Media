"""Execution context shared by both stages (tenant scope, IDs, scratch; 19.1 layers 1, 3)."""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from amw_core.contracts.task_input import TaskInput
from amw_core.errors import TenantMismatchError
from amw_core.ids import (
    ATTEMPT,
    CHANNEL,
    CORRELATION,
    JOB,
    ORG,
    TASK,
    ActorRef,
    AttemptId,
    ChannelId,
    CorrelationId,
    JobId,
    OrgId,
    TaskId,
    actor_ref,
)
from amw_core.interfaces.tenancy_context import TenantContext

AGENT_ID = "agent_07"


@dataclass(frozen=True, slots=True)
class ExecContext:
    tenant: TenantContext
    job_id: JobId
    task_id: TaskId
    attempt_id: AttemptId
    channel_id: ChannelId | None
    attempt_no: int

    @property
    def org_id(self) -> OrgId:
        return self.tenant.org_id

    @property
    def correlation_id(self) -> CorrelationId:
        assert self.tenant.correlation_id is not None  # noqa: S101 - set by from_task_input
        return self.tenant.correlation_id

    @classmethod
    def from_task_input(cls, task_input: TaskInput, attempt_id: str) -> ExecContext:
        """V1 TenantScope: the envelope org, the Task Input org and every typed ID must agree.
        Anything else is ``TENANT_MISMATCH`` before any step runs (19.1 layer 1)."""
        actor: ActorRef = actor_ref(AGENT_ID)
        org = ORG.validate(task_input.org_id)
        if task_input.agent_id != AGENT_ID:
            raise TenantMismatchError("task is not addressed to agent_07")
        return cls(
            tenant=TenantContext(
                org_id=org,
                actor=actor,
                correlation_id=CORRELATION.validate(task_input.correlation_id),
            ),
            job_id=JOB.validate(task_input.job_id),
            task_id=TASK.validate(task_input.task_id),
            attempt_id=ATTEMPT.validate(attempt_id),
            channel_id=CHANNEL.validate(task_input.channel_id)
            if task_input.channel_id is not None
            else None,
            attempt_no=task_input.retry_count + 1,
        )


@contextmanager
def scratch_dir(root: Path, ctx: ExecContext) -> Iterator[Path]:
    """Per-org, per-task scratch space, mode 0700, wiped at attempt end and on drain (19.1 layer 3).
    FFmpeg is given absolute paths inside this directory only."""
    path = root / str(ctx.org_id) / str(ctx.task_id) / str(ctx.attempt_id)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        yield path.resolve()
    finally:
        shutil.rmtree(path, ignore_errors=True)
