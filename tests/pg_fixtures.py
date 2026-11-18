"""PostgreSQL fixtures for the DB-backed suites (tenancy, state machine, job store, queue).

``AMW_TEST_DATABASE_URL`` names a superuser connection to a scratch cluster (CI: the PostgreSQL 18
service; locally: PostgreSQL 16). Each test session creates its own database, applies every
migration under ``migrations/`` and drops it at the end. Without the variable the suites are
skipped with a clear reason. Application code runs as ``amw_app`` (``SET ROLE``), never as the
superuser, so RLS is really enforced.
"""

import os
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
def scratch_database(*, migrated: bool) -> Iterator[str]:
    """Create a database (optionally migrated), yield its DSN, drop it afterwards."""
    base = admin_dsn()
    name = f"amw_t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = _with_dbname(base, name)
    try:
        if migrated:
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
