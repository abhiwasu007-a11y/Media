"""R14 owner-evidence verification is enforced in code (03 11.6 rule 6; 04 5.16; CCR-010, D5).

Every rejection the reviewer listed has a negative test; the store accepts only sealed
verifier output and fetches confirmation events itself.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from amw_core import ids
from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    InstructionSourceKind,
)
from amw_core.errors import (
    IdempotencyConflictError,
    InvalidTransitionError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.interfaces import OwnerEvidenceStore, SessionEventSource, TenantContext
from amw_core.owner_evidence_verifier import (
    CONFIRMATION,
    EventUnavailable,
    NewEvidence,
    Refusal,
    SessionEvent,
    VerifiedEvidence,
    VerifierPolicy,
    decisions_in,
    evidence_sha256,
    verify_owner_event,
    verify_recorded_evidence,
)
from amw_core.testing.memory import (
    MemoryOwnerEvidenceStore,
    MemorySessionEventSource,
    MemoryTransaction,
)

REQUESTED = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
SAID = REQUESTED + timedelta(minutes=5)
NOW = REQUESTED + timedelta(hours=1)
SECOND = timedelta(seconds=1)
POLICY = VerifierPolicy(
    human_inbound_origins=frozenset({"human"}),
    decision_words={
        "approve": ApprovalStepState.APPROVED,
        "मंजूर": ApprovalStepState.APPROVED,
        "reject": ApprovalStepState.REJECTED,
        "changes": ApprovalStepState.CHANGES_REQUESTED,
    },
)
SUBJECT = ids.new_id(ids.Prefix.RENDER)
OWNER = ids.USER.new()


def event(
    uuid: str = "ev-1",
    content: str = "R7K2 approve the final video",
    at: datetime = SAID,
    **change: object,
) -> SessionEvent:
    base = SessionEvent("ses-1", uuid, "user", False, "human", content, at)
    return replace(base, **change)  # type: ignore[arg-type]


def evidence(**change: object) -> NewEvidence:
    base = NewEvidence(
        record_kind=EvidenceRecordKind.STEP_DECISION,
        subject_kind="render",
        subject_id=SUBJECT,
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        session_id="ses-1",
        event_uuid="ev-1",
        quote="R7K2 approve",
        message_at=SAID,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=OWNER,
        review_code="R7K2",
        parsed_decision=ApprovalStepState.APPROVED,
    )
    return replace(base, **change)  # type: ignore[arg-type]


def verify(
    ev: SessionEvent | None,
    ne: NewEvidence | None = None,
    superseded: datetime | None = None,
) -> object:
    source = MemorySessionEventSource([ev] if ev else [])
    return verify_recorded_evidence(
        source,
        ne or evidence(),
        POLICY,
        request_created_at=REQUESTED,
        superseded_message_at=superseded,
        now=NOW,
    )


def refused_by(outcome: object) -> str:
    assert isinstance(outcome, Refusal), outcome
    failed = [name for name, ok in outcome.checks.items() if not ok]
    assert outcome.reason.endswith(failed[0])
    return failed[0]


def test_valid_owner_message_is_verified() -> None:
    outcome = verify(event())
    assert isinstance(outcome, VerifiedEvidence)
    assert all(outcome.checks.values())
    assert outcome.bound_sha256 == evidence_sha256(evidence())
    assert outcome.event_timestamp == SAID


def test_devanagari_decision_word() -> None:
    ev = event(content="R7K2 मंजूर आहे")
    assert isinstance(verify(ev, evidence(quote="मंजूर")), VerifiedEvidence)


@pytest.mark.parametrize(
    ("case", "ev", "expected"),
    [
        ("sub-agent message", event(inbound_origin="subagent"), "human_origin"),
        ("peer session message", event(inbound_origin="peer_session"), "human_origin"),
        ("notification", event(inbound_origin="notification"), "human_origin"),
        ("tool result as user turn", event(inbound_origin="tool_result"), "human_origin"),
        ("document", event(inbound_origin="document"), "human_origin"),
        ("tool-result role", event(role="tool"), "role_user"),
        ("assistant role", event(role="assistant"), "role_user"),
        ("synthetic event", event(is_synthetic=True), "not_synthetic"),
        ("quote not in content", event(content="approve R7K2"), "quote_verbatim"),
        ("altered timestamp", event(at=SAID + timedelta(seconds=1)), "timestamp_equal"),
        ("before the request", event(at=REQUESTED - timedelta(minutes=1)), "timestamp_equal"),
    ],
)
def test_rejections(case: str, ev: SessionEvent, expected: str) -> None:
    assert refused_by(verify(ev)) == expected, case


def test_message_order_violated() -> None:
    early = REQUESTED - timedelta(minutes=1)
    outcome = verify(event(at=early), evidence(message_at=early))
    assert refused_by(outcome) == "message_order"
    # later than the request but not later than the evidence it supersedes
    assert refused_by(verify(event(), superseded=SAID)) == "message_order"


def test_event_not_found_stays_pending() -> None:
    outcome = verify(None)
    assert isinstance(outcome, EventUnavailable)


def test_wrong_event_returned_by_source() -> None:
    class Liar:
        def fetch(self, session_id: str, event_uuid: str) -> SessionEvent | None:
            return event(uuid="ev-other")

    assert isinstance(Liar(), SessionEventSource)
    outcome = verify_recorded_evidence(
        Liar(),
        evidence(),
        POLICY,
        request_created_at=REQUESTED,
        superseded_message_at=None,
        now=NOW,
    )
    assert refused_by(outcome) == "event_identity"


def test_replay_of_the_same_event_for_another_subject() -> None:
    # Another approval has another review code; the old message does not contain it.
    other = evidence(subject_id=ids.new_id(ids.Prefix.RENDER), review_code="Q9Z1")
    assert refused_by(verify(event(), other)) == "review_code_present"


@pytest.mark.parametrize(
    ("content", "decision"),
    [
        ("R7K2 reject this", ApprovalStepState.APPROVED),
        ("R7K2 approve or reject?", ApprovalStepState.APPROVED),
        ("R7K2 approvement", ApprovalStepState.APPROVED),
        ("R7K2 approve", ApprovalStepState.REJECTED),
    ],
)
def test_decision_mismatch(content: str, decision: ApprovalStepState) -> None:
    outcome = verify(event(content=content), evidence(quote="R7K2", parsed_decision=decision))
    assert refused_by(outcome) == "decision_matches"


def test_review_code_must_be_a_whole_token() -> None:
    outcome = verify(event(content="XR7K2 approve"), evidence(quote="approve"))
    assert refused_by(outcome) == "review_code_present"


def test_non_owner_source_is_refused_without_fetch() -> None:
    outcome = verify(event(), evidence(source_kind=InstructionSourceKind.TOOL_RESULT))
    assert isinstance(outcome, Refusal)
    assert outcome.checks == {"source": False}


def test_decisions_in() -> None:
    assert decisions_in("Approve!", POLICY) == {ApprovalStepState.APPROVED}
    assert decisions_in("unapproved", POLICY) == frozenset()


def test_verified_evidence_cannot_be_forged() -> None:
    with pytest.raises(TypeError):
        VerifiedEvidence(
            object(),
            purpose="RECORD",
            bound_sha256="0" * 64,
            event=event(),
            checks={},
            verified_at=NOW,
        )


# --- the store ---------------------------------------------------------------------------


def setup(*events: SessionEvent) -> tuple[OwnerEvidenceStore, MemoryTransaction]:
    store = MemoryOwnerEvidenceStore(MemorySessionEventSource(events), POLICY)
    return store, MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))


def verified_for(ne: NewEvidence, ev: SessionEvent) -> VerifiedEvidence:
    outcome = verify(ev, ne)
    assert isinstance(outcome, VerifiedEvidence)
    return outcome


def test_two_phase_lifecycle() -> None:
    confirmation = event(uuid="ev-2", content="R7K2 yes, confirmed", at=SAID + timedelta(minutes=2))
    store, t = setup(event(), confirmation)
    row = store.record(t, evidence())
    with pytest.raises(InvalidTransitionError):
        store.confirm(t, row.id, "ses-1", "ev-2", "confirmed", NOW)  # not verified yet
    verified = store.mark_verified(t, row.id, verified_for(evidence(), event()))
    assert verified.state is EvidenceState.VERIFIED
    assert verified.verifier_result["human_origin"] is True
    confirmed = store.confirm(t, row.id, "ses-1", "ev-2", "confirmed", NOW)
    assert confirmed.state is EvidenceState.CONFIRMED
    assert confirmed.confirmation_message_at == SAID + timedelta(minutes=2)
    with pytest.raises(InvalidTransitionError):
        store.refuse(t, row.id, "too late")
    with pytest.raises(InvalidTransitionError):
        store.mark_verified(t, row.id, verified_for(evidence(), event()))


def test_mark_verified_rejects_proof_of_another_row() -> None:
    store, t = setup(event())
    row = store.record(t, evidence())
    other = evidence(quote="approve")  # different evidence_sha256
    with pytest.raises(InvalidTransitionError):
        store.mark_verified(t, row.id, verified_for(other, event()))
    confirmation = verify_owner_event(
        event(),
        purpose=CONFIRMATION,
        bound_sha256=row.evidence_sha256,
        session_id="ses-1",
        event_uuid="ev-1",
        quote="R7K2",
        message_at=None,
        review_code=None,
        parsed_decision=None,
        not_before=REQUESTED,
        distinct_from_event_uuid=None,
        policy=POLICY,
        now=NOW,
    )
    assert isinstance(confirmation, VerifiedEvidence)
    with pytest.raises(InvalidTransitionError):
        store.mark_verified(t, row.id, confirmation)  # wrong purpose
    with pytest.raises(InvalidTransitionError):
        store.mark_verified(t, row.id, {"role_user": True})  # type: ignore[arg-type]


def later(**change: object) -> SessionEvent:
    return replace(event(uuid="ev-2", at=NOW), **change)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("case", "confirmation", "error"),
    [
        ("same event again", event(), PermissionDeniedError),
        ("earlier than the record", later(timestamp=SAID - SECOND), PermissionDeniedError),
        ("synthetic", later(is_synthetic=True), PermissionDeniedError),
        ("from a sub-agent", later(inbound_origin="subagent"), PermissionDeniedError),
        ("without review code", later(content="yes confirmed"), PermissionDeniedError),
        ("not found", None, MissingDependencyError),
    ],
)  # fmt: skip
def test_confirmation_rejections(
    case: str, confirmation: SessionEvent | None, error: type[Exception]
) -> None:
    events = [event()] + ([confirmation] if confirmation else [])
    store, t = setup(*events)
    row = store.record(t, evidence())
    store.mark_verified(t, row.id, verified_for(evidence(), event()))
    uuid = confirmation.event_uuid if confirmation else "ev-missing"
    content = confirmation.content if confirmation else "R7K2"
    quote = "R7K2" if "R7K2" in content else "confirmed"
    with pytest.raises(error):
        store.confirm(t, row.id, "ses-1", uuid, quote, NOW)
    current = store.get(t, row.id)
    assert current is not None
    assert current.state is EvidenceState.VERIFIED, case


def test_replay_key_and_refusal() -> None:
    store, t = setup(event())
    first = store.record(t, evidence())
    with pytest.raises(IdempotencyConflictError):
        store.record(t, evidence())
    assert store.refuse(t, first.id, "ambiguous").state is EvidenceState.REFUSED
    assert store.record(t, evidence()).state is EvidenceState.PENDING_VERIFICATION
    assert len(store.for_subject(t, "render", SUBJECT)) == 2
    other_tenant = MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))
    assert store.get(other_tenant, first.id) is None
