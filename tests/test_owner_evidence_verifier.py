"""R14 owner-evidence verification (03 11.6 rule 6; 04 5.16; CCR-010, D5).

The store verifies: it fetches events through its own source and runs the check itself. Every
rejection has a negative test, including the strict decision grammar (negations, ambiguity).
"""

import copy
import dataclasses
import inspect
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

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
from amw_core.interfaces import TenantContext
from amw_core.owner_evidence_fake import MemorySessionEventSource
from amw_core.owner_evidence_verifier import (
    DEFAULT_DECISION_WORDS,
    NEEDS_CLARIFICATION,
    RECORD,
    EventUnavailable,
    NewEvidence,
    Refusal,
    SessionEvent,
    Verified,
    VerifierPolicy,
    evidence_sha256,
    read_decision,
    verify_owner_event,
)
from amw_core.testing.memory import MemoryTransaction
from tests.evidence_support import EvidenceHarness

REQUESTED = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
SAID = REQUESTED + timedelta(minutes=5)
NOW = REQUESTED + timedelta(hours=1)
SECOND = timedelta(seconds=1)
POLICY = VerifierPolicy(
    human_inbound_origins=frozenset({"human"}),
    owner_account_ids=frozenset({"acct-owner"}),
    content_max_age_ms=24 * 3600 * 1000,
    decision_words=DEFAULT_DECISION_WORDS,
)
SUBJECT = ids.new_id(ids.Prefix.RENDER)
OWNER = ids.USER.new()
APPROVED = ApprovalStepState.APPROVED


def event(uuid: str = "ev-1", **change: Any) -> SessionEvent:
    base = SessionEvent(
        "ses-1", uuid, "user", False, "human", "Approve R7K2 please", SAID, "acct-owner", None
    )
    return replace(base, **change)


def evidence(**change: Any) -> NewEvidence:
    base = NewEvidence(
        record_kind=EvidenceRecordKind.STEP_DECISION,
        subject_kind="render",
        subject_id=SUBJECT,
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        session_id="ses-1",
        event_uuid="ev-1",
        quote="Approve R7K2",
        message_at=SAID,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=OWNER,
        review_code="R7K2",
        parsed_decision=APPROVED,
    )
    return replace(base, **change)


def late(**change: Any) -> SessionEvent:
    return event("ev-2", timestamp=NOW, **change)


def new_store(*events: SessionEvent) -> tuple[EvidenceHarness, MemoryTransaction]:
    store = EvidenceHarness(MemorySessionEventSource(events), POLICY)
    tx = MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))
    return store, tx


def verify_via_store(ev: SessionEvent | None, ne: NewEvidence | None = None) -> Any:
    store, tx = new_store(*([ev] if ev else []))
    row = store.record(tx, ne or evidence())
    return store.verify_recorded(tx, row.id, REQUESTED, NOW)


def refused_with(record: Any, reason: str) -> None:
    assert record.state is EvidenceState.REFUSED
    assert record.refused_reason == reason
    assert record.verifier_result[reason] is False


# --- the happy path ------------------------------------------------------------------------


def test_store_verifies_and_confirms() -> None:
    confirmation = event("ev-2", content="R7K2 confirmed", timestamp=SAID + SECOND)
    store, tx = new_store(event(), confirmation)
    row = store.record(tx, evidence())
    with pytest.raises(InvalidTransitionError):
        store.confirm(tx, row.id, "ses-1", "ev-2", "confirmed", NOW)  # not verified yet
    verified = store.verify_recorded(tx, row.id, REQUESTED, NOW)
    assert verified.state is EvidenceState.VERIFIED
    assert all(verified.verifier_result.values())
    confirmed = store.confirm(tx, row.id, "ses-1", "ev-2", "confirmed", NOW)
    assert confirmed.state is EvidenceState.CONFIRMED
    assert confirmed.confirmation_message_at == SAID + SECOND
    with pytest.raises(InvalidTransitionError):
        store.verify_recorded(tx, row.id, REQUESTED, NOW)
    with pytest.raises(InvalidTransitionError):
        store.refuse(tx, row.id, "late")
    with pytest.raises(InvalidTransitionError):
        store.confirm(tx, row.id, "ses-1", "ev-2", "confirmed", NOW)


@pytest.mark.parametrize(
    ("content", "quote", "decision"),
    [
        ("R7K2 मंजूर", "मंजूर", APPROVED),
        ("R7K2: approved.", "approved", APPROVED),
        ("reject R7K2", "reject", ApprovalStepState.REJECTED),
        ("R7K2 नामंजूर", "नामंजूर", ApprovalStepState.REJECTED),
        ("Approve R7K2 please 👍", "Approve R7K2", APPROVED),
        ("R7K2 go ahead, thanks", "go ahead", APPROVED),
    ],
)
def test_grammar_accepts(content: str, quote: str, decision: ApprovalStepState) -> None:
    ne = evidence(quote=quote, parsed_decision=decision)
    assert verify_via_store(event(content=content), ne).state is EvidenceState.VERIFIED


# --- every rejection ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "ev", "reason"),
    [
        ("sub-agent message", event(inbound_origin="subagent"), "human_origin"),
        ("peer session message", event(inbound_origin="peer_session"), "human_origin"),
        ("notification", event(inbound_origin="notification"), "human_origin"),
        ("tool result as a user turn", event(inbound_origin="tool_result"), "human_origin"),
        ("document", event(inbound_origin="document"), "human_origin"),
        ("tool-result role", event(role="tool"), "role_user"),
        ("assistant role", event(role="assistant"), "role_user"),
        ("synthetic event", event(is_synthetic=True), "not_synthetic"),
        ("another account", event(sender_account="acct-guest"), "owner_account"),
        ("child / sub-agent session", event(parent_session_id="ses-0"), "top_level_session"),
        ("quote not a substring", event(content="R7K2 approve"), "quote_verbatim"),
        ("altered timestamp", event(timestamp=SAID + SECOND), "timestamp_equal"),
    ],
)
def test_event_rejections(case: str, ev: SessionEvent, reason: str) -> None:
    refused_with(verify_via_store(ev), reason)


def test_event_not_found_keeps_the_row_pending() -> None:
    store, tx = new_store()
    row = store.record(tx, evidence())
    with pytest.raises(MissingDependencyError):
        store.verify_recorded(tx, row.id, REQUESTED, NOW)
    current = store.get(tx, row.id)
    assert current is not None
    assert current.state is EvidenceState.PENDING_VERIFICATION


def test_message_order_violated() -> None:
    early = REQUESTED - SECOND
    refused_with(
        verify_via_store(event(timestamp=early), evidence(message_at=early)), "message_order"
    )


def test_superseding_evidence_must_be_later() -> None:
    store, tx = new_store(event(), event("ev-0"))
    older = store.record(tx, evidence())
    store.refuse(tx, older.id, "corrected")
    newer = store.record(tx, evidence(event_uuid="ev-0", supersedes_id=older.id))
    refused_with(store.verify_recorded(tx, newer.id, REQUESTED, NOW), "message_order")


def test_replay_of_the_same_event_for_another_subject() -> None:
    other = evidence(subject_id=ids.new_id(ids.Prefix.RENDER), review_code="Q9Z3")
    refused_with(verify_via_store(event(), other), NEEDS_CLARIFICATION)


@pytest.mark.parametrize(
    ("field", "reason"),
    [("review_code", "review_code_given"), ("parsed_decision", "decision_given")],
)
def test_review_code_and_decision_are_mandatory(field: str, reason: str) -> None:
    refused_with(verify_via_store(event(), evidence(**{field: None})), reason)


def test_decision_mismatch() -> None:
    ne = evidence(parsed_decision=ApprovalStepState.REJECTED)
    refused_with(verify_via_store(event(), ne), "decision_matches")


def test_non_owner_source_is_refused() -> None:
    record = verify_via_store(event(), evidence(source_kind=InstructionSourceKind.TOOL_RESULT))
    assert record.state is EvidenceState.REFUSED


@pytest.mark.parametrize(
    "content",
    [
        "R7K2 do not approve",
        "R7K2 not approved",
        "R7K2 don't approve",
        "R7K2 मंजूर नाही",
        "approve R7K2 or reject?",
        "R7K2 approve, no wait",
        "approve R7K2 नामंजूर",
        "R7K2 looks fine to me, approve",
        "R7K2 approvement",
        "R7K2 R7K2 approve",
        "XR7K2 approve",
        "R7K2",
        "R7K2 approve approved",
    ],
)
def test_strict_grammar_refuses(content: str) -> None:
    assert read_decision(content, "R7K2", POLICY) is None
    refused_with(
        verify_via_store(event(content=content), evidence(quote="R7K2")), NEEDS_CLARIFICATION
    )


@pytest.mark.parametrize(
    ("case", "confirmation", "error"),
    [
        ("same event again", event(), PermissionDeniedError),
        ("not later", event("ev-2", timestamp=SAID), PermissionDeniedError),
        ("synthetic", late(is_synthetic=True), PermissionDeniedError),
        ("sub-agent", late(inbound_origin="subagent"), PermissionDeniedError),
        ("no review code", late(content="approve"), PermissionDeniedError),
        ("other decision", late(content="R7K2 reject"), PermissionDeniedError),
        ("extra words", late(content="R7K2 approve, confirmed"), PermissionDeniedError),
        ("negated", late(content="R7K2 not approve"), PermissionDeniedError),
        ("deferred", late(content="R7K2 approve tomorrow"), PermissionDeniedError),
        ("not found", None, MissingDependencyError),
    ],
)  # fmt: skip
def test_confirmation_rejections(
    case: str, confirmation: SessionEvent | None, error: type[Exception]
) -> None:
    store, tx = new_store(event(), *([confirmation] if confirmation else []))
    row = store.record(tx, evidence())
    store.verify_recorded(tx, row.id, REQUESTED, NOW)
    uuid = confirmation.event_uuid if confirmation else "ev-missing"
    quote = (confirmation.content if confirmation else "x")[:4]
    with pytest.raises(error):
        store.confirm(tx, row.id, "ses-1", uuid, quote, NOW)
    current = store.get(tx, row.id)
    assert current is not None
    assert current.state is EvidenceState.VERIFIED, case


# --- the store, not a proof object, authorises ----------------------------------------------


def test_no_public_method_accepts_a_proof() -> None:
    from amw_core.interfaces import EvidenceDatabase
    from amw_core.owner_evidence_service import EvidenceVerifierService

    for cls in (EvidenceDatabase, EvidenceVerifierService):
        for name, member in inspect.getmembers(cls, inspect.isfunction):
            if name.startswith("_"):
                continue
            for annotation in inspect.get_annotations(member).values():
                assert "Verified" not in str(annotation), name
                assert "SessionEvent" not in str(annotation), name


def test_forged_verification_result_changes_nothing() -> None:
    store, tx = new_store()  # the store's source has no event at all
    row = store.record(tx, evidence())
    forged = verify_owner_event(
        event(),  # a made-up event handed to the public pure function
        evidence=evidence(),
        evidence_id=row.id,
        purpose=RECORD,
        quote="Approve R7K2",
        message_at=SAID,
        anchor=REQUESTED,
        distinct_from_event_uuid=None,
        policy=POLICY,
        now=NOW,
    )
    assert isinstance(forged, Verified)  # Python cannot stop anyone building this value ...
    with pytest.raises(MissingDependencyError):
        store.verify_recorded(tx, row.id, REQUESTED, NOW)  # ... but the store checks itself
    current = store.get(tx, row.id)
    assert current is not None
    assert current.state is EvidenceState.PENDING_VERIFICATION


def test_verified_value_is_immutable_and_bound() -> None:
    outcome = verify_owner_event(
        event(),
        evidence=evidence(),
        evidence_id=ids.OWNER_EVIDENCE.new(),
        purpose=RECORD,
        quote="Approve R7K2",
        message_at=SAID,
        anchor=REQUESTED,
        distinct_from_event_uuid=None,
        policy=POLICY,
        now=NOW,
    )
    assert isinstance(outcome, Verified)
    assert outcome.bound_sha256 == evidence_sha256(evidence())
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.evidence_id = ids.OWNER_EVIDENCE.new()  # type: ignore[misc]
    assert not hasattr(outcome, "__dict__")
    assert copy.copy(outcome) == outcome  # a copy is just an equal value; it authorises nothing
    assert isinstance(outcome.checks, tuple)
    assert outcome.event_uuid == "ev-1"


def test_unfetchable_event_outcome() -> None:
    outcome = verify_owner_event(
        None,
        evidence=evidence(event_uuid="ev-9"),
        evidence_id=ids.OWNER_EVIDENCE.new(),
        purpose=RECORD,
        quote="q",
        message_at=SAID,
        anchor=REQUESTED,
        distinct_from_event_uuid=None,
        policy=POLICY,
        now=NOW,
    )
    assert outcome == EventUnavailable("ses-1", "ev-9")
    assert not isinstance(outcome, Refusal)


def test_replay_key_and_tenant_isolation() -> None:
    store, tx = new_store(event())
    first = store.record(tx, evidence())
    with pytest.raises(IdempotencyConflictError):
        store.record(tx, evidence())
    assert store.refuse(tx, first.id, "ambiguous").state is EvidenceState.REFUSED
    assert store.record(tx, evidence()).state is EvidenceState.PENDING_VERIFICATION
    assert len(store.for_subject(tx, "render", SUBJECT)) == 2
    other = MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))
    assert store.get(other, first.id) is None
    with pytest.raises(MissingDependencyError):
        store.verify_recorded(other, first.id, REQUESTED, NOW)
