"""``claims`` (04 section 5.11; CCR-029, CCR-132; migration 0054): columns incl. ``final_verdict``,
CHECKs, the replay-safe key, tenant foreign keys and RLS. The cross-tenant sweep
(``test_cross_tenant.py``) covers the table through the seed row."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from amw_core.ids import new_uuid7
from tests.pg_fixtures import make_tenant
from tests.tenancy.seed import World, seed_tenant

pytestmark = pytest.mark.tenancy
Conn = psycopg.Connection[tuple[Any, ...]]
REASONS = ["NO_EVIDENCE_CANDIDATES", "SPAN_INVALID"]


@pytest.fixture(scope="module")
def worlds(pg_dsn: str) -> tuple[World, World]:
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        return seed_tenant(conn, make_tenant(conn)), seed_tenant(conn, make_tenant(conn))


@contextmanager
def as_app(conn: Conn, w: World) -> Iterator[Conn]:
    with conn.transaction():
        conn.execute("SET LOCAL ROLE amw_app")
        conn.execute("SELECT set_config('app.org_id', %s, true)", (str(w.tenant.org_uuid),))
        yield conn


def claim(w: World, **change: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": new_uuid7(),
        "org_id": w.tenant.org_uuid,
        "script_id": w["script"],
        "job_id": w["job"],
        "segment_id": "seg_1",
        "char_start": 10,
        "char_end": 20,
        "quote": "q",
        "normalized_claim": "q",
        "claim_type": "STATISTICAL",
        "time_reference_kind": "HISTORICAL",
        "status": "EXTRACTED",
        "rule_flags": Jsonb([]),
        "proposed_verdict": "ALLOWED",
        "requires_citation": True,
        "extracted_by_task_id": w["task"],
    }
    row.update(change)
    return row


def insert(conn: Conn, row: dict[str, Any]) -> uuid.UUID:
    names = psycopg.sql.SQL(", ").join(map(psycopg.sql.Identifier, row))
    marks = psycopg.sql.SQL(", ").join(psycopg.sql.Placeholder() * len(row))
    conn.execute(
        psycopg.sql.SQL("INSERT INTO claims ({}) VALUES ({})").format(names, marks),
        list(row.values()),
    )
    return uuid.UUID(str(row["id"]))


def test_seed_has_the_ids_this_file_uses(worlds: tuple[World, World]) -> None:
    a, _ = worlds
    assert {"script", "job", "task", "claim"} <= set(a.ids)


def test_app_inserts_and_agent_16_sets_the_final_verdict(
    admin: Conn, worlds: tuple[World, World]
) -> None:
    a, _ = worlds
    with as_app(admin, a) as c:
        cid = insert(c, claim(a, status_reasons=REASONS))
        c.execute(
            "UPDATE claims SET status = 'VERIFIED', final_verdict = 'BLOCKED',"
            " verified_by_task_id = %s WHERE id = %s",
            (a["task"], cid),
        )
    row = admin.execute(
        "SELECT final_verdict, status, status_reasons, row_version >= 1 FROM claims WHERE id = %s",
        (cid,),
    ).fetchone()
    assert row == ("BLOCKED", "VERIFIED", REASONS, True)


@pytest.mark.parametrize(
    "change",
    [
        {"char_start": 20, "char_end": 20},
        {"claim_type": "RUMOUR"},
        {"time_reference_kind": "SOON"},
        {"status": "DONE"},
        {"proposed_verdict": "MAYBE"},
        {"final_verdict": "MAYBE"},
        {"status_reasons": ["NOT_A_REASON"]},
        {"rule_flags": Jsonb({"rule_id": "x"})},
        {"rule_flags": None},
        {"proposed_verdict": None},
    ],
)
def test_checks_refuse_bad_rows(
    admin: Conn, worlds: tuple[World, World], change: dict[str, Any]
) -> None:
    a, _ = worlds
    with pytest.raises(psycopg.errors.IntegrityError), as_app(admin, a) as c:
        insert(c, claim(a, **change))


def test_replay_key_is_unique(admin: Conn, worlds: tuple[World, World]) -> None:
    a, _ = worlds
    with as_app(admin, a) as c:
        insert(c, claim(a, segment_id="seg_replay"))
    with pytest.raises(psycopg.errors.UniqueViolation), as_app(admin, a) as c:
        insert(c, claim(a, segment_id="seg_replay"))


@pytest.mark.parametrize("column", ["script_id", "job_id", "extracted_by_task_id"])
def test_foreign_tenant_references_are_refused(
    admin: Conn, worlds: tuple[World, World], column: str
) -> None:
    a, b = worlds
    other = {"script_id": b["script"], "job_id": b["job"], "extracted_by_task_id": b["task"]}
    with pytest.raises(psycopg.errors.ForeignKeyViolation), as_app(admin, a) as c:
        insert(c, claim(a, **{column: other[column], "segment_id": f"seg_{column}"}))


def test_rls_enable_force_and_no_cross_tenant_reads(
    admin: Conn, worlds: tuple[World, World]
) -> None:
    a, b = worlds
    flags = admin.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'claims'"
    ).fetchone()
    assert flags == (True, True)
    with as_app(admin, a) as c:
        seen = c.execute("SELECT count(*) FROM claims WHERE id = %s", (b["claim"],)).fetchone()
        assert seen == (0,)
        moved = c.execute(
            "UPDATE claims SET final_verdict = 'ALLOWED' WHERE id = %s", (b["claim"],)
        ).rowcount
        assert moved == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege), as_app(admin, a) as c:
        insert(c, claim(b, segment_id="seg_foreign_org"))
