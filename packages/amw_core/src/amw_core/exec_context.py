"""Execution context shared by the stages of one task attempt (CCR-130, ticket P4-17; 19.1).

Tenant scope, typed IDs and the attempt number. ``from_task_input`` is V1 TenantScope: the
envelope org, the Task Input org and every typed ID must agree, else ``TENANT_MISMATCH`` before
any step runs (19.1 layer 1).
"""

from dataclasses import dataclass

from amw_core.contracts.task_input import TaskInput
from amw_core.errors import TenantMismatchError
from amw_core.ids import (
    ATTEMPT,
    CHANNEL,
    CORRELATION,
    JOB,
    ORG,
    TASK,
    AttemptId,
    ChannelId,
    CorrelationId,
    JobId,
    OrgId,
    TaskId,
    actor_ref,
)
from amw_core.interfaces.tenancy_context import TenantContext


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
        corr = self.tenant.correlation_id
        if corr is None:
            raise TenantMismatchError("execution context has no correlation id")
        return corr

    @classmethod
    def from_task_input(cls, task_input: TaskInput, attempt_id: str, agent_id: str) -> ExecContext:
        if task_input.agent_id != agent_id:
            raise TenantMismatchError(f"task is not addressed to {agent_id}")
        return cls(
            tenant=TenantContext(
                org_id=ORG.validate(task_input.org_id),
                actor=actor_ref(agent_id),
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
