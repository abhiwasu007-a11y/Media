"""GLOSSARY section 2: UUIDv7, prefixed wire IDs, actor refs, idempotency keys."""

import re
import uuid

import pytest

from amw_core import ids
from amw_core.errors import InputInvalidError
from tests.docs_tables import glossary_prefixes, idempotency_scopes

WIRE_RE = re.compile(
    r"^[a-z]{3}_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def test_prefixes_equal_glossary_table() -> None:
    assert {p.value for p in ids.Prefix} == set(glossary_prefixes())


@pytest.mark.parametrize("prefix", list(ids.Prefix))
def test_new_id_round_trip(prefix: ids.Prefix) -> None:
    wire = ids.new_id(prefix)
    assert WIRE_RE.fullmatch(wire)
    assert wire.startswith(prefix.value + "_")
    value = ids.parse_id(wire, prefix)
    assert value.version == 7
    assert ids.format_id(prefix, value) == wire
    assert ids.prefix_of(wire) is prefix


def test_ids_are_time_ordered_and_unique() -> None:
    generated = [ids.new_uuid7() for _ in range(200)]
    assert len(set(generated)) == 200
    assert [g.bytes[:6] for g in generated] == sorted(g.bytes[:6] for g in generated)


def test_wrong_prefix_is_input_invalid() -> None:
    job = ids.new_id(ids.Prefix.JOB)
    with pytest.raises(InputInvalidError, match="wrong ID prefix"):
        ids.parse_id(job, ids.Prefix.TASK)
    assert ids.is_valid_id(job, ids.Prefix.JOB)
    assert not ids.is_valid_id(job, ids.Prefix.TASK)


@pytest.mark.parametrize(
    "bad",
    [
        "job_" + str(uuid.uuid4()),  # v4, not v7
        "JOB_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f",
        "zzz_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f",  # unknown prefix
        "job0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f",
        "",
    ],
)
def test_malformed_ids_rejected(bad: str) -> None:
    assert not ids.is_valid_id(bad)
    with pytest.raises(InputInvalidError):
        ids.prefix_of(bad)


def test_format_refuses_non_v7() -> None:
    with pytest.raises(InputInvalidError):
        ids.format_id(ids.Prefix.JOB, uuid.uuid4())


def test_typed_kinds() -> None:
    job = ids.JOB.new()
    assert ids.JOB.validate(job) == job
    assert ids.JOB.from_uuid(ids.JOB.to_uuid(job)) == job
    with pytest.raises(InputInvalidError):
        ids.TASK.validate(job)


@pytest.mark.parametrize(
    ("value", "actor", "executor"),
    [
        ("agent_01", True, True),
        ("agent_17", True, True),
        ("agent_18", False, False),
        ("svc_s13", True, True),
        ("svc_s14", False, False),
        ("sys_reaper", True, False),
        ("sys_x", False, False),
        ("usr_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f", True, False),
    ],
)
def test_actor_and_executor_refs(value: str, actor: bool, executor: bool) -> None:
    assert ids.is_actor_ref(value) is actor
    assert ids.is_executor_id(value) is executor
    if actor:
        assert ids.actor_ref(value) == value
    else:
        with pytest.raises(InputInvalidError):
            ids.actor_ref(value)
    if executor:
        assert ids.executor_id(value) == value
    else:
        with pytest.raises(InputInvalidError):
            ids.executor_id(value)


def test_idempotency_key_is_deterministic_and_canonical() -> None:
    org = ids.ORG.new()
    a = ids.make_idempotency_key(org, "llm.call", ["tsk_x", "draft", 3])
    b = ids.make_idempotency_key(org, "llm.call", ["tsk_x", "draft", 3])
    c = ids.make_idempotency_key(org, "llm.call", ["tsk_x", "draft", 4])
    assert a == b != c
    assert ids.is_idempotency_key(a)
    assert ids.idempotency_key_of(a) == a
    with pytest.raises(InputInvalidError):
        ids.idempotency_key_of("idk_short")


def test_idempotency_key_known_vector() -> None:
    org = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f"
    key = ids.make_idempotency_key(org, "job.create", ["brief-1"])
    # sha256 of {"natural_key":["brief-1"],"org_id":"org_0192...","scope":"job.create"}
    import hashlib

    material = ('{"natural_key":["brief-1"],"org_id":"' + org + '","scope":"job.create"}').encode()
    assert key == "idk_" + hashlib.sha256(material).hexdigest()


@pytest.mark.parametrize("part", [1.5, True, None])
def test_idempotency_key_rejects_non_canonical_parts(part: object) -> None:
    with pytest.raises(InputInvalidError):
        ids.make_idempotency_key(ids.ORG.new(), "llm.call", [part])  # type: ignore[list-item]


def test_idempotency_key_requires_org_wire_id() -> None:
    with pytest.raises(InputInvalidError):
        ids.make_idempotency_key(ids.JOB.new(), "llm.call", ["a"])


def test_scopes_equal_03_table() -> None:
    doc = idempotency_scopes()
    assert "task.<task_type>" in doc
    assert {s.value for s in ids.IdempotencyScope} == {s for s in doc if "<" not in s}


@pytest.mark.parametrize(
    ("scope", "ok"),
    [
        ("job.create", True),
        ("task.agent_06.claim_extraction", True),
        ("task.svc_s07.request_approval", True),
        ("task.agent_18.x", False),
        ("task.", False),
        ("llm.calls", False),
        ("conformance", False),
    ],
)
def test_scope_validation(scope: str, ok: bool) -> None:
    assert ids.is_idempotency_scope(scope) is ok
    if ok:
        assert ids.make_idempotency_key(ids.ORG.new(), scope, ["a"])
    else:
        with pytest.raises(InputInvalidError, match="scope"):
            ids.make_idempotency_key(ids.ORG.new(), scope, ["a"])
