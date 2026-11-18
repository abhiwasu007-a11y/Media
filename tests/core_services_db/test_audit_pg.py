"""PostgreSQL audit log: chain per tenant under the head lock, verification, tamper detection,
INSERT-only for the app role, append-only for every role, tenant isolation."""

import threading
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from amw_core.audit.pg import PgAuditLog
from amw_core.enums import ActorKind
from amw_core.errors import PermissionDeniedError
from amw_core.ids import CORRELATION, ActorRef
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy import PgTenancy, connection_of
from tests.core_services.support import T0
from tests.core_services_db.conftest import Work, run_sql
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
ORCH = ActorRef("agent_01")


def _entry(work: Work, i: int = 0) -> NewAuditEntry:
    return NewAuditEntry(
        actor_kind=ActorKind.AGENT,
        actor_ref=ORCH,
        authority="orchestrator",
        action="task.completed",
        target_kind="TASK",
        target_id=work.task_id,
        occurred_at=T0 + timedelta(microseconds=7 + i),
        job_id=work.job_id,
        correlation_id=CORRELATION.new(),
        details={"from": "RUNNING", "to": "COMPLETED", "state_version": i},
    )


def test_is_an_audit_log() -> None:
    assert isinstance(PgAuditLog(), AuditLog)


def test_append_verify_and_export(
    tenancy: PgTenancy, readonly: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    log = PgAuditLog()
    ctx = TenantContext(tenant_a.org_id, ORCH)
    with tenancy.transaction(ctx) as tx:
        written = [log.append(tx, _entry(work_a, i)) for i in range(3)]
    with tenancy.transaction(ctx) as tx:
        written.append(log.append(tx, _entry(work_a, 3)))
    assert [w.seq for w in written] == [1, 2, 3, 4]
    with readonly.transaction(ctx) as tx:
        v = log.verify_chain(tx)
        assert v.ok
        assert v.entries_checked == 4
        exported = list(log.export(tx))
        assert [(e.seq, e.row_hash) for e in exported] == [(w.seq, w.row_hash) for w in written]
        assert exported[0].entry.target_id == work_a.task_id
        assert exported[0].entry.occurred_at == written[0].entry.occurred_at
        assert [e.seq for e in log.export(tx, since_seq=2, target_id=work_a.task_id)] == [3, 4]


@pytest.mark.security
def test_app_role_may_only_insert(tenancy: PgTenancy, tenant_a: Tenant, work_a: Work) -> None:
    log = PgAuditLog()
    ctx = TenantContext(tenant_a.org_id, ORCH)
    with tenancy.transaction(ctx) as tx:
        log.append(tx, _entry(work_a))
    for stmt in (
        "SELECT count(*) FROM audit_log",
        "UPDATE audit_log SET action = 'x.y'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ):
        with pytest.raises(PermissionDeniedError), tenancy.transaction(ctx) as tx:
            run_sql(tx, stmt)
    with pytest.raises(PermissionDeniedError), tenancy.transaction(ctx) as tx:
        log.verify_chain(tx)


@pytest.mark.security
def test_trigger_rejects_update_and_delete_for_every_role(
    admin: psycopg.Connection[tuple[Any, ...]], tenancy: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        PgAuditLog().append(tx, _entry(work_a))
    for stmt in ("UPDATE audit_log SET action = 'x.y'", "DELETE FROM audit_log"):
        with pytest.raises(psycopg.DatabaseError, match=r"rejected|advance"):
            admin.execute(stmt)
    with pytest.raises(psycopg.DatabaseError, match=r"rejected|advance"):
        admin.execute("UPDATE audit_chain_heads SET last_seq = 0")
    with pytest.raises(psycopg.DatabaseError, match=r"rejected|advance"):
        admin.execute("DELETE FROM audit_chain_heads")


@pytest.mark.security
def test_tampering_by_a_superuser_is_detected(
    admin: psycopg.Connection[tuple[Any, ...]],
    tenancy: PgTenancy,
    readonly: PgTenancy,
    tenant_a: Tenant,
    work_a: Work,
) -> None:
    log = PgAuditLog()
    ctx = TenantContext(tenant_a.org_id, ORCH)
    with tenancy.transaction(ctx) as tx:
        for i in range(3):
            log.append(tx, _entry(work_a, i))
    with admin.transaction():
        admin.execute("ALTER TABLE audit_log_default DISABLE TRIGGER USER")
        admin.execute(
            'UPDATE audit_log_default SET details = \'{"to": "CANCELLED"}\''
            " WHERE org_id = %s AND seq = 2",
            (tenant_a.org_uuid,),
        )
        admin.execute("ALTER TABLE audit_log_default ENABLE TRIGGER USER")
    with readonly.transaction(ctx) as tx:
        v = log.verify_chain(tx)
    assert not v.ok
    assert v.first_bad_seq == 2


def test_concurrent_writers_serialise_on_the_head(
    pg_dsn: str, tenancy: PgTenancy, readonly: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    log = PgAuditLog()
    ctx = TenantContext(tenant_a.org_id, ORCH)
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for i in range(10):
                with tenancy.transaction(ctx) as tx:
                    log.append(tx, _entry(work_a, i))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with readonly.transaction(ctx) as tx:
        assert [e.seq for e in log.export(tx)] == list(range(1, 41))
        assert log.verify_chain(tx).ok


@pytest.mark.tenancy
def test_tenant_b_sees_none_of_tenant_a_audit_rows(
    tenancy: PgTenancy, readonly: PgTenancy, tenant_a: Tenant, tenant_b: Tenant, work_a: Work
) -> None:
    log = PgAuditLog()
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        log.append(tx, _entry(work_a))
    with readonly.transaction(TenantContext(tenant_b.org_id, ORCH)) as tx:
        assert list(log.export(tx)) == []
        v = log.verify_chain(tx)
        assert v.ok
        assert v.entries_checked == 0
        assert connection_of(tx).execute("SELECT count(*) FROM audit_chain_heads").fetchone() == (
            0,
        )
    with (
        pytest.raises(PermissionDeniedError),
        tenancy.transaction(TenantContext(tenant_b.org_id, ORCH)) as tx,
    ):
        # tenant B cannot create a chain head for tenant A (RLS WITH CHECK)
        run_sql(
            tx,
            "INSERT INTO audit_chain_heads (org_id, last_seq, last_hash) VALUES (%s, 0, %s)",
            (tenant_a.org_uuid, bytes(32)),
        )


@pytest.mark.security
@pytest.mark.parametrize("table", ["audit_log", "audit_log_default"])
@pytest.mark.parametrize("role", ["amw_owner", "amw_migrator", "amw_app"])
def test_audit_partition_cannot_be_truncated(admin: Any, table: str, role: str) -> None:
    """PR #44 m3: statement triggers are not cloned to partitions; the default partition has its
    own, so a plain TRUNCATE is refused for the owner too. Not claimed: the owner can still
    DISABLE the trigger or DETACH + DROP the partition; a deliberate wipe is detected by the
    chain head, not prevented."""
    with admin.transaction(force_rollback=True):
        admin.execute(f"SET LOCAL ROLE {role}")
        with pytest.raises(psycopg.Error):
            admin.execute(f"TRUNCATE {table}")
