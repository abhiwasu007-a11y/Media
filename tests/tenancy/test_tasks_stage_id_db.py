"""``tasks.stage_id`` (04 section 5.3; CCR-214 (a), CCR-211; migration 0058): format CHECK, the
partial unique key ``(org_id, job_id, stage_id, iteration) WHERE stage_id IS NOT NULL AND state <>
'CANCELLED'``, NULL stage allowed repeatedly, RLS / tenant-FK isolation of dependency re-pointing
at SQL level, and zero rows without a tenant context. The ``job_store`` methods of ticket
PASS6-A2 are tested in tests/core_db/test_job_store.py."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from amw_core.ids import new_uuid7
from tests.pg_fixtures import make_tenant
from tests.tenancy.seed import World, seed_tenant

pytestmark = pytest.mark.tenancy
Conn = psycopg.Connection[tuple[Any, ...]]


@pytest.fixture(scope="module")
def worlds(pg_dsn: str) -> tuple[World, World]:
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        return seed_tenant(conn, make_tenant(conn)), seed_tenant(conn, make_tenant(conn))


@contextmanager
def as_app(conn: Conn, w: World) -> Iterator[Conn]:
    with conn.transaction():
        conn.execute("SET LOCAL ROLE amw_app")
        conn.execute("SELECT set_config('app.org_id', %s, true)", (str(w.tenant.org_uuid),))
        yield conn


def add_task(
    conn: Conn, w: World, stage_id: str | None, iteration: int = 0, **kw: Any
) -> uuid.UUID:
    task = new_uuid7()
    conn.execute(
        "INSERT INTO tasks (id, org_id, job_id, task_type, agent_id, iteration, priority,"
        " resource_class, required_capabilities, idempotency_key, payload_schema,"
        " payload_schema_version, resource_budget, max_attempts, stage_id)"
        " VALUES (%s, %s, %s, 'agent_06.verify', 'agent_06', %s, 2, 'AI_IO', ARRAY['llm'], %s,"
        " 'agent_06.verify.input', '1.0.0', %s, 3, %s)",
        (
            task,
            w.tenant.org_uuid,
            kw.get("job", w["job"]),
            iteration,
            "idk_" + task.hex.ljust(64, "0"),
            Jsonb({"max_cost_micros": 1, "currency": "INR", "max_wall_ms": 1}),
            stage_id,
        ),
    )
    return task


def cancel(conn: Conn, task: uuid.UUID) -> None:
    conn.execute("UPDATE tasks SET state = 'CANCELLED' WHERE id = %s", (task,))


def test_stage_id_is_a_nullable_text_column(admin: Conn) -> None:
    row = admin.execute(
        "SELECT data_type, is_nullable FROM information_schema.columns"
        " WHERE table_name = 'tasks' AND column_name = 'stage_id'"
    ).fetchone()
    assert row == ("text", "YES")


def test_valid_stage_ids_are_accepted(admin: Conn, worlds: tuple[World, World]) -> None:
    a, _ = worlds
    with as_app(admin, a) as c:
        for n, stage in enumerate(["ab", "s06_verify", "s06_chart", "x" * 32, "a1_" + "b" * 29]):
            add_task(c, a, stage, iteration=100 + n)


@pytest.mark.parametrize(
    "stage", ["", "a", "x" * 33, "S06_verify", "s06-verify", "s06 verify", "s06.verify", "é1"]
)
def test_bad_stage_id_pattern_is_refused(
    admin: Conn, worlds: tuple[World, World], stage: str
) -> None:
    a, _ = worlds
    with pytest.raises(psycopg.errors.CheckViolation), as_app(admin, a) as c:
        add_task(c, a, stage)


def test_duplicate_live_stage_iteration_is_refused(
    admin: Conn, worlds: tuple[World, World]
) -> None:
    a, _ = worlds
    with as_app(admin, a) as c:
        add_task(c, a, "dup_stage", 0)
    with pytest.raises(psycopg.errors.UniqueViolation), as_app(admin, a) as c:
        add_task(c, a, "dup_stage", 0)


def test_other_iteration_or_stage_is_allowed(admin: Conn, worlds: tuple[World, World]) -> None:
    a, _ = worlds
    with as_app(admin, a) as c:
        add_task(c, a, "iter_stage", 0)
        add_task(c, a, "iter_stage", 1)
        add_task(c, a, "other_stage", 0)


def test_replacement_allowed_once_the_first_is_cancelled(
    admin: Conn, worlds: tuple[World, World]
) -> None:
    a, _ = worlds
    with as_app(admin, a) as c:
        first = add_task(c, a, "repl_stage", 0)
        cancel(c, first)
        add_task(c, a, "repl_stage", 0)
    # the replacement is live: a third at the same iteration is refused again
    with pytest.raises(psycopg.errors.UniqueViolation), as_app(admin, a) as c:
        add_task(c, a, "repl_stage", 0)


@pytest.mark.parametrize("state", ["FAILED", "DEAD_LETTER", "COMPLETED"])
def test_only_cancelled_frees_the_key(admin: Conn, worlds: tuple[World, World], state: str) -> None:
    a, _ = worlds
    stage = f"keep_{state.lower()}"[:32]
    with as_app(admin, a) as c:
        t = add_task(c, a, stage, 0)
    with admin.transaction():  # superuser, transition trigger skipped: sets the state directly
        admin.execute("SET LOCAL session_replication_role = replica")
        admin.execute("UPDATE tasks SET state = %s WHERE id = %s", (state, t))
    with pytest.raises(psycopg.errors.UniqueViolation), as_app(admin, a) as c:
        add_task(c, a, stage, 0)


def test_null_stage_is_allowed_twice(admin: Conn, worlds: tuple[World, World]) -> None:
    a, _ = worlds
    with as_app(admin, a) as c:
        add_task(c, a, None, 0)
        add_task(c, a, None, 0)


def test_same_stage_in_another_org_does_not_collide(
    admin: Conn, worlds: tuple[World, World]
) -> None:
    a, b = worlds
    with as_app(admin, a) as c:
        add_task(c, a, "shared_stage", 0)
    with as_app(admin, b) as c:
        add_task(c, b, "shared_stage", 0)


def test_cross_tenant_dependency_repoint_is_refused(
    admin: Conn, worlds: tuple[World, World]
) -> None:
    """Re-pointing a dependency (the SQL under ``repoint_dependency``) at another tenant's task is
    refused by the tenant foreign key; the foreign row is not even visible through RLS."""
    a, b = worlds
    with as_app(admin, a) as c:
        old = add_task(c, a, "dep_old", 0)
        new_same = add_task(c, a, "dep_new", 0)
        down = add_task(c, a, "dep_down", 0)
        c.execute(
            "INSERT INTO task_dependencies (org_id, task_id, depends_on_task_id)"
            " VALUES (%s, %s, %s)",
            (a.tenant.org_uuid, down, old),
        )
        # same org: allowed
        cur = c.execute(
            "UPDATE task_dependencies SET depends_on_task_id = %s"
            " WHERE org_id = %s AND task_id = %s AND depends_on_task_id = %s",
            (new_same, a.tenant.org_uuid, down, old),
        )
        assert cur.rowcount == 1
    with pytest.raises(psycopg.errors.ForeignKeyViolation), as_app(admin, a) as c:
        c.execute(
            "UPDATE task_dependencies SET depends_on_task_id = %s"
            " WHERE org_id = %s AND task_id = %s",
            (b["task"], a.tenant.org_uuid, down),
        )
    # tenant B cannot touch A's dependency row at all
    with as_app(admin, b) as c:
        cur = c.execute(
            "UPDATE task_dependencies SET depends_on_task_id = %s WHERE task_id = %s",
            (b["task"], down),
        )
        assert cur.rowcount == 0


def test_stage_id_is_invisible_across_tenants_and_without_context(
    admin: Conn, worlds: tuple[World, World]
) -> None:
    a, b = worlds
    with as_app(admin, a) as c:
        add_task(c, a, "vis_stage", 0)
    with as_app(admin, b) as c:
        assert c.execute("SELECT count(*) FROM tasks WHERE stage_id = 'vis_stage'").fetchone() == (
            0,
        )
    with admin.transaction():
        admin.execute("SET LOCAL ROLE amw_app")
        admin.execute("SELECT set_config('app.org_id', '', true)")
        assert admin.execute("SELECT count(*) FROM tasks").fetchone() == (0,)


def test_tasks_keep_rls_enable_and_force(admin: Conn) -> None:
    row = admin.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'tasks'"
    ).fetchone()
    assert row == (True, True)
