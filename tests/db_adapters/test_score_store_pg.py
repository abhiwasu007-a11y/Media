"""``PgScoreStore`` on real PostgreSQL: machine ``quality_scores`` and ``qc_results`` rows,
idempotency per key, subject binding, tenant isolation and the tables it must not touch."""

from typing import Any

import pytest

from agent_16_compliance_qa.scoring.stage import NewScoreQcRow, NewScoreRow, ScoreStore
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import CheckKind, CheckVerdict
from amw_core.errors import (
    ConfigInvalidError,
    IdempotencyConflictError,
    InputInvalidError,
    LockConflictError,
    MissingDependencyError,
)
from amw_core.ids import (
    JOB,
    RENDER,
    TASK,
    ActorRef,
    IdempotencyKey,
    IdempotencyScope,
    make_idempotency_key,
)
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy import PgTenancy
from amw_core.testing.memory import MemoryTransaction
from amw_orchestrator.db_adapters import PgScoreStore
from tests.core_services.support import T0, FixedClock
from tests.db_adapters.seed import Conn, Seeded, seed, seed_render
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
EVIDENCE = {"rubric_version": "rubric.v1", "criteria": [{"criterion_id": "R1", "earned": 4}]}


def _store() -> PgScoreStore:
    return PgScoreStore(FixedClock(), lock_ms=60_000)


def _ctx(t: Tenant) -> TenantContext:
    return TenantContext(t.org_id, ActorRef("agent_16"))


def _key(s: Seeded, *parts: str) -> Any:
    return make_idempotency_key(
        s.tenant.org_id, IdempotencyScope.DB_OUTPUT.value, [TASK.from_uuid(s.task), 0, *parts]
    )


def _score(s: Seeded, render: Any, digest: bytes, **over: Any) -> NewScoreRow:
    base: dict[str, Any] = {
        "job_id": JOB.from_uuid(s.job),
        "task_id": TASK.from_uuid(s.task),
        "render_id": RENDER.from_uuid(render),
        "render_sha256": digest.hex(),
        "dimension": "STORYTELLING",
        "max_points": 15,
        "points": 11.5,
        "scorer_kind": "LLM_JUDGE",
        "evidence": EVIDENCE,
    }
    return NewScoreRow(**{**base, **over})


def _qc(s: Seeded, render: Any, **over: Any) -> NewScoreQcRow:
    result: dict[str, Any] = {
        "check_id": "a16.q.score_floor",
        "kind": CheckKind.DETERMINISTIC,
        "verdict": CheckVerdict.FAIL,
        "blocking": True,
        "rule_id": "QS-R1",
        "measured": 61.5,
        "threshold": 70,
        "unit": "points",
        "message": "below the floor",
        "gate": True,
        "remedy_stage_id": "s05_script",
    }
    return NewScoreQcRow(
        JOB.from_uuid(s.job),
        TASK.from_uuid(s.task),
        RENDER.from_uuid(render),
        ValidationResult(**{**result, **over}),
    )


def _count(conn: Conn, table: str, org: Tenant | None = None) -> int:
    """Rows of the table (of one tenant when given; the test database is shared by the session)."""
    where, params = ("WHERE org_id = %s", (org.org_uuid,)) if org else ("", ())
    row = conn.execute(f"SELECT count(*) FROM {table} {where}", params).fetchone()  # noqa: S608
    assert row is not None
    return int(row[0])


def test_port_is_satisfied() -> None:
    store: ScoreStore = _store()
    assert store is not None


def test_writes_one_score_row_with_its_binding(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    render, digest = seed_render(admin, tenant_a, s.job)
    others = {
        t: _count(admin, t, tenant_a)
        for t in ("jobs", "tasks", "renders", "qc_results", "approvals")
    }
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        wire = _store().insert_score(
            tx, _score(s, render, digest), _key(s, "score", "STORYTELLING")
        )
    assert wire.startswith("qsc_")
    row = admin.execute(
        "SELECT job_id, subject_kind, subject_id, subject_sha256, rubric_version, dimension,"
        " max_points, points, scorer_kind, scorer_ref, evidence_ref, approval_channel, evidence_id"
        " FROM quality_scores WHERE org_id = %s",
        (tenant_a.org_uuid,),
    ).fetchone()
    assert row is not None
    assert row[:10] == (
        s.job, "render", render, digest, "rubric.v1", "STORYTELLING", 15, row[7],
        "LLM_JUDGE", "agent_16",
    )  # fmt: skip
    assert float(row[7]) == 11.5
    assert '"criterion_id":"R1"' in row[10]  # the canonical JSON of the evidence (18 9.1.5)
    assert row[11:] == (None, None)  # a machine row carries no human fields
    assert {t: _count(admin, t, tenant_a) for t in others} == others
    assert admin.execute(
        "SELECT scope, status, result_ref, task_id FROM idempotency_keys WHERE org_id = %s",
        (tenant_a.org_uuid,),
    ).fetchone() == ("db.output", "COMPLETED", wire, s.task)


def test_replay_with_the_same_key_returns_the_stored_id_and_writes_nothing(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    render, digest = seed_render(admin, tenant_a, s.job)
    key = _key(s, "score", "STORYTELLING")
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        first = _store().insert_score(tx, _score(s, render, digest), key)
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        again = _store().insert_score(tx, _score(s, render, digest), key)
    assert again == first
    assert _count(admin, "quality_scores", tenant_a) == 1
    with tenancy.transaction(_ctx(tenant_a)) as tx, pytest.raises(IdempotencyConflictError):
        _store().insert_score(tx, _score(s, render, digest, points=3.0), key)
    assert _count(admin, "quality_scores", tenant_a) == 1


def test_a_key_still_in_flight_is_a_transient_conflict(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    render, digest = seed_render(admin, tenant_a, s.job)
    key = _key(s, "score", "STORYTELLING")
    row = _score(s, render, digest)
    # another attempt began the key (same request) and has not completed: no second writer
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        store = _store()
        store._idem.begin(
            tx, key, "db.output", _request_hash(row), TASK.from_uuid(s.task), T0, 60_000
        )
    with tenancy.transaction(_ctx(tenant_a)) as tx, pytest.raises(LockConflictError):
        store.insert_score(tx, row, key)
    assert _count(admin, "quality_scores", tenant_a) == 0


def _request_hash(row: NewScoreRow) -> str:
    import hashlib

    from amw_orchestrator.db_adapters.score_store import _canonical

    request = _canonical(
        {
            "kind": "score", "job": row.job_id, "task": row.task_id, "render": row.render_id,
            "sha": row.render_sha256, "dimension": row.dimension, "max": row.max_points,
            "points": row.points, "scorer": row.scorer_kind, "evidence": row.evidence,
        }
    )  # fmt: skip
    return hashlib.sha256(request.encode()).hexdigest()


def test_score_refusals_fail_closed(tenancy: PgTenancy, admin: Conn, tenant_a: Tenant) -> None:
    s = seed(admin, tenant_a)
    render, digest = seed_render(admin, tenant_a, s.job)
    other_render, _ = seed_render(admin, tenant_a, s.job, "r2")
    store = _store()
    cases: list[tuple[type[Exception], NewScoreRow]] = [
        (InputInvalidError, _score(s, render, digest, scorer_kind="HUMAN")),
        (InputInvalidError, _score(s, render, digest, evidence={"criteria": []})),
        (InputInvalidError, _score(s, render, digest, render_sha256="zz")),
        (InputInvalidError, _score(s, render, digest, render_sha256="ab" * 8)),
        (InputInvalidError, _score(s, other_render, digest)),  # another render's content hash
        (InputInvalidError, _score(s, render, digest, points=99.0)),  # above max_points
        (InputInvalidError, _score(s, render, digest, max_points=14)),  # not the dimension's 15
        (MissingDependencyError, _score(s, render, digest, job_id=JOB.new())),
        (MissingDependencyError, _score(s, render, digest, task_id=TASK.new())),
    ]
    for n, (error, row) in enumerate(cases):
        with tenancy.transaction(_ctx(tenant_a)) as tx, pytest.raises(error):
            store.insert_score(tx, row, _key(s, "case", str(n)))
    assert _count(admin, "quality_scores", tenant_a) == 0
    assert _count(admin, "idempotency_keys", tenant_a) == 0  # every refusal rolled back


def test_unknown_render_and_foreign_tenant_are_missing_dependencies(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    s = seed(admin, tenant_a)
    render, digest = seed_render(admin, tenant_a, s.job)
    unknown = _score(s, render, digest, render_id=RENDER.new())
    with tenancy.transaction(_ctx(tenant_a)) as tx, pytest.raises(MissingDependencyError):
        _store().insert_score(tx, unknown, _key(s, "unknown"))
    # tenant B names A's job, task and render: invisible, nothing is written
    with tenancy.transaction(_ctx(tenant_b)) as tx, pytest.raises(MissingDependencyError):
        _store().insert_score(tx, _score(s, render, digest), _key(s, "foreign"))
    with tenancy.transaction(_ctx(tenant_b)) as tx, pytest.raises(MissingDependencyError):
        _store().insert_qc_result(tx, _qc(s, render), _key(s, "foreign-qc"))
    assert (_count(admin, "quality_scores", tenant_a), _count(admin, "qc_results", tenant_a)) == (
        0,
        0,
    )


def test_qc_result_row_and_replay(tenancy: PgTenancy, admin: Conn, tenant_a: Tenant) -> None:
    s = seed(admin, tenant_a)
    render, _digest = seed_render(admin, tenant_a, s.job)
    key = _key(s, "qc", "a16.q.score_floor")
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        wire = _store().insert_qc_result(tx, _qc(s, render), key)
    assert wire.startswith("qcr_")
    row = admin.execute(
        "SELECT job_id, task_id, render_id, check_id, kind, verdict, blocking, rule_id,"
        " measured_num, measured_text, threshold_num, threshold_text, unit, message, evidence_ref"
        " FROM qc_results WHERE org_id = %s",
        (tenant_a.org_uuid,),
    ).fetchone()
    assert row is not None
    assert row[:8] == (
        s.job,
        s.task,
        render,
        "a16.q.score_floor",
        "DETERMINISTIC",
        "FAIL",
        True,
        "QS-R1",
    )
    assert (float(row[8]), row[9], float(row[10]), row[11]) == (61.5, None, 70.0, None)
    assert row[12:] == ("points", "below the floor", None)
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        assert _store().insert_qc_result(tx, _qc(s, render), key) == wire
    assert _count(admin, "qc_results", tenant_a) == 1
    with tenancy.transaction(_ctx(tenant_a)) as tx, pytest.raises(IdempotencyConflictError):
        _store().insert_qc_result(tx, _qc(s, render, message="changed"), key)


def test_qc_measured_values_map_to_their_columns(
    tenancy: PgTenancy, admin: Conn, tenant_a: Tenant
) -> None:
    s = seed(admin, tenant_a)
    render, _digest = seed_render(admin, tenant_a, s.job)
    cases: list[tuple[str, dict[str, Any]]] = [
        ("a16.q.text", {"measured": "abc", "threshold": True, "unit": None}),
        ("a16.q.none", {"measured": None, "threshold": None, "unit": None}),
        ("a16.q.off", {"measured": False, "threshold": "x", "unit": None}),
    ]
    with tenancy.transaction(_ctx(tenant_a)) as tx:
        for check_id, over in cases:
            _store().insert_qc_result(
                tx, _qc(s, render, check_id=check_id, **over), _key(s, "qc", check_id)
            )
    got = {
        r[0]: r[1:]
        for r in admin.execute(
            "SELECT check_id, measured_num, measured_text, threshold_num, threshold_text"
            " FROM qc_results WHERE org_id = %s",
            (tenant_a.org_uuid,),
        ).fetchall()
    }
    assert got == {
        "a16.q.text": (None, "abc", None, "true"),
        "a16.q.none": (None, None, None, None),
        "a16.q.off": (None, "false", None, "x"),
    }


def test_wiring_errors(tenant_a: Tenant) -> None:
    with pytest.raises(InputInvalidError):
        PgScoreStore(FixedClock(), lock_ms=0)
    memory = MemoryTransaction(_ctx(tenant_a))
    row = NewScoreRow(
        JOB.new(),
        TASK.new(),
        RENDER.new(),
        "00" * 32,
        "STORYTELLING",
        15,
        1.0,
        "LLM_JUDGE",
        EVIDENCE,
    )
    with pytest.raises(ConfigInvalidError):
        _store().insert_score(memory, row, IdempotencyKey("idk_" + "0" * 64))
