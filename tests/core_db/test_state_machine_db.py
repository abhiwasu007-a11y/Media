"""state_transition_rules seed and the transition trigger (03 section 11.1 defence in depth)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from amw_core.enums import EntityKind, JobState, TaskState
from amw_core.state_machine import ALL_RULES, JOB_RULES, TASK_RULES, Rule, is_allowed_pair
from tests.pg_fixtures import Tenant, insert_job, insert_task

pytestmark = [pytest.mark.state_machine, pytest.mark.integration]
Conn = psycopg.Connection[tuple[Any, ...]]


def test_seed_equals_code(admin: Conn) -> None:
    rows = admin.execute(
        "SELECT entity_kind, transition_id, from_state, to_state, allowed_actor_kinds"
        " FROM state_transition_rules"
    ).fetchall()
    seed = {(e, t, f, to, frozenset(a)) for e, t, f, to, a in rows}
    code = {
        (
            r.entity_kind.value,
            r.transition_id.value,
            r.from_state,
            r.to_state,
            frozenset(k.value for k in r.actor_kinds),
        )
        for r in ALL_RULES
    }
    assert seed == code
    assert len(rows) == len(ALL_RULES)


def test_seed_is_immutable(admin: Conn) -> None:
    with pytest.raises(psycopg.DatabaseError):
        admin.execute("DELETE FROM state_transition_rules")


def _place(admin: Conn, table: str, row: uuid.UUID, state: str) -> None:
    """Put a row into ``state`` bypassing the trigger (fixture set-up only)."""
    extra = ""
    if table == "tasks":
        extra = (
            ", wait_reason = CASE WHEN %(s)s = 'CHECKPOINTED' THEN 'DRAIN' END"
            ", next_attempt_at = CASE WHEN %(s)s = 'RETRY_WAIT' THEN now() END"
        )
    else:
        extra = ", outcome = CASE WHEN %(s)s = 'COMPLETED' THEN 'DELIVERED' END"
    with admin.transaction():
        admin.execute("SET LOCAL session_replication_role = replica")
        admin.execute(
            f"UPDATE {table} SET state = %(s)s{extra} WHERE id = %(id)s",  # noqa: S608
            {"s": state, "id": row},
        )


def _move(admin: Conn, table: str, row: uuid.UUID, to: str) -> None:
    if table == "tasks":
        admin.execute(
            "UPDATE tasks SET state = %(s)s,"
            " wait_reason = CASE WHEN %(s)s = 'CHECKPOINTED' THEN 'DRAIN' END,"
            " next_attempt_at = CASE WHEN %(s)s = 'RETRY_WAIT' THEN now() END"
            " WHERE id = %(id)s",
            {"s": to, "id": row},
        )
    else:
        admin.execute(
            "UPDATE jobs SET state = %(s)s,"
            " outcome = CASE WHEN %(s)s = 'COMPLETED' THEN 'DELIVERED' END WHERE id = %(id)s",
            {"s": to, "id": row},
        )


@pytest.fixture
def rows(admin: Conn, tenant_a: Tenant) -> tuple[uuid.UUID, uuid.UUID]:
    job = insert_job(admin, tenant_a)
    return job, insert_task(admin, tenant_a, job)


@pytest.mark.parametrize(
    "rule",
    [r for r in ALL_RULES if r.from_state],
    ids=lambda r: f"{r.transition_id}:{r.from_state}",
)
def test_trigger_allows_every_rule(
    admin: Conn, rows: tuple[uuid.UUID, uuid.UUID], rule: Rule
) -> None:
    table = "tasks" if rule.entity_kind is EntityKind.TASK else "jobs"
    row = rows[1] if table == "tasks" else rows[0]
    assert rule.from_state is not None
    _place(admin, table, row, rule.from_state)
    _move(admin, table, row, rule.to_state)
    got = admin.execute(f"SELECT state FROM {table} WHERE id = %s", (row,)).fetchone()  # noqa: S608
    assert got == (rule.to_state,)


INVALID = [
    ("tasks", f.value, t.value)
    for f in TaskState
    for t in TaskState
    if f != t and not is_allowed_pair(EntityKind.TASK, f, t)
] + [
    ("jobs", f.value, t.value)
    for f in JobState
    for t in JobState
    if f != t and not is_allowed_pair(EntityKind.JOB, f, t)
]


@pytest.mark.parametrize(("table", "frm", "to"), INVALID)
def test_trigger_rejects_every_invalid_pair(
    admin: Conn, rows: tuple[uuid.UUID, uuid.UUID], table: str, frm: str, to: str
) -> None:
    row = rows[1] if table == "tasks" else rows[0]
    _place(admin, table, row, frm)
    with pytest.raises(psycopg.DatabaseError, match="invalid") as info:
        _move(admin, table, row, to)
    assert info.value.sqlstate == "AMW01"


@pytest.mark.parametrize("state", [s.value for s in TaskState if s is not TaskState.PENDING])
def test_insert_only_as_pending(admin: Conn, tenant_a: Tenant, state: str) -> None:
    job = insert_job(admin, tenant_a)
    task = insert_task(admin, tenant_a, job)
    row = admin.execute("SELECT * FROM tasks WHERE id = %s", (task,)).fetchone()
    assert row is not None
    with pytest.raises(psycopg.DatabaseError, match="invalid"):
        admin.execute(
            "INSERT INTO tasks (id, org_id, job_id, task_type, agent_id, priority,"
            " resource_class, required_capabilities, idempotency_key, payload_schema,"
            " payload_schema_version, resource_budget, max_attempts, state, wait_reason,"
            " next_attempt_at) SELECT gen_random_uuid(), org_id, job_id, task_type, agent_id,"
            " priority, resource_class, required_capabilities, %s, payload_schema,"
            " payload_schema_version, resource_budget, max_attempts, %s,"
            " CASE WHEN %s = 'CHECKPOINTED' THEN 'DRAIN' END, %s FROM tasks WHERE id = %s",
            ("idk_" + "e" * 64, state, state, datetime.now(UTC), task),
        )


def test_same_state_update_is_not_a_transition(
    admin: Conn, rows: tuple[uuid.UUID, uuid.UUID]
) -> None:
    _place(admin, "tasks", rows[1], "RETRY_WAIT")
    admin.execute(
        "UPDATE tasks SET state = 'RETRY_WAIT', next_attempt_at = now() WHERE id = %s", (rows[1],)
    )


def test_table_sizes() -> None:
    assert len(TASK_RULES) == 25
    assert len(JOB_RULES) == 22
