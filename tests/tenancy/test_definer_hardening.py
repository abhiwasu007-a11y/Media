"""SECURITY DEFINER hygiene and role-membership hardening (PR #40 review M1, M2)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest

from tests.pg_fixtures import make_tenant
from tests.tenancy.seed import World, seed_tenant

pytestmark = pytest.mark.tenancy
Conn = psycopg.Connection[tuple[Any, ...]]
LOGIN_ROLES = (
    "amw_app",
    "amw_publisher",
    "amw_readonly",
    "amw_auth",
    "amw_operator",
    "amw_verifier",
    "amw_migrator",
)
PRIVILEGED = ("amw_verifier_fn", "amw_sysfn", "amw_owner")


@contextmanager
def rolled_back(conn: Conn) -> Iterator[None]:
    with conn.transaction(force_rollback=True):
        yield


def test_every_definer_function_pins_pg_temp_last(admin: Conn) -> None:
    rows = admin.execute(
        "SELECT p.proname, p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
        " WHERE n.nspname = 'public' AND p.prosecdef"
    ).fetchall()
    assert rows, "the catalogue check would be vacuous"
    bad = []
    for name, config in rows:
        paths = [c for c in (config or []) if c.startswith("search_path=")]
        if len(paths) != 1 or not paths[0].replace(" ", "").endswith(",pg_temp"):
            bad.append((name, config))
    assert bad == []


def test_no_role_may_create_temporary_tables(admin: Conn) -> None:
    allowed = admin.execute(
        "SELECT r.rolname FROM pg_roles r WHERE r.rolname = ANY(%s)"
        " AND has_database_privilege(r.rolname, current_database(), 'TEMPORARY')",
        (list(LOGIN_ROLES + PRIVILEGED),),
    ).fetchall()
    assert allowed == []
    with rolled_back(admin):
        admin.execute("SET LOCAL ROLE amw_auth")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            admin.execute("CREATE TEMP TABLE x (a int)")


def test_temp_memberships_cannot_shadow_the_session_org_guard(admin: Conn) -> None:
    """Regression for M1: a temp table named like a tenant table must not feed a definer function.
    The shadow is made by the superuser (no role can create one any more); with ``pg_temp`` first
    on the path the guard would read the fake ACTIVE membership and accept a foreign org."""
    a, b = make_tenant(admin), make_tenant(admin)
    world: World = seed_tenant(admin, a)
    seed_tenant(admin, b)
    with rolled_back(admin):
        admin.execute(
            "CREATE TEMP TABLE memberships (org_id uuid, user_id uuid, status text) ON COMMIT DROP"
        )
        admin.execute("GRANT SELECT ON pg_temp.memberships TO amw_sysfn")
        admin.execute(
            "INSERT INTO pg_temp.memberships VALUES (%s, %s, 'ACTIVE')",
            (b.org_uuid, world["user"]),
        )
        admin.execute("SET LOCAL ROLE amw_auth")
        admin.execute("SELECT set_config('app.user_id', %s, true)", (str(world["user"]),))
        with pytest.raises(psycopg.Error) as err:
            admin.execute(
                "INSERT INTO user_sessions (id, user_id, active_org_id, expires_at)"
                " VALUES (%s, %s, %s, now() + interval '1 hour')",
                (uuid.uuid4(), world["user"], b.org_uuid),
            )
        assert err.value.sqlstate == "AMW02"


def _can_set_role(admin: Conn, login: str, target: str) -> bool:
    """``SET ROLE`` is checked against the *session* user, so the catalogue answers it (incl.
    transitive membership), not a ``SET ROLE`` from the superuser's own session."""
    row = admin.execute("SELECT pg_has_role(%s, %s, 'SET')", (login, target)).fetchone()
    assert row is not None
    return bool(row[0])


@pytest.mark.parametrize("target", ["amw_verifier_fn", "amw_sysfn"])
@pytest.mark.parametrize("login", LOGIN_ROLES)
def test_no_login_role_can_become_a_privileged_function_owner(
    admin: Conn, login: str, target: str
) -> None:
    assert _can_set_role(admin, login, target) is False


def test_migrator_cannot_read_the_mac_keys(admin: Conn) -> None:
    assert admin.execute(
        "SELECT has_table_privilege('amw_migrator', 'evidence_mac_keys', 'SELECT')"
    ).fetchone() == (False,)
    assert _can_set_role(admin, "amw_migrator", "amw_owner") is True  # migrations still run


def test_owner_membership_catalogue(admin: Conn) -> None:
    rows = admin.execute(
        "SELECT g.rolname, m.rolname, am.set_option, am.inherit_option FROM pg_auth_members am"
        " JOIN pg_roles g ON g.oid = am.roleid JOIN pg_roles m ON m.oid = am.member"
        " WHERE g.rolname = ANY(%s)",
        (["amw_verifier_fn", "amw_sysfn"],),
    ).fetchall()
    assert rows, "the catalogue check would be vacuous"
    assert [r for r in rows if r[2] or r[3]] == []
