"""07 section 12: DLQ replay with reconciliation; a replay never duplicates an effect
(27 section 9 acceptance test 3: replaying the delivery task creates no second bundle)."""

from dataclasses import replace
from datetime import timedelta

import pytest

from amw_core.config import load_settings
from amw_core.enums import DlqRecoveryStatus, EscalationLevel, FailureClass
from amw_core.errors import (
    InputInvalidError,
    InvalidTransitionError,
    LoopCapExceededError,
    PermissionDeniedError,
)
from amw_core.ids import APPROVAL, JOB, ORG, TASK, USER, make_idempotency_key
from amw_core.interfaces.idempotency_store import BeginAction
from amw_core.retries import dlq
from amw_core.testing.memory import MemoryIdempotencyStore
from tests.core_services.support import T0, tx_for

pytestmark = pytest.mark.failure_injection
CFG = load_settings(environ={})
OWNER = USER.new()
ALL = frozenset({"dlq.triage", "dlq.replay", "dlq.discard"})
SHA = "ab" * 32


def _item(code: str = "INFRASTRUCTURE.STORAGE_UNAVAILABLE", **kw: object) -> dlq.DeadLetter:
    history = [
        dlq.AttemptHistoryItem(
            n, T0 + timedelta(minutes=n), T0 + timedelta(minutes=n, seconds=5), "wkr_x", code
        )
        for n in (2, 1, 3)
    ]
    item = dlq.build_dead_letter(
        task_id=TASK.new(),
        job_id=JOB.new(),
        error={"code": code, "message": "injected"},
        reason="retries exhausted",
        payload_ref="amw-blob://org_x/jobs/j/tasks/t/attempts/a/input.json",
        payload_sha256=SHA,
        retry_history=history,
    )
    return replace(item, **kw)  # type: ignore[arg-type]


def test_record_content_from_the_catalogue() -> None:
    item = _item()
    assert item.failure_class is FailureClass.INFRASTRUCTURE
    assert item.escalation_level is EscalationLevel.L2
    assert [h.attempt_no for h in item.retry_history] == [1, 2, 3]
    assert item.last_run_at == T0 + timedelta(minutes=3, seconds=5)
    assert item.recovery_status is DlqRecoveryStatus.NEW
    assert _item("PERMANENT.CROSS_TENANT_REF").escalation_level is EscalationLevel.L3
    assert item.retry_history[0].to_json()["error_code"] == item.error_code
    with pytest.raises(InputInvalidError):
        dlq.build_dead_letter(
            task_id=TASK.new(),
            job_id=JOB.new(),
            error={},
            reason="r",
            payload_ref="x",
            payload_sha256=SHA,
            retry_history=[],
        )
    with pytest.raises(InputInvalidError):
        dlq.build_dead_letter(
            task_id=TASK.new(),
            job_id=JOB.new(),
            error={"code": "AGENT.CRASH"},
            reason="r",
            payload_ref="x",
            payload_sha256="ab",
            retry_history=[],
        )


def test_full_workflow_to_resolved() -> None:
    item = dlq.triage(_item(), OWNER, "disk was full; cleaned", ALL, T0)
    item = dlq.request_replay(item, OWNER, ALL, T0)
    item = dlq.approve_replay(item, OWNER, ALL, CFG, T0)
    plan = dlq.plan_replay(item, CFG)
    assert plan.payload_ref == item.payload_ref
    assert plan.attempt_counter_reset
    item = dlq.mark_replayed(item, CFG, T0)
    assert item.replay_count == 1
    assert item.recovery_status is DlqRecoveryStatus.REPLAYED
    item = dlq.mark_resolved(item, T0)
    assert item.resolved_at == T0
    assert [e["to"] for e in item.events] == [
        "TRIAGED",
        "REPLAY_REQUESTED",
        "REPLAY_APPROVED",
        "REPLAYED",
        "RESOLVED",
    ]
    with pytest.raises(InvalidTransitionError):
        dlq.discard(item, OWNER, "late", ALL, T0)


def test_guards_permissions_notes_and_order() -> None:
    with pytest.raises(PermissionDeniedError):
        dlq.triage(_item(), OWNER, "note", frozenset(), T0)
    with pytest.raises(InputInvalidError):
        dlq.triage(_item(), OWNER, "  ", ALL, T0)
    with pytest.raises(InvalidTransitionError):
        dlq.request_replay(_item(), OWNER, ALL, T0)  # NEW -> REPLAY_REQUESTED skips triage
    with pytest.raises(InvalidTransitionError):
        dlq.plan_replay(_item(), CFG)
    no_note = replace(_item(), recovery_status=DlqRecoveryStatus.REPLAY_REQUESTED)
    with pytest.raises(InvalidTransitionError):
        dlq.approve_replay(no_note, OWNER, ALL, CFG, T0)
    approved_no_note = replace(_item(), recovery_status=DlqRecoveryStatus.REPLAY_APPROVED)
    with pytest.raises(InvalidTransitionError):
        dlq.plan_replay(approved_no_note, CFG)
    with pytest.raises(PermissionDeniedError):
        dlq.discard(_item(), OWNER, "x", frozenset({"dlq.replay"}), T0)
    with pytest.raises(InputInvalidError):
        dlq.discard(_item(), OWNER, "", ALL, T0)
    gone = dlq.discard(_item(), OWNER, "superseded", ALL, T0)
    assert gone.recovery_status is DlqRecoveryStatus.DISCARDED
    assert gone.events[-1]["note"]


def test_failed_replay_returns_to_new() -> None:
    item = dlq.triage(_item(), OWNER, "n", ALL, T0)
    item = dlq.approve_replay(dlq.request_replay(item, OWNER, ALL, T0), OWNER, ALL, CFG, T0)
    item = dlq.mark_failed_again(dlq.mark_replayed(item, CFG, T0), T0)
    assert item.recovery_status is DlqRecoveryStatus.NEW
    assert item.replay_count == 1


@pytest.mark.parametrize(
    ("scope", "cost", "needs"),
    [
        ("upload.youtube", 0, True),
        ("publish.youtube", 0, True),
        ("stock.license", 0, True),
        ("delivery.file", 0, False),
        ("task.agent_05.script_draft", 10, True),  # paid and no review threshold configured
        ("task.agent_10.render", 0, False),
    ],
)
def test_replay_approval_requirement(scope: str, cost: int, needs: bool) -> None:
    item = _item(idempotency_scope=scope, estimated_cost_micros=cost)
    assert dlq.needs_replay_approval(item, CFG) is needs


def test_replay_cost_threshold_when_configured() -> None:
    cfg = load_settings(environ={"AMW_DLQ__REPLAY_COST_REVIEW_MICROS": "100"})
    assert not dlq.needs_replay_approval(_item(estimated_cost_micros=100), cfg)
    assert dlq.needs_replay_approval(_item(estimated_cost_micros=101), cfg)


def test_side_effect_replay_needs_an_approval_row() -> None:
    item = _item(idempotency_scope="upload.youtube")
    item = dlq.request_replay(dlq.triage(item, OWNER, "n", ALL, T0), OWNER, ALL, T0)
    with pytest.raises(PermissionDeniedError):
        dlq.approve_replay(item, OWNER, ALL, CFG, T0)
    approved = dlq.approve_replay(item, OWNER, ALL, CFG, T0, APPROVAL.new())
    assert approved.replay_approval_id is not None
    assert dlq.plan_replay(approved, CFG).reconcile_first


def test_replay_cap_is_reached_once() -> None:
    item = replace(
        _item(),
        recovery_status=DlqRecoveryStatus.REPLAY_APPROVED,
        root_cause_note="n",
        replay_count=3,
    )
    with pytest.raises(LoopCapExceededError):
        dlq.plan_replay(item, CFG)


def test_bulk_replay_batches() -> None:
    items = [_item() for _ in range(5)]
    with pytest.raises(PermissionDeniedError):
        dlq.bulk_replay_batches(items, CFG)
    cfg = load_settings(environ={"AMW_DLQ__BULK_REPLAY_MAX": "2"})
    assert [len(b) for b in dlq.bulk_replay_batches(items, cfg)] == [2, 2, 1]
    with pytest.raises(InputInvalidError):
        dlq.bulk_replay_batches([_item(), _item("AGENT.CRASH")], cfg)


def test_replayed_delivery_performs_the_effect_once() -> None:
    """Same Task Input, same idempotency key: the completed effect is returned, not repeated."""
    org = ORG.new()
    tx = tx_for(org)
    store = MemoryIdempotencyStore()
    key = make_idempotency_key(org, "delivery.file", ["job_1", "yt_master_1080p", SHA])
    effects: list[str] = []

    def deliver() -> str:
        decision = store.begin(tx, key, "delivery.file", SHA, None, T0, 60_000)
        if decision.action is BeginAction.RETURN_STORED:
            return decision.record.result_ref or ""
        assert decision.action is BeginAction.PROCEED
        effects.append("bundle")
        return store.complete(tx, key, "amw-entity://x/publications/p1", T0).result_ref or ""

    first = deliver()
    item = _item(
        "INFRASTRUCTURE.STORAGE_UNAVAILABLE", idempotency_key=key, idempotency_scope="delivery.file"
    )
    item = dlq.approve_replay(
        dlq.request_replay(dlq.triage(item, OWNER, "n", ALL, T0), OWNER, ALL, T0),
        OWNER,
        ALL,
        CFG,
        T0,
    )
    plan = dlq.plan_replay(item, CFG)
    assert plan.idempotency_key == key
    assert plan.reconcile_first
    assert deliver() == first
    assert effects == ["bundle"]
