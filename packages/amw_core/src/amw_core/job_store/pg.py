"""``JobStore`` on PostgreSQL (04 section 5.3; 03 sections 11.3-11.7).

Every write runs in the caller's tenant transaction and filters ``org_id`` explicitly (RLS is the
second line). Transitions are checked by ``amw_core.state_machine`` first, applied with optimistic
locking (``WHERE state = :from AND state_version = :expected``; zero rows = ``LockConflictError``),
and each one writes its ``audit_log`` row (through the injected ``AuditLog``) and its
``state_transitions`` row carrying that audit ``seq``, in the same transaction. The store writes
the audit row itself because ``state_transitions.audit_seq`` is NOT NULL (04 section 5.6), so the
audit sequence must exist before the history row.
"""

import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from amw_core.contracts.common import ResourceBudget
from amw_core.contracts.error import ErrorObject
from amw_core.contracts.task_output import ResourceUsage
from amw_core.enums import (
    AttemptResult,
    Capability,
    EntityKind,
    JobOutcome,
    JobState,
    Priority,
    ProductionTypeKey,
    ResourceClass,
    TaskState,
    TransitionId,
    WaitReason,
)
from amw_core.errors import (
    InputInvalidError,
    InvalidTransitionError,
    LockConflictError,
    LoopCapExceededError,
    MissingDependencyError,
    WorkerLostError,
)
from amw_core.ids import (
    APPROVAL,
    ATTEMPT,
    CHANNEL,
    CHECKPOINT,
    CORRELATION,
    JOB,
    ORG,
    PROJECT,
    STATE_TRANSITION,
    TASK,
    WORKER,
    WORKSPACE,
    ActorRef,
    AttemptId,
    CheckpointId,
    ExecutorId,
    IdempotencyKey,
    JobId,
    TaskId,
    WorkerId,
    new_uuid7,
)
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.job_store import (
    AttemptRecord,
    JobRecord,
    JobTransition,
    NewJob,
    NewTask,
    TaskRecord,
    TaskTransition,
)
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.state_machine import (
    Rule,
    actor_kind_of,
    authority_of,
    check_job,
    check_task,
    find_rule,
)
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

Row = dict[str, Any]
_STAGE_ID = re.compile(r"^[a-z0-9_]{2,32}$")  # migration 0058 tasks_stage_id_format
_T01_JOB_STATES = (JobState.VALIDATING, JobState.RUNNING, JobState.CHECKPOINTED)


def _opt(kind: Any, value: uuid.UUID | None) -> Any:
    return None if value is None else kind.from_uuid(value)


def _hex(value: bytes | None) -> str | None:
    return None if value is None else bytes(value).hex()


def _unhex(value: str | None) -> bytes | None:
    if value is None:
        return None
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise InputInvalidError("SHA-256 must be 64 hex characters") from exc
    if len(raw) != 32:
        raise InputInvalidError("SHA-256 must be 64 hex characters")
    return raw


def _job(row: Row) -> JobRecord:
    return JobRecord(
        id=JOB.from_uuid(row["id"]),
        org_id=ORG.from_uuid(row["org_id"]),
        workspace_id=WORKSPACE.from_uuid(row["workspace_id"]),
        project_id=_opt(PROJECT, row["project_id"]),
        channel_id=_opt(CHANNEL, row["channel_id"]),
        parent_job_id=_opt(JOB, row["parent_job_id"]),
        production_type_key=ProductionTypeKey(row["production_type_key"]),
        production_type_version=row["production_type_version"],
        language=row["language"],
        state=JobState(row["state"]),
        state_version=row["state_version"],
        state_changed_at=row["state_changed_at"],
        outcome=JobOutcome(row["outcome"]) if row["outcome"] else None,
        priority=_priority(row["priority"]),
        deadline=row["deadline"],
        correlation_id=CORRELATION.from_uuid(row["correlation_id"]),
        idempotency_key=IdempotencyKey(row["idempotency_key"]),
        requested_by=ActorRef(row["requested_by"]),
        input_ref=row["input_ref"],
        monetized_destination=row["monetized_destination"],
        task_count=row["task_count"],
        cost_estimate_micros=row["cost_estimate_micros"],
        cost_verified_micros=row["cost_verified_micros"],
        currency=row["currency"],
        failed_task_id=_opt(TASK, row["failed_task_id"]),
        completed_at=row["completed_at"],
    )


def _priority(value: int) -> Priority:
    return next(p for p in Priority if p.queue_int == value)


def _task(row: Row) -> TaskRecord:
    return TaskRecord(
        id=TASK.from_uuid(row["id"]),
        org_id=ORG.from_uuid(row["org_id"]),
        job_id=JOB.from_uuid(row["job_id"]),
        task_type=row["task_type"],
        agent_id=ExecutorId(row["agent_id"]),
        iteration=row["iteration"],
        stage_id=row["stage_id"],
        is_required=row["is_required"],
        state=TaskState(row["state"]),
        wait_reason=WaitReason(row["wait_reason"]) if row["wait_reason"] else None,
        state_version=row["state_version"],
        state_changed_at=row["state_changed_at"],
        priority=_priority(row["priority"]),
        resource_class=ResourceClass(row["resource_class"]),
        required_capabilities=tuple(Capability(c) for c in row["required_capabilities"]),
        idempotency_key=IdempotencyKey(row["idempotency_key"]),
        input_ref=row["input_ref"],
        input_sha256=_hex(row["input_sha256"]),
        output_ref=row["output_ref"],
        output_sha256=_hex(row["output_sha256"]),
        input_schema_version=row["input_schema_version"],
        payload_schema=row["payload_schema"],
        payload_schema_version=row["payload_schema_version"],
        resource_budget=ResourceBudget.model_validate(row["resource_budget"]),
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        next_attempt_at=row["next_attempt_at"],
        deadline=row["deadline"],
        cancel_requested_at=row["cancel_requested_at"],
        cancel_reason=row["cancel_reason"],
        resume_checkpoint_id=_opt(CHECKPOINT, row["resume_checkpoint_id"]),
        approval_id=_opt(APPROVAL, row["approval_id"]),
        last_error=ErrorObject.model_validate(row["last_error"]) if row["last_error"] else None,
        completed_at=row["completed_at"],
    )


def _attempt(row: Row) -> AttemptRecord:
    return AttemptRecord(
        id=ATTEMPT.from_uuid(row["id"]),
        task_id=TASK.from_uuid(row["task_id"]),
        attempt_no=row["attempt_no"],
        worker_id=_opt(WORKER, row["worker_id"]),
        result=AttemptResult(row["result"]),
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_ms=row["duration_ms"],
        resumed_from_checkpoint_id=_opt(CHECKPOINT, row["resumed_from_checkpoint_id"]),
        is_replay=row["is_replay"],
        output_ref=row["output_ref"],
        resource_usage=(
            ResourceUsage.model_validate(row["resource_usage"]) if row["resource_usage"] else None
        ),
        error=ErrorObject.model_validate(row["error"]) if row["error"] else None,
    )


def _error_doc(error: ErrorObject | None) -> Jsonb | None:
    return None if error is None else Jsonb(error.to_doc())


class PgJobStore:
    """``JobStore`` implementation. ``max_tasks_per_job`` is config ``limits.max_tasks_per_job``."""

    def __init__(self, audit: AuditLog, *, max_tasks_per_job: int) -> None:
        if max_tasks_per_job < 1:
            raise InputInvalidError("limits.max_tasks_per_job must be at least 1")
        self._audit = audit
        self._max_tasks = max_tasks_per_job

    # --- plumbing -------------------------------------------------------------------------------
    @contextmanager
    def _cur(self, tx: TenantTransaction) -> Iterator[psycopg.Cursor[Row]]:
        conn = connection_of(tx)
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                yield cur
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc

    def _record(
        self,
        tx: TenantTransaction,
        cur: psycopg.Cursor[Row],
        rule: Rule,
        *,
        entity_id: uuid.UUID,
        job_id: uuid.UUID,
        correlation_id: uuid.UUID,
        state_version_after: int,
        occurred_at: datetime,
        wait_reason: WaitReason | None = None,
        error_code: str | None = None,
        reason: str | None = None,
    ) -> None:
        """03 section 11.7 audit row, then the ``state_transitions`` row with its ``seq``."""
        actor = tx.context.actor
        entity = rule.entity_kind
        kind = TASK if entity is EntityKind.TASK else JOB
        details: dict[str, Any] = {
            "from": rule.from_state,
            "to": rule.to_state,
            "transition_id": rule.transition_id.value,
            "wait_reason": wait_reason.value if wait_reason else None,
            "error_code": error_code,
            "state_version": state_version_after,
        }
        if reason is not None:
            details["reason"] = reason
        entry = self._audit.append(
            tx,
            NewAuditEntry(
                actor_kind=actor_kind_of(actor),
                actor_ref=actor,
                authority=authority_of(rule),
                action=rule.audit_event,
                target_kind=entity.value,
                target_id=kind.from_uuid(entity_id),
                occurred_at=occurred_at,
                job_id=JOB.from_uuid(job_id),
                correlation_id=CORRELATION.from_uuid(correlation_id),
                details=details,
            ),
        )
        cur.execute(
            "INSERT INTO state_transitions (id, org_id, entity_kind, entity_id, transition_id,"
            " from_state, to_state, wait_reason, actor_kind, actor_ref, authority, error_code,"
            " state_version_after, correlation_id, occurred_at, audit_seq)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                STATE_TRANSITION.to_uuid(STATE_TRANSITION.new()),
                org_uuid_of(tx),
                entity.value,
                entity_id,
                rule.transition_id.value,
                rule.from_state,
                rule.to_state,
                wait_reason.value if wait_reason else None,
                actor_kind_of(actor).value,
                actor,
                authority_of(rule),
                error_code,
                state_version_after,
                correlation_id,
                occurred_at,
                entry.seq,
            ),
        )

    @staticmethod
    def _creation_rule(tid: TransitionId, initial: str, actor: ActorRef) -> Rule:
        rule = find_rule(tid, None, initial)
        assert rule is not None  # noqa: S101 - T01 / J01 are in the table
        if actor_kind_of(actor) not in rule.actor_kinds:
            raise InvalidTransitionError(f"{tid.value} is not allowed for this actor")
        return rule

    # --- jobs -------------------------------------------------------------------------------------
    def create_job(self, tx: TenantTransaction, job: NewJob) -> JobRecord:
        rule = self._creation_rule(TransitionId.J01, JobState.PENDING, tx.context.actor)
        org = org_uuid_of(tx)
        with self._cur(tx) as cur:
            cur.execute(
                "INSERT INTO jobs (id, org_id, workspace_id, project_id, channel_id, parent_job_id,"
                " production_type_key, production_type_version, language, priority, deadline,"
                " correlation_id, idempotency_key, requested_by, input_ref, currency)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (org_id, idempotency_key) DO NOTHING RETURNING *",
                (
                    new_uuid7(),
                    org,
                    WORKSPACE.to_uuid(job.workspace_id),
                    PROJECT.to_uuid(job.project_id) if job.project_id else None,
                    CHANNEL.to_uuid(job.channel_id) if job.channel_id else None,
                    JOB.to_uuid(job.parent_job_id) if job.parent_job_id else None,
                    job.production_type_key.value,
                    job.production_type_version,
                    job.language,
                    job.priority.queue_int,
                    job.deadline,
                    CORRELATION.to_uuid(job.correlation_id),
                    job.idempotency_key,
                    job.requested_by,
                    job.input_ref,
                    job.currency,
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT * FROM jobs WHERE org_id = %s AND idempotency_key = %s",
                    (org, job.idempotency_key),
                )
                existing = cur.fetchone()
                if existing is None:  # pragma: no cover - conflict implies the row exists
                    raise LockConflictError("job create raced with a concurrent delete")
                return _job(existing)
            self._record(
                tx,
                cur,
                rule,
                entity_id=row["id"],
                job_id=row["id"],
                correlation_id=row["correlation_id"],
                state_version_after=row["state_version"],
                occurred_at=row["state_changed_at"],
            )
            return _job(row)

    def get_job(self, tx: TenantTransaction, job_id: JobId) -> JobRecord | None:
        with self._cur(tx) as cur:
            cur.execute(
                "SELECT * FROM jobs WHERE org_id = %s AND id = %s",
                (org_uuid_of(tx), JOB.to_uuid(job_id)),
            )
            row = cur.fetchone()
        return None if row is None else _job(row)

    def transition_job(self, tx: TenantTransaction, change: JobTransition) -> JobRecord:
        rule = check_job(change)
        org = org_uuid_of(tx)
        job_uuid = JOB.to_uuid(change.job_id)
        with self._cur(tx) as cur:
            cur.execute(
                "UPDATE jobs SET state = %(to)s, state_version = state_version + 1,"
                " state_changed_at = now(), outcome = %(outcome)s,"
                " failed_task_id = coalesce(%(failed)s, failed_task_id),"
                " monetized_destination = coalesce(%(monetized)s, monetized_destination),"
                " completed_at = CASE WHEN %(to)s = 'COMPLETED' THEN now() ELSE completed_at END"
                " WHERE org_id = %(org)s AND id = %(id)s AND state = %(from)s"
                " AND state_version = %(expected)s RETURNING *",
                {
                    "to": change.to_state.value,
                    "outcome": change.outcome.value if change.outcome else None,
                    "failed": TASK.to_uuid(change.failed_task_id)
                    if change.failed_task_id
                    else None,
                    "monetized": change.monetized_destination,
                    "org": org,
                    "id": job_uuid,
                    "from": change.from_state.value,
                    "expected": change.expected_state_version,
                },
            )
            row = cur.fetchone()
            if row is None:
                self._conflict(cur, "jobs", org, job_uuid)
            assert row is not None  # noqa: S101 - _conflict always raises
            self._record(
                tx,
                cur,
                rule,
                entity_id=job_uuid,
                job_id=job_uuid,
                correlation_id=row["correlation_id"],
                state_version_after=row["state_version"],
                occurred_at=row["state_changed_at"],
                reason=change.reason,
            )
            return _job(row)

    @staticmethod
    def _conflict(cur: psycopg.Cursor[Row], table: str, org: uuid.UUID, row_id: uuid.UUID) -> None:
        cur.execute(
            psycopg.sql.SQL(
                "SELECT state, state_version FROM {} WHERE org_id = %s AND id = %s"
            ).format(psycopg.sql.Identifier(table)),
            (org, row_id),
        )
        current = cur.fetchone()
        if current is None:
            raise MissingDependencyError(f"{table[:-1]} not found in this tenant")
        raise LockConflictError(
            "state or state_version changed; re-read and re-evaluate",
            details={"state": current["state"], "state_version": current["state_version"]},
        )

    def add_job_cost(
        self, tx: TenantTransaction, job_id: JobId, estimate_micros: int, verified_micros: int
    ) -> None:
        if estimate_micros < 0 or verified_micros < 0:
            raise InputInvalidError("cost amounts are non-negative micros")
        with self._cur(tx) as cur:
            cur.execute(
                "UPDATE jobs SET cost_estimate_micros = cost_estimate_micros + %s,"
                " cost_verified_micros = cost_verified_micros + %s"
                " WHERE org_id = %s AND id = %s",
                (estimate_micros, verified_micros, org_uuid_of(tx), JOB.to_uuid(job_id)),
            )
            if cur.rowcount != 1:
                raise MissingDependencyError("job not found in this tenant")

    # --- tasks ------------------------------------------------------------------------------------
    @staticmethod
    def _check_stages(tasks: Sequence[NewTask]) -> None:
        """``stage_id`` format (0058 CHECK); one task per ``(stage_id, iteration)`` per batch."""
        seen: set[tuple[str, int]] = set()
        for task in tasks:
            stage = task.stage_id
            if stage is None:
                continue
            if not isinstance(stage, str) or not _STAGE_ID.fullmatch(stage):
                raise InputInvalidError(
                    "stage_id is malformed", details={"stage_id": str(stage)[:64]}
                )
            if task.iteration < 0:
                raise InputInvalidError("iteration must be >= 0")
            key = (stage, task.iteration)
            if key in seen:
                raise InputInvalidError(
                    "two tasks of one stage and iteration in the batch",
                    details={"stage_id": stage, "iteration": task.iteration},
                )
            seen.add(key)

    @staticmethod
    def _check_dag(tasks: Sequence[NewTask]) -> None:
        n = len(tasks)
        for i, task in enumerate(tasks):
            for dep in task.depends_on:
                if not 0 <= dep < n or dep == i:
                    raise InputInvalidError("depends_on must index another task of the batch")
        state = [0] * n  # 0 new, 1 on stack, 2 done

        def visit(i: int) -> None:
            if state[i] == 1:
                raise InputInvalidError("task graph is not a DAG")
            if state[i] == 0:
                state[i] = 1
                for dep in tasks[i].depends_on:
                    visit(dep)
                state[i] = 2

        for i in range(n):
            visit(i)

    def create_tasks(
        self, tx: TenantTransaction, job_id: JobId, tasks: Sequence[NewTask]
    ) -> Sequence[TaskRecord]:
        rule = self._creation_rule(TransitionId.T01, TaskState.PENDING, tx.context.actor)
        self._check_dag(tasks)
        self._check_stages(tasks)
        org = org_uuid_of(tx)
        job_uuid = JOB.to_uuid(job_id)
        with self._cur(tx) as cur:
            cur.execute(
                "SELECT state, task_count, correlation_id FROM jobs"
                " WHERE org_id = %s AND id = %s FOR UPDATE",
                (org, job_uuid),
            )
            job = cur.fetchone()
            if job is None:
                raise MissingDependencyError("job not found in this tenant")
            if job["state"] not in _T01_JOB_STATES:
                raise InvalidTransitionError("T01 needs the job in VALIDATING/RUNNING/CHECKPOINTED")
            if job["task_count"] + len(tasks) > self._max_tasks:
                raise LoopCapExceededError(
                    "limits.max_tasks_per_job reached",
                    details={"task_count": job["task_count"], "adding": len(tasks)},
                )
            for task in tasks:
                if task.stage_id is None:
                    continue
                cur.execute(
                    "SELECT 1 FROM tasks WHERE org_id = %s AND job_id = %s AND stage_id = %s"
                    " AND iteration = %s AND state <> 'CANCELLED'",
                    (org, job_uuid, task.stage_id, task.iteration),
                )
                if cur.fetchone() is not None:
                    raise InputInvalidError(
                        "a live task of this stage and iteration exists",
                        details={"stage_id": task.stage_id, "iteration": task.iteration},
                    )
            ids = [new_uuid7() for _ in tasks]
            created: list[TaskRecord] = []
            for task_uuid, task in zip(ids, tasks, strict=True):
                cur.execute(
                    "INSERT INTO tasks (id, org_id, job_id, task_type, agent_id, iteration,"
                    " is_required, priority, resource_class, required_capabilities,"
                    " idempotency_key, payload_schema, payload_schema_version, resource_budget,"
                    " max_attempts, deadline, stage_id)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " RETURNING *",
                    (
                        task_uuid,
                        org,
                        job_uuid,
                        task.task_type,
                        task.agent_id,
                        task.iteration,
                        task.is_required,
                        task.priority.queue_int,
                        task.resource_class.value,
                        [c.value for c in task.required_capabilities],
                        task.idempotency_key,
                        task.payload_schema,
                        task.payload_schema_version,
                        Jsonb(task.resource_budget.to_doc()),
                        task.max_attempts,
                        task.deadline,
                        task.stage_id,
                    ),
                )
                row = cur.fetchone()
                assert row is not None  # noqa: S101 - INSERT ... RETURNING
                self._record(
                    tx,
                    cur,
                    rule,
                    entity_id=task_uuid,
                    job_id=job_uuid,
                    correlation_id=job["correlation_id"],
                    state_version_after=row["state_version"],
                    occurred_at=row["state_changed_at"],
                )
                created.append(_task(row))
            for task_uuid, task in zip(ids, tasks, strict=True):
                for dep in task.depends_on:
                    cur.execute(
                        "INSERT INTO task_dependencies (org_id, task_id, depends_on_task_id)"
                        " VALUES (%s, %s, %s)",
                        (org, task_uuid, ids[dep]),
                    )
            cur.execute(
                "UPDATE jobs SET task_count = task_count + %s WHERE org_id = %s AND id = %s",
                (len(tasks), org, job_uuid),
            )
        return created

    def repoint_dependency(
        self,
        tx: TenantTransaction,
        task_id: TaskId,
        old_upstream_id: TaskId,
        new_upstream_id: TaskId,
    ) -> None:
        task_u, old_u, new_u = (
            TASK.to_uuid(t) for t in (task_id, old_upstream_id, new_upstream_id)
        )
        if old_u == new_u:
            raise InputInvalidError("old and new upstream task are the same")
        if task_u == new_u:
            raise InputInvalidError("a task cannot depend on itself")
        org = org_uuid_of(tx)
        with self._cur(tx) as cur:
            cur.execute(
                "SELECT id, job_id FROM tasks WHERE org_id = %s AND id = ANY(%s) ORDER BY id"
                " FOR UPDATE",
                (org, [task_u, old_u, new_u]),
            )
            jobs = {r["id"]: r["job_id"] for r in cur.fetchall()}
            if {task_u, old_u, new_u} - jobs.keys():
                raise MissingDependencyError("task not found in this tenant")
            if not jobs[task_u] == jobs[old_u] == jobs[new_u]:
                raise InputInvalidError("re-pointing is only allowed within one job")
            cur.execute(
                "SELECT depends_on_task_id FROM task_dependencies WHERE org_id = %s"
                " AND task_id = %s AND depends_on_task_id = ANY(%s)",
                (org, task_u, [old_u, new_u]),
            )
            edges = {r["depends_on_task_id"] for r in cur.fetchall()}
            if old_u not in edges:
                raise MissingDependencyError("no dependency on the old upstream task")
            if new_u in edges:
                raise InputInvalidError("the dependency on the new upstream task already exists")
            cur.execute(
                "UPDATE task_dependencies SET depends_on_task_id = %s"
                " WHERE org_id = %s AND task_id = %s AND depends_on_task_id = %s",
                (new_u, org, task_u, old_u),
            )

    def get_task(self, tx: TenantTransaction, task_id: TaskId) -> TaskRecord | None:
        with self._cur(tx) as cur:
            cur.execute(
                "SELECT * FROM tasks WHERE org_id = %s AND id = %s",
                (org_uuid_of(tx), TASK.to_uuid(task_id)),
            )
            row = cur.fetchone()
        return None if row is None else _task(row)

    def list_tasks(self, tx: TenantTransaction, job_id: JobId) -> Sequence[TaskRecord]:
        with self._cur(tx) as cur:
            cur.execute(
                "SELECT * FROM tasks WHERE org_id = %s AND job_id = %s ORDER BY created_at, id",
                (org_uuid_of(tx), JOB.to_uuid(job_id)),
            )
            return [_task(r) for r in cur.fetchall()]

    def _edges(
        self, tx: TenantTransaction, task_id: TaskId, column: str, other: str
    ) -> list[TaskId]:
        query = psycopg.sql.SQL(
            "SELECT {} AS t FROM task_dependencies WHERE org_id = %s AND {} = %s ORDER BY 1"
        ).format(psycopg.sql.Identifier(other), psycopg.sql.Identifier(column))
        with self._cur(tx) as cur:
            cur.execute(query, (org_uuid_of(tx), TASK.to_uuid(task_id)))
            return [TASK.from_uuid(r["t"]) for r in cur.fetchall()]

    def dependencies(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[TaskId]:
        return self._edges(tx, task_id, "task_id", "depends_on_task_id")

    def dependants(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[TaskId]:
        return self._edges(tx, task_id, "depends_on_task_id", "task_id")

    def transition_task(self, tx: TenantTransaction, change: TaskTransition) -> TaskRecord:
        rule = check_task(change)
        org = org_uuid_of(tx)
        task_uuid = TASK.to_uuid(change.task_id)
        error = change.error
        params: Mapping[str, Any] = {
            "to": change.to_state.value,
            "wait": change.wait_reason.value if change.wait_reason else None,
            "next": change.next_attempt_at,
            "input_ref": change.input_ref,
            "input_sha": _unhex(change.input_sha256),
            "input_schema": change.input_schema_version,
            "output_ref": change.output_ref,
            "output_sha": _unhex(change.output_sha256),
            "resume": CHECKPOINT.to_uuid(change.resume_checkpoint_id)
            if change.resume_checkpoint_id
            else None,
            "approval": APPROVAL.to_uuid(change.approval_id) if change.approval_id else None,
            "error_code": error.code if error else None,
            "error_class": error.error_class.value if error else None,
            "error": _error_doc(error),
            "org": org,
            "id": task_uuid,
            "from": change.from_state.value,
            "expected": change.expected_state_version,
        }
        with self._cur(tx) as cur:
            cur.execute(
                "UPDATE tasks SET state = %(to)s, wait_reason = %(wait)s,"
                " state_version = state_version + 1, state_changed_at = now(),"
                " next_attempt_at = CASE WHEN %(to)s = 'COMPLETED' THEN NULL"
                " ELSE coalesce(%(next)s, next_attempt_at) END,"
                " input_ref = coalesce(%(input_ref)s, input_ref),"
                " input_sha256 = coalesce(%(input_sha)s, input_sha256),"
                " input_schema_version = coalesce(%(input_schema)s, input_schema_version),"
                " output_ref = coalesce(%(output_ref)s, output_ref),"
                " output_sha256 = coalesce(%(output_sha)s, output_sha256),"
                " resume_checkpoint_id = coalesce(%(resume)s, resume_checkpoint_id),"
                " approval_id = coalesce(%(approval)s, approval_id),"
                " error_code = CASE WHEN %(to)s = 'COMPLETED' THEN NULL"
                " ELSE coalesce(%(error_code)s, error_code) END,"
                " error_class = CASE WHEN %(to)s = 'COMPLETED' THEN NULL"
                " ELSE coalesce(%(error_class)s, error_class) END,"
                " last_error = CASE WHEN %(to)s = 'COMPLETED' THEN NULL"
                " ELSE coalesce(%(error)s, last_error) END,"
                " completed_at = CASE WHEN %(to)s = 'COMPLETED' THEN now() ELSE completed_at END"
                " WHERE org_id = %(org)s AND id = %(id)s AND state = %(from)s"
                " AND state_version = %(expected)s"
                " RETURNING *, (SELECT j.correlation_id FROM jobs j"
                "   WHERE j.org_id = tasks.org_id AND j.id = tasks.job_id) AS job_correlation_id",
                params,
            )
            row = cur.fetchone()
            if row is None:
                self._conflict(cur, "tasks", org, task_uuid)
            assert row is not None  # noqa: S101 - _conflict always raises
            self._record(
                tx,
                cur,
                rule,
                entity_id=task_uuid,
                job_id=row["job_id"],
                correlation_id=row["job_correlation_id"],
                state_version_after=row["state_version"],
                occurred_at=row["state_changed_at"],
                wait_reason=change.wait_reason,
                error_code=error.code if error else None,
                reason=change.reason,
            )
            return _task(row)

    def request_cancel(self, tx: TenantTransaction, task_id: TaskId, reason: str) -> TaskRecord:
        if not reason:
            raise InputInvalidError("a cancel request records its reason")
        with self._cur(tx) as cur:
            cur.execute(
                "UPDATE tasks SET cancel_requested_at = coalesce(cancel_requested_at, now()),"
                " cancel_reason = coalesce(cancel_reason, %s)"
                " WHERE org_id = %s AND id = %s RETURNING *",
                (reason, org_uuid_of(tx), TASK.to_uuid(task_id)),
            )
            row = cur.fetchone()
        if row is None:
            raise MissingDependencyError("task not found in this tenant")
        return _task(row)

    # --- attempts ---------------------------------------------------------------------------------
    def start_attempt(
        self,
        tx: TenantTransaction,
        task_id: TaskId,
        worker_id: WorkerId,
        resumed_from_checkpoint_id: CheckpointId | None,
        is_replay: bool,
    ) -> AttemptRecord:
        org = org_uuid_of(tx)
        task_uuid = TASK.to_uuid(task_id)
        with self._cur(tx) as cur:
            # T07 side effect (03 section 11.3): the task is RUNNING and this worker holds its queue
            # row under a live lease; a worker whose lease lapsed cannot open an attempt.
            cur.execute(
                "UPDATE tasks SET attempt_count = attempt_count + 1"
                " WHERE org_id = %s AND id = %s AND state = 'RUNNING' AND EXISTS ("
                "  SELECT 1 FROM task_queue q WHERE q.org_id = tasks.org_id"
                "   AND q.task_id = tasks.id AND q.status = 'CLAIMED' AND q.claimed_by = %s"
                "   AND q.lease_expires_at >= now())"
                " RETURNING attempt_count",
                (org, task_uuid, WORKER.to_uuid(worker_id)),
            )
            counted = cur.fetchone()
            if counted is None:
                cur.execute(
                    "SELECT state FROM tasks WHERE org_id = %s AND id = %s", (org, task_uuid)
                )
                found = cur.fetchone()
                if found is None:
                    raise MissingDependencyError("task not found in this tenant")
                if found["state"] != "RUNNING":
                    raise InvalidTransitionError("an attempt starts only on a RUNNING task")
                raise WorkerLostError("this worker does not hold a live lease on the task")
            cur.execute(
                "INSERT INTO task_attempts (id, org_id, task_id, attempt_no, worker_id, started_at,"
                " heartbeat_at, resumed_from_checkpoint_id, is_replay)"
                " VALUES (%s, %s, %s, %s, %s, now(), now(), %s, %s) RETURNING *",
                (
                    new_uuid7(),
                    org,
                    task_uuid,
                    counted["attempt_count"],
                    WORKER.to_uuid(worker_id),
                    CHECKPOINT.to_uuid(resumed_from_checkpoint_id)
                    if resumed_from_checkpoint_id
                    else None,
                    is_replay,
                ),
            )
            row = cur.fetchone()
        assert row is not None  # noqa: S101 - INSERT ... RETURNING
        return _attempt(row)

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
        if result is AttemptResult.RUNNING:
            raise InputInvalidError("a finished attempt has a final result")
        if duration_ms < 0:
            raise InputInvalidError("duration_ms is non-negative")
        with self._cur(tx) as cur:
            cur.execute(
                "UPDATE task_attempts SET result = %s, ended_at = now(), duration_ms = %s,"
                " output_ref = %s, resource_usage = %s, error_code = %s, error = %s"
                " WHERE org_id = %s AND id = %s AND result = 'RUNNING' RETURNING *",
                (
                    result.value,
                    duration_ms,
                    output_ref,
                    Jsonb(resource_usage.to_doc()) if resource_usage else None,
                    error.code if error else None,
                    _error_doc(error),
                    org_uuid_of(tx),
                    ATTEMPT.to_uuid(attempt_id),
                ),
            )
            row = cur.fetchone()
        if row is None:
            raise InvalidTransitionError("attempt not found or already finished")
        return _attempt(row)

    def heartbeat_attempt(self, tx: TenantTransaction, attempt_id: AttemptId) -> None:
        with self._cur(tx) as cur:
            cur.execute(
                "UPDATE task_attempts SET heartbeat_at = now()"
                " WHERE org_id = %s AND id = %s AND result = 'RUNNING'",
                (org_uuid_of(tx), ATTEMPT.to_uuid(attempt_id)),
            )
            if cur.rowcount != 1:
                raise InvalidTransitionError("attempt not found or no longer running")
