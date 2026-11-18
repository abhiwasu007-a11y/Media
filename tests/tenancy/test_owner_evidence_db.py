"""Database-level provenance of owner evidence (CCR-100; 04 sections 3.1, 3.6a, 5.16).

Identity is the database role: the tests switch with ``SET LOCAL SESSION AUTHORIZATION`` so that
``session_user`` really is ``amw_operator`` / ``amw_verifier`` / ``amw_app``. ``app.actor`` is set
to ``sys_operator`` in the forgery cases to prove it is ignored.
"""

import hashlib
import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from amw_core.errors import InputInvalidError
from amw_core.ids import new_uuid7
from amw_core.tenancy.evidence_keys import install_evidence_mac_key
from tests.pg_fixtures import Tenant, insert_job, insert_user

pytestmark = [pytest.mark.tenancy, pytest.mark.security]
Conn = psycopg.Connection[tuple[Any, ...]]
DENIED = psycopg.Error


@pytest.fixture(scope="module", autouse=True)
def mac_key(pg_dsn: str) -> None:
    """A test-time key (never a literal; the real one comes from the secret mechanism)."""
    with psycopg.connect(pg_dsn) as conn:
        loaded = conn.execute("SELECT count(*) FROM evidence_mac_keys").fetchone()
    if loaded == (0,):
        install_evidence_mac_key(pg_dsn, 1, os.urandom(32))


@contextmanager
def as_role(conn: Conn, role: str, tenant: Tenant, actor: str = "sys_operator") -> Iterator[Conn]:
    """One transaction whose session_user and current_user are ``role``."""
    with conn.transaction():
        conn.execute(
            psycopg.sql.SQL("SET LOCAL SESSION AUTHORIZATION {}").format(
                psycopg.sql.Identifier(role)
            )
        )
        conn.execute("SELECT set_config('app.org_id', %s, true)", (str(tenant.org_uuid),))
        conn.execute("SELECT set_config('app.actor', %s, true)", (actor,))
        yield conn


@dataclass
class World:
    tenant: Tenant
    owner: uuid.UUID
    job: uuid.UUID
    approval: uuid.UUID
    subject_sha: bytes


def _world(admin: Conn, tenant: Tenant, kind: str = "FINAL_VIDEO") -> World:
    owner = insert_user(admin, tenant)
    job = insert_job(admin, tenant)
    approval = new_uuid7()
    sha = hashlib.sha256(approval.bytes).digest()
    admin.execute(
        "INSERT INTO approvals (id, org_id, job_id, kind, subject_kind, subject_id, subject_sha256,"
        " state, workflow_key, current_step, managed_service, requested_by, review_code)"
        " VALUES (%s, %s, %s, %s, 'render', %s, %s, 'PENDING', 'owner_one_tap', 1, false,"
        " 'svc_s07', %s)",
        (approval, tenant.org_uuid, job, kind, approval, sha, approval.hex[-6:]),
    )
    admin.execute(
        "INSERT INTO approval_steps (id, org_id, approval_id, step_no, required_role, state)"
        " VALUES (%s, %s, %s, 1, 'REVIEWER_APPROVER', 'PENDING')",
        (new_uuid7(), tenant.org_uuid, approval),
    )
    return World(tenant, owner, job, approval, sha)


@pytest.fixture
def world(admin: Conn, tenant_a: Tenant) -> World:
    return _world(admin, tenant_a)


def _insert_evidence(
    conn: Conn,
    w: World,
    *,
    kind: str = "STEP_DECISION",
    decision: str | None = "APPROVED",
    state: str = "PENDING_VERIFICATION",
    scores: dict[str, int] | None = None,
    quote: str = "R7K2 approve",
    extra: dict[str, Any] | None = None,
) -> uuid.UUID:
    ev = new_uuid7()
    cols: dict[str, Any] = {
        "id": ev,
        "org_id": w.tenant.org_uuid,
        "job_id": w.job,
        "approval_id": w.approval,
        "step_no": 1,
        "record_kind": kind,
        "subject_kind": "render",
        "subject_id": w.approval,
        "parsed_decision": decision,
        "claimed_scores": json.dumps(scores) if scores else None,
        "source_kind": "OWNER_CHAT_MESSAGE",
        "session_id": "ses-1",
        "event_uuid": str(uuid.uuid4()),
        "quote": quote,
        "message_at": datetime.now(UTC) - timedelta(minutes=5),
        "state": state,
        "recorded_by": "sys_operator",
        "on_behalf_of": w.owner,
        "evidence_sha256": hashlib.sha256(ev.bytes).digest(),
        "refused_reason": "refused" if state == "REFUSED" else None,
        **(extra or {}),
    }
    names = psycopg.sql.SQL(", ").join(map(psycopg.sql.Identifier, cols))
    marks = psycopg.sql.SQL(", ").join(psycopg.sql.Placeholder() * len(cols))
    conn.execute(
        psycopg.sql.SQL("INSERT INTO owner_instruction_evidence ({}) VALUES ({})").format(
            names, marks
        ),
        list(cols.values()),
    )
    return ev


def _verify(conn: Conn, w: World, ev: uuid.UUID) -> None:
    with as_role(conn, "amw_verifier", w.tenant) as c:
        c.execute("SELECT amw_evidence_mark_verified(%s, %s)", (ev, json.dumps({"A1": True})))


def _confirm(conn: Conn, w: World, ev: uuid.UUID) -> None:
    with as_role(conn, "amw_verifier", w.tenant) as c:
        c.execute(
            "SELECT amw_evidence_mark_confirmed(%s, %s, 'yes', %s, %s)",
            (ev, str(uuid.uuid4()), datetime.now(UTC), json.dumps({"C1": True})),
        )


def _confirmed(conn: Conn, w: World, **kw: Any) -> uuid.UUID:
    with as_role(conn, "amw_operator", w.tenant) as c:
        ev = _insert_evidence(c, w, **kw)
    _verify(conn, w, ev)
    _confirm(conn, w, ev)
    return ev


def _mac_valid(conn: Conn, w: World, ev: uuid.UUID, role: str = "amw_app") -> bool:
    with as_role(conn, role, w.tenant) as c:
        row = c.execute("SELECT amw_evidence_mac_valid(%s)", (ev,)).fetchone()
    assert row is not None
    return bool(row[0])


def _state(admin: Conn, ev: uuid.UUID) -> str:
    row = admin.execute("SELECT state FROM owner_instruction_evidence WHERE id = %s", (ev,))
    found = row.fetchone()
    assert found is not None
    return str(found[0])


# --- creation ---------------------------------------------------------------------------------
def test_operator_creates_pending_evidence(admin: Conn, world: World) -> None:
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world)
    assert _state(admin, ev) == "PENDING_VERIFICATION"
    assert not _mac_valid(admin, world, ev)


def test_recorded_by_is_derived_from_the_login_role(admin: Conn, world: World) -> None:
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world, extra={"recorded_by": "usr_someone_else"})
    assert admin.execute(
        "SELECT recorded_by FROM owner_instruction_evidence WHERE id = %s", (ev,)
    ).fetchone() == ("sys_operator",)
    mac_input = admin.execute(
        "SELECT convert_from(amw_evidence_mac_input(e), 'UTF8')::jsonb->>'recorded_by'"
        " FROM owner_instruction_evidence e WHERE id = %s",
        (ev,),
    ).fetchone()
    assert mac_input == ("sys_operator",)


def test_operator_may_store_a_refused_attempt(admin: Conn, world: World) -> None:
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world, state="REFUSED")
    assert _state(admin, ev) == "REFUSED"


@pytest.mark.parametrize("state", ["VERIFIED", "CONFIRMED"])
@pytest.mark.parametrize("role", ["amw_operator", "amw_app", "amw_verifier"])
def test_nobody_inserts_verified_or_confirmed(
    admin: Conn, world: World, role: str, state: str
) -> None:
    extra = {
        "evidence_mac": os.urandom(32),
        "mac_key_version": 1,
        "event_verified_at": datetime.now(UTC),
        "confirmation_event_uuid": str(uuid.uuid4()),
        "confirmation_quote": "yes",
        "confirmation_message_at": datetime.now(UTC),
    }
    with pytest.raises(DENIED), as_role(admin, role, world.tenant) as c:
        _insert_evidence(c, world, state=state, extra=extra)


def test_pending_insert_with_verification_fields_is_refused(admin: Conn, world: World) -> None:
    with (
        pytest.raises(psycopg.DatabaseError),
        as_role(admin, "amw_operator", world.tenant) as c,
    ):
        _insert_evidence(c, world, extra={"evidence_mac": os.urandom(32), "mac_key_version": 1})


@pytest.mark.parametrize("role", ["amw_app", "amw_publisher", "amw_verifier", "amw_readonly"])
def test_other_roles_cannot_insert_evidence(admin: Conn, world: World, role: str) -> None:
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_role(admin, role, world.tenant) as c,
    ):
        _insert_evidence(c, world)


# --- verification -----------------------------------------------------------------------------
def test_verifier_moves_evidence_forward_and_stamps_the_mac(admin: Conn, world: World) -> None:
    ev = _confirmed(admin, world)
    assert _state(admin, ev) == "CONFIRMED"
    for role in ("amw_app", "amw_operator", "amw_verifier", "amw_publisher"):
        assert _mac_valid(admin, world, ev, role)


@pytest.mark.parametrize("role", ["amw_operator", "amw_app", "amw_verifier"])
def test_no_role_updates_or_deletes_evidence(admin: Conn, world: World, role: str) -> None:
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_role(admin, role, world.tenant) as c,
    ):
        c.execute("UPDATE owner_instruction_evidence SET state = 'VERIFIED' WHERE id = %s", (ev,))
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_role(admin, role, world.tenant) as c,
    ):
        c.execute("DELETE FROM owner_instruction_evidence WHERE id = %s", (ev,))


def test_even_the_superuser_cannot_update_outside_the_functions(admin: Conn, world: World) -> None:
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world)
    with pytest.raises(psycopg.DatabaseError, match="verifier functions"):
        admin.execute(
            "UPDATE owner_instruction_evidence SET quote = 'changed' WHERE id = %s", (ev,)
        )


@pytest.mark.parametrize("role", ["amw_operator", "amw_app"])
def test_only_the_verifier_runs_the_verifier_functions(
    admin: Conn, world: World, role: str
) -> None:
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_role(admin, role, world.tenant) as c,
    ):
        c.execute("SELECT amw_evidence_mark_verified(%s, '{}')", (ev,))


def test_verifier_function_checks_the_login_not_the_role(admin: Conn, world: World) -> None:
    """SET ROLE amw_verifier from another login keeps session_user: refused."""
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world)
    with admin.transaction():
        admin.execute("SET LOCAL ROLE amw_verifier")
        admin.execute("SELECT set_config('app.org_id', %s, true)", (str(world.tenant.org_uuid),))
        with pytest.raises(psycopg.DatabaseError, match="verifier login"):
            admin.execute("SELECT amw_evidence_mark_verified(%s, '{}')", (ev,))


def test_confirm_needs_verified_and_refuse_is_final(admin: Conn, world: World) -> None:
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world)
    with pytest.raises(psycopg.DatabaseError, match="not VERIFIED"):
        _confirm(admin, world, ev)
    with as_role(admin, "amw_verifier", world.tenant) as c:
        c.execute("SELECT amw_evidence_refuse(%s, 'ambiguous', NULL)", (ev,))
    assert _state(admin, ev) == "REFUSED"
    with pytest.raises(psycopg.DatabaseError):
        _verify(admin, world, ev)


def test_forged_mac_is_detected_and_blocks_use(admin: Conn, world: World) -> None:
    ev = _confirmed(admin, world)
    with admin.transaction():
        admin.execute("SET LOCAL session_replication_role = replica")  # bypass triggers
        admin.execute(
            "UPDATE owner_instruction_evidence SET evidence_mac = %s WHERE id = %s",
            (os.urandom(32), ev),
        )
    assert not _mac_valid(admin, world, ev)
    with (
        pytest.raises(psycopg.DatabaseError, match="valid MAC"),
        as_role(admin, "amw_operator", world.tenant) as c,
    ):
        c.execute("SELECT amw_human_record_apply(%s)", (ev,))


def test_tampered_content_invalidates_the_mac(admin: Conn, world: World) -> None:
    ev = _confirmed(admin, world)
    with admin.transaction():
        admin.execute("SET LOCAL session_replication_role = replica")
        admin.execute(
            "UPDATE owner_instruction_evidence SET parsed_decision = 'REJECTED' WHERE id = %s",
            (ev,),
        )
    assert not _mac_valid(admin, world, ev)


def test_key_table_is_unreadable(admin: Conn, world: World) -> None:
    for role in ("amw_app", "amw_operator", "amw_verifier", "amw_publisher", "amw_readonly"):
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            as_role(admin, role, world.tenant) as c,
        ):
            c.execute("SELECT key FROM evidence_mac_keys")


def test_mac_valid_is_tenant_bound(admin: Conn, world: World, tenant_b: Tenant) -> None:
    ev = _confirmed(admin, world)
    other = World(tenant_b, world.owner, world.job, world.approval, world.subject_sha)
    assert not _mac_valid(admin, other, ev)
    with as_role(admin, "amw_operator", tenant_b) as c:
        assert c.execute("SELECT count(*) FROM owner_instruction_evidence").fetchone() == (0,)


def test_one_message_backs_one_live_record(admin: Conn, world: World) -> None:
    event = str(uuid.uuid4())
    with as_role(admin, "amw_operator", world.tenant) as c:
        _insert_evidence(c, world, extra={"event_uuid": event})
    with (
        pytest.raises(psycopg.errors.UniqueViolation),
        as_role(admin, "amw_operator", world.tenant) as c,
    ):
        _insert_evidence(c, world, extra={"event_uuid": event})


def test_key_install_validates_input(pg_dsn: str) -> None:
    with pytest.raises(InputInvalidError):
        install_evidence_mac_key(pg_dsn, 0, os.urandom(32))
    with pytest.raises(InputInvalidError):
        install_evidence_mac_key(pg_dsn, 9, b"short")


# --- human rows -------------------------------------------------------------------------------
def test_apply_records_the_step_decision(admin: Conn, world: World) -> None:
    ev = _confirmed(admin, world)
    with as_role(admin, "amw_operator", world.tenant) as c:
        c.execute("SELECT amw_human_record_apply(%s)", (ev,))
    row = admin.execute(
        "SELECT state, decided_by, approval_channel, recorded_by, evidence_id FROM approval_steps"
        " WHERE approval_id = %s",
        (world.approval,),
    ).fetchone()
    assert row == ("APPROVED", world.owner, "OWNER_CHAT_OPERATOR", "sys_operator", ev)


def test_apply_needs_the_operator_login(admin: Conn, world: World) -> None:
    ev = _confirmed(admin, world)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        as_role(admin, "amw_app", world.tenant) as c,
    ):
        c.execute("SELECT amw_human_record_apply(%s)", (ev,))


def test_apply_refuses_unconfirmed_evidence(admin: Conn, world: World) -> None:
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world)
    _verify(admin, world, ev)
    with (
        pytest.raises(psycopg.DatabaseError, match="CONFIRMED"),
        as_role(admin, "amw_operator", world.tenant) as c,
    ):
        c.execute("SELECT amw_human_record_apply(%s)", (ev,))


def test_sensitive_claim_step_also_writes_the_human_verdict(admin: Conn, tenant_a: Tenant) -> None:
    w = _world(admin, tenant_a, kind="SENSITIVE_CLAIM")
    ev = _confirmed(admin, w, decision="REJECTED")
    with as_role(admin, "amw_operator", w.tenant) as c:
        c.execute("SELECT amw_human_record_apply(%s)", (ev,))
    row = admin.execute(
        "SELECT verdict, is_final, decided_by FROM compliance_verdicts WHERE evidence_id = %s",
        (ev,),
    ).fetchone()
    assert row == ("BLOCKED", True, f"usr_{w.owner}")


def test_apply_contribution_and_scores(admin: Conn, world: World) -> None:
    quote = "R7K2 add the 2008 crash example to segment two"
    ev = _confirmed(admin, world, kind="CONTRIBUTION", decision=None, quote=quote)
    with as_role(admin, "amw_operator", world.tenant) as c:
        c.execute(
            "SELECT amw_human_record_apply(%s, 'EXAMPLE', %s)",
            (ev, "add the 2008 crash example to segment two"),
        )
    row = admin.execute(
        "SELECT type, contributor_user_id FROM editorial_contributions WHERE evidence_id = %s",
        (ev,),
    ).fetchone()
    assert row == ("EXAMPLE", world.owner)
    scores = {"STORYTELLING": 12, "COMPLIANCE": 5}
    ev3 = _confirmed(
        admin,
        world,
        kind="HUMAN_SCORE",
        decision=None,
        scores=scores,
        quote="R7K2 storytelling 12 compliance 5",
    )
    with as_role(admin, "amw_operator", world.tenant) as c:
        c.execute("SELECT amw_human_record_apply(%s, NULL, NULL, 'r1')", (ev3,))
    rows = admin.execute(
        "SELECT dimension, points FROM quality_scores WHERE evidence_id = %s ORDER BY dimension",
        (ev3,),
    ).fetchall()
    assert [(d, int(p)) for d, p in rows] == [("COMPLIANCE", 5), ("STORYTELLING", 12)]


def test_contribution_description_must_be_quoted(admin: Conn, world: World) -> None:
    ev = _confirmed(admin, world, kind="CONTRIBUTION", decision=None, quote="R7K2 add an example")
    with (
        pytest.raises(psycopg.DatabaseError, match="contribution"),
        as_role(admin, "amw_operator", world.tenant) as c,
    ):
        c.execute("SELECT amw_human_record_apply(%s, 'EXAMPLE', 'something else')", (ev,))


@pytest.mark.parametrize("role", ["amw_app", "amw_operator", "amw_publisher"])
def test_app_actor_spoofing_cannot_write_human_rows(admin: Conn, world: World, role: str) -> None:
    """``app.actor = sys_operator`` (or the owner's usr_ ID) is ignored: the role decides."""
    ev = _confirmed(admin, world)
    for actor in ("sys_operator", f"usr_{world.owner}"):
        with pytest.raises(DENIED), as_role(admin, role, world.tenant, actor) as c:
            c.execute(
                "UPDATE approval_steps SET state = 'APPROVED', decided_by = %s,"
                " approval_channel = 'OWNER_CHAT_OPERATOR', recorded_by = 'sys_operator',"
                " evidence_id = %s WHERE approval_id = %s",
                (world.owner, ev, world.approval),
            )
        with pytest.raises(DENIED), as_role(admin, role, world.tenant, actor) as c:
            c.execute(
                "INSERT INTO editorial_contributions (id, org_id, job_id, approval_id,"
                " contributor_user_id, approval_channel, recorded_by, evidence_id, type,"
                " description) VALUES (%s, %s, %s, %s, %s, 'OWNER_CHAT_OPERATOR',"
                " 'sys_operator', %s, 'EXAMPLE', 'R7K2')",
                (new_uuid7(), world.tenant.org_uuid, world.job, world.approval, world.owner, ev),
            )


def test_app_still_manages_undecided_steps(admin: Conn, world: World) -> None:
    with as_role(admin, "amw_app", world.tenant, "svc_s07") as c:
        c.execute(
            "INSERT INTO approval_steps (id, org_id, approval_id, step_no, required_role, state)"
            " VALUES (%s, %s, %s, 2, 'REVIEWER_APPROVER', 'NOT_STARTED')",
            (new_uuid7(), world.tenant.org_uuid, world.approval),
        )
        c.execute(
            "UPDATE approval_steps SET state = 'PENDING' WHERE approval_id = %s AND step_no = 2",
            (world.approval,),
        )


def test_final_verdict_by_a_machine_is_agent_16_only(admin: Conn, world: World) -> None:
    sql = (
        "INSERT INTO compliance_verdicts (id, org_id, job_id, subject_kind, subject_id,"
        " subject_sha256, verdict, rationale, decided_by, is_final)"
        " VALUES (%s, %s, %s, 'render', %s, %s, 'ALLOWED', 'ok', %s, true)"
    )
    with as_role(admin, "amw_app", world.tenant, "agent_16") as c:
        c.execute(
            sql,
            (
                new_uuid7(),
                world.tenant.org_uuid,
                world.job,
                world.approval,
                world.subject_sha,
                "agent_16",
            ),
        )
    with (
        pytest.raises(psycopg.DatabaseError),
        as_role(admin, "amw_app", world.tenant, "agent_16") as c,
    ):
        c.execute(
            sql,
            (
                new_uuid7(),
                world.tenant.org_uuid,
                world.job,
                world.approval,
                world.subject_sha,
                "agent_05",
            ),
        )
