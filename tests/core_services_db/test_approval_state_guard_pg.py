# ruff: noqa: F811
"""approvals.state is a human row (migration 0060; PR 108 review r1 BLOCKER; R14).

Every application login is refused a direct decided-state write, a hash change and a rewrite of
``tasks.approval_id``; the legal path (owner evidence -> ``amw_human_record_apply`` ->
``amw_approval_settle``) still works; the publish guard re-checks the evidence at use time.
NOT a claim about the real chat: the evidence here is synthetic (tests/session_transcript.py).
"""

import uuid
from datetime import datetime
from typing import Any

import psycopg
import pytest

from amw_core import ids
from amw_core.enums import ApprovalStepState
from amw_core.errors import PermissionDeniedError
from amw_core.interfaces import DbRole
from amw_core.owner_evidence_approvals import PgApprovalEvidencePort
from amw_core.owner_evidence_operator import locate
from amw_core.owner_evidence_pg import PgDbSession
from amw_core.tenancy import PgTenancy, connection_of
from tests.core_services_db.test_approval_desk_pg import (  # noqa: F401 (fixtures)
    SHA,
    Job,
    World,
    mac_key,
    world,
)
from tests.core_services_db.test_owner_evidence_real_path_pg import login

pytestmark = [pytest.mark.integration, pytest.mark.security]
Conn = psycopg.Connection[tuple[Any, ...]]
ROLES = ["amw_app", "amw_publisher", "amw_operator", "amw_verifier"]
DECIDED = ["APPROVED", "REJECTED", "CHANGES_REQUESTED", "WITHDRAWN"]


def as_login(world: World, role: str) -> PgTenancy:
    return PgTenancy(login(world.dsn, role))


def refused(world: World, role: str, stmt: str, params: tuple[Any, ...] = ()) -> None:
    """The statement, run by ``role`` in a tenant transaction, is refused (guard AMW02 or no
    privilege 42501, both ``PermissionDeniedError``)."""
    with pytest.raises(PermissionDeniedError), as_login(world, role).transaction(world.ctx) as tx:
        connection_of(tx).execute(stmt.encode(), params)


def opened(world: World) -> tuple[Job, uuid.UUID]:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    return job, world.approval(job)["id"]


def state_of(world: World, approval: uuid.UUID) -> tuple[Any, ...]:
    row = world.admin.execute(
        "SELECT state, subject_sha256, decided_at FROM approvals WHERE id = %s", (approval,)
    ).fetchone()
    assert row is not None
    return row


def settled(world: World) -> tuple[Job, uuid.UUID]:
    """An approval settled APPROVED through the legal path."""
    job, approval = opened(world)
    world.owner_decides(job)
    assert world.real.decision(job.task_input(), job.ctx()) is not None
    assert state_of(world, approval)[0] == "APPROVED"
    return job, approval


# ---- a PENDING approval: no login can decide it, change its hash or re-point a task ----------
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("decided", DECIDED)
def test_no_login_writes_a_decided_state(world: World, role: str, decided: str) -> None:
    _, approval = opened(world)
    before = state_of(world, approval)
    refused(world, role, "UPDATE approvals SET state = %s WHERE id = %s", (decided, approval))
    refused(
        world,
        role,
        "UPDATE approvals SET state = %s, decided_at = now() WHERE id = %s",
        (decided, approval),
    )
    assert state_of(world, approval) == before


@pytest.mark.parametrize("role", ROLES)
def test_no_login_changes_the_subject_hash_or_subject(world: World, role: str) -> None:
    _, approval = opened(world)
    before = state_of(world, approval)
    other = bytes.fromhex("cd" * 32)
    refused(
        world, role, "UPDATE approvals SET subject_sha256 = %s WHERE id = %s", (other, approval)
    )
    refused(world, role, "UPDATE approvals SET subject_sha256 = NULL WHERE id = %s", (approval,))
    refused(
        world, role, "UPDATE approvals SET subject_id = %s WHERE id = %s", (uuid.uuid4(), approval)
    )
    refused(world, role, "UPDATE approvals SET workflow_key = 'x' WHERE id = %s", (approval,))
    refused(world, role, "UPDATE approvals SET kind = 'PUBLISH' WHERE id = %s", (approval,))
    assert state_of(world, approval) == before


@pytest.mark.parametrize("role", ROLES)
def test_no_login_rewrites_tasks_approval_id(world: World, role: str) -> None:
    job, approval = opened(world)
    other_job, other = opened(world)
    task = ids.TASK.to_uuid(job.task)
    refused(world, role, "UPDATE tasks SET approval_id = %s WHERE id = %s", (other, task))
    refused(world, role, "UPDATE tasks SET approval_id = NULL WHERE id = %s", (task,))
    got = world.admin.execute("SELECT approval_id FROM tasks WHERE id = %s", (task,)).fetchone()
    assert got == (approval,)
    # a task without an approval cannot be pointed at an approval of another job either
    free = world.job()
    refused(
        world,
        role,
        "UPDATE tasks SET approval_id = %s WHERE id = %s",
        (other, ids.TASK.to_uuid(free.task)),
    )
    got = world.admin.execute(
        "SELECT approval_id FROM tasks WHERE id = %s", (ids.TASK.to_uuid(free.task),)
    ).fetchone()
    assert got == (None,)
    assert other_job.task != job.task


@pytest.mark.parametrize("role", ["amw_app", "amw_publisher"])
@pytest.mark.parametrize("decided", DECIDED)
def test_an_approval_is_never_created_decided(world: World, role: str, decided: str) -> None:
    job = world.job()
    new = uuid.uuid4()
    refused(
        world,
        role,
        "INSERT INTO approvals (id, org_id, job_id, kind, subject_kind, subject_id,"
        " subject_sha256, state, workflow_key, current_step, managed_service, requested_by,"
        " review_code) VALUES (%s, amw_current_org(), %s, 'FINAL_VIDEO', 'render', %s, %s, %s,"
        " 'owner_one_tap', 1, false, 'svc_s07', 'Q7Q7')",
        (new, ids.JOB.to_uuid(job.job), uuid.uuid4(), bytes.fromhex(SHA), decided),
    )
    count = world.admin.execute("SELECT count(*) FROM approvals WHERE id = %s", (new,)).fetchone()
    assert count == (0,)


def test_settle_is_refused_without_a_decided_step_and_to_other_roles(world: World) -> None:
    _, approval = opened(world)
    refused(world, "amw_app", "SELECT amw_approval_settle(%s)", (approval,))  # step undecided
    for role in ("amw_publisher", "amw_operator", "amw_verifier"):  # no EXECUTE
        refused(world, role, "SELECT amw_approval_settle(%s)", (approval,))
    assert state_of(world, approval)[0] == "PENDING"


def test_even_the_definer_role_needs_backing_evidence(world: World) -> None:
    """amw_verifier_fn (the role of amw_approval_settle) cannot decide without evidence either."""
    job, approval = opened(world)
    with world.admin.transaction():
        world.admin.execute(
            "SELECT set_config('app.org_id', %s, true)", (str(world.tenant.org_uuid),)
        )
        world.admin.execute("SET LOCAL ROLE amw_verifier_fn")
        with pytest.raises(psycopg.Error):
            world.admin.execute(
                "UPDATE approvals SET state = 'APPROVED' WHERE id = %s", (approval,)
            )
    assert state_of(world, approval)[0] == "PENDING"
    assert job.task


# ---- the legal path, and a decided approval is immutable ---------------------------------
def test_the_legal_path_settles_and_the_result_is_immutable(world: World) -> None:
    job, approval = settled(world)
    decided_at = state_of(world, approval)[2]
    assert decided_at is not None
    for role in ROLES:
        refused(world, role, "UPDATE approvals SET state = 'REJECTED' WHERE id = %s", (approval,))
        refused(world, role, "UPDATE approvals SET state = 'PENDING' WHERE id = %s", (approval,))
        refused(
            world,
            role,
            "UPDATE approvals SET subject_sha256 = %s WHERE id = %s",
            (bytes.fromhex("cd" * 32), approval),
        )
        refused(world, role, "UPDATE approvals SET decided_at = now() WHERE id = %s", (approval,))
    row = state_of(world, approval)
    assert (row[0], bytes(row[1]).hex(), row[2]) == ("APPROVED", SHA, decided_at)
    # the settle door is idempotent and returns False for an already settled approval
    with world.app_db.transaction(world.ctx) as tx:
        got = connection_of(tx).execute("SELECT amw_approval_settle(%s)", (approval,)).fetchone()
    assert got == (False,)
    # the step evidence is still the legal decision
    assert world.real.decided(str(job.job), str(job.task))


def test_a_rejection_settles_through_the_same_door(world: World) -> None:
    job, approval = opened(world)
    world.owner_decides(job, "reject", parsed_decision=ApprovalStepState.REJECTED)
    out = world.real.decision(job.task_input(), job.ctx())
    assert out is not None
    assert state_of(world, approval)[0] == "REJECTED"


# ---- use-time re-check: the publish guard and the evidence port --------------------------
def _publication(world: World, job: Job, approval: uuid.UUID) -> uuid.UUID:
    pub = uuid.uuid4()
    with world.admin.transaction():
        world.admin.execute("SET LOCAL session_replication_role = replica")  # no FK, no guard
        world.admin.execute(
            "INSERT INTO publications (id, org_id, job_id, render_id, render_sha256,"
            " destination_kind, state, approval_id, authorisation_verdict_id, idempotency_key)"
            " VALUES (%s, %s, %s, %s, %s, 'FILE_DELIVERY', 'DRAFT', %s, %s, %s)",
            (pub, world.tenant.org_uuid, ids.JOB.to_uuid(job.job), uuid.uuid4(),
             bytes.fromhex(SHA), approval, uuid.uuid4(), "idk_" + pub.hex.ljust(64, "1")),
        )  # fmt: skip
    return pub


def _upload(world: World, pub: uuid.UUID) -> str:
    """Move the publication to UPLOADING with the guard on; returns the guard's message."""
    try:
        with world.admin.transaction():
            world.admin.execute(  # the guard runs inside a tenant transaction (RLS of the MAC key)
                "SELECT set_config('app.org_id', %s, true)", (str(world.tenant.org_uuid),)
            )
            world.admin.execute("UPDATE publications SET state = 'UPLOADING' WHERE id = %s", (pub,))
    except psycopg.Error as exc:
        return str(exc)
    return "allowed"


def test_publish_guard_rechecks_the_evidence_at_use_time(world: World) -> None:
    job, approval = settled(world)
    pub = _publication(world, job, approval)
    # the approval check passes (the next check, the contribution, is what refuses here)
    assert "editorial contribution" in _upload(world, pub)
    code = world.approval(job)["code"]
    text = f"reject {code}"
    uid = world.t.human(text, world.at(10))
    world.t.write(world.root)
    said: datetime = locate(world.src, world.t.session_id, text).timestamp
    with world.operator_db.transaction(world.ctx) as tx:
        world.db.insert_evidence(
            PgDbSession(DbRole.OPERATOR),
            tx,
            world.draft(job, uid, text, said, parsed_decision=ApprovalStepState.REJECTED),
        )
    # approvals.state still says APPROVED, but the evidence is superseded: the guard refuses
    assert state_of(world, approval)[0] == "APPROVED"
    assert "no APPROVED approval" in _upload(world, pub)


def test_publish_guard_does_not_trust_a_forged_state_column(world: World) -> None:
    job, approval = opened(world)
    with world.admin.transaction():  # the owner of the database forces the column (no trigger)
        world.admin.execute("SET LOCAL session_replication_role = replica")
        world.admin.execute("UPDATE approvals SET state = 'APPROVED' WHERE id = %s", (approval,))
    pub = _publication(world, job, approval)
    assert "no APPROVED approval" in _upload(world, pub)


def test_evidence_port_answers_only_for_the_approved_subject(world: World) -> None:
    job, approval = opened(world)
    wire = ids.format_id(ids.Prefix.APPROVAL, approval)
    port = world.desk_port()
    assert port.approved(wire, SHA) is None  # pending
    world.owner_decides(job)
    assert port.approved(wire, SHA) is None  # decided but not settled yet
    world.real.decision(job.task_input(), job.ctx())
    status = port.approved(wire, SHA)
    assert status is not None
    assert (status.approval_id, status.subject_sha256, status.decision) == (wire, SHA, "APPROVED")
    assert port.approved(wire, "cd" * 32) is None  # another subject hash
    assert port.approved("apr_not-an-id", SHA) is None
    assert isinstance(port, PgApprovalEvidencePort)


def test_evidence_port_never_answers_for_a_rejection(world: World) -> None:
    job, approval = opened(world)
    world.owner_decides(job, "reject", parsed_decision=ApprovalStepState.REJECTED)
    world.real.decision(job.task_input(), job.ctx())
    wire = ids.format_id(ids.Prefix.APPROVAL, approval)
    port = world.desk_port()
    assert port.approved(wire, SHA) is None
    with world.app_db.transaction(world.ctx) as tx:
        lookup = world.lookup(tx)
        step_ev = ids.format_id(ids.Prefix.OWNER_INSTRUCTION_EVIDENCE, world.step_evidence(job))
        assert lookup.get(step_ev) is not None  # `get` is any decision row ...
        assert lookup.get_approved(step_ev, wire, SHA) is None  # ... `get_approved` only APPROVED
        assert lookup.explain(step_ev, wire, decision="APPROVED", subject_sha256=SHA) == (
            "evidence carries another decision than the one asked for"
        )


# ---- PR 108 r2: source mark vs database profile (MAJOR), residual columns (MINORs) --------------
def _set_marks(world: World, job: Job, result: str) -> None:
    """Rewrite the stored verifier result of the step evidence as the database owner (the
    trigger-free path of a forged or unmarked verification)."""
    evidence = world.step_evidence(job)
    with world.admin.transaction():
        world.admin.execute("SET LOCAL session_replication_role = replica")
        world.admin.execute(
            "UPDATE owner_instruction_evidence SET verifier_result = %s::jsonb WHERE id = %s",
            (result, evidence),
        )


def _marks(world: World, job: Job) -> str:
    got = world.admin.execute(
        "SELECT verifier_result::text FROM owner_instruction_evidence WHERE id = %s",
        (world.step_evidence(job),),
    ).fetchone()
    assert got is not None
    return str(got[0])


def test_real_profile_settle_needs_the_production_mark(world: World) -> None:
    job, approval = opened(world)
    world.owner_decides(job)
    real_result = _marks(world, job)
    assert "session_source_production" in real_result
    _set_marks(world, job, "{}")  # verified without the production mark
    with pytest.raises(PermissionDeniedError):
        world.real.decision(job.task_input(), job.ctx())
    refused(world, "amw_app", "SELECT amw_approval_settle(%s)", (approval,))
    assert state_of(world, approval)[0] == "PENDING"
    _set_marks(world, job, '{"session_source_test_fixture": true}')  # a TEST mark in REAL
    refused(world, "amw_app", "SELECT amw_approval_settle(%s)", (approval,))
    _set_marks(world, job, real_result)  # the mark is what decides: restored, it settles
    with world.app_db.transaction(world.ctx) as tx:
        got = connection_of(tx).execute("SELECT amw_approval_settle(%s)", (approval,)).fetchone()
    assert got == (True,)
    assert state_of(world, approval)[0] == "APPROVED"


def test_real_profile_publish_guard_needs_the_production_mark(world: World) -> None:
    job, approval = settled(world)
    pub = _publication(world, job, approval)
    assert "editorial contribution" in _upload(world, pub)  # the approval check passes
    _set_marks(world, job, "{}")
    assert state_of(world, approval)[0] == "APPROVED"
    assert "no APPROVED approval" in _upload(world, pub)


def test_test_profile_accepts_only_the_test_mark(world: World, admin: Conn) -> None:
    from tests.core_services_db.test_approval_desk_pg import dry_decision, profile_test

    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    approval = world.approval(job)["id"]
    with profile_test(admin):
        dry_decision(world, job)  # TEST-marked evidence
        original = _marks(world, job)
        assert "session_source_test_fixture" in original
        _set_marks(world, job, '{"session_source_production": true}')
        refused(world, "amw_app", "SELECT amw_approval_settle(%s)", (approval,))
        _set_marks(world, job, "{}")
        refused(world, "amw_app", "SELECT amw_approval_settle(%s)", (approval,))
        _set_marks(world, job, original)
        assert world.dry.decision(job.task_input(), job.ctx()) is not None
    assert state_of(world, approval)[0] == "APPROVED"


@pytest.mark.parametrize("role", ["amw_app", "amw_publisher"])
@pytest.mark.parametrize(
    "assignment",
    [
        "state = 'EXPIRED'",
        "decided_at = now()",
        "current_step = current_step + 1",
        "managed_service = NOT managed_service",
    ],
)
def test_a_pending_approval_keeps_state_step_and_service_flag(
    world: World, role: str, assignment: str
) -> None:
    _, approval = opened(world)
    refused(world, role, f"UPDATE approvals SET {assignment} WHERE id = %s", (approval,))  # noqa: S608
    assert state_of(world, approval)[0] == "PENDING"


def test_the_task_pointer_needs_an_approval_of_the_same_job(world: World) -> None:
    free = world.job()
    task = ids.TASK.to_uuid(free.task)
    _, other = opened(world)
    with world.admin.transaction():  # an approval without a job (the schema allows NULL)
        orphan = world.admin.execute(
            "INSERT INTO approvals (id, org_id, kind, subject_kind, subject_id, state,"
            " workflow_key, current_step, managed_service, requested_by, review_code)"
            " SELECT gen_random_uuid(), org_id, kind, subject_kind, gen_random_uuid(), 'PENDING',"
            " workflow_key, 1, managed_service, requested_by, 'ZZ99'"
            " FROM approvals WHERE id = %s RETURNING id",
            (other,),
        ).fetchone()
    assert orphan is not None
    for target in (orphan[0], other):
        refused(
            world,
            "amw_app",
            "UPDATE tasks SET approval_id = %s WHERE id = %s",
            (target, task),
        )


def test_definer_roles_cannot_create_objects_in_public(world: World) -> None:
    for role in ("amw_verifier_fn", "amw_owner", "amw_sysfn"):
        got = world.admin.execute(
            "SELECT has_schema_privilege(%s, 'public', 'CREATE')", (role,)
        ).fetchone()
        assert got == (False,), role
