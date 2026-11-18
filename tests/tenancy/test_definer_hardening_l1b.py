"""The L1a hardening (PR #40 review M1/M2) still holds across the full migration set, after the
lane L1b migrations (0050+). Runs against the database the suite migrated (every file)."""

import re
from pathlib import Path
from typing import Any

import psycopg
import pytest

from tests.tenancy.test_definer_hardening import LOGIN_ROLES, PRIVILEGED, rolled_back

pytestmark = pytest.mark.tenancy
Conn = psycopg.Connection[tuple[Any, ...]]
MIGRATIONS = sorted((Path(__file__).parents[2] / "migrations").glob("*.sql"))
HARDENED_OWNERS = ("amw_sysfn", "amw_verifier_fn")


def test_l1b_migrations_are_part_of_the_checked_set(admin: Conn) -> None:
    applied = {r[0] for r in admin.execute("SELECT version FROM amw_schema_migrations").fetchall()}
    assert 50 in applied
    assert 10 in applied
    assert applied == {int(p.name[:4]) for p in MIGRATIONS}


def test_no_migration_after_l1a_changes_function_owner_without_set_grant_and_revoke() -> None:
    """A migration that runs ALTER ... OWNER TO a hardened role must GRANT ... SET TRUE first and
    revoke it again (SET FALSE) after the last such statement, within the same file."""
    for path in MIGRATIONS:
        if int(path.name[:4]) <= 10:
            continue
        text = path.read_text(encoding="utf-8")
        for role in HARDENED_OWNERS:
            owner_stmts = [
                m.start() for m in re.finditer(rf"(?:OWNER TO|SET LOCAL ROLE) {role}\b", text)
            ]
            if not owner_stmts:
                continue
            grant = re.search(rf"GRANT {role} TO amw_owner[^;]*SET TRUE", text)
            revoke = list(re.finditer(rf"GRANT {role} TO amw_owner[^;]*SET FALSE", text))
            assert grant is not None, path.name
            assert grant.start() < owner_stmts[0], path.name
            assert revoke, path.name
            assert revoke[-1].start() > owner_stmts[-1], path.name


def test_the_breaker_admission_migration_regrants_and_revokes_set() -> None:
    text = (MIGRATIONS[-1].parent / "0051_breaker_admit.sql").read_text(encoding="utf-8")
    assert "GRANT amw_sysfn TO amw_owner WITH INHERIT FALSE, SET TRUE" in text
    assert "GRANT amw_sysfn TO amw_owner WITH INHERIT FALSE, SET FALSE" in text
    assert text.index("SET TRUE") < text.index("SET LOCAL ROLE amw_sysfn") < text.index("SET FALSE")


def test_l1b_migrations_add_no_security_definer_without_pg_temp_last() -> None:
    for path in MIGRATIONS:
        if int(path.name[:4]) < 50:
            continue
        text = path.read_text(encoding="utf-8")
        for fn in re.finditer(r"CREATE (?:OR REPLACE )?FUNCTION.*?\$\$;", text, re.S):
            body = fn.group(0)
            if "SECURITY DEFINER" in body:
                assert re.search(r"SET search_path\s*=[^$]*,\s*pg_temp\s", body), path.name


def test_membership_and_temp_state_after_all_migrations(admin: Conn) -> None:
    for login in LOGIN_ROLES:
        for target in HARDENED_OWNERS:
            row = admin.execute("SELECT pg_has_role(%s, %s, 'SET')", (login, target)).fetchone()
            assert row == (False,), (login, target)
    rows = admin.execute(
        "SELECT g.rolname, am.set_option, am.inherit_option FROM pg_auth_members am"
        " JOIN pg_roles g ON g.oid = am.roleid JOIN pg_roles m ON m.oid = am.member"
        " WHERE m.rolname = 'amw_owner' AND g.rolname = ANY(%s)",
        (list(HARDENED_OWNERS),),
    ).fetchall()
    assert rows
    assert all(not s and not i for _, s, i in rows)
    temp = admin.execute(
        "SELECT r.rolname FROM pg_roles r WHERE r.rolname = ANY(%s)"
        " AND has_database_privilege(r.rolname, current_database(), 'TEMPORARY')",
        (list(LOGIN_ROLES + PRIVILEGED),),
    ).fetchall()
    assert temp == []


@pytest.mark.parametrize("role", ["amw_app", "amw_publisher", "amw_readonly"])
def test_l1b_tables_cannot_be_shadowed_by_a_temp_table(admin: Conn, role: str) -> None:
    for table in ("audit_log", "cost_ledger", "budgets", "circuit_breakers"):
        with rolled_back(admin):
            admin.execute(psycopg.sql.SQL("SET LOCAL ROLE {}").format(psycopg.sql.Identifier(role)))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                admin.execute(
                    psycopg.sql.SQL("CREATE TEMP TABLE {} (a int)").format(
                        psycopg.sql.Identifier(table)
                    )
                )


def test_breaker_function_pins_pg_temp_and_is_owned_by_sysfn(admin: Conn) -> None:
    row = admin.execute(
        "SELECT pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig FROM pg_proc p"
        " WHERE p.proname = 'amw_breaker_record'"
    ).fetchall()
    assert len(row) == 1, "exactly one amw_breaker_record (L1b must not redefine L1a's)"
    owner, definer, config = row[0]
    assert owner == "amw_sysfn"
    assert definer
    assert any(c.replace(" ", "").endswith(",pg_temp") for c in config)
