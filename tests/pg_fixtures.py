"""PostgreSQL fixtures for the DB-backed suites (tenancy, state machine, job store, queue).

``AMW_TEST_DATABASE_URL`` names a superuser connection to a scratch cluster (CI: the PostgreSQL 18
service; locally: PostgreSQL 16). Each test session creates its own database, applies every
migration under ``migrations/`` and drops it at the end. Without the variable the suites are
skipped with a clear reason. Application code runs as ``amw_app`` (``SET ROLE``), never as the
superuser, so RLS is really enforced.
"""

import fcntl
import os
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import conninfo as pg_conninfo
from psycopg import sql

from amw_core.enums import OrgKind
from amw_core.ids import ORG, WORKSPACE, OrgId, WorkspaceId, new_uuid7
from amw_core.tenancy import PgTenancy, dsn_connection_factory
from amw_core.tenancy.migrate import migrate

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
ENV = "AMW_TEST_DATABASE_URL"
SKIP_REASON = f"{ENV} is not set: PostgreSQL suites need a scratch database (CI sets it)"


def admin_dsn() -> str:
    dsn = os.environ.get(ENV)
    if not dsn:
        pytest.skip(SKIP_REASON)
    return dsn


def _with_dbname(dsn: str, dbname: str) -> str:
    params = pg_conninfo.conninfo_to_dict(dsn)
    params["dbname"] = dbname
    return pg_conninfo.make_conninfo(**{k: str(v) for k, v in params.items() if v is not None})


@contextmanager
def _one_migration_at_a_time() -> Iterator[None]:
    """Serialise migrations of concurrent test processes on one cluster. The migrations create and
    re-grant cluster-global roles (0001, 0010, 0051), and two sessions doing that at once fail with
    "tuple concurrently updated" or "must be able to SET ROLE" (observed with three parallel pytest
    runs; the databases are separate, the roles are not). A host-wide file lock removes that race
    for local runs; CI has one session per cluster."""
    path = Path(tempfile.gettempdir()) / "amw_test_migrate.lock"
    with path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def scratch_database(*, migrated: bool) -> Iterator[str]:
    """Create a database (optionally migrated), yield its DSN, drop it afterwards."""
    base = admin_dsn()
    name = f"amw_t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = _with_dbname(base, name)
    try:
        if migrated:
            with _one_migration_at_a_time():
                migrate(dsn, MIGRATIONS)
        yield dsn
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    """DSN of a fresh, fully migrated database shared by this test session."""
    with scratch_database(migrated=True) as dsn:
        yield dsn


@pytest.fixture
def empty_dsn() -> Iterator[str]:
    """DSN of an empty database for this test only (migration runner tests)."""
    with scratch_database(migrated=False) as dsn:
        yield dsn


@pytest.fixture
def admin(pg_dsn: str) -> Iterator[psycopg.Connection[tuple[Any, ...]]]:
    """Superuser connection (fixtures and catalogue checks only; bypasses RLS)."""
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        yield conn


@pytest.fixture
def tenancy(pg_dsn: str) -> PgTenancy:
    """Tenant transactions as ``amw_app`` (RLS enforced)."""
    return PgTenancy(dsn_connection_factory(pg_dsn, role="amw_app"))


@dataclass(frozen=True, slots=True)
class Tenant:
    org_id: OrgId
    org_uuid: uuid.UUID
    workspace_id: WorkspaceId
    workspace_uuid: uuid.UUID


def make_tenant(
    conn: psycopg.Connection[tuple[Any, ...]],
    *,
    platform_owner: bool = False,
    status: str = "ACTIVE",
) -> Tenant:
    """Insert an organisation and one workspace as the superuser (creation is a platform-owner
    function in production, 04 section 5.1)."""
    org = new_uuid7()
    wsp = new_uuid7()
    conn.execute(
        "INSERT INTO organisations (id, name, slug, kind, status, is_platform_owner)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (
            org,
            f"Org {org.hex[-6:]}",
            f"org-{org.hex[-12:]}",
            OrgKind.PLATFORM_OWNER if platform_owner else OrgKind.CLIENT,
            status,
            platform_owner,
        ),
    )
    conn.execute(
        "INSERT INTO workspaces (id, org_id, name, status) VALUES (%s, %s, 'main', 'ACTIVE')",
        (wsp, org),
    )
    return Tenant(ORG.from_uuid(org), org, WORKSPACE.from_uuid(wsp), wsp)


@pytest.fixture
def tenant_a(admin: psycopg.Connection[tuple[Any, ...]]) -> Tenant:
    return make_tenant(admin)


@pytest.fixture
def tenant_b(admin: psycopg.Connection[tuple[Any, ...]]) -> Tenant:
    return make_tenant(admin)


PRODUCTION_TYPE = ("CHANNEL_LONG_FORM", 1)


def ensure_production_type(conn: psycopg.Connection[tuple[Any, ...]]) -> None:
    """A registry row for job foreign keys (the real records are loaded by ticket 3A-03)."""
    conn.execute(
        "INSERT INTO production_types (id, key, version, status, tier, record, record_sha256)"
        " VALUES (%s, %s, %s, 'PLANNED', 'TIER_0', '{}'::jsonb, %s) ON CONFLICT DO NOTHING",
        (new_uuid7(), *PRODUCTION_TYPE, b"\0" * 32),
    )


def insert_job(conn: psycopg.Connection[tuple[Any, ...]], tenant: Tenant) -> uuid.UUID:
    """A PENDING job row inserted as the superuser (fixtures only)."""
    ensure_production_type(conn)
    job = new_uuid7()
    conn.execute(
        "INSERT INTO jobs (id, org_id, workspace_id, production_type_key, production_type_version,"
        " language, priority, correlation_id, idempotency_key, requested_by, currency)"
        " VALUES (%s, %s, %s, %s, %s, 'en', 2, %s, %s, 'agent_01', 'INR')",
        (
            job,
            tenant.org_uuid,
            tenant.workspace_uuid,
            *PRODUCTION_TYPE,
            new_uuid7(),
            "idk_" + job.hex.ljust(64, "0"),
        ),
    )
    return job


def insert_user(
    conn: psycopg.Connection[tuple[Any, ...]], tenant: Tenant, role: str = "REVIEWER_APPROVER"
) -> uuid.UUID:
    user = new_uuid7()
    conn.execute(
        "INSERT INTO users (id, email, display_name, status) VALUES (%s, %s, 'U', 'ACTIVE')",
        (user, f"{user.hex}@example.invalid"),
    )
    conn.execute(
        "INSERT INTO memberships (id, org_id, user_id, role, status)"
        " VALUES (%s, %s, %s, %s, 'ACTIVE')",
        (new_uuid7(), tenant.org_uuid, user, role),
    )
    return user


def insert_task(
    conn: psycopg.Connection[tuple[Any, ...]],
    tenant: Tenant,
    job: uuid.UUID,
    task_type: str = "agent_05.script_draft",
) -> uuid.UUID:
    """A PENDING task row inserted as the superuser (fixtures only)."""
    task = new_uuid7()
    conn.execute(
        "INSERT INTO tasks (id, org_id, job_id, task_type, agent_id, priority, resource_class,"
        " required_capabilities, idempotency_key, payload_schema, payload_schema_version,"
        " resource_budget, max_attempts)"
        " VALUES (%s, %s, %s, %s, %s, 2, 'AI_IO', ARRAY['llm'], %s, %s, '1.0.0', '{}'::jsonb, 3)",
        (
            task,
            tenant.org_uuid,
            job,
            task_type,
            task_type.split(".", 1)[0],
            "idk_" + task.hex.ljust(64, "0"),
            f"{task_type}.input",
        ),
    )
    return task


TEST_PROBE_LEASE_BOUND_MS = 600_000
"""Test fixture value only (the longest probe lease the suites request), never a deployment
value: the real bounds are REQUIRES REVIEW (Phase 1) (07 section 4.2; migration 0055)."""


def allow_probe_lease(
    dsn: str, provider: str, operation_class: str, max_ms: int = TEST_PROBE_LEASE_BOUND_MS
) -> None:
    """Set the server-side probe lease bound of one breaker key (``platform_controls`` key
    ``breaker_probe_timeout_max_ms``, migration 0055) as the superuser, standing in for the
    ``PLATFORM_OWNER`` write path (04 section 5.1)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO platform_controls (id, key, value, updated_by)"
            " VALUES (%s, 'breaker_probe_timeout_max_ms', jsonb_build_object(%s::text, %s::bigint),"
            " 'sys_test')"
            " ON CONFLICT (key) DO UPDATE SET value = platform_controls.value || EXCLUDED.value",
            (new_uuid7(), f"{provider}.{operation_class}", max_ms),
        )
