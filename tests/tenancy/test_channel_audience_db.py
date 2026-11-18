"""R14 write path of ``channels.audience_kind`` (CCR-114, migration 0053; 04 sections 5.1, 3.6a).

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
) -> World:
    owner = insert_user(admin, tenant)
    job = insert_job(admin, tenant)
    approval = new_uuid7()
    sha = hashlib.sha256(document or subject_document(channel, audience)).digest()
    admin.execute(
        "INSERT INTO approvals (id, org_id, job_id, kind, subject_kind, subject_id, subject_sha256,"
        " state, workflow_key, current_step, managed_service, requested_by, review_code)"
        " VALUES (%s, %s, %s, 'NEW_CHANNEL', %s, %s, %s, 'PENDING', 'owner_one_tap', 1, false,"
        " 'svc_s07', %s)",
        (approval, tenant.org_uuid, job, subject_kind, channel, sha, approval.hex[-6:]),
    )
    for step in range(1, steps + 1):
        admin.execute(
            "INSERT INTO approval_steps (id, org_id, approval_id, step_no, required_role, state)"
            " VALUES (%s, %s, %s, %s, 'REVIEWER_APPROVER', 'PENDING')",
            (new_uuid7(), tenant.org_uuid, approval, step),
        )
    return World(tenant, owner, job, approval, sha)


def decide(admin: Conn, w: World, channel: uuid.UUID, decision: str = "APPROVED") -> None:
    ev = _confirmed(
        admin, w, decision=decision, extra={"subject_kind": "channel", "subject_id": channel}
    )
    with as_role(admin, "amw_operator", w.tenant) as c:
        c.execute("SELECT amw_human_record_apply(%s)", (ev,))


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
