"""Whitelist grammar for DECISION kinds and clarity refusals for CONTENT / SCORE kinds (PR #13
review rounds 4-5). Lists are configuration (defaults marked owner to confirm)."""

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
    QUOTED_OR_FORWARDED,
    NewEvidence,
    SessionEvent,
    VerificationKind,
    VerifierPolicy,
    clarity_problem,
    normalise,
    read_decision,
    tokens,
    whitelist_tokens,
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
LDQ, RDQ = chr(0x201C), chr(0x201D)  # curly double quotes
FULL_WIDTH_CODE = "".join(chr(0xFEE0 + ord(c)) for c in "R7K2")
A = ApprovalStepState.APPROVED
R = ApprovalStepState.REJECTED
OK = "VERIFIED"
CL = NEEDS_CLARIFICATION
NEG = NEGATION_OR_WITHHOLDING
ASK = QUESTION_OR_DEFERRED
QUO = QUOTED_OR_FORWARDED


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


# The 25 sentences of round 4, re-judged under the whitelist grammar.
MY_25 = [
    ("Approve R7K2", A, OK),
    ("R7K2 approved.", A, OK),
    ("R7K2 मंजूर", A, OK),
    ("R7K2 मंजूर आहे", A, CL),
    ("reject R7K2", R, OK),
    ("R7K2 नामंजूर", R, OK),
    ("R7K2 changes in the hook", ApprovalStepState.CHANGES_REQUESTED, CL),
    ("R7K2 बदल हवा", ApprovalStepState.CHANGES_REQUESTED, CL),
    ("I cannot approve R7K2", A, CL),
    ("R7K2 shouldn't be approved", A, CL),
    (f"R7K2 won{RSQ}t approve", A, CL),
    ("R7K2 approve without the outro", A, CL),
    ("R7K2 not yet approved", A, CL),
    ("hold R7K2, approve later", A, CL),
    ("R7K2 मंजूर नाही", A, CL),
    ("R7K2 मंजूर करू नका", A, CL),
    ("R7K2 मत approve", A, CL),
    ("R7K2 approve?", A, CL),
    ("Should I approve R7K2", A, CL),
    ("R7K2 मंजूर का", A, CL),
    ("I will approve R7K2 after I check", A, CL),
    ("R7K2 उद्या मंजूर", A, CL),
    ("let me approve R7K2", A, CL),
    ("approve R7K2 नामंजूर", A, CL),
    ("R7K2 approve, knotty edit is fine", A, CL),
]
# The reviewer's 20 tricky sentences (round 5): the 9 that verified before, and the rest.
REVIEWER_20 = [
    ("R7K2 मंजूर करू नकोस", A, CL),
    ("approve nahi karna R7K2", A, CL),
    ("R7K2 approve mat karo", A, CL),
    ("Approve R7K2 except the intro", A, CL),
    ('Ravi said "approve R7K2"', A, CL),
    ("Forwarded message: Approve R7K2", A, CL),
    ("Yesterday I would have approved R7K2", A, CL),
    ("approve R7K2 and Q9Z1", A, CL),
    (f"{LDQ}approve R7K2{RDQ}", A, CL),
    ("R7K2 approve but not the thumbnail", A, CL),
    ("R7K2 ठीक आहे", A, OK),
    ("होय R7K2", A, OK),
    ("R7K2 ok", A, OK),
    ("R7K2 yes please", A, OK),
    ("stop R7K2", R, OK),
    ("R7K2 नाही", R, OK),
    ("R7K2 yes no", A, CL),
    ("R7K2 approve 👍", A, OK),
    (f"{FULL_WIDTH_CODE} approve", A, OK),
    ("R7K2 नहीं", R, OK),
]


def test_tables_have_45_sentences() -> None:
    assert (len(MY_25), len(REVIEWER_20)) == (25, 20)


@pytest.mark.parametrize(("sentence", "decision", "expected"), MY_25 + REVIEWER_20)
def test_whitelist_sentences(sentence: str, decision: ApprovalStepState, expected: str) -> None:
    quote = sentence.split()[0]
    record = run(sentence, EvidenceRecordKind.STEP_DECISION, quote, decision)
    assert outcome(record) == expected
    assert (read_decision(sentence, "R7K2", POLICY) is not None) is (expected == OK)


def test_clarification_refusals_are_flagged() -> None:
    record = run("I cannot approve R7K2", EvidenceRecordKind.STEP_DECISION, "I", A)
    assert outcome(record) == CL


@pytest.mark.parametrize(
    "sentence",
    [
        "R7K2 approve after I check",
        "R7K2 approve tomorrow",
        "If it looks fine, approve R7K2",
        "approve R7K2 later",
        "maybe approve R7K2",
        "Can you approve R7K2",
        f"R7K2 approve{FWQ}",
        "R7K2 नंतर मंजूर",
    ],
)
def test_question_or_deferred_decisions_need_clarification(sentence: str) -> None:
    quote = sentence.split()[0]
    assert outcome(run(sentence, EvidenceRecordKind.STEP_DECISION, quote, A)) == CL


def test_the_accepted_forms_are_what_the_operator_asks_for() -> None:
    for sentence in ("approve R7K2", "R7K2 मंजूर", "reject R7K2", "R7K2 नामंजूर"):
        assert read_decision(sentence, "R7K2", POLICY) is not None


# --- knowledge release uses the decision grammar --------------------------------------------


def test_release_is_a_decision_kind() -> None:
    rules = DEFAULT_RECORD_KIND_RULES
    assert rules[EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST] is VerificationKind.DECISION


@pytest.mark.parametrize(
    ("sentence", "decision", "expected"),
    [
        ("release R7K2", A, OK),
        ("R7K2 release chapter 4 notes", A, CL),
        ("R7K2 do not release chapter 4 notes", A, CL),
        ("release R7K2 after I check", A, CL),
        ("release R7K2", None, "decision_given"),
        ("release R7K2", R, "decision_matches"),
    ],
)
def test_release_requests(sentence: str, decision: Any, expected: str) -> None:
    kind = EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST
    assert outcome(run(sentence, kind, "R7K2", decision)) == expected


# --- content and score kinds: clarity refusals -----------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("R7K2 use the 2008 crash as the opening example", OK),
        ("R7K2 do not add the intro joke at all please", NEG),
        ("R7K2 never use the 2020 example in the opening", NEG),
        ("R7K2 use the 2008 crash as the opening, intro nako", NEG),
        ("R7K2 use the 2008 crash as the opening, intro mat lagao", NEG),
        ("R7K2 सुरुवातीला 2008 चे उदाहरण वापरू नकोस", NEG),
        ("R7K2 use the 2008 crash everywhere except the intro", NEG),
        ("R7K2 Ravi said use the 2008 crash as the opening example", QUO),
        ("R7K2 forwarded: use the 2008 crash as the opening example", QUO),
        ("R7K2 could we use the 2008 crash as the opening example?", ASK),
        ("R7K2 use the 2008 crash as the opening example once the intro is final", ASK),
        ("R7K2 I would use the 2008 crash as the opening example", ASK),
        ("R7K2 Q9Z1 use the 2008 crash as the opening example", "subject_reference"),
    ],
)
def test_contribution_clarity(sentence: str, expected: str) -> None:
    quote = (
        sentence.split(" ", 2)[-1] if expected == "subject_reference" else sentence.split(" ", 1)[1]
    )
    assert outcome(run(sentence, EvidenceRecordKind.CONTRIBUTION, quote, None)) == expected


def test_wholly_quoted_content_is_refused() -> None:
    sentence = f"{LDQ}R7K2 use the 2008 crash as the opening example{RDQ}"
    quote = "use the 2008 crash as the opening example"
    assert outcome(run(sentence, EvidenceRecordKind.CONTRIBUTION, quote, None)) == QUO


def test_owner_topic_with_deferral_is_refused() -> None:
    record = run(
        "R7K2 topic RSI divergence, maybe weekly", EvidenceRecordKind.OWNER_TOPIC, "RSI", None
    )
    assert outcome(record) == ASK


# --- normalisation and whole-word matching --------------------------------------------------


def test_normalisation() -> None:
    assert normalise(f"DON{RSQ}T") == "don't"
    assert normalise(f"Don{MLA}t") == "don't"
    assert tokens(f"R7K2 can{RSQ}t approve") == ["r7k2", "can't", "approve"]
    assert whitelist_tokens(f"{LDQ}Approve, R7K2!{RDQ} 👍") == ["approve", "r7k2"]
    assert whitelist_tokens(FULL_WIDTH_CODE) == ["r7k2"]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("knotty nothing notable", None),
        ("unless", ASK),
        ("nowhere notice", None),
        ("stop", NEG),
        ("काय", ASK),
        ("this is it", None),
        ("Is it fine", ASK),
        ("namaskar", None),  # "na" only as a whole word
        ("he wrote it", QUO),
    ],
)
def test_whole_word_matching(text: str, problem: str | None) -> None:
    assert clarity_problem(text, POLICY) == problem


def test_lists_are_configurable() -> None:
    relaxed = replace(POLICY, deferral_tokens=frozenset())
    assert clarity_problem("approve later", relaxed) is None
    assert clarity_problem("approve later", POLICY) == ASK
    wider = replace(POLICY, neutral_tokens=POLICY.neutral_tokens | {"आहे"})
    assert read_decision("R7K2 मंजूर आहे", "R7K2", wider) is A
