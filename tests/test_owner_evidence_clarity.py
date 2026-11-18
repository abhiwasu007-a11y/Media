"""Negation, withholding, questions and deferred wording never verify (PR #13 review round 4).

Lists are configuration (defaults marked owner to confirm); tokens match whole words on
normalised text.
"""

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
from amw_core.interfaces import TenantContext
from amw_core.owner_evidence_verifier import (
    DEFAULT_RECORD_KIND_RULES,
    NEEDS_CLARIFICATION,
    NEGATION_OR_WITHHOLDING,
    QUESTION_OR_DEFERRED,
    NewEvidence,
    SessionEvent,
    VerificationKind,
    VerifierPolicy,
    clarity_problem,
    normalise,
    tokens,
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
RSQ = chr(0x2019)  # right single quotation mark
MLA = chr(0x02BC)  # modifier letter apostrophe
FWQ = chr(0xFF1F)  # full-width question mark
A = ApprovalStepState.APPROVED
R = ApprovalStepState.REJECTED
C = ApprovalStepState.CHANGES_REQUESTED
OK = "VERIFIED"
NEG = NEGATION_OR_WITHHOLDING
ASK = QUESTION_OR_DEFERRED


def run(content: str, kind: EvidenceRecordKind, quote: str, decision: Any) -> Any:
    ev = SessionEvent("ses-1", "ev-1", "user", False, "human", content, SAID, "acct-owner", None)
    ne = NewEvidence(
        record_kind=kind,
        subject_kind="script",
        subject_id=ids.new_id(ids.Prefix.SCRIPT),
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        session_id="ses-1",
        event_uuid="ev-1",
        quote=quote,
        message_at=SAID,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=ids.USER.new(),
        job_id=ids.JOB.new(),
        review_code="R7K2",
        parsed_decision=decision,
    )
    store = MemoryOwnerEvidenceStore(MemorySessionEventSource([ev]), POLICY)
    tx = MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))
    row = store.record(tx, ne)
    return store.verify_recorded(tx, row.id, REQUESTED, NOW)


def outcome(record: Any) -> str:
    if record.state is EvidenceState.VERIFIED:
        return OK
    assert record.state is EvidenceState.REFUSED
    return str(record.refused_reason)


# 25 mixed English / Marathi (and Hindi-Marathi) sentences, decision kind.
SENTENCES = [
    ("Approve R7K2", A, OK),
    ("R7K2 approved.", A, OK),
    ("R7K2 मंजूर", A, OK),
    ("R7K2 मंजूर आहे", A, OK),
    ("reject R7K2", R, OK),
    ("R7K2 नामंजूर", R, OK),
    ("R7K2 changes in the hook", C, OK),
    ("R7K2 बदल हवा", C, OK),
    ("I cannot approve R7K2", A, NEG),
    ("R7K2 shouldn't be approved", A, NEG),
    (f"R7K2 won{RSQ}t approve", A, NEG),
    ("R7K2 approve without the outro", A, NEG),
    ("R7K2 not yet approved", A, NEG),
    ("hold R7K2, approve later", A, NEG),
    ("R7K2 मंजूर नाही", A, NEG),
    ("R7K2 मंजूर करू नका", A, NEG),
    ("R7K2 मत approve", A, NEG),
    ("R7K2 approve?", A, ASK),
    ("Should I approve R7K2", A, ASK),
    ("R7K2 मंजूर का", A, ASK),
    ("I will approve R7K2 after I check", A, ASK),
    ("R7K2 उद्या मंजूर", A, ASK),
    ("let me approve R7K2", A, ASK),
    ("approve R7K2 नामंजूर", A, NEEDS_CLARIFICATION),
    ("R7K2 approve, knotty edit is fine", A, OK),
]


def test_table_has_25_sentences() -> None:
    assert len(SENTENCES) == 25


@pytest.mark.parametrize(("sentence", "decision", "expected"), SENTENCES)
def test_mixed_sentences(sentence: str, decision: ApprovalStepState, expected: str) -> None:
    record = run(sentence, EvidenceRecordKind.STEP_DECISION, "R7K2", decision)
    assert outcome(record) == expected


@pytest.mark.parametrize(
    "sentence",
    [
        "R7K2 approve after I check",
        "R7K2 approve tomorrow",
        "If it looks fine, approve R7K2",
        "approve R7K2 once the intro is fixed",
        "approve R7K2 later",
        "maybe approve R7K2",
        "R7K2 approve, will check",
        "R7K2 नंतर मंजूर",
        "कदाचित मंजूर R7K2",
        "Can you approve R7K2",
        f"R7K2 approve{FWQ}",
    ],
)
def test_question_or_deferred_needs_clarification(sentence: str) -> None:
    record = run(sentence, EvidenceRecordKind.STEP_DECISION, "R7K2", A)
    assert outcome(record) == QUESTION_OR_DEFERRED


def test_cannot_approve_does_not_verify() -> None:
    assert outcome(run("I cannot approve R7K2", EvidenceRecordKind.STEP_DECISION, "R7K2", A)) == NEG


# --- knowledge release uses the decision grammar --------------------------------------------


def test_release_is_a_decision_kind() -> None:
    rules = DEFAULT_RECORD_KIND_RULES
    assert rules[EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST] is VerificationKind.DECISION


@pytest.mark.parametrize(
    ("sentence", "decision", "expected"),
    [
        ("R7K2 release chapter 4 notes", A, OK),
        ("R7K2 do not release chapter 4 notes", A, NEG),
        ("R7K2 release chapter 4 notes after I check them", A, ASK),
        ("chapter 4 notes, R7K2", A, "decision_matches"),
        ("R7K2 release chapter 4 notes", None, "decision_given"),
    ],
)
def test_release_requests(sentence: str, decision: Any, expected: str) -> None:
    kind = EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST
    assert outcome(run(sentence, kind, "chapter 4 notes", decision)) == expected


# --- content and score kinds refuse negation / questions / deferral too ---------------------


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("R7K2 use the 2008 crash as the opening example", OK),
        ("R7K2 do not add the intro joke at all please", NEG),
        ("R7K2 never use the 2020 example in the opening", NEG),
        ("R7K2 could we use the 2008 crash as the opening example?", ASK),
        ("R7K2 use the 2008 crash as the opening example once the intro is final", ASK),
        ("R7K2 सुरुवातीला 2008 चे उदाहरण वापरू नका", NEG),
    ],
)
def test_contribution_clarity(sentence: str, expected: str) -> None:
    quote = sentence.split(" ", 1)[1]
    assert outcome(run(sentence, EvidenceRecordKind.CONTRIBUTION, quote, None)) == expected


def test_owner_topic_with_deferral_is_refused() -> None:
    sentence = "R7K2 topic RSI divergence, maybe weekly"
    record = run(sentence, EvidenceRecordKind.OWNER_TOPIC, "RSI divergence", None)
    assert outcome(record) == ASK


# --- normalisation and whole-word matching --------------------------------------------------


def test_normalisation() -> None:
    assert normalise(f"DON{RSQ}T") == "don't"
    assert normalise(f"Don{MLA}t") == "don't"
    assert tokens(f"R7K2 can{RSQ}t approve") == ["r7k2", "can't", "approve"]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("knotty nothing notable", None),  # "not" only inside other words
        ("unless", ASK),
        ("nowhere notice", None),
        ("stop", NEG),
        ("काय", ASK),
        ("this is it", None),  # "is" is a question only as the first word
        ("Is it fine", ASK),
    ],
)
def test_whole_word_matching(text: str, problem: str | None) -> None:
    assert clarity_problem(text, POLICY) == problem


def test_lists_are_configurable() -> None:
    relaxed = replace(POLICY, deferral_tokens=frozenset())
    assert clarity_problem("approve later", relaxed) is None
    assert clarity_problem("approve later", POLICY) == ASK
