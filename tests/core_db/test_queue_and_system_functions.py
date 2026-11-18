"""``PgTaskQueue`` and ``PgSystemFunctions`` (ADR-001 A; 04 sections 3.6, 5.4; 07 sections 4, 6)."""

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from amw_core.contracts.envelope import Envelope
from amw_core.enums import (
    Capability,
    CircuitState,
    Priority,
    QueueName,
    ResourceClass,
    TaskState,
    WaitReason,
)
from amw_core.errors import (
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
    WorkerLostError,
)
from amw_core.ids import (
    CORRELATION,
    JOB,
    MESSAGE,
    QUEUE_ITEM,
    TASK,
    WORKER,
    ActorRef,
    TaskId,
    WorkerId,
    new_uuid7,
)
from amw_core.interfaces.queue import ClaimRequest, NewQueueItem, TaskQueue
from amw_core.interfaces.system_functions import BreakerKey, SystemFunctions
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.queue import PgTaskQueue
from amw_core.system_functions import BreakerConfig, DwellLimits, PgSystemFunctions
from amw_core.tenancy import PgTenancy, connection_of, dsn_connection_factory
from tests.pg_fixtures import Tenant, insert_job, insert_task, make_tenant

pytestmark = pytest.mark.integration
Conn = psycopg.Connection[tuple[Any, ...]]
ORCH = ActorRef("agent_01")
SCHED = ActorRef("sys_scheduler")


@pytest.fixture
def queue(pg_dsn: str) -> PgTaskQueue:
    return PgTaskQueue(dsn_connection_factory(pg_dsn, role="amw_app"))


CFG = BreakerConfig(
    window_ms=60_000,
    min_calls=5,
    failure_ratio=Decimal("0.5"),
    consecutive_failures=3,
    open_ms=50,
    open_ms_max=1_000,
    half_open_successes_to_close=2,
)


@pytest.fixture
def sysfn(pg_dsn: str) -> PgSystemFunctions:
    return PgSystemFunctions(
        dsn_connection_factory(pg_dsn, role="amw_app"),
        breaker_config=lambda _key: CFG,
        dwell=DwellLimits(validating_ms=1, failed_without_dlq_ms=1),
    )


@pytest.fixture(autouse=True)
def clean_queue(admin: Conn) -> None:
    """The session database is shared: start each test with an empty queue."""
    admin.execute("UPDATE task_queue SET status = 'DONE' WHERE status IN ('READY', 'CLAIMED')")


def worker(
    admin: Conn, caps: list[str] | None = None, dedicated: uuid.UUID | None = None
) -> WorkerId:
    wid = new_uuid7()
    admin.execute(
        "INSERT INTO workers (id, logical_name, capabilities, resource_classes, max_concurrency,"
        " status, software_version, dedicated_org_id)"
        " VALUES (%s, %s, %s, ARRAY['AI_IO', 'LIGHT'], 2, 'IDLE', 't', %s)",
        (wid, f"w-{wid.hex[-10:]}", caps or ["llm", "tts"], dedicated),
    )
    return WORKER.from_uuid(wid)


def envelope(tenant: Tenant, job: uuid.UUID, task: uuid.UUID) -> Envelope:
    return Envelope.model_validate(
        {
            "org_id": tenant.org_id,
            "message_id": MESSAGE.new(),
            "sender": "agent_01",
            "receiver": "agent_05",
            "job_id": JOB.from_uuid(job),
            "task_id": TASK.from_uuid(task),
            "payload_ref": {
                "uri": f"amw-blob://{tenant.org_id}/jobs/x/input.json",
                "schema": "amw.task_input",
                "schema_version": "1.0.0",
                "sha256": "cd" * 32,
                "size_bytes": 10,
                "media_type": "application/json",
            },
            "priority": "NORMAL",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "correlation_id": CORRELATION.new(),
            "schema_version": "1.0.0",
        }
    )


def enqueue(
    tenancy: PgTenancy,
    queue: PgTaskQueue,
    admin: Conn,
    tenant: Tenant,
    *,
    priority: Priority = Priority.NORMAL,
    caps: tuple[Capability, ...] = (Capability.LLM,),
    when: datetime | None = None,
    name: QueueName = QueueName.AI,
) -> TaskId:
    job = insert_job(admin, tenant)
    task = insert_task(admin, tenant, job)
    with tenancy.transaction(TenantContext(tenant.org_id, ORCH)) as tx:
        item = queue.enqueue(
            tx,
            NewQueueItem(
                task_id=TASK.from_uuid(task),
                job_id=JOB.from_uuid(job),
                queue_name=name,
                priority=priority,
                resource_class=ResourceClass.AI_IO,
                required_capabilities=caps,
                scheduled_at=when or datetime.now(UTC) - timedelta(seconds=1),
                envelope=envelope(tenant, job, task),
            ),
        )
    assert item.status.value == "READY"
    assert item.org_id == tenant.org_id
    return TASK.from_uuid(task)


def req(
    w: WorkerId, limit: int = 1, caps: tuple[Capability, ...] = (Capability.LLM, Capability.TTS)
) -> ClaimRequest:
    return ClaimRequest(
        worker_id=w,
        queue_names=(QueueName.AI,),
        capabilities=caps,
        resource_classes=(ResourceClass.AI_IO,),
        lease_ms=60_000,
        limit=limit,
    )


def test_protocols(queue: PgTaskQueue, sysfn: PgSystemFunctions) -> None:
    assert isinstance(queue, TaskQueue)
    assert isinstance(sysfn, SystemFunctions)


def test_enqueue_claim_heartbeat_done(
    tenancy: PgTenancy, queue: PgTaskQueue, admin: Conn, tenant_a: Tenant
) -> None:
    w = worker(admin)
    task = enqueue(tenancy, queue, admin, tenant_a)
    (claimed,) = queue.claim(req(w, limit=5))
    assert claimed.org_id == tenant_a.org_id
    assert claimed.task_id == task
    assert claimed.envelope.task_id == task
    assert queue.claim(req(w)) == []
    until = queue.heartbeat(claimed.queue_item_id, w, 120_000)
    assert until > datetime.now(UTC) + timedelta(seconds=60)
    with pytest.raises(WorkerLostError):
        queue.heartbeat(claimed.queue_item_id, worker(admin), 1_000)
    with tenancy.transaction(TenantContext(tenant_a.org_id, ActorRef("agent_05"))) as tx:
        with pytest.raises(WorkerLostError):  # another worker cannot complete it
            queue.mark_done(tx, claimed.queue_item_id, worker(admin))
        queue.mark_done(tx, claimed.queue_item_id, w)
        with pytest.raises(WorkerLostError):
            queue.mark_done(tx, claimed.queue_item_id, w)
    with pytest.raises(WorkerLostError):
        queue.heartbeat(claimed.queue_item_id, w, 1_000)


def test_mark_done_refused_after_lease_expiry(
    tenancy: PgTenancy, queue: PgTaskQueue, admin: Conn, tenant_a: Tenant
) -> None:
    w = worker(admin)
    enqueue(tenancy, queue, admin, tenant_a)
    (claimed,) = queue.claim(req(w))
    admin.execute(
        "UPDATE task_queue SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
        (QUEUE_ITEM.to_uuid(claimed.queue_item_id),),
    )
    ctx = TenantContext(tenant_a.org_id, ActorRef("agent_05"))
    with tenancy.transaction(ctx) as tx, pytest.raises(WorkerLostError):
        queue.mark_done(tx, claimed.queue_item_id, w)


def test_one_live_row_per_task_and_cancel(
    tenancy: PgTenancy, queue: PgTaskQueue, admin: Conn, tenant_a: Tenant
) -> None:
    task = enqueue(tenancy, queue, admin, tenant_a)
    row = admin.execute(
        "SELECT job_id, envelope FROM task_queue WHERE task_id = %s", (TASK.to_uuid(task),)
    ).fetchone()
    assert row is not None
    with (
        pytest.raises(psycopg.errors.UniqueViolation),
        tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx,
    ):
        queue.enqueue(
            tx,
            NewQueueItem(
                task_id=task,
                job_id=JOB.from_uuid(row[0]),
                queue_name=QueueName.AI,
                priority=Priority.NORMAL,
                resource_class=ResourceClass.AI_IO,
                required_capabilities=(),
                scheduled_at=datetime.now(UTC),
                envelope=Envelope.model_validate(row[1]),
            ),
        )
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        queue.cancel_for_task(tx, task)
    assert queue.claim(req(worker(admin))) == []


def test_enqueue_refuses_foreign_envelope(
    tenancy: PgTenancy, queue: PgTaskQueue, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    job = insert_job(admin, tenant_a)
    task = insert_task(admin, tenant_a, job)
    with (
        pytest.raises(InputInvalidError),
        tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx,
    ):
        queue.enqueue(
            tx,
            NewQueueItem(
                task_id=TASK.from_uuid(task),
                job_id=JOB.from_uuid(job),
                queue_name=QueueName.AI,
                priority=Priority.NORMAL,
                resource_class=ResourceClass.AI_IO,
                required_capabilities=(),
                scheduled_at=datetime.now(UTC),
                envelope=envelope(tenant_b, job, task),
            ),
        )


def test_claim_filters(
    tenancy: PgTenancy, queue: PgTaskQueue, admin: Conn, tenant_a: Tenant
) -> None:
    w = worker(admin, caps=["llm"])
    enqueue(tenancy, queue, admin, tenant_a, caps=(Capability.TTS,))
    enqueue(tenancy, queue, admin, tenant_a, when=datetime.now(UTC) + timedelta(hours=1))
    enqueue(tenancy, queue, admin, tenant_a, name=QueueName.RENDER)
    assert queue.claim(req(w, limit=5, caps=(Capability.LLM,))) == []
    with pytest.raises(InputInvalidError):
        queue.claim(req(w, limit=0))
    with pytest.raises(InputInvalidError):
        queue.heartbeat(QUEUE_ITEM.new(), w, 0)


def test_unregistered_worker_cannot_claim(queue: PgTaskQueue) -> None:
    with pytest.raises(MissingDependencyError):
        queue.claim(req(WORKER.new()))


def test_priority_then_fair_share(
    tenancy: PgTenancy, queue: PgTaskQueue, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    w = worker(admin)
    a1 = enqueue(tenancy, queue, admin, tenant_a)
    a2 = enqueue(tenancy, queue, admin, tenant_a)
    b1 = enqueue(tenancy, queue, admin, tenant_b)
    urgent = enqueue(tenancy, queue, admin, tenant_a, priority=Priority.CRITICAL)
    (first,) = queue.claim(req(w))
    assert first.task_id == urgent  # priority first
    # A now holds one CLAIMED row and B none: B's row goes before A's older rows
    assert [c.task_id for c in queue.claim(req(w, limit=3))] == [b1, a1, a2]


def test_skip_locked_gives_disjoint_claims(
    tenancy: PgTenancy, queue: PgTaskQueue, admin: Conn, tenant_a: Tenant, pg_dsn: str
) -> None:
    w1, w2 = worker(admin), worker(admin)
    first = enqueue(tenancy, queue, admin, tenant_a)
    second = enqueue(tenancy, queue, admin, tenant_a)
    with psycopg.connect(pg_dsn) as held:
        held.execute("SET ROLE amw_app")
        row = held.execute(
            "SELECT task_id FROM amw_queue_claim(%s, ARRAY['llm'], ARRAY['AI_IO'], 1, ARRAY['ai'],"
            " 60000)",
            (WORKER.to_uuid(w1),),
        ).fetchone()
        assert row is not None
        assert TASK.from_uuid(row[0]) == first
        # first claim not committed yet: the other worker skips the locked row
        other = queue.claim(req(w2, limit=2))
        assert [c.task_id for c in other] == [second]
        held.rollback()


def test_dedicated_worker_serves_only_its_org(
    tenancy: PgTenancy, queue: PgTaskQueue, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    enqueue(tenancy, queue, admin, tenant_a)
    b = enqueue(tenancy, queue, admin, tenant_b)
    w = worker(admin, dedicated=tenant_b.org_uuid)
    assert [c.task_id for c in queue.claim(req(w, limit=5))] == [b]


def test_notify_wakes_a_listener(queue: PgTaskQueue) -> None:
    assert queue.wait_for_work([QueueName.AI], timeout_ms=50) is False
    woke: list[bool] = []
    listener = threading.Thread(
        target=lambda: woke.append(queue.wait_for_work([QueueName.AI], 5_000))
    )
    listener.start()
    time.sleep(0.5)
    queue.notify(QueueName.RENDER)  # another queue: not a wake-up for this listener
    queue.notify(QueueName.AI)
    listener.join(10)
    assert woke == [True]


def test_expired_leases_and_reaper_identifiers(
    tenancy: PgTenancy, queue: PgTaskQueue, sysfn: PgSystemFunctions, admin: Conn, tenant_a: Tenant
) -> None:
    w = worker(admin)
    task = enqueue(tenancy, queue, admin, tenant_a)
    (claimed,) = queue.claim(req(w))
    admin.execute(
        "UPDATE task_queue SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
        (QUEUE_ITEM.to_uuid(claimed.queue_item_id),),
    )
    leases = sysfn.expired_leases(ActorRef("sys_reaper"), 100)
    assert (tenant_a.org_id, task, claimed.queue_item_id) in {
        (x.org_id, x.task_id, x.queue_item_id) for x in leases
    }
    with pytest.raises(WorkerLostError):
        queue.heartbeat(claimed.queue_item_id, w, 1_000)


def _place(admin: Conn, task: uuid.UUID, state: str, extra: str = "") -> None:
    with admin.transaction():
        admin.execute("SET LOCAL session_replication_role = replica")
        admin.execute(
            f"UPDATE tasks SET state = %s, state_changed_at = now() - interval '1 hour'{extra}"  # noqa: S608
            " WHERE id = %s",
            (state, task),
        )


def test_due_retries_resumes_and_stuck(
    sysfn: PgSystemFunctions, admin: Conn, tenant_a: Tenant
) -> None:
    job = insert_job(admin, tenant_a)
    retry, later, drain, approval_wait, validating, failed = (
        insert_task(admin, tenant_a, job) for _ in range(6)
    )
    _place(admin, retry, "RETRY_WAIT", ", next_attempt_at = now() - interval '1 second'")
    _place(admin, later, "RETRY_WAIT", ", next_attempt_at = now() + interval '1 hour'")
    _place(admin, drain, "CHECKPOINTED", ", wait_reason = 'DRAIN'")
    _place(admin, approval_wait, "CHECKPOINTED", ", wait_reason = 'AWAITING_APPROVAL'")
    _place(admin, validating, "VALIDATING")
    _place(admin, failed, "FAILED")
    due = {(d.org_id, d.task_id) for d in sysfn.due_retries(SCHED, 1000)}
    assert (tenant_a.org_id, TASK.from_uuid(retry)) in due
    assert (tenant_a.org_id, TASK.from_uuid(later)) not in due
    resumes = {(d.task_id, d.wait_reason) for d in sysfn.due_resumes(SCHED, 1000)}
    assert (TASK.from_uuid(drain), WaitReason.DRAIN) in resumes
    assert TASK.from_uuid(approval_wait) not in {t for t, _ in resumes}
    stuck = {(s.task_id, s.state) for s in sysfn.stuck_tasks(ActorRef("sys_reaper"), 1000)}
    assert (TASK.from_uuid(validating), TaskState.VALIDATING) in stuck
    assert (TASK.from_uuid(failed), TaskState.FAILED) in stuck
    with pytest.raises(InputInvalidError):
        sysfn.due_retries(SCHED, 0)
    with pytest.raises(InputInvalidError):
        sysfn.due_retries(ActorRef("nobody"), 1)


def test_breaker_open_half_open_close(sysfn: PgSystemFunctions) -> None:
    key = BreakerKey(f"p{uuid.uuid4().hex[:6]}", "llm.completion", "platform")
    reaper = ActorRef("agent_05")
    assert sysfn.breaker_record(reaper, key, True, None).state is CircuitState.CLOSED
    # PERMANENT codes never count (07 section 4.2)
    for _ in range(5):
        state = sysfn.breaker_record(reaper, key, False, "PERMANENT.INPUT_INVALID")
    assert state.state is CircuitState.CLOSED
    for _ in range(3):
        state = sysfn.breaker_record(reaper, key, False, "TEMPORARY.UPSTREAM_5XX")
    assert state.state is CircuitState.OPEN
    assert state.open_until is not None
    assert sysfn.breaker_record(reaper, key, True, None).state is CircuitState.OPEN
    time.sleep(0.1)
    state = sysfn.breaker_record(reaper, key, False, "TEMPORARY.TIMEOUT")  # probe fails: reopen
    assert state.state is CircuitState.OPEN
    time.sleep(0.2)
    assert sysfn.breaker_record(reaper, key, True, None).state is CircuitState.HALF_OPEN
    assert sysfn.breaker_record(reaper, key, True, None).state is CircuitState.CLOSED
    with pytest.raises(InputInvalidError):
        sysfn.breaker_record(reaper, key, True, "TEMPORARY.TIMEOUT")
    with pytest.raises(InputInvalidError):
        sysfn.breaker_record(reaper, key, False, None)


def test_breaker_failure_ratio(sysfn: PgSystemFunctions) -> None:
    key = BreakerKey(f"p{uuid.uuid4().hex[:6]}", "tts.synthesize", "platform")
    actor = ActorRef("agent_07")
    for ok in (True, False, True, False):
        assert (
            sysfn.breaker_record(actor, key, ok, None if ok else "TEMPORARY.NETWORK").state
            is CircuitState.CLOSED
        )
    assert sysfn.breaker_record(actor, key, False, "TEMPORARY.NETWORK").state is CircuitState.OPEN


def _write_breaker(tenancy: PgTenancy, tenant: Tenant) -> None:
    with tenancy.transaction(TenantContext(tenant.org_id, ORCH)) as tx:
        connection_of(tx).execute("UPDATE circuit_breakers SET state = 'CLOSED'")


def test_app_cannot_write_breakers_directly(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    with pytest.raises(PermissionDeniedError):
        _write_breaker(tenancy, tenant_a)


def test_make_tenant_helper_creates_distinct_orgs(admin: Conn) -> None:
    assert make_tenant(admin).org_id != make_tenant(admin).org_id
