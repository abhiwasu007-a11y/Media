"""In-memory IdempotencyStore / CheckpointStore fakes follow 03 section 9.1 rule 3 and 04 5.7."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from amw_core import ids
from amw_core.enums import IdempotencyStatus
from amw_core.errors import IdempotencyConflictError, InputInvalidError, InvalidTransitionError
from amw_core.interfaces import (
    BeginAction,
    CheckpointStore,
    IdempotencyStore,
    NewCheckpoint,
    TenantContext,
)
from amw_core.testing.memory import (
    MemoryCheckpointStore,
    MemoryIdempotencyStore,
    MemoryTransaction,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def tx(org: ids.OrgId | None = None) -> MemoryTransaction:
    return MemoryTransaction(TenantContext(org or ids.ORG.new(), ids.ActorRef("agent_01")))


def test_fakes_satisfy_protocols() -> None:
    idem: IdempotencyStore = MemoryIdempotencyStore()
    ckpt: CheckpointStore = MemoryCheckpointStore()
    assert isinstance(idem, IdempotencyStore)
    assert isinstance(ckpt, CheckpointStore)


def test_idempotency_lifecycle() -> None:
    store = MemoryIdempotencyStore(default_retention=timedelta(days=30))
    t = tx()
    key = ids.make_idempotency_key(t.context.org_id, "llm.call", ["tsk", "s", 1])
    first = store.begin(t, key, "llm.call", "a" * 64, None, NOW, 1000)
    assert first.action is BeginAction.PROCEED
    assert first.record.expires_at == NOW + timedelta(days=30)
    assert (
        store.begin(t, key, "llm.call", "a" * 64, None, NOW, 1000).action is BeginAction.IN_FLIGHT
    )
    later = NOW + timedelta(seconds=5)
    assert (
        store.begin(t, key, "llm.call", "a" * 64, None, later, 1000).action is BeginAction.RECONCILE
    )
    with pytest.raises(IdempotencyConflictError):
        store.begin(t, key, "llm.call", "b" * 64, None, NOW, 1000)
    done = store.complete(t, key, "amw-blob://x", NOW)
    assert done.status is IdempotencyStatus.COMPLETED
    stored = store.begin(t, key, "llm.call", "a" * 64, None, NOW, 1000)
    assert stored.action is BeginAction.RETURN_STORED
    assert stored.record.result_ref == "amw-blob://x"
    with pytest.raises(IdempotencyConflictError):
        store.begin(t, key, "llm.call", "b" * 64, None, NOW, 1000)
    with pytest.raises(InvalidTransitionError):
        store.complete(t, key, "again", NOW)


def test_idempotency_failed_then_retry_and_tenant_isolation() -> None:
    store = MemoryIdempotencyStore()
    t = tx()
    key = ids.make_idempotency_key(t.context.org_id, "upload.youtube", ["chn", "sha"])
    rec = store.begin(t, key, "upload.youtube", "a" * 64, None, NOW, 1000).record
    assert rec.expires_at is None  # upload.* never expires
    assert store.fail(t, key, NOW).status is IdempotencyStatus.FAILED
    again = store.begin(t, key, "upload.youtube", "a" * 64, None, NOW, 1000)
    assert again.action is BeginAction.PROCEED
    assert store.get(tx(), key) is None  # other tenant sees nothing
    with pytest.raises(InvalidTransitionError):
        store.fail(tx(), key, NOW)


def test_idempotency_rejects_unknown_scope_and_bad_key() -> None:
    store = MemoryIdempotencyStore()
    t = tx()
    key = ids.make_idempotency_key(t.context.org_id, "llm.call", ["x"])
    with pytest.raises(InputInvalidError):
        store.begin(t, key, "made.up", "a" * 64, None, NOW, 1)
    with pytest.raises(InputInvalidError):
        store.begin(t, ids.IdempotencyKey("idk_bad"), "llm.call", "a" * 64, None, NOW, 1)


def _ckpt(task: ids.TaskId, step: str, ratio: str | None = None) -> NewCheckpoint:
    return NewCheckpoint(
        task_id=task,
        attempt_id=ids.ATTEMPT.new(),
        step_key=step,
        state_ref="amw-blob://x/state.json",
        state_sha256="c" * 64,
        completed_effects=(),
        progress_ratio=Decimal(ratio) if ratio else None,
    )


def test_checkpoints_seq_and_latest() -> None:
    store = MemoryCheckpointStore()
    t = tx()
    task = ids.TASK.new()
    first = store.write(t, _ckpt(task, "a", "0.250"), NOW)
    second = store.write(t, _ckpt(task, "b"), NOW)
    store.write(t, _ckpt(ids.TASK.new(), "other"), NOW)
    assert (first.seq, second.seq) == (1, 2)
    latest = store.latest(t, task)
    assert latest is not None
    assert latest.id == second.id
    assert [r.is_latest for r in store.list_for_task(t, task)] == [False, True]
    assert store.get(t, first.id) is not None
    assert store.get(tx(), first.id) is None
    assert store.latest(tx(), task) is None
    with pytest.raises(InputInvalidError):
        store.write(t, _ckpt(task, "c", "1.5"), NOW)


# --- owner instruction evidence (04 section 5.16, CCR-010) -------------------------------

from amw_core.enums import (  # noqa: E402
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    InstructionSourceKind,
)
from amw_core.interfaces import NewEvidence, OwnerEvidenceStore, SessionEvent  # noqa: E402
from amw_core.testing.memory import MemoryOwnerEvidenceStore  # noqa: E402


def _evidence(
    source: InstructionSourceKind = InstructionSourceKind.OWNER_CHAT_MESSAGE,
) -> NewEvidence:
    return NewEvidence(
        record_kind=EvidenceRecordKind.STEP_DECISION,
        subject_kind="render",
        subject_id=ids.new_id(ids.Prefix.RENDER),
        source_kind=source,
        session_id="session_x",
        event_uuid="event-1",
        quote="approve R7K2",
        message_at=NOW,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=ids.USER.new(),
        review_code="R7K2",
        parsed_decision=ApprovalStepState.APPROVED,
    )


def _event(uuid: str, at: datetime) -> SessionEvent:
    return SessionEvent("session_x", uuid, "user", False, "human", "yes", at)


def test_evidence_forward_only_lifecycle() -> None:
    store: OwnerEvidenceStore = MemoryOwnerEvidenceStore()
    t = tx()
    row = store.record(t, _evidence())
    assert row.state is EvidenceState.PENDING_VERIFICATION
    assert len(row.evidence_sha256) == 64
    with pytest.raises(InvalidTransitionError):
        store.confirm(t, row.id, _event("event-2", NOW + timedelta(minutes=1)))
    verified = store.mark_verified(t, row.id, {"role_user": True}, NOW)
    assert verified.state is EvidenceState.VERIFIED
    with pytest.raises(InvalidTransitionError):
        store.confirm(t, row.id, _event("event-1", NOW + timedelta(minutes=1)))  # same event
    with pytest.raises(InvalidTransitionError):
        store.confirm(t, row.id, _event("event-2", NOW))  # not later
    confirmed = store.confirm(t, row.id, _event("event-2", NOW + timedelta(minutes=1)))
    assert confirmed.state is EvidenceState.CONFIRMED
    with pytest.raises(InvalidTransitionError):
        store.refuse(t, row.id, "too late")
    assert store.for_subject(t, "render", row.evidence.subject_id) == [confirmed]
    assert store.get(tx(), row.id) is None


def test_evidence_replay_key_and_refusal() -> None:
    store = MemoryOwnerEvidenceStore()
    t = tx()
    first = store.record(t, _evidence())
    with pytest.raises(IdempotencyConflictError):
        store.record(t, first.evidence)
    refused = store.refuse(t, first.id, "ambiguous")
    assert refused.state is EvidenceState.REFUSED
    assert store.record(t, first.evidence).state is EvidenceState.PENDING_VERIFICATION


def test_non_owner_source_can_never_be_verified() -> None:
    store = MemoryOwnerEvidenceStore()
    t = tx()
    row = store.record(t, _evidence(InstructionSourceKind.TOOL_RESULT))
    with pytest.raises(InvalidTransitionError):
        store.mark_verified(t, row.id, {}, NOW)
    assert store.refuse(t, row.id, "not owner-authored").state is EvidenceState.REFUSED
