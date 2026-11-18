"""PostgreSQL fixtures (tests/pg_fixtures.py) plus job / task rows for the lane L1b stores."""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest

from amw_core.ids import (
    ATTEMPT,
    JOB,
    TASK,
    USER,
    AttemptId,
    JobId,
    TaskId,
    UserId,
    new_uuid7,
)
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy import PgTenancy, connection_of, dsn_connection_factory, translate_db_error
from tests.pg_fixtures import Tenant, admin, empty_dsn, pg_dsn, tenancy, tenant_a, tenant_b

__all__ = ["admin", "empty_dsn", "pg_dsn", "readonly", "tenancy", "tenant_a", "tenant_b"]

Conn = psycopg.Connection[tuple[Any, ...]]


@pytest.fixture
def readonly(pg_dsn: str) -> PgTenancy:
    """Tenant transactions as ``amw_readonly`` (audit verification and export)."""
    return PgTenancy(dsn_connection_factory(pg_dsn, role="amw_readonly"))


@dataclass(frozen=True, slots=True)
class Work:
    job_id: JobId
    task_id: TaskId
    attempt_id: AttemptId


def _production_type(conn: Conn) -> None:
    record = {"key": "CHANNEL_LONG_FORM", "version": 2}
    raw = json.dumps(record, sort_keys=True).encode()
    conn.execute(
        "INSERT INTO production_types (id, key, version, status, tier, record, record_sha256)"
        " VALUES (%s, 'CHANNEL_LONG_FORM', 2, 'IN_DEVELOPMENT', 'TIER_0', %s, %s)"
        " ON CONFLICT (key, version) DO NOTHING",
        (new_uuid7(), json.dumps(record), hashlib.sha256(raw).digest()),
    )


def make_job(conn: Conn, tenant: Tenant, *, max_cost_micros: int = 0) -> JobId:
    _production_type(conn)
    job = new_uuid7()
    conn.execute(
        "INSERT INTO jobs (id, org_id, workspace_id, production_type_key, production_type_version,"
        " language, priority, correlation_id, idempotency_key, requested_by, currency)"
        " VALUES (%s, %s, %s, 'CHANNEL_LONG_FORM', 2, 'mr', 2, %s, %s, 'sys_operator', 'INR')",
        (job, tenant.org_uuid, tenant.workspace_uuid, new_uuid7(), "idk_" + uuid.uuid4().hex * 2),
    )
    return JOB.from_uuid(job)


def make_task(
    conn: Conn, tenant: Tenant, job_id: JobId, *, max_cost_micros: int = 0
) -> tuple[TaskId, AttemptId]:
    task, att = new_uuid7(), new_uuid7()
    conn.execute(
        "INSERT INTO tasks (id, org_id, job_id, task_type, agent_id, priority, resource_class,"
        " required_capabilities, idempotency_key, payload_schema, payload_schema_version,"
        " resource_budget, max_attempts)"
        " VALUES (%s, %s, %s, 'agent_05.script_draft', 'agent_05', 2, 'AI_IO', '{llm}', %s,"
        " 'agent_05.script_draft.input', '1.0.0', %s, 5)",
        (
            task,
            tenant.org_uuid,
            JOB.to_uuid(job_id),
            "idk_" + uuid.uuid4().hex * 2,
            json.dumps({"max_cost_micros": max_cost_micros}),
        ),
    )
    conn.execute(
        "INSERT INTO task_attempts (id, org_id, task_id, attempt_no, started_at)"
        " VALUES (%s, %s, %s, 1, now())",
        (att, tenant.org_uuid, task),
    )
    return TASK.from_uuid(task), ATTEMPT.from_uuid(att)


def make_work(conn: Conn, tenant: Tenant, max_cost_micros: int = 0) -> Work:
    job = make_job(conn, tenant)
    task, att = make_task(conn, tenant, job, max_cost_micros=max_cost_micros)
    return Work(job, task, att)


def make_user(conn: Conn) -> UserId:
    user = new_uuid7()
    conn.execute(
        "INSERT INTO users (id, email, display_name, status) VALUES (%s, %s, 'Owner', 'ACTIVE')",
        (user, f"u{user.hex[-10:]}@example.invalid"),
    )
    return USER.from_uuid(user)


@pytest.fixture
def work_a(admin: Conn, tenant_a: Tenant) -> Work:
    return make_work(admin, tenant_a)


def run_sql(tx: TenantTransaction, stmt: str, params: Any = None) -> Any:
    """Raw statement inside a tenant transaction; driver errors become the 07 typed errors."""
    try:
        return connection_of(tx).execute(stmt.encode(), params)
    except psycopg.Error as exc:
        raise translate_db_error(exc) from exc
