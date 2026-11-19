"""R14 write path of ``channels.audience_kind`` (CCR-114, migration 0056; 04 sections 5.1, 3.6a).

The column changes only inside ``amw_human_record_apply`` when the confirmed, MAC-valid decision
of the final step of a ``NEW_CHANNEL`` approval is ``APPROVED``; the value comes from the subject
document bound by ``subject_sha256``. Every other write is refused by the trigger.
"""

import hashlib
import json
import uuid
from typing import Any

import psycopg
import pytest

from amw_core.ids import new_uuid7
from tests.pg_fixtures import Tenant, insert_job, insert_user
from tests.tenancy.test_owner_evidence_db import (
    World,
    _confirmed,
    as_role,
    mac_key,  # noqa: F401 - module fixture that loads the test MAC key
)

pytestmark = [pytest.mark.tenancy, pytest.mark.security]
Conn = psycopg.Connection[tuple[Any, ...]]


def subject_document(channel: uuid.UUID, audience: str) -> bytes:
    """Canonical JSON (03 section 9.1: sorted keys, no insignificant whitespace, UTF-8)."""
    material = {"channel_id": f"chn_{channel}", "audience_kind": audience}
    return json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")


def insert_channel(admin: Conn, tenant: Tenant) -> uuid.UUID:
    channel = new_uuid7()
    admin.execute(
        "INSERT INTO channels (id, org_id, workspace_id, platform, title, language, category,"
        " status) VALUES (%s, %s, %s, 'YOUTUBE', 'c', 'en', 'finance', 'DRAFT')",
        (channel, tenant.org_uuid, tenant.workspace_uuid),
    )
    return channel


def new_channel_world(
    admin: Conn,
    tenant: Tenant,
    channel: uuid.UUID,
    *,
    audience: str = "KIDS",
    steps: int = 1,
    document: bytes | None = None,
    subject_kind: str = "channel",
    kind: str = "NEW_CHANNEL",
) -> World:
    owner = insert_user(admin, tenant)
    job = insert_job(admin, tenant)
    approval = new_uuid7()
    sha = hashlib.sha256(document or subject_document(channel, audience)).digest()
    admin.execute(
        "INSERT INTO approvals (id, org_id, job_id, kind, subject_kind, subject_id, subject_sha256,"
        " state, workflow_key, current_step, managed_service, requested_by, review_code)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', 'owner_one_tap', 1, false,"
        " 'svc_s07', %s)",
        (approval, tenant.org_uuid, job, kind, subject_kind, channel, sha, approval.hex[-6:]),
    )
    for step in range(1, steps + 1):
        admin.execute(
            "INSERT INTO approval_steps (id, org_id, approval_id, step_no, required_role, state)"
            " VALUES (%s, %s, %s, %s, 'REVIEWER_APPROVER', 'PENDING')",
            (new_uuid7(), tenant.org_uuid, approval, step),
        )
    return World(tenant, owner, job, approval, sha)


def confirm_decision(
    admin: Conn,
    w: World,
    channel: uuid.UUID,
    decision: str = "APPROVED",
    *,
    step: int = 1,
    **overrides: Any,
) -> uuid.UUID:
    """A CONFIRMED, MAC-valid owner decision naming the channel and the approval's review code."""
    extra: dict[str, Any] = {
        "subject_kind": "channel",
        "subject_id": channel,
        "review_code": w.approval.hex[-6:],
        "step_no": step,
        **overrides,
    }
    return _confirmed(admin, w, decision=decision, extra=extra)


def apply(admin: Conn, w: World, ev: uuid.UUID) -> None:
    with as_role(admin, "amw_operator", w.tenant) as c:
        c.execute("SELECT amw_human_record_apply(%s)", (ev,))


def decide(
    admin: Conn, w: World, channel: uuid.UUID, decision: str = "APPROVED", *, step: int = 1
) -> None:
    apply(admin, w, confirm_decision(admin, w, channel, decision, step=step))


def audience_of(admin: Conn, channel: uuid.UUID) -> str | None:
    row = admin.execute("SELECT audience_kind FROM channels WHERE id = %s", (channel,)).fetchone()
    assert row is not None
    return None if row[0] is None else str(row[0])


def step_state(admin: Conn, w: World) -> str:
    row = admin.execute(
        "SELECT state FROM approval_steps WHERE approval_id = %s AND step_no = 1", (w.approval,)
    ).fetchone()
    assert row is not None
    return str(row[0])


@pytest.mark.parametrize("audience", ["GENERAL", "KIDS"])
def test_approved_final_step_sets_audience_kind(
    admin: Conn, tenant_a: Tenant, audience: str
) -> None:
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, audience=audience)
    decide(admin, w, channel)
    assert audience_of(admin, channel) == audience
    assert step_state(admin, w) == "APPROVED"


@pytest.mark.parametrize("decision", ["REJECTED", "CHANGES_REQUESTED"])
def test_other_decisions_leave_it_unset(admin: Conn, tenant_a: Tenant, decision: str) -> None:
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel)
    decide(admin, w, channel, decision)
    assert audience_of(admin, channel) is None
    assert step_state(admin, w) == decision


def test_approved_non_final_step_leaves_it_unset(admin: Conn, tenant_a: Tenant) -> None:
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, steps=2)
    decide(admin, w, channel)
    assert audience_of(admin, channel) is None
    assert step_state(admin, w) == "APPROVED"


@pytest.mark.parametrize(
    ("document", "subject_kind"),
    [
        (b'{"audience_kind":"ADULTS","channel_id":"chn_x"}', "channel"),  # not a known value
        (b'{"channel_id":"chn_x","audience_kind":"KIDS"}', "channel"),  # not canonical
        (None, "render"),  # not a channel subject
    ],
)
def test_unverifiable_subject_document_refuses_the_whole_decision(
    admin: Conn, tenant_a: Tenant, document: bytes | None, subject_kind: str
) -> None:
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, document=document, subject_kind=subject_kind)
    with pytest.raises(psycopg.Error) as err:
        decide(admin, w, channel)
    assert err.value.sqlstate == "AMW02"
    assert audience_of(admin, channel) is None
    assert step_state(admin, w) == "PENDING"  # same transaction: nothing was applied


def test_document_of_another_channel_is_refused(admin: Conn, tenant_a: Tenant) -> None:
    channel, other = insert_channel(admin, tenant_a), insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, document=subject_document(other, "KIDS"))
    with pytest.raises(psycopg.Error) as err:
        decide(admin, w, channel)
    assert err.value.sqlstate == "AMW02"
    assert audience_of(admin, channel) is None
    assert audience_of(admin, other) is None


def test_foreign_tenant_channel_is_never_set(
    admin: Conn, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Tenant A's approval names tenant B's channel: the update finds no row in A (org filter and
    RLS), the decision is refused and B's channel is untouched."""
    foreign = insert_channel(admin, tenant_b)
    w = new_channel_world(admin, tenant_a, foreign)
    with pytest.raises(psycopg.Error) as err:
        decide(admin, w, foreign)
    assert err.value.sqlstate == "AMW03"
    assert audience_of(admin, foreign) is None
    assert step_state(admin, w) == "PENDING"


@pytest.mark.parametrize("role", ["amw_app", "amw_publisher", "amw_operator", "amw_verifier"])
def test_no_role_writes_the_column_directly(admin: Conn, tenant_a: Tenant, role: str) -> None:
    channel = insert_channel(admin, tenant_a)
    with pytest.raises(psycopg.Error), as_role(admin, role, tenant_a) as c:
        c.execute("UPDATE channels SET audience_kind = 'GENERAL' WHERE id = %s", (channel,))
    assert audience_of(admin, channel) is None


def test_trigger_refuses_even_the_table_owner_and_inserts(admin: Conn, tenant_a: Tenant) -> None:
    channel = insert_channel(admin, tenant_a)
    with pytest.raises(psycopg.Error) as err:
        admin.execute("UPDATE channels SET audience_kind = 'KIDS' WHERE id = %s", (channel,))
    assert err.value.sqlstate == "AMW02"
    with pytest.raises(psycopg.Error) as err:
        admin.execute(
            "INSERT INTO channels (id, org_id, workspace_id, platform, title, language, category,"
            " status, audience_kind) VALUES (%s, %s, %s, 'YOUTUBE', 'c', 'en', 'finance',"
            " 'DRAFT', 'KIDS')",
            (new_uuid7(), tenant_a.org_uuid, tenant_a.workspace_uuid),
        )
    assert err.value.sqlstate == "AMW02"


def test_other_channel_columns_stay_writable(admin: Conn, tenant_a: Tenant) -> None:
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel)
    decide(admin, w, channel)
    with as_role(admin, "amw_app", tenant_a) as c:
        c.execute("UPDATE channels SET title = 'renamed' WHERE id = %s", (channel,))
    assert audience_of(admin, channel) == "KIDS"


def test_function_keeps_owner_grants_and_definer_hygiene(admin: Conn) -> None:
    row = admin.execute(
        "SELECT r.rolname, p.prosecdef, p.proconfig,"
        " has_function_privilege('public', p.oid, 'EXECUTE'),"
        " has_function_privilege('amw_operator', p.oid, 'EXECUTE'),"
        " has_function_privilege('amw_app', p.oid, 'EXECUTE')"
        " FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner"
        " WHERE p.proname = 'amw_human_record_apply'"
    ).fetchall()
    assert len(row) == 1
    owner, definer, config, public, operator, app = row[0]
    assert (owner, definer, public, operator, app) == ("amw_verifier_fn", True, False, True, False)
    assert config == ["search_path=pg_catalog, public, pg_temp"]


# ---------------------------------------------------------------------------------------------
# Review fixes of PR #58 (B1, B2, M1; PROPOSED CCR-190): what the owner decided cannot be
# relabelled, repointed, re-hashed or re-numbered after creation, by any role.
# ---------------------------------------------------------------------------------------------
ROLES = [
    "amw_app",
    "amw_publisher",
    "amw_operator",
    "amw_verifier",
    "amw_readonly",
    "amw_auth",
    "amw_owner",
    "amw_migrator",
    "superuser",
]
ACTORS = [None, "sys_operator", "amw_verifier_fn", "usr_00000000-0000-0000-0000-000000000000"]


def attempt(
    admin: Conn, role: str, tenant: Tenant, actor: str | None, query: str, params: tuple[Any, ...]
) -> str:
    """Run one write as ``role`` (session and current user; ``superuser`` = the test login) with
    or without ``app.actor``; return the SQLSTATE, or ``ok:<rowcount>`` when it went through."""
    try:
        with admin.transaction():
            if role != "superuser":
                admin.execute(
                    psycopg.sql.SQL("SET LOCAL SESSION AUTHORIZATION {}").format(
                        psycopg.sql.Identifier(role)
                    )
                )
            admin.execute("SELECT set_config('app.org_id', %s, true)", (str(tenant.org_uuid),))
            if actor is not None:
                admin.execute("SELECT set_config('app.actor', %s, true)", (actor,))
            cur = admin.execute(query, params)
            return f"ok:{cur.rowcount}"
    except psycopg.Error as exc:
        return str(exc.sqlstate)


def can_write(admin: Conn, role: str, table: str, privilege: str = "UPDATE") -> bool:
    if role == "superuser":
        return True
    row = admin.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, privilege))
    found = row.fetchone()
    assert found is not None
    return bool(found[0])


def assert_refused(admin: Conn, role: str, table: str, outcome: str, privilege: str) -> None:
    if can_write(admin, role, table, privilege):
        assert outcome == "AMW02", outcome  # the freeze trigger, not a missing privilege
    else:
        assert outcome in {"AMW02", "42501", "ok:0"}, outcome


def approval_row(admin: Conn, w: World) -> tuple[Any, ...]:
    row = admin.execute(
        "SELECT kind, subject_kind, subject_id, subject_sha256, org_id, review_code, job_id,"
        " requested_by, created_at FROM approvals WHERE id = %s",
        (w.approval,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def steps_of(admin: Conn, w: World) -> list[tuple[Any, ...]]:
    rows = admin.execute(
        "SELECT id, step_no, approval_id, state, decided_by, evidence_id FROM approval_steps"
        " WHERE approval_id = %s ORDER BY id",
        (w.approval,),
    )
    return [tuple(r) for r in rows.fetchall()]


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("role", ROLES)
def test_approval_identity_is_frozen_for_every_role(
    admin: Conn, tenant_a: Tenant, role: str, actor: str | None
) -> None:
    """B1 / B2: relabel the kind, repoint the subject, flip subject_sha256 to the KIDS document,
    rewrite the review code: refused for every role, whatever app.actor says."""
    channel, other = insert_channel(admin, tenant_a), insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, audience="GENERAL")
    before = approval_row(admin, w)
    kids = hashlib.sha256(subject_document(channel, "KIDS")).digest()
    for query, params in [
        ("UPDATE approvals SET kind = 'SCRIPT' WHERE id = %s", (w.approval,)),
        ("UPDATE approvals SET subject_kind = 'render' WHERE id = %s", (w.approval,)),
        ("UPDATE approvals SET subject_id = %s WHERE id = %s", (other, w.approval)),
        ("UPDATE approvals SET subject_sha256 = %s WHERE id = %s", (kids, w.approval)),
        ("UPDATE approvals SET review_code = 'ZZ99' WHERE id = %s", (w.approval,)),
        ("UPDATE approvals SET requested_by = 'svc_x' WHERE id = %s", (w.approval,)),
        ("DELETE FROM approvals WHERE id = %s", (w.approval,)),
    ]:
        outcome = attempt(admin, role, tenant_a, actor, query, params)
        privilege = "DELETE" if query.startswith("DELETE") else "UPDATE"
        assert_refused(admin, role, "approvals", outcome, privilege)
    assert approval_row(admin, w) == before


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("role", ROLES)
def test_step_identity_is_frozen_for_every_role(
    admin: Conn, tenant_a: Tenant, role: str, actor: str | None
) -> None:
    """M1: renumber an undecided step, move it to another approval, delete it: refused."""
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, steps=2)
    v = new_channel_world(admin, tenant_a, insert_channel(admin, tenant_a))
    before = steps_of(admin, w)
    for query, params in [
        (
            "UPDATE approval_steps SET step_no = 0 WHERE approval_id = %s AND step_no = 2",
            (w.approval,),
        ),
        (
            "UPDATE approval_steps SET approval_id = %s WHERE approval_id = %s AND step_no = 2",
            (v.approval, w.approval),
        ),
        ("DELETE FROM approval_steps WHERE approval_id = %s AND step_no = 2", (w.approval,)),
    ]:
        outcome = attempt(admin, role, tenant_a, actor, query, params)
        privilege = "DELETE" if query.startswith("DELETE") else "UPDATE"
        assert_refused(admin, role, "approval_steps", outcome, privilege)
    assert steps_of(admin, w) == before


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("role", ROLES)
def test_no_step_is_added_or_rewritten_after_a_decision(
    admin: Conn, tenant_a: Tenant, role: str, actor: str | None
) -> None:
    """M1: once step 1 is decided the step set is fixed (no new last step) and the decided step's
    decision columns stay as written."""
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, steps=2)
    decide(admin, w, channel)
    before = steps_of(admin, w)
    for query, params, privilege in [
        (
            "INSERT INTO approval_steps (id, org_id, approval_id, step_no, required_role, state)"
            " VALUES (%s, %s, %s, 3, 'REVIEWER_APPROVER', 'PENDING')",
            (new_uuid7(), tenant_a.org_uuid, w.approval),
            "INSERT",
        ),
        (
            "UPDATE approval_steps SET state = 'REJECTED' WHERE approval_id = %s AND step_no = 1",
            (w.approval,),
            "UPDATE",
        ),
        (
            "UPDATE approval_steps SET required_role = 'VIEWER' WHERE approval_id = %s"
            " AND step_no = 1",
            (w.approval,),
            "UPDATE",
        ),
    ]:
        outcome = attempt(admin, role, tenant_a, actor, query, params)
        assert_refused(admin, role, "approval_steps", outcome, privilege)
    assert steps_of(admin, w) == before


def test_relabelled_script_approval_never_sets_the_channel(admin: Conn, tenant_a: Tenant) -> None:
    """Reviewer probe kind_swap: the owner approves an unrelated SCRIPT approval; amw_app tries to
    turn it into a NEW_CHANNEL approval of a channel; refused, and the apply sets nothing."""
    channel, script = insert_channel(admin, tenant_a), new_uuid7()
    w = new_channel_world(
        admin, tenant_a, script, kind="SCRIPT", subject_kind="script", document=b"script v1"
    )
    ev = confirm_decision(admin, w, script, subject_kind="script")
    kids = hashlib.sha256(subject_document(channel, "KIDS")).digest()
    outcome = attempt(
        admin,
        "amw_app",
        tenant_a,
        "svc_s07",
        "UPDATE approvals SET kind = 'NEW_CHANNEL', subject_kind = 'channel', subject_id = %s,"
        " subject_sha256 = %s WHERE id = %s",
        (channel, kids, w.approval),
    )
    assert outcome == "AMW02"
    apply(admin, w, ev)  # the SCRIPT decision itself is recorded
    assert audience_of(admin, channel) is None


def test_flipped_subject_hash_cannot_change_the_value(admin: Conn, tenant_a: Tenant) -> None:
    """Reviewer probe value_flip: the owner confirms GENERAL; amw_app tries the KIDS hash."""
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, audience="GENERAL")
    ev = confirm_decision(admin, w, channel)
    kids = hashlib.sha256(subject_document(channel, "KIDS")).digest()
    outcome = attempt(
        admin,
        "amw_app",
        tenant_a,
        "svc_s07",
        "UPDATE approvals SET subject_sha256 = %s WHERE id = %s",
        (kids, w.approval),
    )
    assert outcome == "AMW02"
    apply(admin, w, ev)
    assert audience_of(admin, channel) == "GENERAL"


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject_kind": "render"},  # evidence about another kind of subject
        {"subject_id": "other-channel"},  # evidence about another channel
        {"review_code": "ZZ99"},  # the owner quoted another approval's code
        {"review_code": None},
    ],
)
def test_evidence_must_name_the_approval_subject(
    admin: Conn, tenant_a: Tenant, overrides: dict[str, Any]
) -> None:
    """B1: the MAC-bound evidence subject and review code must be the approval's."""
    channel, other = insert_channel(admin, tenant_a), insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel)
    if overrides.get("subject_id") == "other-channel":
        overrides = {"subject_id": other}
    ev = confirm_decision(admin, w, channel, **overrides)
    with pytest.raises(psycopg.Error) as err:
        apply(admin, w, ev)
    assert err.value.sqlstate == "AMW02"
    assert audience_of(admin, channel) is None
    assert audience_of(admin, other) is None
    assert step_state(admin, w) == "PENDING"


def test_skipping_an_earlier_step_refuses_the_final_decision(admin: Conn, tenant_a: Tenant) -> None:
    """Reviewer probe skip_step1: current_step is app-writable; the final step applies only when
    every other step was APPROVED from evidence."""
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, steps=2)
    outcome = attempt(
        admin,
        "amw_app",
        tenant_a,
        "svc_s07",
        "UPDATE approvals SET current_step = 2 WHERE id = %s",
        (w.approval,),
    )
    assert outcome == "ok:1"  # workflow progress stays the app's (03 section 11.6)
    ev = confirm_decision(admin, w, channel, step=2)
    with pytest.raises(psycopg.Error) as err:
        apply(admin, w, ev)
    assert err.value.sqlstate == "AMW02"
    assert audience_of(admin, channel) is None
    assert step_state(admin, w) == "PENDING"


def test_two_step_approval_sets_the_value_after_both_owner_decisions(
    admin: Conn, tenant_a: Tenant
) -> None:
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel, steps=2)
    decide(admin, w, channel)
    admin.execute("UPDATE approvals SET current_step = 2 WHERE id = %s", (w.approval,))
    decide(admin, w, channel, step=2)
    assert audience_of(admin, channel) == "KIDS"


def test_freeze_triggers_are_owned_invoker_functions(admin: Conn) -> None:
    rows = admin.execute(
        "SELECT p.proname, r.rolname, p.prosecdef, p.proconfig,"
        " has_function_privilege('public', p.oid, 'EXECUTE')"
        " FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner"
        " WHERE p.proname IN ('amw_approval_identity_frozen', 'amw_approval_step_frozen')"
        " ORDER BY 1"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        (name, "amw_owner", False, ["search_path=pg_catalog, public, pg_temp"], False)
        for name in ("amw_approval_identity_frozen", "amw_approval_step_frozen")
    ]
    member = admin.execute(
        "SELECT m.set_option, m.inherit_option FROM pg_auth_members m"
        " JOIN pg_roles g ON g.oid = m.roleid JOIN pg_roles u ON u.oid = m.member"
        " WHERE g.rolname = 'amw_verifier_fn' AND u.rolname = 'amw_owner'"
    ).fetchall()
    assert [tuple(r) for r in member] == [(False, False)]


def run_at_level(
    admin: Conn, level: str, role: str, tenant: Tenant, query: str, params: tuple[Any, ...]
) -> None:
    """One transaction at isolation ``level`` whose session and current user are ``role``."""
    with admin.transaction():
        admin.execute(psycopg.sql.SQL("SET TRANSACTION ISOLATION LEVEL " + level))
        admin.execute(
            psycopg.sql.SQL("SET LOCAL SESSION AUTHORIZATION {}").format(
                psycopg.sql.Identifier(role)
            )
        )
        admin.execute("SELECT set_config('app.org_id', %s, true)", (str(tenant.org_uuid),))
        admin.execute("SELECT set_config('app.actor', 'sys_operator', true)")
        admin.execute(query, params)


@pytest.mark.parametrize("level", ["REPEATABLE READ", "SERIALIZABLE"])
def test_apply_and_step_insert_refuse_a_snapshot_isolation_level(
    admin: Conn, tenant_a: Tenant, level: str
) -> None:
    """Review m2: the advisory lock orders the apply and a new step only under READ COMMITTED;
    an older snapshot could miss a committed step 2 and treat step 1 as final."""
    channel = insert_channel(admin, tenant_a)
    w = new_channel_world(admin, tenant_a, channel)
    ev = confirm_decision(admin, w, channel)
    for role, query, params in [
        ("amw_operator", "SELECT amw_human_record_apply(%s)", (ev,)),
        (
            "amw_app",
            "INSERT INTO approval_steps (id, org_id, approval_id, step_no, required_role, state)"
            " VALUES (%s, %s, %s, 2, 'REVIEWER_APPROVER', 'PENDING')",
            (new_uuid7(), tenant_a.org_uuid, w.approval),
        ),
    ]:
        with pytest.raises(psycopg.Error) as err:
            run_at_level(admin, level, role, tenant_a, query, params)
        assert err.value.sqlstate == "AMW02"
    assert audience_of(admin, channel) is None
    assert step_state(admin, w) == "PENDING"
    apply(admin, w, ev)  # READ COMMITTED (the default) still applies
    assert audience_of(admin, channel) == "KIDS"
