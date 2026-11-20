"""``PgScriptRowPort`` on real PostgreSQL: the ``scripts`` row, supersede, audit, idempotent replay,
tenant isolation and "no writes outside the owning tables" (agent_05 blueprint section 13)."""

from dataclasses import replace
from typing import Any

import pytest

from agent_05_scriptwriter.persist.script_repository import ScriptRowPort
from agent_05_scriptwriter.protocols import SavedScript, StepContext
from amw_core.audit.pg import PgAuditLog
from amw_core.errors import (
    IdempotencyConflictError,
    InputInvalidError,
    MissingDependencyError,
)
from amw_core.ids import ATTEMPT, CHANNEL, CORRELATION, JOB, TASK, new_uuid7
from amw_core.tenancy import PgTenancy
from amw_orchestrator.db_adapters import PgScriptRowPort
from amw_orchestrator.db_adapters._sql import SCRIPT
from tests.core_services.support import FixedClock
from tests.db_adapters.seed import Conn, Seeded, seed, seed_channel, seed_job, seed_task, sha
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
OTHER_TABLES = (
    "jobs", "tasks", "channels", "claims", "approvals", "qc_results", "quality_scores", "renders",
    "assets", "licence_ledger", "memory_items",
)  # fmt: skip


def _port(tenancy: PgTenancy) -> PgScriptRowPort:
    return PgScriptRowPort(tenancy, PgAuditLog(), FixedClock())


def _step(s: Seeded) -> StepContext:
    return StepContext(
        org_id=s.tenant.org_id,
        job_id=JOB.from_uuid(s.job),
        task_id=TASK.from_uuid(s.task),
        attempt_id=ATTEMPT.new(),
        channel_id=CHANNEL.from_uuid(s.channel),
        project_id=None,
        correlation_id=CORRELATION.new(),
        max_llm_calls=3,
        max_cost_micros=0,
    )


def _saved(version: int = 1, label: str = "a") -> SavedScript:
    return SavedScript(
        SCRIPT.from_uuid(new_uuid7()), version, f"amw-blob://x/{label}", sha(label).hex(), True
    )


def _insert(port: PgScriptRowPort, ctx: StepContext, saved: SavedScript, **over: Any) -> None:
    kw: dict[str, Any] = {
        "iteration": 1, "language": "mr-IN", "parent_script_id": None, "segment_count": 4,
        "word_count": 120, "est_duration_ms": None, "prompt_id": "agent_05/script_draft.v1",
    }  # fmt: skip
    port.insert(ctx, saved, **{**kw, **over})


def _count(conn: Conn, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
    assert row is not None
    return int(row[0])


def _counts(conn: Conn) -> dict[str, int]:
    return {t: _count(conn, t) for t in OTHER_TABLES}


def test_port_is_satisfied(tenancy: PgTenancy) -> None:
    port: ScriptRowPort = _port(tenancy)
    assert port is not None


def test_insert_find_and_latest_version(tenancy: PgTenancy, admin: Conn, tenant_a: Tenant) -> None:
    s = seed(admin, tenant_a)
    ctx, port = _step(s), _port(tenancy)
    assert port.latest_version(ctx, "mr-IN") == 0
    assert port.find(ctx, "mr-IN", 1) is None
    saved = _saved()
    other = _counts(admin)
    scripts, audits = _count(admin, "scripts"), _count(admin, "audit_log")
    _insert(port, ctx, saved, est_duration_ms=61_000)
    found = port.find(ctx, "mr-IN", 1)
    assert found is not None
    assert (found.script_id, found.version, found.uri, found.sha256, found.inserted) == (
        saved.script_id, 1, saved.uri, saved.sha256, False,
    )  # fmt: skip
    assert port.latest_version(ctx, "mr-IN") == 1
    row = admin.execute(
        "SELECT status, iteration, segment_count, word_count, est_duration_ms, prompt_id,"
        " created_by_task_id, channel_id FROM scripts WHERE id = %s",
        (SCRIPT.to_uuid(saved.script_id),),
    ).fetchone()
    assert row == ("DRAFT", 1, 4, 120, 61_000, "agent_05/script_draft.v1", s.task, s.channel)
    assert _count(admin, "scripts") == scripts + 1
    assert _count(admin, "audit_log") == audits + 1
    assert _counts(admin) == other  # nothing outside scripts and audit_log was written
    event = admin.execute(
        "SELECT action, target_kind, target_id, details FROM audit_log WHERE target_id = %s",
        (SCRIPT.to_uuid(saved.script_id),),
    ).fetchone()
    assert event is not None
    assert event[:3] == ("script.created", "SCRIPT", SCRIPT.to_uuid(saved.script_id))
    assert event[3]["sha256"] == saved.sha256
    assert "text" not in event[3]


def test_a_new_version_supersedes_the_previous_draft_only(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    ctx, port = _step(s), _port(tenancy)
    first, second = _saved(1, "v1"), _saved(2, "v2")
    _insert(port, ctx, first)
    _insert(port, ctx, second, iteration=2, parent_script_id=first.script_id)
    states: dict[int, str] = {
        r[0]: r[1]
        for r in admin.execute(
            "SELECT version, status FROM scripts WHERE job_id = %s", (s.job,)
        ).fetchall()
    }
    assert states == {1: "SUPERSEDED", 2: "DRAFT"}
    assert port.latest_version(ctx, "mr-IN") == 2
    # an approved previous version is decided by the approval path: never touched here
    admin.execute(
        "UPDATE scripts SET status = 'APPROVED' WHERE version = 2 AND job_id = %s", (s.job,)
    )
    _insert(port, ctx, _saved(3, "v3"), iteration=3)
    assert admin.execute(
        "SELECT status FROM scripts WHERE version = 2 AND job_id = %s", (s.job,)
    ).fetchone() == ("APPROVED",)


def test_other_language_is_not_superseded(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    ctx, port = _step(s), _port(tenancy)
    _insert(port, ctx, _saved(1, "mr"), language="mr-IN")
    _insert(port, ctx, _saved(2, "en"), language="en-IN", iteration=1)
    assert admin.execute(
        "SELECT status FROM scripts WHERE job_id = %s AND language = 'mr-IN'", (s.job,)
    ).fetchone() == ("DRAFT",)


def test_equal_replay_writes_nothing_again(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    ctx, port = _step(s), _port(tenancy)
    saved = _saved()
    _insert(port, ctx, saved)
    scripts, audits = _count(admin, "scripts"), _count(admin, "audit_log")
    _insert(port, ctx, saved)
    assert (_count(admin, "scripts"), _count(admin, "audit_log")) == (scripts, audits)


def test_same_key_other_hash_or_other_id_conflicts(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    ctx, port = _step(s), _port(tenancy)
    saved = _saved()
    _insert(port, ctx, saved)
    with pytest.raises(IdempotencyConflictError):
        _insert(port, ctx, SavedScript(saved.script_id, 1, saved.uri, sha("other").hex(), True))
    with pytest.raises(IdempotencyConflictError):
        _insert(port, ctx, SavedScript(_saved().script_id, 1, saved.uri, saved.sha256, True))
    # the same script ID under another version is the ID-reuse case
    with pytest.raises(IdempotencyConflictError):
        _insert(port, ctx, SavedScript(saved.script_id, 2, saved.uri, sha("v2").hex(), True))


def test_cross_tenant_refusal(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    a = seed(admin, tenant_a)
    port = _port(tenancy)
    _insert(port, _step(a), _saved())
    # tenant B's context names A's job, task and channel: nothing is visible, nothing is written
    b_ctx = StepContext(
        org_id=tenant_b.org_id,
        job_id=JOB.from_uuid(a.job),
        task_id=TASK.from_uuid(a.task),
        attempt_id=ATTEMPT.new(),
        channel_id=CHANNEL.from_uuid(a.channel),
        project_id=None,
        correlation_id=CORRELATION.new(),
        max_llm_calls=3,
        max_cost_micros=0,
    )
    scripts = _count(admin, "scripts")
    assert port.find(b_ctx, "mr-IN", 1) is None
    assert port.latest_version(b_ctx, "mr-IN") == 0
    with pytest.raises(MissingDependencyError):
        _insert(port, b_ctx, _saved(1, "intruder"))
    assert _count(admin, "scripts") == scripts


def test_missing_rows_and_bad_input_fail_closed(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    port = _port(tenancy)
    ctx = _step(s)
    scripts_before = _count(admin, "scripts")
    for bad in (
        replace(ctx, job_id=JOB.new()),
        replace(ctx, task_id=TASK.new()),
        replace(ctx, channel_id=CHANNEL.new()),
    ):
        with pytest.raises(MissingDependencyError):
            _insert(port, bad, _saved())
    with pytest.raises(MissingDependencyError):
        _insert(port, ctx, _saved(), parent_script_id=SCRIPT.from_uuid(new_uuid7()))
    with pytest.raises(InputInvalidError):
        _insert(port, ctx, SavedScript(_saved().script_id, 1, "u", "zz", True))
    with pytest.raises(InputInvalidError):
        _insert(port, ctx, SavedScript(_saved().script_id, 1, "u", "ab" * 16, True))
    assert _count(admin, "scripts") == scripts_before


def test_parent_script_of_the_same_tenant_is_accepted(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    other_job = seed_job(admin, tenant_a, seed_channel(admin, tenant_a))
    seed_task(admin, tenant_a, other_job)
    port = _port(tenancy)
    parent = _saved(1, "long")
    _insert(port, _step(s), parent)
    child = _saved(1, "short")
    short_ctx = replace(_step(s), job_id=JOB.from_uuid(other_job))
    # the child's task belongs to the first job: a task of another job is still the tenant's task
    _insert(port, short_ctx, child, parent_script_id=parent.script_id)
    assert admin.execute(
        "SELECT parent_script_id FROM scripts WHERE id = %s", (SCRIPT.to_uuid(child.script_id),)
    ).fetchone() == (SCRIPT.to_uuid(parent.script_id),)
