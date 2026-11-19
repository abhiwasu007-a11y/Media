"""Own review codes of evidence without an approval in PostgreSQL (CCR-116, migration 0052;
04 section 5.16): required for live approval-less CONTENT / SCORE rows, CCR-090 format in upper
case, unique per org across approval codes and evidence codes (case-insensitive), serialised
between concurrent writers by a transaction advisory lock."""

import uuid
from typing import Any

import psycopg
import pytest

from amw_core.ids import new_uuid7
from tests.pg_fixtures import Tenant
from tests.tenancy.test_owner_evidence_db import World, _insert_evidence, _world, as_role

pytestmark = [pytest.mark.tenancy, pytest.mark.security]
Conn = psycopg.Connection[tuple[Any, ...]]


def _own(conn: Conn, w: World, code: str | None, **kw: Any) -> uuid.UUID:
    """An OWNER_TOPIC evidence row without an approval (inserted as ``amw_operator``)."""
    extra = {"approval_id": None, "step_no": None, "job_id": None, "review_code": code}
    extra |= kw.pop("extra", {})
    with as_role(conn, "amw_operator", w.tenant) as c:
        return _insert_evidence(
            c, w, kind=kw.pop("kind", "OWNER_TOPIC"), decision=None, extra=extra, **kw
        )


def _approval(conn: Conn, w: World, code: str) -> None:
    with as_role(conn, "amw_app", w.tenant) as c:
        approval = new_uuid7()
        c.execute(
            "INSERT INTO approvals (id, org_id, job_id, kind, subject_kind, subject_id, state,"
            " workflow_key, current_step, managed_service, requested_by, review_code)"
            " VALUES (%s, %s, %s, 'FINAL_VIDEO', 'render', %s, 'PENDING', 'owner_one_tap', 1,"
            " false, 'svc_s07', %s)",
            (approval, w.tenant.org_uuid, w.job, approval, code),
        )


def _code(admin: Conn, ev: uuid.UUID) -> str | None:
    row = admin.execute(
        "SELECT review_code FROM owner_instruction_evidence WHERE id = %s", (ev,)
    ).fetchone()
    assert row is not None
    return None if row[0] is None else str(row[0])


@pytest.fixture
def world(admin: Conn, tenant_a: Tenant) -> World:
    return _world(admin, tenant_a)


@pytest.mark.parametrize(
    "kind", ["OWNER_TOPIC", "DATASET_INTAKE", "CONTRIBUTION", "REVISION_NOTE", "HUMAN_SCORE"]
)
def test_live_row_without_approval_needs_its_own_code(admin: Conn, world: World, kind: str) -> None:
    scores = {"RESEARCH_ACCURACY": 18} if kind == "HUMAN_SCORE" else None
    with pytest.raises(psycopg.Error) as err:
        _own(admin, world, None, kind=kind, scores=scores)
    assert err.value.sqlstate == "AMW02"
    ev = _own(admin, world, "Q9Z3", kind=kind, scores=scores)
    assert _code(admin, ev) == "Q9Z3"


def test_refused_row_may_have_no_code(admin: Conn, world: World) -> None:
    assert _code(admin, _own(admin, world, None, state="REFUSED")) is None


@pytest.mark.parametrize("code", ["q9z3", "ABCD", "2345", "Q0Z3", "QIZ3", "Q-Z3", ""])
def test_malformed_own_code_is_refused(admin: Conn, world: World, code: str) -> None:
    with pytest.raises(psycopg.Error) as err:
        _own(admin, world, code)
    assert err.value.sqlstate == "AMW02"


def test_own_code_is_unique_among_evidence_incl_refused(admin: Conn, world: World) -> None:
    _own(admin, world, "Q9Z3")
    for state in ("PENDING_VERIFICATION", "REFUSED"):
        with pytest.raises(psycopg.Error) as err:
            _own(admin, world, "Q9Z3", state=state)
        assert err.value.sqlstate == "AMW02"


def test_own_code_may_not_equal_an_approval_code(admin: Conn, world: World) -> None:
    _approval(admin, world, "q9z3")  # approval codes are matched case-insensitively
    with pytest.raises(psycopg.Error) as err:
        _own(admin, world, "Q9Z3")
    assert err.value.sqlstate == "AMW02"


@pytest.mark.parametrize("code", ["Q9Z3", "q9z3"])
def test_approval_code_may_not_equal_an_own_code(admin: Conn, world: World, code: str) -> None:
    _own(admin, world, "Q9Z3")
    with pytest.raises(psycopg.Error) as err:
        _approval(admin, world, code)
    assert err.value.sqlstate == "AMW02"
    with pytest.raises(psycopg.Error) as err, as_role(admin, "amw_app", world.tenant) as c:
        c.execute("UPDATE approvals SET review_code = %s WHERE id = %s", (code, world.approval))
    assert err.value.sqlstate == "AMW02"


def test_codes_are_per_org(admin: Conn, world: World, tenant_b: Tenant) -> None:
    other = _world(admin, tenant_b)
    _own(admin, world, "Q9Z3")
    _approval(admin, other, "Q8Z3")
    assert _code(admin, _own(admin, other, "Q9Z3")) == "Q9Z3"
    _own(admin, world, "Q8Z3")


def test_approval_bound_evidence_carries_the_approval_code(admin: Conn, world: World) -> None:
    code = admin.execute(
        "SELECT review_code FROM approvals WHERE id = %s", (world.approval,)
    ).fetchone()
    assert code is not None
    with as_role(admin, "amw_operator", world.tenant) as c:
        first = _insert_evidence(c, world, extra={"review_code": code[0]})
    with as_role(admin, "amw_operator", world.tenant) as c:
        second = _insert_evidence(c, world, extra={"review_code": code[0]})
    assert _code(admin, first) == _code(admin, second) == code[0]


def test_own_code_is_immutable(admin: Conn, world: World) -> None:
    ev = _own(admin, world, "Q9Z3")
    with pytest.raises(psycopg.Error), as_role(admin, "amw_operator", world.tenant) as c:
        c.execute("UPDATE owner_instruction_evidence SET review_code = 'Q8Z3' WHERE id = %s", (ev,))


def test_concurrent_writers_of_one_code_are_serialised(
    pg_dsn: str, admin: Conn, world: World
) -> None:
    """An uncommitted approval holding the code blocks an evidence insert of the same code
    (advisory lock); once it commits, the insert is refused instead of slipping through."""
    with psycopg.connect(pg_dsn) as first, psycopg.connect(pg_dsn, autocommit=True) as second:
        first.execute("SET SESSION AUTHORIZATION amw_app")
        first.execute("SELECT set_config('app.org_id', %s, false)", (str(world.tenant.org_uuid),))
        approval = new_uuid7()
        first.execute(
            "INSERT INTO approvals (id, org_id, job_id, kind, subject_kind, subject_id, state,"
            " workflow_key, current_step, managed_service, requested_by, review_code)"
            " VALUES (%s, %s, %s, 'FINAL_VIDEO', 'render', %s, 'PENDING', 'owner_one_tap', 1,"
            " false, 'svc_s07', 'Q7Z3')",
            (approval, world.tenant.org_uuid, world.job, approval),
        )
        second.execute("SET lock_timeout = '300ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            _own(second, world, "Q7Z3")
        first.commit()
        with pytest.raises(psycopg.Error) as err:
            _own(second, world, "Q7Z3")
        assert err.value.sqlstate == "AMW02"


# --- review reply P4-01: one registry, approval-bound rows, isolation, format ------------------
def _own_extra(code: str | None) -> dict[str, Any]:
    return {"approval_id": None, "step_no": None, "job_id": None, "review_code": code}


@pytest.mark.parametrize("kind", ["CONTRIBUTION", "OWNER_TOPIC", "STEP_DECISION"])
def test_approval_bound_evidence_cannot_carry_another_rows_code(
    admin: Conn, world: World, kind: str
) -> None:
    """Without the binding, 'confirm Q9Z3' meant for the own-code topic evidence could be bound as
    the confirmation of an approval-bound row that merely copied the code."""
    _own(admin, world, "Q9Z3")
    decision = "APPROVED" if kind == "STEP_DECISION" else None
    for code in ("Q9Z3", "Q8Z3", None):
        with pytest.raises(psycopg.Error) as err, as_role(admin, "amw_operator", world.tenant) as c:
            _insert_evidence(c, world, kind=kind, decision=decision, extra={"review_code": code})
        assert err.value.sqlstate == "AMW02", code


def test_approval_bound_evidence_code_is_checked_case_insensitively(
    admin: Conn, world: World
) -> None:
    row = admin.execute("SELECT review_code FROM approvals WHERE id = %s", (world.approval,))
    code = str(row.fetchone()[0])  # type: ignore[index]
    with as_role(admin, "amw_operator", world.tenant) as c:
        ev = _insert_evidence(c, world, extra={"review_code": code.lower()})
    assert _code(admin, ev) == code.lower()


def test_a_code_resolves_to_exactly_one_owner(admin: Conn, world: World) -> None:
    ev = _own(admin, world, "Q9Z3")
    _approval(admin, world, "Q8Z3")
    with as_role(admin, "amw_operator", world.tenant) as c:
        own = c.execute(
            "SELECT owner_kind, owner_id FROM amw_review_code_owner(%s, %s)",
            (world.tenant.org_uuid, "q9z3"),
        ).fetchall()
        appr = c.execute(
            "SELECT owner_kind FROM amw_review_code_owner(%s, %s)",
            (world.tenant.org_uuid, "Q8Z3"),
        ).fetchall()
        none = c.execute(
            "SELECT 1 FROM amw_review_code_owner(%s, %s)", (world.tenant.org_uuid, "Q7Z3")
        ).fetchall()
    assert own == [("EVIDENCE", ev)]
    assert appr == [("APPROVAL",)]
    assert none == []


@pytest.mark.parametrize("code", ["Q9", "Q9Z", "Q9Z3Q9Z3Z", "Q9Z3" * 8, "Q9 Z3", "Q9Z3\n"])
def test_own_code_length_and_format_are_enforced_by_the_database(
    admin: Conn, world: World, code: str
) -> None:
    with pytest.raises(psycopg.Error) as err:
        _own(admin, world, code)
    assert err.value.sqlstate == "AMW02"


@pytest.mark.parametrize("code", ["Q9Z3", "Q9Z3K", "Q9Z3KMNP"])
def test_own_code_length_range_is_accepted(admin: Conn, world: World, code: str) -> None:
    assert _code(admin, _own(admin, world, code)) == code


def test_approval_code_is_immutable(admin: Conn, world: World) -> None:
    with pytest.raises(psycopg.Error) as err, as_role(admin, "amw_app", world.tenant) as c:
        c.execute("UPDATE approvals SET review_code = 'Z9Z9' WHERE id = %s", (world.approval,))
    assert err.value.sqlstate == "AMW02"


def test_repeatable_read_cannot_share_a_code_across_tables(
    pg_dsn: str, admin: Conn, world: World
) -> None:
    """The evidence transaction's snapshot predates a committed approval holding the code: the
    registry's unique key still refuses it (a table-scan check would not)."""
    with psycopg.connect(pg_dsn) as reader:
        reader.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        reader.execute("SET SESSION AUTHORIZATION amw_operator")
        reader.execute("SELECT set_config('app.org_id', %s, false)", (str(world.tenant.org_uuid),))
        reader.execute("SELECT count(*) FROM approvals").fetchone()  # snapshot taken here
        _approval(admin, world, "Q4Z3")  # committed after the snapshot
        with pytest.raises(psycopg.Error) as err:
            _insert_evidence(
                reader, world, kind="OWNER_TOPIC", decision=None, extra=_own_extra("Q4Z3")
            )
        assert err.value.sqlstate in ("AMW02", "40001")
    total = admin.execute(
        "SELECT (SELECT count(*) FROM approvals WHERE upper(review_code) = 'Q4Z3')"
        " + (SELECT count(*) FROM owner_instruction_evidence WHERE review_code = 'Q4Z3')"
    ).fetchone()
    assert total == (1,)
