"""Job / task store interface (04 section 5.3 ``jobs``, ``tasks``, ``task_dependencies``,
``task_attempts``; 03 section 11 state machine; 3A slice spec section 2.1 and ticket 3A-01/02).

The store persists; it does not decide. ``amw_core.state_machine`` (lane L1) chooses the transition
(T01-T20, J01-J12) and checks guards; the store applies it with optimistic locking
(03 section 11.4): ``UPDATE ... WHERE state = :from AND state_version = :expected``. Zero rows ->
``LockConflictError`` (TEMPORARY.LOCK_CONFLICT, re-read and re-evaluate). A pair not in
``state_transition_rules`` -> ``InvalidTransitionError`` (also enforced by the DB trigger).
Each ``transition_*`` writes the ``state_transitions`` row in the same transaction; the caller
writes the ``audit_log`` row (03 section 11.7) through ``AuditLog`` in that transaction.
Cross-tenant scans (due retries, due resumes, stuck tasks) are not here: they are the identifier-
only system functions of 04 section 3.6 (``SystemFunctions``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from amw_core.contracts.common import ResourceBudget
from amw_core.contracts.error import ErrorObject
from amw_core.contracts.task_output import ResourceUsage
from amw_core.enums import (
    AttemptResult,
    Capability,
    JobOutcome,
    JobState,
    Priority,
    ProductionTypeKey,
    ResourceClass,
    TaskState,
    TransitionId,
    WaitReason,
)
from amw_core.ids import (
    ActorRef,
    ApprovalId,
    AttemptId,
    ChannelId,
    CheckpointId,
    CorrelationId,
    ExecutorId,
    IdempotencyKey,
    JobId,
    OrgId,
    ProjectId,
    TaskId,
    WorkerId,
    WorkspaceId,
)
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class NewJob:
    """J01 input. ``idempotency_key`` has scope ``job.create`` (03 section 9.2)."""

    workspace_id: WorkspaceId
    project_id: ProjectId | None
    channel_id: ChannelId | None
    parent_job_id: JobId | None
    production_type_key: ProductionTypeKey
    production_type_version: int
    language: str
    priority: Priority
    deadline: datetime | None
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    requested_by: ActorRef
    input_ref: str | None
    currency: str


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: JobId
    org_id: OrgId
    workspace_id: WorkspaceId
    project_id: ProjectId | None
    channel_id: ChannelId | None
    parent_job_id: JobId | None
    production_type_key: ProductionTypeKey
    production_type_version: int
    language: str
    state: JobState
    state_version: int
    state_changed_at: datetime
    outcome: JobOutcome | None
    priority: Priority
    deadline: datetime | None
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    requested_by: ActorRef
    input_ref: str | None
    monetized_destination: bool
    """CCR-028: set at J02, read by the licence insert guard; never changed after J03."""
    task_count: int
    cost_estimate_micros: int
    cost_verified_micros: int
    currency: str
    failed_task_id: TaskId | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewTask:
    """T01 input (one node of the registry DAG, 24 section 3)."""

    task_type: str
    agent_id: ExecutorId
    iteration: int
    is_required: bool
    priority: Priority
    resource_class: ResourceClass
    required_capabilities: tuple[Capability, ...]
    idempotency_key: IdempotencyKey
    payload_schema: str
    payload_schema_version: str
    resource_budget: ResourceBudget
    max_attempts: int
    deadline: datetime | None
    depends_on: tuple[int, ...] = ()
    """Indexes into the same ``create_tasks`` batch (the graph is a DAG by construction)."""


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: TaskId
    org_id: OrgId
    job_id: JobId
    task_type: str
    agent_id: ExecutorId
    iteration: int
    is_required: bool
    state: TaskState
    wait_reason: WaitReason | None
    state_version: int
    state_changed_at: datetime
    priority: Priority
    resource_class: ResourceClass
    required_capabilities: tuple[Capability, ...]
    idempotency_key: IdempotencyKey
    input_ref: str | None
    input_sha256: str | None
    output_ref: str | None
    output_sha256: str | None
    input_schema_version: str | None
    payload_schema: str
    payload_schema_version: str
    resource_budget: ResourceBudget
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    deadline: datetime | None
    cancel_requested_at: datetime | None
    cancel_reason: str | None
    resume_checkpoint_id: CheckpointId | None
    approval_id: ApprovalId | None
    last_error: ErrorObject | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class TaskTransition:
    """One row of 03 section 11.3 applied to one task (CHECK: ``wait_reason`` iff CHECKPOINTED;
    ``next_attempt_at`` required for RETRY_WAIT)."""

    task_id: TaskId
    transition_id: TransitionId
    from_state: TaskState
    to_state: TaskState
    expected_state_version: int
    actor: ActorRef
    wait_reason: WaitReason | None = None
    next_attempt_at: datetime | None = None
    error: ErrorObject | None = None
    input_ref: str | None = None
    input_sha256: str | None = None
    input_schema_version: str | None = None
    output_ref: str | None = None
    output_sha256: str | None = None
    resume_checkpoint_id: CheckpointId | None = None
    approval_id: ApprovalId | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class JobTransition:
    """One row of 03 section 11.5 (``outcome`` iff ``to_state = COMPLETED``)."""

    job_id: JobId
    transition_id: TransitionId
    from_state: JobState
    to_state: JobState
    expected_state_version: int
    actor: ActorRef
    outcome: JobOutcome | None = None
    failed_task_id: TaskId | None = None
    monetized_destination: bool | None = None
    """Only at J02 (CCR-028)."""
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    id: AttemptId
    task_id: TaskId
    attempt_no: int
    worker_id: WorkerId | None
    result: AttemptResult
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    resumed_from_checkpoint_id: CheckpointId | None
    is_replay: bool
    output_ref: str | None
    resource_usage: ResourceUsage | None
    error: ErrorObject | None


@runtime_checkable
class JobStore(Protocol):
    # --- jobs ---
    def create_job(self, tx: TenantTransaction, job: NewJob) -> JobRecord:
        """J01. Idempotent on ``(org_id, idempotency_key)``: a repeat returns the existing job."""
        ...

    def get_job(self, tx: TenantTransaction, job_id: JobId) -> JobRecord | None: ...

    def transition_job(self, tx: TenantTransaction, change: JobTransition) -> JobRecord:
        """Apply J02-J12 (derived by the state machine after every task transition, same tx)."""
        ...

    def add_job_cost(
        self, tx: TenantTransaction, job_id: JobId, estimate_micros: int, verified_micros: int
    ) -> None:
        """Roll ledger amounts up into ``jobs.cost_estimate_micros`` / ``cost_verified_micros``."""
        ...

    # --- tasks ---
    def create_tasks(
        self, tx: TenantTransaction, job_id: JobId, tasks: Sequence[NewTask]
    ) -> Sequence[TaskRecord]:
        """T01 for a whole graph: insert ``tasks`` + ``task_dependencies``; enforces
        ``limits.max_tasks_per_job`` (``LoopCapExceededError``) and increments ``task_count``."""
        ...

    def get_task(self, tx: TenantTransaction, task_id: TaskId) -> TaskRecord | None: ...

    def list_tasks(self, tx: TenantTransaction, job_id: JobId) -> Sequence[TaskRecord]: ...

    def dependencies(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[TaskId]:
        """Tasks this task depends on (T02 guard: all ``COMPLETED``)."""
        ...

    def dependants(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[TaskId]:
        """Tasks that depend on this task (unblocked after T08)."""
        ...

    def transition_task(self, tx: TenantTransaction, change: TaskTransition) -> TaskRecord:
        """Apply one of T01-T20 with optimistic locking; writes ``state_transitions``."""
        ...

    def request_cancel(self, tx: TenantTransaction, task_id: TaskId, reason: str) -> TaskRecord:
        """Set ``cancel_requested_at`` / ``cancel_reason`` (T20 is applied at a safe point)."""
        ...

    # --- attempts ---
    def start_attempt(
        self,
        tx: TenantTransaction,
        task_id: TaskId,
        worker_id: WorkerId,
        resumed_from_checkpoint_id: CheckpointId | None,
        is_replay: bool,
    ) -> AttemptRecord:
        """T07 side effect: insert ``task_attempts`` (``RUNNING``), increment ``attempt_count``."""
        ...

    def finish_attempt(
        self,
        tx: TenantTransaction,
        attempt_id: AttemptId,
        result: AttemptResult,
        duration_ms: int,
        output_ref: str | None,
        resource_usage: ResourceUsage | None,
        error: ErrorObject | None,
    ) -> AttemptRecord:
        """Close the attempt (T08-T11, T20)."""
        ...

    def heartbeat_attempt(self, tx: TenantTransaction, attempt_id: AttemptId) -> None: ...
