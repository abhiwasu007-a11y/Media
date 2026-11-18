"""``PgJobStore`` (04 section 5.3; 03 sections 11.3-11.7) against PostgreSQL as ``amw_app``."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from amw_core.contracts.common import ResourceBudget
from amw_core.contracts.error import error_object_from_exception
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
from amw_core.errors import (
    InputInvalidError,
    InvalidTransitionError,
    LockConflictError,
    LoopCapExceededError,
    MissingDependencyError,
    NetworkError,
)
from amw_core.ids import (
    CORRELATION,
    JOB,
    TASK,
    WORKER,
    ActorRef,
    ExecutorId,
    JobId,
    make_idempotency_key,
    new_uuid7,
)
from amw_core.interfaces.job_store import (
    JobStore,
    JobTransition,
    NewJob,
    NewTask,
    TaskRecord,
    TaskTransition,
)
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_core.job_store import PgJobStore
from amw_core.tenancy import PgTenancy
from tests.fake_audit import RecordingAuditLog
from tests.pg_fixtures import Tenant, ensure_production_type

pytestmark = [pytest.mark.integration, pytest.mark.state_machine]
ORCH = ActorRef("agent_01")
WKR = ActorRef("agent_05")
Conn = psycopg.Connection[tuple[Any, ...]]


@pytest.fixture
def audit() -> RecordingAuditLog:
    return RecordingAuditLog()


@pytest.fixture
def store(audit: RecordingAuditLog) -> PgJobStore:
    return PgJobStore(audit, max_tasks_per_job=5)


@pytest.fixture
def worker(admin: Conn) -> Any:
    wid = new_uuid7()
    admin.execute(
        "INSERT INTO workers (id, logical_name, capabilities, resource_classes, max_concurrency,"
        " status, software_version) VALUES (%s, %s, ARRAY['llm'], ARRAY['AI_IO'], 1, 'IDLE', 't')",
        (wid, f"ai-{wid.hex[-8:]}"),
    )
    return WORKER.from_uuid(wid)


@contextmanager
def tx(tenancy: PgTenancy, tenant: Tenant, actor: ActorRef = ORCH) -> Iterator[TenantTransaction]:
    with tenancy.transaction(TenantContext(tenant.org_id, actor)) as t:
        yield t


def new_job(tenant: Tenant, source: str = "topic-1") -> NewJob:
    return NewJob(
        workspace_id=tenant.workspace_id,
        project_id=None,
        channel_id=None,
        parent_job_id=None,
        production_type_key=ProductionTypeKey.CHANNEL_LONG_FORM,
        production_type_version=1,
        language="en",
        priority=Priority.NORMAL,
        deadline=None,
        correlation_id=CORRELATION.new(),
        idempotency_key=make_idempotency_key(tenant.org_id, "job.create", [source]),
        requested_by=ActorRef("sys_operator"),
        input_ref=None,
        currency="INR",
    )


def new_task(job: JobId, tenant: Tenant, n: int, deps: tuple[int, ...] = ()) -> NewTask:
    return NewTask(
        task_type="agent_05.script_draft",
        agent_id=ExecutorId("agent_05"),
        iteration=0,
        is_required=True,
        priority=Priority.NORMAL,
        resource_class=ResourceClass.AI_IO,
        required_capabilities=(Capability.LLM,),
        idempotency_key=make_idempotency_key(
            tenant.org_id, "task.agent_05.script_draft", [job, f"s{n}", "agent_05.script_draft", 0]
        ),
        payload_schema="agent_05.script_draft.input",
        payload_schema_version="1.0.0",
        resource_budget=ResourceBudget(max_cost_micros=1000, currency="INR", max_wall_ms=60_000),
        max_attempts=3,
        deadline=None,
        depends_on=deps,
    )


def _validating_job(store: PgJobStore, t: TenantTransaction, tenant: Tenant) -> JobId:
    job = store.create_job(t, new_job(tenant, str(new_uuid7())))
    moved = store.transition_job(
        t,
        JobTransition(
            job.id,
            TransitionId.J02,
            JobState.PENDING,
            JobState.VALIDATING,
            1,
            ORCH,
            monetized_destination=True,
        ),
    )
    assert moved.state is JobState.VALIDATING
    assert moved.state_version == 2
    return job.id


def _move(
    store: PgJobStore,
    t: TenantTransaction,
    task: TaskRecord,
    tid: TransitionId,
    to: TaskState,
    **kw: Any,
) -> TaskRecord:
    return store.transition_task(
        t, TaskTransition(task.id, tid, task.state, to, task.state_version, t.context.actor, **kw)
    )


def test_is_a_job_store(store: PgJobStore) -> None:
    assert isinstance(store, JobStore)


def test_rejects_bad_limit(audit: RecordingAuditLog) -> None:
    with pytest.raises(InputInvalidError):
        PgJobStore(audit, max_tasks_per_job=0)


def test_create_job_is_idempotent_and_audited(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, store: PgJobStore, audit: RecordingAuditLog
) -> None:
    ensure_production_type(admin)
    spec = new_job(tenant_a)
    with tx(tenancy, tenant_a, ActorRef("sys_operator")) as t:
        first = store.create_job(t, spec)
        again = store.create_job(t, replace(spec, correlation_id=CORRELATION.new()))
        assert again.id == first.id
        assert store.get_job(t, first.id) == first
        assert store.get_job(t, JOB.new()) is None
    assert first.state is JobState.PENDING
    assert first.priority is Priority.NORMAL
    assert audit.actions() == ["job.created"]
    rows = admin.execute(
        "SELECT transition_id, from_state, to_state, actor_kind, audit_seq FROM state_transitions"
        " WHERE entity_id = %s",
        (JOB.to_uuid(first.id),),
    ).fetchall()
    assert rows == [("J01", None, "PENDING", "SYSTEM", audit.entries[0].seq)]


def test_job_transition_locking(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, store: PgJobStore
) -> None:
    ensure_production_type(admin)
    with tx(tenancy, tenant_a) as t:
        job_id = _validating_job(store, t, tenant_a)
        stale = JobTransition(
            job_id, TransitionId.J03, JobState.VALIDATING, JobState.QUEUED, 1, ORCH
        )
        with pytest.raises(LockConflictError):
            store.transition_job(t, stale)
    with tx(tenancy, tenant_a) as t:
        missing = JobTransition(
            JOB.new(), TransitionId.J03, JobState.VALIDATING, JobState.QUEUED, 2, ORCH
        )
        with pytest.raises(MissingDependencyError):
            store.transition_job(t, missing)
    with tx(tenancy, tenant_a) as t, pytest.raises(InvalidTransitionError):
        store.transition_job(
            t,
            JobTransition(job_id, TransitionId.J03, JobState.PENDING, JobState.QUEUED, 2, ORCH),
        )


def test_add_job_cost(tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, store: PgJobStore) -> None:
    ensure_production_type(admin)
    with tx(tenancy, tenant_a) as t:
        job_id = store.create_job(t, new_job(tenant_a, "cost")).id
        store.add_job_cost(t, job_id, 120, 100)
        store.add_job_cost(t, job_id, 5, 0)
        job = store.get_job(t, job_id)
        assert job is not None
        assert (job.cost_estimate_micros, job.cost_verified_micros) == (125, 100)
        with pytest.raises(InputInvalidError):
            store.add_job_cost(t, job_id, -1, 0)
        with pytest.raises(MissingDependencyError):
            store.add_job_cost(t, JOB.new(), 1, 1)


def test_task_lifecycle_end_to_end(
    tenancy: PgTenancy,
    admin: Conn,
    tenant_a: Tenant,
    store: PgJobStore,
    audit: RecordingAuditLog,
    worker: Any,
) -> None:
    ensure_production_type(admin)
    with tx(tenancy, tenant_a) as t:
        job_id = _validating_job(store, t, tenant_a)
        a, b = store.create_tasks(
            t, job_id, [new_task(job_id, tenant_a, 1), new_task(job_id, tenant_a, 2, (0,))]
        )
        assert store.dependencies(t, b.id) == [a.id]
        assert store.dependants(t, a.id) == [b.id]
        assert [x.id for x in store.list_tasks(t, job_id)] == [a.id, b.id]
        job = store.get_job(t, job_id)
        assert job is not None
        assert job.task_count == 2
        sha = "ab" * 32
        a = _move(
            store,
            t,
            a,
            TransitionId.T02,
            TaskState.VALIDATING,
            input_ref="amw-blob://x/in.json",
            input_sha256=sha,
            input_schema_version="1.0.0",
        )
        assert a.input_sha256 == sha
        a = _move(store, t, a, TransitionId.T03, TaskState.QUEUED)
    with tx(tenancy, tenant_a, WKR) as t:
        a = _move(store, t, a, TransitionId.T07, TaskState.RUNNING)
        attempt = store.start_attempt(t, a.id, worker, None, False)
        assert attempt.attempt_no == 1
        assert attempt.result is AttemptResult.RUNNING
        store.heartbeat_attempt(t, attempt.id)
        err = error_object_from_exception(
            NetworkError("reset"),
            actor="agent_05",
            attempt_no=1,
            occurred_at=datetime.now(UTC),
            correlation_id=CORRELATION.new(),
        )
        done = store.finish_attempt(
            t, attempt.id, AttemptResult.FAILED_RETRYABLE, 12, None, None, err
        )
        assert done.error == err
        assert done.ended_at is not None
        with pytest.raises(InvalidTransitionError):
            store.finish_attempt(t, attempt.id, AttemptResult.SUCCEEDED, 1, None, None, None)
        with pytest.raises(InvalidTransitionError):
            store.heartbeat_attempt(t, attempt.id)
        a = _move(
            store,
            t,
            a,
            TransitionId.T10,
            TaskState.RETRY_WAIT,
            next_attempt_at=datetime.now(UTC) + timedelta(seconds=5),
            error=err,
        )
        assert a.last_error == err
        assert a.attempt_count == 1
    with tx(tenancy, tenant_a, ActorRef("sys_scheduler")) as t:
        a = _move(store, t, a, TransitionId.T12, TaskState.QUEUED)
    with tx(tenancy, tenant_a, WKR) as t:
        a = _move(store, t, a, TransitionId.T07, TaskState.RUNNING)
        attempt = store.start_attempt(t, a.id, worker, None, False)
        usage = ResourceUsage(
            cpu_ms=1,
            peak_rss_bytes=1,
            tokens_in=1,
            tokens_out=1,
            tokens_cached_in=0,
            llm_calls=1,
            provider_calls=1,
            cost_estimate_micros=10,
            currency="INR",
            cost_entry_ids=(),
        )
        finished = store.finish_attempt(
            t, attempt.id, AttemptResult.SUCCEEDED, 5, "amw-blob://o", usage, None
        )
        assert finished.resource_usage == usage
        assert finished.attempt_no == 2
        a = _move(
            store,
            t,
            a,
            TransitionId.T08,
            TaskState.COMPLETED,
            output_ref="amw-blob://o",
            output_sha256="cd" * 32,
        )
        assert a.completed_at is not None
        assert a.output_sha256 == "cd" * 32
    events = audit.actions()
    assert events.count("task.created") == 2
    assert events[-1] == "task.completed"
    seqs = admin.execute(
        "SELECT audit_seq FROM state_transitions WHERE org_id = %s ORDER BY audit_seq",
        (tenant_a.org_uuid,),
    ).fetchall()
    assert [s for (s,) in seqs] == [e.seq for e in audit.entries if e.org_id == tenant_a.org_id]


def test_checkpoint_and_cancel(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, store: PgJobStore
) -> None:
    ensure_production_type(admin)
    with tx(tenancy, tenant_a) as t:
        job_id = _validating_job(store, t, tenant_a)
        (task,) = store.create_tasks(t, job_id, [new_task(job_id, tenant_a, 1)])
        task = _move(store, t, task, TransitionId.T02, TaskState.VALIDATING)
        task = _move(
            store,
            t,
            task,
            TransitionId.T05,
            TaskState.CHECKPOINTED,
            wait_reason=WaitReason.AWAITING_BUDGET,
        )
        assert task.wait_reason is WaitReason.AWAITING_BUDGET
        task = store.request_cancel(t, task.id, "superseded")
        assert task.cancel_reason == "superseded"
        assert task.cancel_requested_at is not None
        task = _move(store, t, task, TransitionId.T19, TaskState.CANCELLED, reason="superseded")
        assert task.wait_reason is None
        with pytest.raises(InputInvalidError):
            store.request_cancel(t, task.id, "")
        with pytest.raises(MissingDependencyError):
            store.request_cancel(t, TASK.new(), "x")


def test_task_lock_conflict_and_missing(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, store: PgJobStore
) -> None:
    ensure_production_type(admin)
    with tx(tenancy, tenant_a) as t:
        job_id = _validating_job(store, t, tenant_a)
        (task,) = store.create_tasks(t, job_id, [new_task(job_id, tenant_a, 1)])
        _move(store, t, task, TransitionId.T02, TaskState.VALIDATING)
        with pytest.raises(LockConflictError):
            _move(store, t, task, TransitionId.T02, TaskState.VALIDATING)
        with pytest.raises(MissingDependencyError):
            store.transition_task(
                t,
                TaskTransition(
                    TASK.new(), TransitionId.T02, TaskState.PENDING, TaskState.VALIDATING, 1, ORCH
                ),
            )
        assert store.get_task(t, TASK.new()) is None


def test_create_tasks_guards(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, store: PgJobStore
) -> None:
    ensure_production_type(admin)
    with tx(tenancy, tenant_a) as t:
        pending = store.create_job(t, new_job(tenant_a, "pending"))
        with pytest.raises(InvalidTransitionError):
            store.create_tasks(t, pending.id, [new_task(pending.id, tenant_a, 1)])
        with pytest.raises(MissingDependencyError):
            store.create_tasks(t, JOB.new(), [new_task(pending.id, tenant_a, 1)])
    with tx(tenancy, tenant_a) as t:
        job_id = _validating_job(store, t, tenant_a)
        too_many = [new_task(job_id, tenant_a, i) for i in range(6)]
        with pytest.raises(LoopCapExceededError):
            store.create_tasks(t, job_id, too_many)
        for bad in (
            [new_task(job_id, tenant_a, 1, (0,))],
            [new_task(job_id, tenant_a, 1, (3,))],
            [new_task(job_id, tenant_a, 1, (1,)), new_task(job_id, tenant_a, 2, (0,))],
        ):
            with pytest.raises(InputInvalidError):
                store.create_tasks(t, job_id, bad)
    with (
        tx(tenancy, tenant_a, ActorRef("sys_scheduler")) as t,
        pytest.raises(InvalidTransitionError),
    ):
        store.create_tasks(t, job_id, [new_task(job_id, tenant_a, 1)])


def test_finish_attempt_input_checks(
    tenancy: PgTenancy, tenant_a: Tenant, store: PgJobStore
) -> None:
    with tx(tenancy, tenant_a) as t:
        with pytest.raises(InputInvalidError):
            store.finish_attempt(t, "att_x", AttemptResult.RUNNING, 1, None, None, None)  # type: ignore[arg-type]
        with pytest.raises(InputInvalidError):
            store.finish_attempt(t, "att_x", AttemptResult.SUCCEEDED, -1, None, None, None)  # type: ignore[arg-type]
        with pytest.raises(MissingDependencyError):
            store.start_attempt(t, TASK.new(), WORKER.new(), None, False)


def test_bad_sha_is_refused(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, store: PgJobStore
) -> None:
    ensure_production_type(admin)
    with tx(tenancy, tenant_a) as t:
        job_id = _validating_job(store, t, tenant_a)
        (task,) = store.create_tasks(t, job_id, [new_task(job_id, tenant_a, 1)])
        for bad in ("zz", "ab"):
            with pytest.raises(InputInvalidError):
                _move(store, t, task, TransitionId.T02, TaskState.VALIDATING, input_sha256=bad)


def test_job_completion_and_failure(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, store: PgJobStore
) -> None:
    ensure_production_type(admin)
    with tx(tenancy, tenant_a) as t:
        job_id = _validating_job(store, t, tenant_a)
        (task,) = store.create_tasks(t, job_id, [new_task(job_id, tenant_a, 1)])
        job = store.transition_job(
            t,
            JobTransition(job_id, TransitionId.J03, JobState.VALIDATING, JobState.QUEUED, 2, ORCH),
        )
        job = store.transition_job(
            t,
            JobTransition(
                job_id,
                TransitionId.J08,
                JobState.QUEUED,
                JobState.FAILED,
                3,
                ORCH,
                failed_task_id=task.id,
            ),
        )
        assert job.failed_task_id == task.id
    with tx(tenancy, tenant_a) as t:
        job_id = _validating_job(store, t, tenant_a)
        store.transition_job(
            t,
            JobTransition(job_id, TransitionId.J03, JobState.VALIDATING, JobState.QUEUED, 2, ORCH),
        )
        job = store.transition_job(
            t,
            JobTransition(
                job_id,
                TransitionId.J07,
                JobState.QUEUED,
                JobState.COMPLETED,
                3,
                ORCH,
                outcome=JobOutcome.DELIVERED,
            ),
        )
        assert job.completed_at is not None
        assert job.outcome is JobOutcome.DELIVERED
