"""P4-17 (CCR-130): core Protocols, ExecContext and the memory_items fake."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from amw_core import interfaces
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import MemoryScope
from amw_core.errors import IdempotencyConflictError, InputInvalidError, TenantMismatchError
from amw_core.exec_context import ExecContext
from amw_core.ids import ORG, ActorRef, Prefix, new_id
from amw_core.interfaces import TenantContext
from amw_core.interfaces.memory_items import MemoryItem, MemoryItems
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
    first = store.put(t, item())
    assert store.put(t, item()) == first
    with pytest.raises(IdempotencyConflictError):
        store.put(t, item(sha="b" * 64))


def test_tenant_isolation() -> None:
    store = InMemoryMemoryItems()
    a, b = tx(), tx()
    store.put(a, item())
    assert store.get(a, MemoryScope.PROJECT, None, "research_pack.1") is not None
    assert store.get(b, MemoryScope.PROJECT, None, "research_pack.1") is None
    assert store.list_for_scope(b, MemoryScope.PROJECT, None) == []
    assert len(store.list_for_scope(a, MemoryScope.PROJECT, None)) == 1


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
        InMemoryMemoryItems().put(tx(), item(**change))


def test_exec_context_tenant_scope() -> None:
    ti = _task_input()
    ctx = ExecContext.from_task_input(ti, new_id(Prefix.TASK_ATTEMPT), "agent_07")
    assert ctx.org_id == ti.org_id
    assert ctx.attempt_no == ti.retry_count + 1
    assert ctx.correlation_id == ti.correlation_id
    with pytest.raises(TenantMismatchError):
        ExecContext.from_task_input(ti, new_id(Prefix.TASK_ATTEMPT), "agent_08")


def _task_input() -> TaskInput:
    return TaskInput.model_validate(task_input_doc() | {"agent_id": "agent_07"})
