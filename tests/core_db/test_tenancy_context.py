"""Tenant transactions (04 section 3.2): SET LOCAL context, fail-closed, typed errors."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest

from amw_core.errors import (
    CrossTenantRefError,
    DbTransientError,
    DbUnavailableError,
    InputInvalidError,
    InvalidTransitionError,
    MissingDependencyError,
    PermissionDeniedError,
    TenantInactiveError,
    TenantMismatchError,
)
from amw_core.ids import ORG, ActorRef, new_uuid7
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext
from amw_core.tenancy import (
    PgTenancy,
    blob_uri,
    cache_key,
    connection_of,
    org_uuid_of,
    require_uri_tenant,
    translate_db_error,
    uri_owner,
)
from amw_core.testing.memory import MemoryTransaction
from tests.pg_fixtures import Tenant, make_tenant

pytestmark = pytest.mark.integration
ORCH = ActorRef("agent_01")


def test_is_a_tenancy_context(tenancy: PgTenancy) -> None:
    assert isinstance(tenancy, TenancyContext)


def test_settings_are_transaction_local(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        conn = connection_of(tx)
        row = conn.execute(
            "SELECT amw_current_org(), current_setting('app.actor'), amw_current_user(),"
            " current_user"
        ).fetchone()
        assert row == (tenant_a.org_uuid, "agent_01", None, "amw_app")
        assert org_uuid_of(tx) == tenant_a.org_uuid
    with pytest.raises(TypeError, match="closed"):
        connection_of(tx)


def test_pooled_connection_carries_no_tenant(pg_dsn: str, tenant_a: Tenant) -> None:
    with psycopg.connect(pg_dsn) as shared:
        shared.execute("SET ROLE amw_app")
        shared.commit()

        @contextmanager
        def same() -> Iterator[psycopg.Connection[tuple[Any, ...]]]:
            yield shared

        pool = PgTenancy(same)
        with pool.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
            assert connection_of(tx).execute("SELECT count(*) FROM workspaces").fetchone() == (1,)
        assert shared.execute("SELECT amw_current_org()").fetchone() == (None,)
        assert shared.execute("SELECT count(*) FROM workspaces").fetchone() == (0,)
        shared.rollback()


def test_human_actor_sets_user(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    user = new_uuid7()
    actor = ActorRef(f"usr_{user}")
    with tenancy.transaction(TenantContext(tenant_a.org_id, actor)) as tx:
        row = connection_of(tx).execute("SELECT amw_current_user()").fetchone()
        assert row == (user,)


def _rename_then_fail(tenancy: PgTenancy, tenant: Tenant) -> None:
    with tenancy.transaction(TenantContext(tenant.org_id, ORCH)) as tx:
        connection_of(tx).execute(
            "UPDATE workspaces SET name = 'renamed' WHERE org_id = %s", (tenant.org_uuid,)
        )
        raise RuntimeError("boom")


def test_rollback_on_exception(tenancy: PgTenancy, tenant_a: Tenant, admin: Any) -> None:
    with pytest.raises(RuntimeError):
        _rename_then_fail(tenancy, tenant_a)
    row = admin.execute("SELECT name FROM workspaces WHERE id = %s", (tenant_a.workspace_uuid,))
    assert row.fetchone() == ("main",)


@pytest.mark.parametrize("status", ["SUSPENDED", "OFFBOARDING", "DELETED"])
def test_inactive_org_is_refused(tenancy: PgTenancy, admin: Any, status: str) -> None:
    tenant = make_tenant(admin, status=status)
    with (
        pytest.raises(TenantInactiveError),
        tenancy.transaction(TenantContext(tenant.org_id, ORCH)),
    ):
        pass


def test_unknown_org_is_refused(tenancy: PgTenancy) -> None:
    with pytest.raises(TenantInactiveError), tenancy.transaction(TenantContext(ORG.new(), ORCH)):
        pass


def test_bad_actor_is_refused(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    with (
        pytest.raises(TenantMismatchError),
        tenancy.transaction(TenantContext(tenant_a.org_id, ActorRef("nobody"))),
    ):
        pass


def test_require_same_tenant(tenancy: PgTenancy, tenant_a: Tenant, tenant_b: Tenant) -> None:
    with tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx:
        tenancy.require_same_tenant(tx, tenant_a.org_id)
        with pytest.raises(TenantMismatchError):
            tenancy.require_same_tenant(tx, tenant_b.org_id)


def test_connection_of_rejects_foreign_handles(tenant_a: Tenant) -> None:
    with pytest.raises(TypeError):
        connection_of(MemoryTransaction(TenantContext(tenant_a.org_id, ORCH)))


def test_db_errors_map_to_typed_errors(tenancy: PgTenancy, tenant_a: Tenant) -> None:
    with (
        pytest.raises(PermissionDeniedError),
        tenancy.transaction(TenantContext(tenant_a.org_id, ORCH)) as tx,
    ):
        connection_of(tx).execute("DELETE FROM jobs")  # no DELETE grant for amw_app


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("AMW01", InvalidTransitionError),
        ("AMW02", PermissionDeniedError),
        ("40001", DbTransientError),
    ],
)
def test_translate_sqlstates(admin: Any, state: str, expected: type[Exception]) -> None:
    with pytest.raises(psycopg.Error) as info:
        admin.execute(f"DO $$ BEGIN RAISE EXCEPTION 'probe' USING ERRCODE = '{state}'; END $$")
    assert isinstance(translate_db_error(info.value), expected)


def test_translate_unknown_reraises(admin: Any) -> None:
    with pytest.raises(psycopg.Error) as info:
        admin.execute("SELECT 1 / 0")
    with pytest.raises(psycopg.errors.DivisionByZero):
        translate_db_error(info.value)


def test_translate_operational() -> None:
    assert isinstance(translate_db_error(psycopg.OperationalError("down")), DbUnavailableError)


def test_cache_key(tenancy: PgTenancy) -> None:
    org = ORG.new()
    assert cache_key(org, "kb", "kch_1") == f"amw:{org}:kb:kch_1"
    assert tenancy.cache_key(org, "kb", "k") == f"amw:{org}:kb:k"
    with pytest.raises(InputInvalidError):
        cache_key(org, "a:b", "k")
    with pytest.raises(InputInvalidError):
        cache_key(org, "kb", "")
    with pytest.raises(InputInvalidError):
        cache_key("wsp_x", "kb", "k")  # type: ignore[arg-type]


def test_storage_refs(tenant_a: Tenant, tenant_b: Tenant) -> None:
    uri = blob_uri(tenant_a.org_id, "jobs/job_1", "renders/r.mp4")
    assert uri == f"amw-blob://{tenant_a.org_id}/jobs/job_1/renders/r.mp4"
    assert uri_owner(uri) == tenant_a.org_id
    assert uri_owner("amw-blob://platform/templates/x.json") == "platform"
    tx = MemoryTransaction(TenantContext(tenant_a.org_id, ORCH))
    require_uri_tenant(tx, uri)
    require_uri_tenant(tx, "amw-entity://platform/rule_packs/rpk_1", allow_platform=True)
    with pytest.raises(CrossTenantRefError):
        require_uri_tenant(tx, blob_uri(tenant_b.org_id, "jobs", "a.json"))
    with pytest.raises(CrossTenantRefError):
        require_uri_tenant(tx, "amw-blob://platform/templates/x.json")
    for bad in ("s3://x/y", "amw-blob://platform/../etc", "amw-blob://wsp_1/a/b"):
        with pytest.raises(InputInvalidError):
            uri_owner(bad)
    with pytest.raises(InputInvalidError):
        blob_uri(tenant_a.org_id, "jobs", "../escape")
