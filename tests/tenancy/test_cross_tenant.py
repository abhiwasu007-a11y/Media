"""Cross-tenant suite (04 section 3.7; 27 section 9 acceptance test 5): a blocking CI gate.

Tenant A and tenant B each get one row in every TENANT and SHARED-CATALOGUE table (``seed``).
Reads and writes run as ``amw_app`` (RLS enforced); the catalogue checks read ``pg_class``.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg import sql

from amw_core.enums import AttemptResult, JobState, TaskState, TransitionId
from amw_core.errors import (
    CrossTenantRefError,
    InvalidTransitionError,
    MissingDependencyError,
    WorkerLostError,
)
from amw_core.ids import ATTEMPT, JOB, QUEUE_ITEM, TASK, WORKER, ActorRef
from amw_core.interfaces.job_store import JobTransition, TaskTransition
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.job_store import PgJobStore
from amw_core.queue import PgTaskQueue
from amw_core.tenancy import PgTenancy, blob_uri, require_uri_tenant
from amw_core.testing.memory import MemoryTransaction
from tests.fake_audit import RecordingAuditLog
from tests.pg_fixtures import make_tenant
from tests.tenancy.seed import World, seed_tenant

pytestmark = pytest.mark.tenancy
Conn = psycopg.Connection[tuple[Any, ...]]

GLOBAL_ALLOW_LIST = frozenset(
    {
        # 04 section 4 GLOBAL allow-list (no org_id) and migration bookkeeping
        "users",
        "user_auth_refs",
        "user_sessions",
        "platform_controls",
        "production_types",
        "state_transition_rules",
        "workers",
        "plans",
        "evidence_mac_keys",
        "amw_schema_migrations",
    }
)
CATALOGUE = frozenset({"rule_packs", "licences", "gcp_projects", "circuit_breakers", "quota_usage"})
ORCH = ActorRef("agent_01")


@pytest.fixture(scope="module")
def worlds(pg_dsn: str) -> tuple[World, World]:
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        a, b = make_tenant(conn), make_tenant(conn)
        return seed_tenant(conn, a), seed_tenant(conn, b)


def _tables(admin: Conn) -> list[tuple[str, bool, bool, bool, int]]:
    """(name, has org_id, rls, force, policy count) of every table of the schema."""
    rows = admin.execute(
        "SELECT c.relname,"
        " EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'org_id'"
        "   AND NOT a.attisdropped),"
        " c.relrowsecurity, c.relforcerowsecurity,"
        " (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)"
        " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY 1"
    ).fetchall()
    return [(str(r[0]), bool(r[1]), bool(r[2]), bool(r[3]), int(r[4])) for r in rows]


def tenant_tables(admin: Conn) -> list[str]:
    return [t[0] for t in _tables(admin) if t[1] or t[0] == "organisations"]


def _org_col(table: str) -> sql.Identifier:
    return sql.Identifier("id" if table == "organisations" else "org_id")


@contextmanager
def as_app(conn: Conn, org: uuid.UUID | None, role: str = "amw_app") -> Iterator[Conn]:
    """One transaction as ``role`` (default ``amw_app``) with ``app.org_id`` = ``org`` (or unset);
    rolled back."""
    tx = conn.transaction(force_rollback=True)
    with tx:
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
        if org is not None:
            conn.execute("SELECT set_config('app.org_id', %s, true)", (str(org),))
        yield conn


@contextmanager
def savepoint(conn: Conn) -> Iterator[None]:
    with conn.transaction(force_rollback=True):
        yield


# --- 3.7.6 catalogue checks ------------------------------------------------------------------
def test_every_table_has_enable_and_force_rls(admin: Conn) -> None:
    missing = [
        name
        for name, _org, rls, force, _p in _tables(admin)
        if name not in GLOBAL_ALLOW_LIST and not (rls and force)
    ]
    assert missing == []


def test_every_rls_table_has_a_policy(admin: Conn) -> None:
    assert [n for n, _o, rls, _f, policies in _tables(admin) if rls and policies == 0] == []


def test_allow_listed_tables_carry_no_org_id(admin: Conn) -> None:
    assert [n for n, org, *_ in _tables(admin) if org and n in GLOBAL_ALLOW_LIST] == []


def test_a_table_without_policy_fails_the_check(admin: Conn) -> None:
    """The gate itself: a new table without RLS is reported."""
    with savepoint(admin):
        admin.execute("CREATE TABLE amw_probe_no_rls (id uuid, org_id uuid)")
        flagged = [
            n
            for n, _o, rls, force, _p in _tables(admin)
            if n not in GLOBAL_ALLOW_LIST and not (rls and force)
        ]
        assert flagged == ["amw_probe_no_rls"]


def test_every_tenant_table_is_seeded(admin: Conn, worlds: tuple[World, World]) -> None:
    a, b = worlds
    tables = set(tenant_tables(admin))
    assert tables - a.tables == set(), "add a seed module for the new tenant table"
    assert a.tables == b.tables


# --- 3.7.2 reads and writes as tenant A --------------------------------------------------------
SWEEP_ROLES = (
    "amw_app",
    "amw_publisher",
    "amw_readonly",
    "amw_auth",
    "amw_operator",
    "amw_verifier",
)
_PRIVILEGE = {"select": "SELECT", "insert": "INSERT", "update": "UPDATE", "delete": "DELETE"}


@pytest.mark.parametrize("role", SWEEP_ROLES)
@pytest.mark.parametrize("probe", ["select", "insert", "update", "delete"])
def test_tenant_a_never_touches_tenant_b(
    admin: Conn, worlds: tuple[World, World], probe: str, role: str
) -> None:
    """Every login role of the application. A table the role holds the privilege on must be
    *probed* (a policy answers with zero rows / a WITH CHECK refusal); a plain "permission
    denied" on such a table is a failure, so a privilege gap cannot mask a missing policy."""
    a, b = worlds
    problems: list[str] = []
    probed = 0
    for table in tenant_tables(admin):
        ident, col = sql.Identifier(table), _org_col(table)
        held = admin.execute(
            "SELECT has_table_privilege(%s, %s, %s)", (role, table, _PRIVILEGE[probe])
        ).fetchone()
        if held != (True,):
            continue  # no privilege: nothing to leak (pg_class level check is the catalogue test)
        probed += 1
        if probe == "insert":
            row = admin.execute(
                sql.SQL("SELECT to_jsonb(t) FROM {} t WHERE {} = %s LIMIT 1").format(ident, col),
                (a.tenant.org_uuid,),
            ).fetchone()
            assert row is not None, table
            doc = dict(row[0])
            doc[col.as_string(admin).strip('"')] = str(b.tenant.org_uuid)
            if "id" in doc and table != "organisations":
                doc["id"] = str(uuid.uuid4())
        with as_app(admin, a.tenant.org_uuid, role) as conn:
            try:
                with savepoint(conn):
                    if probe == "select":
                        cur = conn.execute(
                            sql.SQL("SELECT count(*) FROM {} WHERE {} <> %s").format(ident, col),
                            (a.tenant.org_uuid,),
                        )
                        found = cur.fetchone()
                        if found != (0,):
                            problems.append(f"{table}: sees {found} foreign rows")
                    elif probe == "insert":
                        conn.execute(
                            sql.SQL(
                                "INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{}, %s)"
                            ).format(ident, ident),
                            (psycopg.types.json.Jsonb(doc),),
                        )
                        problems.append(f"{table}: inserted a row for tenant B")
                    elif probe == "update":
                        cur = conn.execute(
                            sql.SQL("UPDATE {} SET {} = {} WHERE {} = %s").format(
                                ident, col, col, col
                            ),
                            (b.tenant.org_uuid,),
                        )
                        if cur.rowcount != 0:
                            problems.append(f"{table}: updated {cur.rowcount} B rows")
                    else:
                        cur = conn.execute(
                            sql.SQL("DELETE FROM {} WHERE {} = %s").format(ident, col),
                            (b.tenant.org_uuid,),
                        )
                        if cur.rowcount != 0:
                            problems.append(f"{table}: deleted {cur.rowcount} B rows")
            except psycopg.Error as exc:
                # refused: no privilege / RLS WITH CHECK (42501) or a guard trigger (AMW02)
                if exc.sqlstate == "42501" and "permission denied" in str(exc):
                    problems.append(f"{table}: privilege held but {exc}")
                elif exc.sqlstate not in ("42501", "AMW02"):
                    problems.append(f"{table}: unexpected {exc.sqlstate} {exc}")
    assert problems == []
    if probe == "select":
        assert probed > 0, f"{role} reads no tenant table: the sweep would be vacuous"


def test_tenant_a_sees_its_own_rows(admin: Conn, worlds: tuple[World, World]) -> None:
    a, _b = worlds
    empty = []
    for table in tenant_tables(admin):
        with as_app(admin, a.tenant.org_uuid) as conn:
            try:
                count = conn.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()
            except psycopg.errors.InsufficientPrivilege:
                continue  # e.g. partitions are reached through their parent only
            if count == (0,):
                empty.append(table)
    assert empty == []


# --- 3.7.3 no context = no rows -----------------------------------------------------------------
def test_unset_context_reads_nothing(admin: Conn, worlds: tuple[World, World]) -> None:
    seen = []
    for table in tenant_tables(admin):
        if table in CATALOGUE:
            continue
        with as_app(admin, None) as conn:
            try:
                count = conn.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()
            except psycopg.errors.InsufficientPrivilege:
                continue
            if count != (0,):
                seen.append(table)
    assert seen == []


def test_unset_context_sees_only_platform_catalogue_rows(
    admin: Conn, worlds: tuple[World, World]
) -> None:
    for table in sorted(CATALOGUE):
        with as_app(admin, None) as conn:
            count = conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE org_id IS NOT NULL").format(
                    sql.Identifier(table)
                )
            ).fetchone()
            assert count == (0,), table


# --- 3.7.4 tenant-composite foreign keys -------------------------------------------------------
def _composite_fks(admin: Conn) -> list[tuple[str, str, list[str], list[str]]]:
    rows = admin.execute(
        "SELECT con.conname, cl.relname, ref.relname,"
        " array(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(n, o)"
        "   JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.n ORDER BY k.o),"
        " array(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(n, o)"
        "   JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.n ORDER BY k.o)"
        " FROM pg_constraint con JOIN pg_class cl ON cl.oid = con.conrelid"
        " JOIN pg_class ref ON ref.oid = con.confrelid"
        " WHERE con.contype = 'f' AND con.conparentid = 0 AND array_length(con.conkey, 1) = 2"
        " AND 'org_id' = ANY (array(SELECT a.attname FROM unnest(con.conkey) k(n)"
        "   JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.n))"
    ).fetchall()
    return [(f"{r[1]}.{r[0]}", r[2], list(r[3]), list(r[4])) for r in rows]


def test_there_are_composite_foreign_keys(admin: Conn) -> None:
    assert len(_composite_fks(admin)) >= 60


def test_a_row_of_a_can_never_point_at_a_parent_of_b(
    admin: Conn, worlds: tuple[World, World]
) -> None:
    a, b = worlds
    problems = []
    for name, parent, cols, ref_cols in _composite_fks(admin):
        table = name.split(".", 1)[0]
        col = next(c for c in cols if c != "org_id")
        ref_col = ref_cols[cols.index(col)]
        target = admin.execute(
            sql.SQL("SELECT {} FROM {} WHERE org_id = %s LIMIT 1").format(
                sql.Identifier(ref_col), sql.Identifier(parent)
            ),
            (b.tenant.org_uuid,),
        ).fetchone()
        if target is None:
            problems.append(f"{name}: no B parent row in {parent}")
            continue
        with savepoint(admin):
            # user triggers (append-only, guards) off; the FK's own RI triggers stay on
            admin.execute(
                sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(sql.Identifier(table))
            )
            try:
                cur = admin.execute(
                    sql.SQL("UPDATE {} SET {} = %s WHERE org_id = %s").format(
                        sql.Identifier(table), sql.Identifier(col)
                    ),
                    (target[0], a.tenant.org_uuid),
                )
                problems.append(f"{name}: {cur.rowcount} A rows now point at B's {parent}")
            except psycopg.errors.ForeignKeyViolation:
                pass
            except psycopg.errors.CheckViolation as exc:
                # cost_ledger: an ESTIMATE row may not carry estimate_entry_id at all, so the
                # update is refused before the FK is reached; nothing was written
                if table != "cost_ledger":
                    problems.append(f"{name}: unexpected {exc.sqlstate} {exc}")
            except psycopg.Error as exc:
                problems.append(f"{name}: unexpected {exc.sqlstate} {exc}")
    assert problems == []


# --- 3.7.5 catalogue rows are read-only for tenants --------------------------------------------
@pytest.mark.parametrize("table", sorted(CATALOGUE))
def test_tenant_cannot_change_platform_rows(
    admin: Conn, worlds: tuple[World, World], table: str
) -> None:
    a, _b = worlds
    ident = sql.Identifier(table)
    for statement in (
        sql.SQL("UPDATE {} SET org_id = org_id WHERE org_id IS NULL").format(ident),
        sql.SQL("DELETE FROM {} WHERE org_id IS NULL").format(ident),
        sql.SQL("UPDATE {} SET org_id = %s WHERE org_id IS NULL").format(ident),
    ):
        with as_app(admin, a.tenant.org_uuid) as conn:
            params = (a.tenant.org_uuid,) if "%s" in statement.as_string(conn) else None
            try:
                changed = conn.execute(statement, params).rowcount
            except psycopg.Error as exc:
                changed = 0 if exc.sqlstate == "42501" else -1
            assert changed == 0
        with as_app(admin, a.tenant.org_uuid) as conn:
            visible = conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE org_id IS NULL").format(ident)
            ).fetchone()
            assert visible is not None
            assert visible[0] >= 1


# --- the app role cannot bypass RLS -------------------------------------------------------------
def test_app_role_attributes(admin: Conn) -> None:
    rows = admin.execute(
        "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN"
        " ('amw_app', 'amw_publisher', 'amw_readonly', 'amw_auth', 'amw_operator', 'amw_verifier',"
        " 'amw_owner', 'amw_migrator', 'amw_verifier_fn')"
    ).fetchall()
    assert len(rows) == 9
    assert all(not sup and not bypass for _n, sup, bypass in rows)
    sysfn = admin.execute(
        "SELECT rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = 'amw_sysfn'"
    ).fetchone()
    assert sysfn == (True, False)
    members = admin.execute(
        "SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member"
        " JOIN pg_roles g ON g.oid = m.roleid WHERE g.rolname IN ('amw_sysfn', 'amw_verifier_fn')"
    ).fetchall()
    assert {m for (m,) in members} <= {"amw_owner"}


def test_row_security_off_is_refused_for_the_app(admin: Conn, worlds: tuple[World, World]) -> None:
    with as_app(admin, worlds[0].tenant.org_uuid) as conn:
        conn.execute("SET LOCAL row_security = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT count(*) FROM jobs")


def test_app_cannot_change_rls_or_policies(admin: Conn, worlds: tuple[World, World]) -> None:
    for statement in (
        "ALTER TABLE jobs DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE jobs NO FORCE ROW LEVEL SECURITY",
        "DROP POLICY tenant_isolation ON jobs",
    ):
        with (
            as_app(admin, worlds[0].tenant.org_uuid) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(statement)


def test_owner_is_subject_to_rls(admin: Conn, worlds: tuple[World, World]) -> None:
    with admin.transaction(force_rollback=True):
        admin.execute("SET LOCAL ROLE amw_owner")
        assert admin.execute("SELECT count(*) FROM jobs").fetchone() == (0,)


# --- 3.7.7 system functions return identifiers only ---------------------------------------------
ALLOWED_OUTPUTS = {
    "queue_item_id",
    "org_id",
    "task_id",
    "envelope",
    "wait_reason",
    "state",
    "open_until",
}


def test_system_functions_return_no_content_columns(admin: Conn) -> None:
    rows = admin.execute(
        "SELECT p.proname, p.proargnames, p.proargmodes, pg_get_function_result(p.oid)"
        " FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner WHERE r.rolname = 'amw_sysfn'"
        " AND p.prosecdef"
    ).fetchall()
    names = {r[0] for r in rows}
    assert {
        "amw_queue_claim",
        "amw_queue_heartbeat",
        "amw_due_retries",
        "amw_due_resumes",
        "amw_expired_leases",
        "amw_stuck_tasks",
        "amw_breaker_record",
    } <= names
    for proname, argnames, modes, result in rows:
        outs = {n for n, m in zip(argnames or [], modes or [], strict=False) if m in ("o", "t")}
        assert outs <= ALLOWED_OUTPUTS, (proname, outs)
        if not outs:
            assert result in ("timestamp with time zone", "trigger", "boolean"), proname


# --- every public store method of tenant B finds nothing of tenant A ----------------------------
@pytest.fixture
def b_tx(pg_dsn: str, worlds: tuple[World, World]) -> Iterator[Any]:
    tenancy = PgTenancy(lambda: _app_conn(pg_dsn))
    with tenancy.transaction(TenantContext(worlds[1].tenant.org_id, ORCH)) as tx:
        yield tx


@contextmanager
def _app_conn(dsn: str) -> Iterator[Conn]:
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE amw_app")
        conn.commit()
        yield conn


def test_job_store_methods_see_nothing_of_a(worlds: tuple[World, World], b_tx: Any) -> None:
    a, _b = worlds
    store = PgJobStore(RecordingAuditLog(), max_tasks_per_job=10)
    job, task = JOB.from_uuid(a["job"]), TASK.from_uuid(a["task"])
    attempt = ATTEMPT.from_uuid(a["attempt"])
    assert store.get_job(b_tx, job) is None
    assert store.get_task(b_tx, task) is None
    assert store.list_tasks(b_tx, job) == []
    assert store.dependencies(b_tx, TASK.from_uuid(a["task1"])) == []
    assert store.dependants(b_tx, task) == []
    for call in (
        lambda: store.add_job_cost(b_tx, job, 1, 1),
        lambda: store.request_cancel(b_tx, task, "x"),
        lambda: store.start_attempt(b_tx, task, WORKER.new(), None, False),
        lambda: store.transition_job(
            b_tx,
            JobTransition(
                job,
                TransitionId.J02,
                JobState.PENDING,
                JobState.VALIDATING,
                1,
                ORCH,
                monetized_destination=True,
            ),
        ),
        lambda: store.transition_task(
            b_tx,
            TaskTransition(
                task, TransitionId.T02, TaskState.PENDING, TaskState.VALIDATING, 1, ORCH
            ),
        ),
        lambda: store.create_tasks(b_tx, job, []),
    ):
        with pytest.raises(MissingDependencyError):
            call()
    with pytest.raises(InvalidTransitionError):
        store.finish_attempt(b_tx, attempt, AttemptResult.SUCCEEDED, 1, None, None, None)
    with pytest.raises(InvalidTransitionError):
        store.heartbeat_attempt(b_tx, attempt)


def test_queue_methods_see_nothing_of_a(
    pg_dsn: str, admin: Conn, worlds: tuple[World, World], b_tx: Any
) -> None:
    a, _b = worlds
    queue = PgTaskQueue(lambda: _app_conn(pg_dsn))
    item = admin.execute(
        "SELECT id FROM task_queue WHERE org_id = %s LIMIT 1", (a.tenant.org_uuid,)
    ).fetchone()
    assert item is not None
    with pytest.raises(WorkerLostError):
        queue.mark_done(b_tx, QUEUE_ITEM.from_uuid(item[0]), WORKER.new())
    queue.cancel_for_task(b_tx, TASK.from_uuid(a["task"]))
    still = admin.execute("SELECT status FROM task_queue WHERE id = %s", (item[0],)).fetchone()
    assert still == ("DONE",)


def test_evidence_mac_check_is_tenant_bound(admin: Conn, worlds: tuple[World, World]) -> None:
    a, b = worlds
    with as_app(admin, b.tenant.org_uuid) as conn:
        assert conn.execute("SELECT amw_evidence_mac_valid(%s)", (a["evidence"],)).fetchone() == (
            False,
        )


# --- 3.7.8 storage and cache keys ---------------------------------------------------------------
def test_storage_refs_of_b_are_rejected_in_a(worlds: tuple[World, World]) -> None:
    a, b = worlds
    tx = MemoryTransaction(TenantContext(a.tenant.org_id, ORCH))
    require_uri_tenant(tx, blob_uri(a.tenant.org_id, "jobs", "x.json"))
    with pytest.raises(CrossTenantRefError):
        require_uri_tenant(tx, blob_uri(b.tenant.org_id, "jobs", "x.json"))
