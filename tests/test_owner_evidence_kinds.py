"""Per-kind owner-evidence rules (DECISION / CONTENT / SCORE), all verified by the store.

DECISION kinds are covered in ``test_owner_evidence_verifier.py``; this file covers the table,
CONTENT and SCORE kinds, and "one owner message verifies exactly one subject".
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from amw_core import ids
from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.interfaces import OwnerEvidenceStore, TenantContext
from amw_core.owner_evidence_verifier import (
    DEFAULT_RECORD_KIND_RULES,
    NewEvidence,
    SessionEvent,
    VerificationKind,
    VerifierPolicy,
)
from amw_core.testing.memory import (
    MemoryOwnerEvidenceStore,
    MemorySessionEventSource,
    MemoryTransaction,
)

REQUESTED = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
SAID = REQUESTED + timedelta(minutes=5)
NOW = REQUESTED + timedelta(hours=1)
POLICY = VerifierPolicy(
    human_inbound_origins=frozenset({"human"}), owner_account_ids=frozenset({"acct-owner"})
)
JOB = ids.JOB.new()
SUBJECT = ids.new_id(ids.Prefix.SCRIPT)
RA = QualityDimension.RESEARCH_ACCURACY
ST = QualityDimension.STORYTELLING
CONTRIBUTION_TEXT = "Add the 2008 crash as the opening example, not 2020"
TEXT = CONTRIBUTION_TEXT


def event(content: str, uuid: str = "ev-1", **change: Any) -> SessionEvent:
    base = SessionEvent("ses-1", uuid, "user", False, "human", content, SAID, "acct-owner", None)
    return replace(base, **change)


def evidence(kind: EvidenceRecordKind, quote: str, **change: Any) -> NewEvidence:
    base = NewEvidence(
        record_kind=kind,
        subject_kind="script",
        subject_id=SUBJECT,
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        session_id="ses-1",
        event_uuid="ev-1",
        quote=quote,
        message_at=SAID,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=ids.USER.new(),
        job_id=JOB,
        review_code="R7K2",
    )
    return replace(base, **change)


def run(ev: SessionEvent, ne: NewEvidence, policy: VerifierPolicy = POLICY) -> Any:
    store = MemoryOwnerEvidenceStore(MemorySessionEventSource([ev]), policy)
    tx = MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))
    row = store.record(tx, ne)
    return store.verify_recorded(tx, row.id, REQUESTED, NOW)


def refused(record: Any, reason: str) -> None:
    assert record.state is EvidenceState.REFUSED, record
    assert record.refused_reason == reason


def test_every_record_kind_has_a_rule() -> None:
    assert set(DEFAULT_RECORD_KIND_RULES) == set(EvidenceRecordKind)
    assert DEFAULT_RECORD_KIND_RULES[EvidenceRecordKind.STEP_DECISION] is VerificationKind.DECISION
    assert DEFAULT_RECORD_KIND_RULES[EvidenceRecordKind.HUMAN_SCORE] is VerificationKind.SCORE


def test_kind_without_rule_is_refused() -> None:
    policy = replace(POLICY, record_kind_rules={})
    kind = EvidenceRecordKind.CONTRIBUTION
    message = f"R7K2 {CONTRIBUTION_TEXT}"
    refused(run(event(message), evidence(kind, CONTRIBUTION_TEXT), policy), "rule_defined")


# --- CONTENT kinds -------------------------------------------------------------------------

CONTENT_KINDS = [
    EvidenceRecordKind.CONTRIBUTION,
    EvidenceRecordKind.OWNER_TOPIC,
    EvidenceRecordKind.DATASET_INTAKE,
    EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST,
]


@pytest.mark.parametrize("kind", CONTENT_KINDS)
def test_content_with_review_code_is_verified(kind: EvidenceRecordKind) -> None:
    message = f"For R7K2: {CONTRIBUTION_TEXT}."
    assert run(event(message), evidence(kind, CONTRIBUTION_TEXT)).state is EvidenceState.VERIFIED


def test_content_with_job_reference_is_verified() -> None:
    message = f"{JOB} {CONTRIBUTION_TEXT}"
    ne = evidence(EvidenceRecordKind.CONTRIBUTION, CONTRIBUTION_TEXT, review_code=None)
    assert run(event(message), ne).state is EvidenceState.VERIFIED


@pytest.mark.parametrize(
    ("case", "message", "quote", "change", "reason"),
    [
        ("no subject reference", CONTRIBUTION_TEXT, CONTRIBUTION_TEXT, {}, "subject_reference"),
        ("code twice", f"R7K2 R7K2 {TEXT}", TEXT, {}, "subject_reference"),
        ("only a decision word", "R7K2 approve", "approve", {}, "content_present"),
        ("decision and reference only", "R7K2 approve", "R7K2 approve", {}, "content_present"),
        ("too short", "R7K2 make it shorter", "make it shorter", {}, "content_present"),
        ("not verbatim", f"R7K2 {TEXT}", TEXT.lower(), {}, "quote_verbatim"),
        ("decision recorded", f"R7K2 {CONTRIBUTION_TEXT}", CONTRIBUTION_TEXT,
         {"parsed_decision": ApprovalStepState.APPROVED}, "decision_not_applicable"),
    ],
)  # fmt: skip
def test_contribution_rejections(
    case: str, message: str, quote: str, change: dict[str, Any], reason: str
) -> None:
    ne = evidence(EvidenceRecordKind.CONTRIBUTION, quote, **change)
    refused(run(event(message), ne), reason)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"inbound_origin": "subagent"}, "human_origin"),
        ({"parent_session_id": "ses-0"}, "top_level_session"),
        ({"sender_account": "acct-other"}, "owner_account"),
        ({"is_synthetic": True}, "not_synthetic"),
        ({"timestamp": REQUESTED - timedelta(seconds=1)}, "timestamp_equal"),
    ],
)
def test_content_authenticity(change: dict[str, Any], reason: str) -> None:
    message = f"R7K2 {CONTRIBUTION_TEXT}"
    ne = evidence(EvidenceRecordKind.OWNER_TOPIC, CONTRIBUTION_TEXT)
    refused(run(event(message, **change), ne), reason)


def test_owner_topic_short_title_is_fine() -> None:
    # The 20-character minimum is the editorial-contribution rule only (04 5.16).
    ne = evidence(EvidenceRecordKind.OWNER_TOPIC, "RSI divergence")
    assert run(event("R7K2 RSI divergence"), ne).state is EvidenceState.VERIFIED


# --- SCORE kinds ---------------------------------------------------------------------------


def score_evidence(*scores: tuple[QualityDimension, str], **change: Any) -> NewEvidence:
    parsed = tuple((d, Decimal(p)) for d, p in scores)
    quote = change.pop("quote", "R7K2")
    return evidence(EvidenceRecordKind.HUMAN_SCORE, quote, scores=parsed, **change)


def test_scores_stated_exactly_are_verified() -> None:
    message = "R7K2 research_accuracy 18, storytelling: 12.5"
    ne = score_evidence((RA, "18"), (ST, "12.5"))
    assert run(event(message), ne).state is EvidenceState.VERIFIED


@pytest.mark.parametrize(
    ("case", "message", "scores", "reason"),
    [
        ("inferred number", "R7K2 research_accuracy good", [(RA, "18")], "scores_stated"),
        ("other number", "R7K2 research_accuracy 17", [(RA, "18")], "scores_stated"),
        ("dimension missing", "R7K2 research_accuracy 18", [(RA, "18"), (ST, "12")],
         "scores_stated"),
        ("dimension stated twice", "R7K2 research_accuracy 18 research_accuracy 19", [(RA, "18")],
         "scores_stated"),
        ("duplicate claim", "R7K2 research_accuracy 18", [(RA, "18"), (RA, "18")], "scores_stated"),
        ("over the dimension max", "R7K2 storytelling 16", [(ST, "16")], "scores_in_range"),
        ("negative", "R7K2 storytelling -1", [(ST, "-1")], "scores_in_range"),
        ("three decimals", "R7K2 storytelling 12.125", [(ST, "12.125")], "scores_in_range"),
        ("no scores", "R7K2 nice", [], "scores_given"),
        ("no subject reference", "research_accuracy 18", [(RA, "18")], "subject_reference"),
    ],
)  # fmt: skip
def test_score_rejections(
    case: str, message: str, scores: list[tuple[QualityDimension, str]], reason: str
) -> None:
    ne = score_evidence(*scores, quote=message.split()[0])
    refused(run(event(message), ne), reason)


def test_score_with_decision_is_refused() -> None:
    ne = score_evidence((RA, "18"), parsed_decision=ApprovalStepState.APPROVED)
    refused(run(event("R7K2 research_accuracy 18"), ne), "decision_not_applicable")


def test_scores_are_bound_into_the_evidence_hash() -> None:
    store = MemoryOwnerEvidenceStore(MemorySessionEventSource([]), POLICY)
    tx = MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))
    a = store.record(tx, score_evidence((RA, "18")))
    b = store.record(tx, score_evidence((RA, "19"), subject_id=ids.new_id(ids.Prefix.SCRIPT)))
    assert a.evidence_sha256 != b.evidence_sha256


# --- one owner message, one subject --------------------------------------------------------


def test_one_message_verifies_exactly_one_subject() -> None:
    message = f"R7K2 {CONTRIBUTION_TEXT}"
    store: OwnerEvidenceStore = MemoryOwnerEvidenceStore(
        MemorySessionEventSource([event(message)]), POLICY
    )
    tx = MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))
    first = store.record(tx, evidence(EvidenceRecordKind.CONTRIBUTION, CONTRIBUTION_TEXT))
    assert store.verify_recorded(tx, first.id, REQUESTED, NOW).state is EvidenceState.VERIFIED
    other_subject = evidence(
        EvidenceRecordKind.CONTRIBUTION, CONTRIBUTION_TEXT, subject_id=ids.new_id(ids.Prefix.SCRIPT)
    )
    second = store.record(tx, other_subject)
    refused(store.verify_recorded(tx, second.id, REQUESTED, NOW), "one_subject_per_message")


def test_content_confirmation_needs_subject_reference() -> None:
    later = SAID + timedelta(minutes=1)
    events = [
        event(f"R7K2 {TEXT}"),
        event("yes that is right", uuid="ev-2", timestamp=later),
        event("R7K2 yes that is right", uuid="ev-3", timestamp=later),
    ]
    store = MemoryOwnerEvidenceStore(MemorySessionEventSource(events), POLICY)
    tx = MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))
    row = store.record(tx, evidence(EvidenceRecordKind.CONTRIBUTION, TEXT))
    store.verify_recorded(tx, row.id, REQUESTED, NOW)
    from amw_core.errors import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        store.confirm(tx, row.id, "ses-1", "ev-2", "yes", NOW)
    assert store.confirm(tx, row.id, "ses-1", "ev-3", "yes", NOW).state is EvidenceState.CONFIRMED
