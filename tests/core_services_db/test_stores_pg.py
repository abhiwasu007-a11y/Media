"""PostgreSQL idempotency and checkpoint stores implement the Step 0 Protocols exactly like the
in-memory fakes (03 section 9.1; 04 sections 5.7, 5.9), plus concurrency and tenant isolation."""

import threading
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from amw_core.checkpoint_store import PgCheckpointStore
from amw_core.enums import IdempotencyStatus
from amw_core.errors import IdempotencyConflictError, InputInvalidError, InvalidTransitionError
from amw_core.idempotency_store import PgIdempotencyStore
from amw_core.ids import ActorRef, make_idempotency_key
from amw_core.interfaces.checkpoint_store import CheckpointStore, NewCheckpoint
from amw_core.interfaces.idempotency_store import BeginAction, IdempotencyStore
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_core.tenancy import PgTenancy
from amw_core.testing.memory import (
    MemoryCheckpointStore,
    MemoryIdempotencyStore,
    MemoryTransaction,
)
from tests.core_services.support import T0
from tests.core_services_db.conftest import Work, make_task
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
ORCH = ActorRef("agent_13")
H1, H2 = "11" * 32, "22" * 32


def test_protocols() -> None:
    assert isinstance(PgIdempotencyStore(), IdempotencyStore)
    assert isinstance(PgCheckpointStore(), CheckpointStore)


def _idem_script(store: Any, tx: TenantTransaction, key: str, task: str | None) -> list[object]:
    """One decision sequence covering every row of the 03 section 9.1 table."""
    out: list[object] = []
    d = store.begin(tx, key, "delivery.file", H1, task, T0, 1_000)
    out.append(d.action)
    out.append(store.begin(tx, key, "delivery.file", H1, task, T0, 1_000).action)  # IN_FLIGHT
    out.append(
        store.begin(tx, key, "delivery.file", H1, task, T0 + timedelta(seconds=2), 1_000).action
    )  # RECONCILE
    try:
        store.begin(tx, key, "delivery.file", H2, task, T0, 1_000)
    except IdempotencyConflictError:
        out.append("conflict-in-progress")
    out.append(store.fail(tx, key, T0).status)
    out.append(
        store.begin(tx, key, "delivery.file", H2, task, T0, 1_000).action
    )  # FAILED -> PROCEED
    rec = store.complete(tx, key, "amw-entity://x/publications/p", T0)
    out.append((rec.status, rec.result_ref, rec.request_sha256 == H2, rec.locked_until))
    out.append(store.begin(tx, key, "delivery.file", H2, task, T0, 1_000).action)  # RETURN_STORED
    try:
        store.begin(tx, key, "delivery.file", H1, task, T0, 1_000)
    except IdempotencyConflictError:
        out.append("conflict-completed")
    try:
        store.complete(tx, key, "x", T0)
    except InvalidTransitionError:
        out.append("invalid")
    try:
        store.fail(tx, key, T0)
    except InvalidTransitionError:
        out.append("invalid")
    out.append(store.get(tx, key).status)
    return out


def test_idempotency_decisions_equal_the_memory_fake(
    tenancy: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    key = make_idempotency_key(tenant_a.org_id, "delivery.file", [work_a.job_id, "p", H1])
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        pg = _idem_script(PgIdempotencyStore(), tx, key, work_a.task_id)
        assert PgIdempotencyStore().get(tx, key).task_id == work_a.task_id  # type: ignore[union-attr]
    mem_tx = MemoryTransaction(TenantContext(tenant_a.org_id, ORCH))
    mem = _idem_script(MemoryIdempotencyStore(), mem_tx, key, work_a.task_id)
    assert pg == mem
    assert pg[:3] == [BeginAction.PROCEED, BeginAction.IN_FLIGHT, BeginAction.RECONCILE]
    assert pg[-1] is IdempotencyStatus.COMPLETED


def test_idempotency_validation_and_expiry(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    store = PgIdempotencyStore(default_retention=timedelta(days=30))
    ctx = TenantContext(tenant_a.org_id, ORCH)
    key = make_idempotency_key(tenant_a.org_id, "llm.call", ["t", "s", 1])
    up = make_idempotency_key(tenant_a.org_id, "upload.youtube", ["chn", H1])
    with tenancy.transaction(ctx) as tx:
        assert store.begin(
            tx, key, "llm.call", H1, None, T0, 10
        ).record.expires_at == T0 + timedelta(days=30)
        assert store.begin(tx, up, "upload.youtube", H1, None, T0, 10).record.expires_at is None
        with pytest.raises(InputInvalidError):
            store.begin(tx, key, "nope.scope", H1, None, T0, 10)
        with pytest.raises(InputInvalidError):
            store.begin(tx, key, "llm.call", "zz" * 32, None, T0, 10)
        with pytest.raises(InputInvalidError):
            store.begin(tx, key, "llm.call", "ab", None, T0, 10)
        with pytest.raises(InputInvalidError):
            store.begin(tx, "idk_bad", "llm.call", H1, None, T0, 10)  # type: ignore[arg-type]
        assert store.get(tx, make_idempotency_key(tenant_a.org_id, "llm.call", ["none"])) is None


def test_racing_attempts_never_both_proceed(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    key = make_idempotency_key(tenant_a.org_id, "delivery.file", ["race"])
    actions: list[BeginAction] = []
    barrier = threading.Barrier(4)

    def attempt() -> None:
        with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
            barrier.wait()
            actions.append(
                PgIdempotencyStore().begin(tx, key, "delivery.file", H1, None, T0, 60_000).action
            )

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(actions) == sorted([BeginAction.PROCEED] + [BeginAction.IN_FLIGHT] * 3)


@pytest.mark.tenancy
def test_idempotency_rows_are_per_tenant(
    tenancy: PgTenancy, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    key = make_idempotency_key(tenant_a.org_id, "delivery.file", ["x"])
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        PgIdempotencyStore().begin(tx, key, "delivery.file", H1, None, T0, 10)
    with tenancy.transaction(TenantContext(tenant_b.org_id, ORCH)) as tx:
        assert PgIdempotencyStore().get(tx, key) is None
        # the same key string in B is a different row (PK is (org_id, key))
        d = PgIdempotencyStore().begin(tx, key, "delivery.file", H2, None, T0, 10)
        assert d.action is BeginAction.PROCEED


def _ckp(
    work: Work, step: str, effects: tuple[str, ...] = (), ratio: str | None = None
) -> NewCheckpoint:
    return NewCheckpoint(
        task_id=work.task_id,
        attempt_id=work.attempt_id,
        step_key=step,
        state_ref=f"amw-blob://org/jobs/j/checkpoints/{step}.json",
        state_sha256="ab" * 32,
        completed_effects=effects,  # type: ignore[arg-type]
        progress_ratio=Decimal(ratio) if ratio else None,
    )


def test_checkpoints_equal_the_memory_fake(
    admin: Any, tenancy: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    key = make_idempotency_key(tenant_a.org_id, "render.segment", ["j", "t", "p", 1])
    pg = PgCheckpointStore()
    mem = MemoryCheckpointStore()
    mem_tx = MemoryTransaction(TenantContext(tenant_a.org_id, ORCH))
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        for store, t in ((pg, tx), (mem, mem_tx)):
            store.write(t, _ckp(work_a, "seg-1", (key,), "0.250"), T0)
            store.write(t, _ckp(work_a, "seg-2", (key,), "0.500"), T0)
        latest = pg.latest(tx, work_a.task_id)
        assert latest is not None
        assert latest.seq == 2
        assert latest.is_latest
        assert latest.checkpoint == mem.latest(mem_tx, work_a.task_id).checkpoint  # type: ignore[union-attr]
        listed = pg.list_for_task(tx, work_a.task_id)
        assert [(c.seq, c.is_latest) for c in listed] == [(1, False), (2, True)]
        assert [(c.seq, c.is_latest) for c in mem.list_for_task(mem_tx, work_a.task_id)] == [
            (1, False),
            (2, True),
        ]
        assert pg.get(tx, listed[0].id) == listed[0]
        assert listed[1].checkpoint.completed_effects == (key,)
        with pytest.raises(InputInvalidError):
            pg.write(tx, _ckp(work_a, "bad", (), "1.5"), T0)
        with pytest.raises(InputInvalidError):
            pg.write(tx, _ckp(work_a, "bad", ("not-a-key",)), T0)
        bad_sha = NewCheckpoint(work_a.task_id, work_a.attempt_id, "s", "r", "ab", ())
        with pytest.raises(InputInvalidError):
            pg.write(tx, bad_sha, T0)
    other_task, _other_att = make_task(admin, tenant_a, work_a.job_id)
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        assert pg.latest(tx, other_task) is None


def test_concurrent_checkpoint_writers_keep_one_latest(
    tenancy: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    def writer(i: int) -> None:
        with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
            PgCheckpointStore().write(tx, _ckp(work_a, f"s{i}"), T0)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        rows = PgCheckpointStore().list_for_task(tx, work_a.task_id)
    assert [r.seq for r in rows] == [1, 2, 3, 4, 5]
    assert sum(r.is_latest for r in rows) == 1


@pytest.mark.tenancy
def test_checkpoints_are_per_tenant(
    tenancy: PgTenancy, tenant_a: Tenant, tenant_b: Tenant, work_a: Work
) -> None:
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        rec = PgCheckpointStore().write(tx, _ckp(work_a, "s"), T0)
    with tenancy.transaction(TenantContext(tenant_b.org_id, ORCH)) as tx:
        assert PgCheckpointStore().get(tx, rec.id) is None
        assert PgCheckpointStore().latest(tx, work_a.task_id) is None
