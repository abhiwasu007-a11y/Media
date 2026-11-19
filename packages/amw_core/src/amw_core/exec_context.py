"""Execution context shared by the stages of one task attempt (CCR-130, ticket P4-17; 19.1).

Tenant scope, typed IDs, the attempt number and (CCR-203) the stage ID and iteration.
``from_task_input`` is V1 TenantScope: the envelope org (required), the Task Input org and
every typed ID must agree and be well formed, else ``TENANT_MISMATCH`` before any step runs
(19.1 layer 1).
"""

import re
from dataclasses import dataclass

from amw_core.contracts.task_input import TaskInput
from amw_core.errors import InputInvalidError, TenantMismatchError
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

_STAGE_ID = re.compile(r"^[a-z0-9_]{2,32}$")


@dataclass(frozen=True, slots=True)
class ExecContext:
    tenant: TenantContext
    job_id: JobId
    task_id: TaskId
    attempt_id: AttemptId
    channel_id: ChannelId | None
    attempt_no: int
    stage_id: str | None = None
    """04 section 5.3 ``tasks.stage_id`` (CCR-203, CCR-214); ``None`` for a task outside a stage."""
    iteration: int = 0
    """04 section 5.3 ``tasks.iteration`` (revision loop counter, CCR-203)."""

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
    def from_task_input(
        cls,
        task_input: TaskInput,
        attempt_id: str,
        agent_id: str,
        *,
        envelope_org_id: str,
        stage_id: str | None = None,
        iteration: int = 0,
    ) -> ExecContext:
        if task_input.agent_id != agent_id:
            raise TenantMismatchError(f"task is not addressed to {agent_id}")
        if envelope_org_id != task_input.org_id:
            raise TenantMismatchError("envelope org differs from the Task Input org")
        if stage_id is not None and (
            not isinstance(stage_id, str) or not _STAGE_ID.fullmatch(stage_id)
        ):
            raise InputInvalidError(
                "stage_id is malformed", details={"stage_id": str(stage_id)[:64]}
            )
        if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
            raise InputInvalidError("iteration must be an integer >= 0")
        if stage_id is not None:
            stage_id = str.__str__(stage_id)  # a str subclass is accepted as a plain str
        try:
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
                stage_id=stage_id,
                iteration=iteration,
            )
        except InputInvalidError as exc:
            raise TenantMismatchError("a typed ID of the task is malformed") from exc
