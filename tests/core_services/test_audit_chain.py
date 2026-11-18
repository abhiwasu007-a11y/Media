"""Audit hash chain (04 section 5.13): append, verification, tamper / truncation detection,
JSON export, validation; the in-memory log serialises per tenant."""

import hashlib
import json
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from amw_core.audit import (
    GENESIS_HASH,
    MemoryAuditLog,
    export_json,
    hash_entry,
    stored_columns,
    verify_entries,
)
from amw_core.audit.chain import ChainHead, canonical_bytes, format_ts
from amw_core.enums import ActorKind
from amw_core.errors import InputInvalidError
from amw_core.ids import CORRELATION, JOB, ORG, TASK, USER, ActorRef
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from tests.core_services.support import T0, tx_for

pytestmark = pytest.mark.unit


def _entry(i: int = 0, **kw: object) -> NewAuditEntry:
    base = NewAuditEntry(
        actor_kind=ActorKind.AGENT,
        actor_ref=ActorRef("agent_01"),
        authority="orchestrator",
        action="task.completed",
        target_kind="TASK",
        target_id=TASK.new(),
        occurred_at=T0 + timedelta(seconds=i),
        job_id=JOB.new(),
        correlation_id=CORRELATION.new(),
        details={"from": "RUNNING", "to": "COMPLETED", "state_version": i, "n": [1, True, None]},
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def test_is_an_audit_log() -> None:
    assert isinstance(MemoryAuditLog(), AuditLog)


def test_append_chains_from_genesis_and_verifies() -> None:
    log = MemoryAuditLog()
    tx = tx_for(ORG.new())
    rows = [log.append(tx, _entry(i)) for i in range(5)]
    assert [r.seq for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0].prev_hash == GENESIS_HASH
    assert all(rows[i].prev_hash == rows[i - 1].row_hash for i in range(1, 5))
    assert all(hash_entry(r) == r.row_hash for r in rows)
    v = log.verify_chain(tx)
    assert v.ok
    assert v.entries_checked == 5
    assert v.first_bad_seq is None


def test_hash_is_sha256_of_prev_and_canonical_columns() -> None:
    log = MemoryAuditLog()
    tx = tx_for(ORG.new())
    row = log.append(tx, _entry())
    columns = stored_columns(row.id, row.org_id, 1, row.entry, GENESIS_HASH)
    assert row.row_hash == hashlib.sha256(GENESIS_HASH + canonical_bytes(columns)).digest()
    text = canonical_bytes(columns).decode()
    assert " " not in text.replace("task.completed", "")  # no insignificant whitespace
    assert json.loads(text)["occurred_at"] == "2026-01-05T10:00:00.000000Z"
    assert json.loads(text)["target_id"] == str(TASK.to_uuid(row.entry.target_id))  # type: ignore[arg-type]


@pytest.mark.security
def test_tampered_row_is_detected_at_its_seq() -> None:
    log = MemoryAuditLog()
    org = ORG.new()
    tx = tx_for(org)
    rows = [log.append(tx, _entry(i)) for i in range(4)]
    forged = replace(rows[2], entry=replace(rows[2].entry, details={"to": "CANCELLED"}))
    log._tamper(org, 2, forged)
    v = log.verify_chain(tx)
    assert not v.ok
    assert v.first_bad_seq == 3
    assert v.entries_checked == 2


@pytest.mark.security
def test_rehashed_forgery_breaks_the_next_link() -> None:
    log = MemoryAuditLog()
    org = ORG.new()
    tx = tx_for(org)
    rows = [log.append(tx, _entry(i)) for i in range(3)]
    forged = replace(rows[1], entry=replace(rows[1].entry, action="task.cancelled"))
    forged = replace(forged, row_hash=hash_entry(forged))
    log._tamper(org, 1, forged)
    assert log.verify_chain(tx).first_bad_seq == 3


@pytest.mark.security
def test_truncation_and_reordering_are_detected() -> None:
    log = MemoryAuditLog()
    org = ORG.new()
    tx = tx_for(org)
    rows = [log.append(tx, _entry(i)) for i in range(4)]
    log._truncate(org, 2)
    v = log.verify_chain(tx)
    assert not v.ok
    assert v.first_bad_seq == 3
    assert verify_entries([rows[1], rows[0]], None).first_bad_seq == 1
    assert verify_entries([], None).ok
    assert not verify_entries([], ChainHead(1, rows[0].row_hash)).ok


@pytest.mark.tenancy
def test_chains_are_per_tenant() -> None:
    log = MemoryAuditLog()
    a, b = tx_for(ORG.new()), tx_for(ORG.new())
    log.append(a, _entry())
    log.append(a, _entry(1))
    first_b = log.append(b, _entry())
    assert first_b.seq == 1
    assert first_b.prev_hash == GENESIS_HASH
    assert [r.seq for r in log.export(b)] == [1]
    assert log.verify_chain(a).entries_checked == 2


def test_export_json_in_seq_order_with_filters() -> None:
    log = MemoryAuditLog()
    tx = tx_for(ORG.new())
    target = TASK.new()
    rows = [log.append(tx, _entry(i, target_id=target if i % 2 else TASK.new())) for i in range(4)]
    doc = json.loads(export_json(log.export(tx)))
    assert [r["seq"] for r in doc["audit_log"]] == [1, 2, 3, 4]
    assert doc["audit_log"][0]["row_hash"] == rows[0].row_hash.hex()
    assert doc["audit_log"][0]["target_id"] == rows[0].entry.target_id
    assert [r.seq for r in log.export(tx, since_seq=2)] == [3, 4]
    assert [r.seq for r in log.export(tx, target_id=target)] == [2, 4]


def test_concurrent_writers_get_a_gap_free_sequence() -> None:
    log = MemoryAuditLog()
    tx = tx_for(ORG.new())

    def write() -> None:
        for i in range(50):
            log.append(tx, _entry(i))

    threads = [threading.Thread(target=write) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [r.seq for r in log.export(tx)] == list(range(1, 201))
    assert log.verify_chain(tx).ok


@pytest.mark.parametrize(
    "change",
    [
        {"actor_ref": "bob"},
        {"authority": ""},
        {"action": ""},
        {"target_kind": "NOT_AN_ENTITY"},
        {"target_kind": "JOB"},  # target_id is a task ID
        {"occurred_at": datetime(2026, 1, 1)},
        {"details": {"ratio": 0.5}},  # floats are not canonical
        {"details": {"x": "a\x00b"}},
        {"details": {1: "x"}},
        {"details": {"x": object()}},
        {"details": {"x": "y" * 70_000}},
    ],
)
def test_invalid_entries_are_refused(change: dict[str, object]) -> None:
    with pytest.raises(InputInvalidError):
        MemoryAuditLog().append(tx_for(ORG.new()), _entry(**change))  # type: ignore[arg-type]


def test_deep_details_refused() -> None:
    deep: dict[str, object] = {}
    node = deep
    for _ in range(40):
        node["x"] = {}
        node = node["x"]  # type: ignore[assignment]
    with pytest.raises(InputInvalidError):
        MemoryAuditLog().append(tx_for(ORG.new()), _entry(details=deep))


@pytest.mark.security
def test_secrets_are_refused_in_details() -> None:
    with pytest.raises(InputInvalidError, match="secret"):
        MemoryAuditLog().append(tx_for(ORG.new()), _entry(details={"api_key": "x"}))
    with pytest.raises(InputInvalidError):
        MemoryAuditLog().append(tx_for(ORG.new()), _entry(details={"note": "sk-ant-" + "z" * 30}))


def test_optional_fields_and_human_actor() -> None:
    user = USER.new()
    log = MemoryAuditLog()
    tx = tx_for(ORG.new(), user)
    row = log.append(
        tx,
        _entry(
            actor_kind=ActorKind.HUMAN,
            actor_ref=ActorRef(user),
            on_behalf_of=user,
            target_id=None,
            target_kind="CONTROL_SETTING",
            job_id=None,
            correlation_id=None,
            details={},
        ),
    )
    assert log.verify_chain(tx).ok
    assert row.entry.on_behalf_of == user


def test_format_ts_converts_to_utc() -> None:
    from zoneinfo import ZoneInfo

    local = datetime(2026, 1, 5, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert format_ts(local) == "2026-01-05T10:00:00.000000Z"
    assert format_ts(datetime(2026, 1, 5, tzinfo=UTC)).endswith("Z")
