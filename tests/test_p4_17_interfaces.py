"""P4-17 (CCR-130): core Protocols, ExecContext and the memory_items fake."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from amw_core import interfaces
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import MemoryScope
from amw_core.errors import (
    IdempotencyConflictError,
    InputInvalidError,
    PermissionDeniedError,
    TenantMismatchError,
)
from amw_core.exec_context import ExecContext
from amw_core.ids import CHANNEL, JOB, ORG, TASK, ActorRef, Prefix, new_id
from amw_core.interfaces import TenantContext
from amw_core.interfaces.memory_items import MemoryItem, MemoryItems, MemoryRequester
from amw_core.testing.memory import MemoryTransaction
from amw_core.testing.memory_items import InMemoryMemoryItems
from tests.contract.examples import task_input as task_input_doc

NOW = datetime(2026, 1, 1, tzinfo=UTC)
WORKSPACE = new_id(Prefix.WORKSPACE)
PROJECT = new_id(Prefix.PROJECT)
ACTOR = ActorRef("agent_04")


def tx(org=None) -> MemoryTransaction:  # type: ignore[no-untyped-def]
    return MemoryTransaction(TenantContext(org or ORG.new(), ACTOR))


def item(sha: str = "a" * 64, **change: Any) -> MemoryItem:
    base: dict[str, object] = {
        "scope": MemoryScope.PROJECT,
        "workspace_id": WORKSPACE,
        "key": "research_pack.1",
        "provenance_ref": "out_1",
        "created_by": ACTOR,
        "value_sha256": sha,
        "value_ref": "s3://x/1",
        "project_id": PROJECT,
        "expires_at": NOW + timedelta(days=1),
    }
    base.update(change)
    return MemoryItem(**base)  # type: ignore[arg-type]


def test_protocols_are_exported_and_the_fake_conforms() -> None:
    for name in (
        "MemoryItems",
        "ClaimStore",
        "KnowledgeReader",
        "ScriptRegistry",
        "SubjectDocuments",
        "BreakerReader",
        "TenantRepository",
    ):
        assert name in interfaces.__all__
    assert isinstance(InMemoryMemoryItems(), MemoryItems)


def test_put_is_idempotent_and_conflicts_on_another_hash() -> None:
    store, t = InMemoryMemoryItems(), tx()
    first = put(store, t, item())
    assert put(store, t, item()) == first
    with pytest.raises(IdempotencyConflictError):
        put(store, t, item(sha="b" * 64))


def own(row: MemoryItem) -> MemoryRequester:
    """The requester whose own scope the row lies in."""
    return MemoryRequester(
        channel_id=row.channel_id,
        project_id=row.project_id,
        job_id=row.job_id,
        task_id=row.task_id,
    )


def put(store: InMemoryMemoryItems, t: MemoryTransaction, row: MemoryItem) -> Any:
    return store.put(t, own(row), row)


def requester(project: Any = PROJECT, task: Any = None, channel: Any = None) -> MemoryRequester:
    return MemoryRequester(channel_id=channel, project_id=project, job_id=None, task_id=task)


def test_tenant_isolation() -> None:
    store = InMemoryMemoryItems()
    a, b = tx(), tx()
    put(store, a, item())
    assert store.get(a, requester(), MemoryScope.PROJECT, "research_pack.1", NOW) is not None
    assert store.get(b, requester(), MemoryScope.PROJECT, "research_pack.1", NOW) is None
    assert store.list_for_scope(b, requester(), MemoryScope.PROJECT, NOW) == []
    assert len(store.list_for_scope(a, requester(), MemoryScope.PROJECT, NOW)) == 1


def test_another_project_never_sees_or_collides_with_a_project_row() -> None:
    """04 5.10 rule 1: never another project. The same key and hash in project P2 is its own row
    (the old fake returned P1's row), and P2 cannot read P1's."""
    store, t = InMemoryMemoryItems(), tx()
    other = new_id(Prefix.PROJECT)
    first = put(store, t, item())
    second = put(store, t, item(project_id=other))
    assert second.id != first.id
    assert store.get(t, requester(other), MemoryScope.PROJECT, "research_pack.1", NOW) == second
    assert store.get(t, requester(), MemoryScope.PROJECT, "research_pack.1", NOW) == first
    stranger = requester(new_id(Prefix.PROJECT))
    assert store.get(t, stranger, MemoryScope.PROJECT, "research_pack.1", NOW) is None
    assert store.list_for_scope(t, stranger, MemoryScope.PROJECT, NOW) == []
    assert store.get(t, requester(None), MemoryScope.PROJECT, "research_pack.1", NOW) is None
    # a different hash is a conflict only inside the same project
    put(store, t, item(project_id=other, key="k2", sha="c" * 64))
    with pytest.raises(IdempotencyConflictError):
        put(store, t, item(project_id=other, key="k2", sha="d" * 64))


def test_task_scope_is_visible_to_the_same_task_only() -> None:
    store, t = InMemoryMemoryItems(), tx()
    job, task, other = JOB.new(), TASK.new(), TASK.new()
    stored = put(store, t, item(scope=MemoryScope.TASK, job_id=job, task_id=task, project_id=None))
    mine = requester(task=task)
    assert store.get(t, mine, MemoryScope.TASK, "research_pack.1", NOW) == stored
    assert store.get(t, requester(task=other), MemoryScope.TASK, "research_pack.1", NOW) is None
    assert store.get(t, requester(task=None), MemoryScope.TASK, "research_pack.1", NOW) is None


def test_channel_scope_is_per_channel() -> None:
    store, t = InMemoryMemoryItems(), tx()
    ch1, ch2 = CHANNEL.new(), CHANNEL.new()
    put(store, t, item(scope=MemoryScope.CHANNEL, channel_id=ch1, project_id=None, expires_at=None))
    seen = store.get(t, requester(channel=ch1), MemoryScope.CHANNEL, "research_pack.1", NOW)
    assert seen is not None
    assert store.get(t, requester(channel=ch2), MemoryScope.CHANNEL, "research_pack.1", NOW) is None


def test_expired_rows_are_not_returned() -> None:
    store, t = InMemoryMemoryItems(), tx()
    put(store, t, item())
    late = NOW + timedelta(days=2)
    assert store.get(t, requester(), MemoryScope.PROJECT, "research_pack.1", late) is None
    assert store.list_for_scope(t, requester(), MemoryScope.PROJECT, late) == []


def test_long_term_needs_provenance() -> None:
    row = item(
        scope=MemoryScope.LONG_TERM,
        channel_id=CHANNEL.new(),
        project_id=None,
        expires_at=None,
        provenance_ref=" ",
    )
    with pytest.raises(InputInvalidError):
        put(InMemoryMemoryItems(), tx(), row)


@pytest.mark.parametrize(
    "change",
    [
        {"expires_at": None},
        {"value": {"x": 1}},
        {"value_ref": None},
        {"project_id": None},
        {"scope": MemoryScope.CHANNEL, "expires_at": None},
        {"scope": MemoryScope.TASK},
    ],
)
def test_rows_that_break_04_checks_are_refused(change: dict[str, Any]) -> None:
    with pytest.raises(InputInvalidError):
        put(InMemoryMemoryItems(), tx(), item(**change))


def test_exec_context_tenant_scope() -> None:
    ti = _task_input()
    ctx = ExecContext.from_task_input(
        ti, new_id(Prefix.TASK_ATTEMPT), "agent_07", envelope_org_id=ti.org_id
    )
    assert ctx.org_id == ti.org_id
    assert ctx.attempt_no == ti.retry_count + 1
    assert ctx.correlation_id == ti.correlation_id
    with pytest.raises(TenantMismatchError):
        ExecContext.from_task_input(
            ti, new_id(Prefix.TASK_ATTEMPT), "agent_08", envelope_org_id=ti.org_id
        )


def _task_input() -> TaskInput:
    return TaskInput.model_validate(task_input_doc() | {"agent_id": "agent_07"})


def test_exec_context_envelope_org_and_malformed_ids() -> None:
    ti = _task_input()
    attempt = new_id(Prefix.TASK_ATTEMPT)
    ok = ExecContext.from_task_input(ti, attempt, "agent_07", envelope_org_id=ti.org_id)
    assert ok.org_id == ti.org_id
    with pytest.raises(TenantMismatchError):
        ExecContext.from_task_input(ti, attempt, "agent_07", envelope_org_id=ORG.new())
    with pytest.raises(TenantMismatchError):
        ExecContext.from_task_input(ti, "not-an-attempt-id", "agent_07", envelope_org_id=ti.org_id)


def test_claim_records_follow_the_claims_table() -> None:
    from amw_core.enums import ClaimType, ComplianceVerdict, TimeReferenceKind
    from amw_core.interfaces.claims import CitationRow, NewClaim

    base = {
        "local_id": "c1",
        "job_id": JOB.new(),
        "segment_id": "s1",
        "quote": "q",
        "normalized_claim": "n",
        "claim_type": ClaimType.FACTUAL,
        "time_reference_kind": TimeReferenceKind.TIMELESS,
        "requires_citation": True,
        "proposed_verdict": ComplianceVerdict.ALLOWED,
    }
    assert NewClaim(**base, char_start=0, char_end=3).rule_flags == ()  # type: ignore[arg-type]
    for start, end in ((3, 3), (-1, 2), (5, 2)):
        with pytest.raises(InputInvalidError):
            NewClaim(**base, char_start=start, char_end=end)  # type: ignore[arg-type]
    from amw_core.enums import CitationSupport

    sup = CitationSupport.SUPPORTS
    CitationRow("c", sup, knowledge_chunk_id="k")
    CitationRow("c", sup, external_url="https://example.invalid", accessed_at=NOW)
    for kwargs in (
        {},
        {"knowledge_chunk_id": "k", "external_url": "https://x.invalid", "accessed_at": NOW},
        {"external_url": "https://x.invalid"},
    ):
        with pytest.raises(InputInvalidError):
            CitationRow("c", sup, **kwargs)


def test_exec_context_requires_the_envelope_org() -> None:
    with pytest.raises(TypeError):
        ExecContext.from_task_input(_task_input(), new_id(Prefix.TASK_ATTEMPT), "agent_07")  # type: ignore[call-arg]


def test_memory_writes_outside_the_requesters_scope_are_refused() -> None:
    """Memory poisoning (04 5.10 rule 1): task T2 cannot write T1's TASK row, project P2 cannot
    write P1's PROJECT row, a channel cannot write another channel's row; nothing is stored."""
    store, t = InMemoryMemoryItems(), tx()
    job, t1, t2 = JOB.new(), TASK.new(), TASK.new()
    p1, p2 = new_id(Prefix.PROJECT), new_id(Prefix.PROJECT)
    ch1, ch2 = CHANNEL.new(), CHANNEL.new()
    task_row = item(scope=MemoryScope.TASK, job_id=job, task_id=t1, project_id=None)
    mallory = MemoryRequester(channel_id=ch1, project_id=p2, job_id=job, task_id=t2)
    with pytest.raises(PermissionDeniedError):
        store.put(t, mallory, task_row)  # T2 writes into T1's row
    with pytest.raises(PermissionDeniedError):
        store.put(t, mallory, item(project_id=p1))  # P2 writes into P1
    chan = item(scope=MemoryScope.CHANNEL, channel_id=ch2, project_id=None, expires_at=None)
    with pytest.raises(PermissionDeniedError):
        store.put(t, mallory, chan)  # channel 1 writes into channel 2
    assert store.list_for_scope(t, mallory, MemoryScope.TASK, NOW) == []
    owner = MemoryRequester(channel_id=ch1, project_id=p1, job_id=job, task_id=t1)
    assert store.put(t, owner, task_row).item == task_row  # the owner can
    # a row with a different job than the requester's job is refused too
    wrong_job = MemoryRequester(channel_id=ch1, project_id=p1, job_id=JOB.new(), task_id=t1)
    with pytest.raises(PermissionDeniedError):
        store.put(
            t,
            wrong_job,
            item(scope=MemoryScope.TASK, job_id=job, task_id=t1, key="k9", project_id=None),
        )


def test_superseded_rows_are_not_live() -> None:
    store, t = InMemoryMemoryItems(), tx()
    row = item(superseded_by=new_id(Prefix.MEMORY_ITEM))
    put(store, t, row)
    assert store.get(t, requester(), MemoryScope.PROJECT, "research_pack.1", NOW) is None


def test_claim_enums_are_checked_at_runtime() -> None:
    from amw_core.enums import ClaimStatus, ComplianceVerdict
    from amw_core.interfaces.claims import ClaimStatusUpdate, RuleFlag

    with pytest.raises(InputInvalidError):
        ClaimStatusUpdate("c", "VERIFIED")  # type: ignore[arg-type]
    with pytest.raises(InputInvalidError):
        RuleFlag("FIN-R1", "BLOCKING", "e")  # type: ignore[arg-type]
    upd = ClaimStatusUpdate("c", ClaimStatus.SUBSTANTIATED, substantiation_ref="doc-1")
    assert upd.substantiation_ref == "doc-1"
    assert ComplianceVerdict.ALLOWED is not None
