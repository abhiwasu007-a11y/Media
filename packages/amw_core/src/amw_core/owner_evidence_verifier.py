"""Deterministic check of owner chat evidence (R14; 03 section 11.6 rule 6; 04 section 5.16 code
check; 08 ``sys_operator``; CCR-010, decision D5).

**The store verifies; nothing built outside the store is trusted.** The operator tool (an LLM
acting as ``sys_operator``) supplies only identifiers and what it read (session ID, event UUID,
quote, message time, review code, decision). The evidence store fetches the event through its
own ``SessionEventSource`` and runs ``verify_owner_event`` itself, in ``verify_recorded`` and in
``confirm``; it has no method that accepts a verification result from a caller. The ``Verified``
value this module returns is an immutable record of one check, bound to the evidence row, event
and evidence hash it was computed for; the store re-checks that binding on its own result.
Python cannot make a value unforgeable (any caller can construct or copy an object), which is
exactly why no proof object is an authorisation: only the store's own call is.

Every record kind is verified by code; ``VerifierPolicy.record_kind_rules`` (config table,
defaults ``DEFAULT_RECORD_KIND_RULES``) maps each ``evidence_record_kind`` to one rule set. No
kind is exempt; a missing input is a refusal, never a skipped check.

Authenticity (every kind):

1. the event exists and is the requested one (same session ID and event UUID);
2. role ``user``; 3. not synthetic; 4. inbound origin is the human owner, not a peer session,
   sub-agent, notification, tool result, scheduled message or document;
5. the sender is the owner's own account and the session is a top-level owner session, not a
   child or sub-agent session (``owner_account_ids``, ``require_top_level_session``);
6. the quote (the stored text) is a non-empty verbatim substring of the content;
7. the recorded message time equals the event timestamp (a confirmation takes its time from it);
8. message order: later than the request and than any evidence it supersedes; a confirmation is
   a second, distinct, later event;
9. a subject reference is present: the review code exactly once as a whole token, or (content
   and score kinds) the job wire ID; one owner message verifies exactly one subject (the store
   also refuses a second subject for one event; a multi-subject format does not exist yet).

Clarity (every kind): a message with negation or withholding language (``not``, ``cannot``,
``don't``, ``hold``, ``नाही``, ...), a question (ends with ``?`` or opens with an interrogative;
Marathi / Hindi interrogatives anywhere) or conditional / deferred wording (``if``, ``once``,
``later``, ``will``, ``let me``, ``उद्या``, ...) anywhere is refused with a clarification reason
(``Refusal.needs_clarification``): nothing is recorded and the operator asks the owner to restate.
Tokens are matched as whole words on normalised text (NFC, case-folded, apostrophe variants
unified), never as substrings of other words.

``DECISION`` kinds (``STEP_DECISION``, ``COMPLIANCE_DECISION``, ``KNOWLEDGE_RELEASE_REQUEST``, the
last because a release is an authorisation): review code and decision are mandatory and the
content states the decision in the strict grammar below.

``CONTENT`` kinds (``CONTRIBUTION``, ``OWNER_TOPIC``, ``DATASET_INTAKE``): no decision may be
recorded; the quote must carry content, not only decision words / negations / references, and a
contribution has at least ``min_contribution_chars`` characters (04 section 5.16
``editorial_contributions``).

``SCORE`` kinds (``HUMAN_SCORE``): no decision; at least one score; each claimed
``(dimension, points)`` is written in the message as ``<dimension label> <number>`` exactly (no
inferred numbers), with ``0 <= points <= max_points`` of the 18 rubric dimension and at most two
decimals; a dimension appears once. The claimed scores are bound into ``evidence_sha256`` only
until the contract integrator decides on a ``claimed_scores`` column for
``owner_instruction_evidence`` (requested by the PR #13 review so the DB human-row trigger can
compare it with the ``quality_scores`` rows); this module does not add that column.

Decision grammar (strict, closed): the content is split into word tokens; every token from the
closed decision list (config ``approvals.owner_chat.decision_words.<lang>``; English and Marathi
defaults below) must map to the same decision, one of them must stand directly next to the
review code; two different decisions are ambiguous (``needs_clarification``). Every list (decision
words, negation, deferral and interrogative tokens, the rule table, the owner-account and
top-level-session tests) is configuration with defaults marked **owner to confirm**.

**Limitation (honest status).** The real ``SessionEventSource`` that reads the platform's session
record is ticket 3A-13. Until then only the in-memory fake
(``amw_core.testing.memory.MemorySessionEventSource``) exists, so no 3A approval recorded through
this path may be treated as production-verified. The real store's ``role`` / ``inbound_origin``
vocabularies are not yet confirmed and are configuration. Record kinds without a step decision
(``OWNER_TOPIC``, ``DATASET_INTAKE``, ...) cannot be verified until their grammar is defined
(fail closed; raised with the contract integrator).
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.ids import ActorRef, ApprovalId, JobId, UserId, WireId

USER_ROLE: Final = "user"
RECORD: Final = "RECORD"
CONFIRMATION: Final = "CONFIRMATION"
NEEDS_CLARIFICATION: Final = "needs_clarification"
"""Reason for a mixed or ambiguous decision (two different decision words)."""
NEGATION_OR_WITHHOLDING: Final = "negation_or_withholding"
QUESTION_OR_DEFERRED: Final = "question_or_deferred"
CLARIFICATION_REASONS: Final = frozenset(
    {NEEDS_CLARIFICATION, NEGATION_OR_WITHHOLDING, QUESTION_OR_DEFERRED}
)
"""Refusals where the operator must ask the owner to restate (nothing is recorded)."""

# Design defaults. OWNER TO CONFIRM: the decision words (English and Marathi forms), the
# negation tokens, the owner-account and top-level-session tests and the rule table below.
# Config (``approvals.owner_chat.*``) overrides every one of them.
DEFAULT_DECISION_WORDS: Final[Mapping[str, ApprovalStepState]] = {
    "approve": ApprovalStepState.APPROVED,
    "approved": ApprovalStepState.APPROVED,
    "मंजूर": ApprovalStepState.APPROVED,
    "release": ApprovalStepState.APPROVED,
    "reject": ApprovalStepState.REJECTED,
    "rejected": ApprovalStepState.REJECTED,
    "नामंजूर": ApprovalStepState.REJECTED,
    "changes": ApprovalStepState.CHANGES_REQUESTED,
    "बदल": ApprovalStepState.CHANGES_REQUESTED,
}
DEFAULT_NEGATION_TOKENS: Final = frozenset(
    {
        # English negation, contractions, modals and withholding words.
        "not", "no", "nope", "never", "without", "cannot", "hold", "wait", "stop", "nor",
        "don't", "dont", "doesn't", "doesnt", "didn't", "didnt", "isn't", "isnt",
        "aren't", "arent", "wasn't", "wasnt", "can't", "cant", "won't", "wont",
        "wouldn't", "wouldnt", "shouldn't", "shouldnt", "couldn't", "couldnt", "mustn't",
        # Marathi.
        "नाही", "नको", "न", "नये", "नका", "थांबा", "थांब", "थांबवा", "रोखा",
        # Hindi-Marathi usage.
        "नहीं", "मत", "रुको", "रोको",
    }
)  # fmt: skip
DEFAULT_DEFERRAL_TOKENS: Final = frozenset(
    {
        # English conditional / deferred wording ("will approve", "let me", "after I check").
        "if", "once", "later", "maybe", "perhaps", "probably", "tomorrow", "after", "let",
        "will", "until", "unless", "when", "pending", "soon", "eventually",
        # Marathi.
        "नंतर", "उद्या", "कदाचित", "जर", "झाल्यावर", "बघतो", "बघू", "पाहतो", "पाहू", "करेन",
        # Hindi-Marathi usage.
        "बाद", "कल", "शायद", "अगर",
    }
)  # fmt: skip
DEFAULT_INTERROGATIVE_FIRST_TOKENS: Final = frozenset(
    {
        "what", "why", "how", "who", "which", "whether", "should", "shall", "can", "could",
        "would", "is", "are", "do", "does", "did",
    }
)  # fmt: skip
"""English interrogatives, a question only when they open the message."""
DEFAULT_INTERROGATIVE_ANY_TOKENS: Final = frozenset(
    {"काय", "का", "कसे", "कसा", "कशी", "कधी", "केव्हा", "क्या", "क्यों", "कब", "कैसे"}
)
"""Marathi / Hindi interrogatives, a question wherever they occur."""
_APOSTROPHES: Final = str.maketrans(
    dict.fromkeys(map(chr, (0x2019, 0x2018, 0x02BC, 0x0060, 0x00B4, 0x2032)), "'")
)


class VerificationKind(StrEnum):
    """Rule set of an evidence record kind (code-local; not a stored value)."""

    DECISION = "DECISION"
    CONTENT = "CONTENT"
    SCORE = "SCORE"


DEFAULT_RECORD_KIND_RULES: Final[Mapping[EvidenceRecordKind, VerificationKind]] = {
    EvidenceRecordKind.STEP_DECISION: VerificationKind.DECISION,
    EvidenceRecordKind.COMPLIANCE_DECISION: VerificationKind.DECISION,
    EvidenceRecordKind.CONTRIBUTION: VerificationKind.CONTENT,
    EvidenceRecordKind.OWNER_TOPIC: VerificationKind.CONTENT,
    EvidenceRecordKind.DATASET_INTAKE: VerificationKind.CONTENT,
    # A release is an authorisation (FIN-R12, Q26): decision grammar, not content rules.
    EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST: VerificationKind.DECISION,
    EvidenceRecordKind.HUMAN_SCORE: VerificationKind.SCORE,
}
DEFAULT_DIMENSION_LABELS: Final[Mapping[QualityDimension, tuple[str, ...]]] = {
    d: (d.value.casefold(),) for d in QualityDimension
}


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """A transcript event exactly as the platform's session event store returns it."""

    session_id: str
    event_uuid: str
    role: str
    is_synthetic: bool
    inbound_origin: str
    content: str
    timestamp: datetime
    sender_account: str
    """The platform account that authored the message."""
    parent_session_id: str | None
    """``None`` for a top-level session; set for a child / sub-agent session."""


@runtime_checkable
class SessionEventSource(Protocol):
    """Read access to the platform's session event store (one event by ID), owned by the store.

    Limitation: the real adapter is ticket 3A-13; until then only the in-memory fake exists and
    3A approvals recorded with it are not production-verified (see the module docstring).
    """

    def fetch(self, session_id: str, event_uuid: str) -> SessionEvent | None:
        """The event, or ``None`` if it cannot be fetched (the evidence then stays pending)."""
        ...


@dataclass(frozen=True, slots=True)
class NewEvidence:
    """What the operator supplies for one owner instruction (04 section 5.16 columns)."""

    record_kind: EvidenceRecordKind
    subject_kind: str
    subject_id: WireId
    source_kind: InstructionSourceKind
    session_id: str
    event_uuid: str
    quote: str
    message_at: datetime
    recorded_by: ActorRef
    on_behalf_of: UserId
    job_id: JobId | None = None
    approval_id: ApprovalId | None = None
    step_no: int | None = None
    review_code: str | None = None
    parsed_decision: ApprovalStepState | None = None
    supersedes_id: WireId | None = None
    scores: tuple[tuple[QualityDimension, Decimal], ...] = ()
    """``HUMAN_SCORE`` only: the claimed points per dimension, checked against the message."""


def evidence_sha256(evidence: NewEvidence) -> str:
    """``evidence_sha256`` of 04 section 5.16: SHA-256 of the canonical evidence fields."""
    material: dict[str, object] = {
        "session_id": evidence.session_id,
        "event_uuid": evidence.event_uuid,
        "quote": evidence.quote,
        "message_at": evidence.message_at.isoformat(),
        "record_kind": evidence.record_kind.value,
        "subject_kind": evidence.subject_kind,
        "subject_id": evidence.subject_id,
        "review_code": evidence.review_code,
        "parsed_decision": evidence.parsed_decision.value if evidence.parsed_decision else None,
    }
    if evidence.scores:  # bound only when present, so the 04 field list is unchanged otherwise
        material["scores"] = [[d.value, str(p)] for d, p in evidence.scores]
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class VerifierPolicy:
    """Configuration of the check (from ``amw_core.config``, never from the model)."""

    human_inbound_origins: frozenset[str]
    """``inbound_origin`` values that mean "typed by the human owner" in the session store."""
    owner_account_ids: frozenset[str]
    """The owner's own platform account(s): only these senders can back a human record."""
    decision_words: Mapping[str, ApprovalStepState] = field(
        default_factory=lambda: dict(DEFAULT_DECISION_WORDS)
    )
    """Closed list of single decision words (all configured languages) -> decision."""
    negation_tokens: frozenset[str] = DEFAULT_NEGATION_TOKENS
    deferral_tokens: frozenset[str] = DEFAULT_DEFERRAL_TOKENS
    interrogative_first_tokens: frozenset[str] = DEFAULT_INTERROGATIVE_FIRST_TOKENS
    interrogative_any_tokens: frozenset[str] = DEFAULT_INTERROGATIVE_ANY_TOKENS
    require_top_level_session: bool = True
    record_kind_rules: Mapping[EvidenceRecordKind, VerificationKind] = field(
        default_factory=lambda: dict(DEFAULT_RECORD_KIND_RULES)
    )
    dimension_labels: Mapping[QualityDimension, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_DIMENSION_LABELS)
    )
    min_contribution_chars: int = 20


@dataclass(frozen=True, slots=True)
class Verified:
    """Immutable result of one passed check, bound to what it was computed for. It authorises
    nothing by itself: the store accepts only the result of its own call (see module doc)."""

    evidence_id: WireId
    event_uuid: str
    bound_sha256: str
    purpose: str
    event_timestamp: datetime
    checks: tuple[tuple[str, bool], ...]
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class Refusal:
    """The check failed; ``reason`` names the first failing test."""

    reason: str
    checks: tuple[tuple[str, bool], ...]

    @property
    def needs_clarification(self) -> bool:
        """The operator must ask the owner to restate; nothing may be recorded."""
        return self.reason in CLARIFICATION_REASONS


@dataclass(frozen=True, slots=True)
class EventUnavailable:
    """The event could not be fetched: the evidence stays ``PENDING_VERIFICATION``."""

    session_id: str
    event_uuid: str


type VerificationOutcome = Verified | Refusal | EventUnavailable

_TOKEN = re.compile(
    "[0-9\u0966-\u096f]+\\.[0-9\u0966-\u096f]+(?![\\w\u0900-\u097f])|[\\w'\u2019\u0900-\u097f]+"
)


def normalise(text: str) -> str:
    """NFC (Devanagari nukta / vowel signs composed), case-folded, apostrophe variants unified."""
    return unicodedata.normalize("NFC", text).casefold().translate(_APOSTROPHES)


def tokens(content: str) -> list[str]:
    """Whole-word tokens of the normalised text (Devanagari signs stay inside the word), so a
    list entry never matches a substring of another word."""
    return _TOKEN.findall(normalise(content))


def clarity_problem(content: str, policy: VerifierPolicy) -> str | None:
    """Negation / withholding, a question, or conditional / deferred wording, anywhere in the
    message: each makes it unusable as evidence until the owner restates it."""
    words = tokens(content)
    if any(w in policy.negation_tokens for w in words):
        return NEGATION_OR_WITHHOLDING
    question = content.strip().endswith(("?", "\uff1f")) or (
        bool(words) and words[0] in policy.interrogative_first_tokens
    )
    if question or any(w in policy.interrogative_any_tokens for w in words):
        return QUESTION_OR_DEFERRED
    if any(w in policy.deferral_tokens for w in words):
        return QUESTION_OR_DEFERRED
    return None


def read_decision(
    content: str, review_code: str, policy: VerifierPolicy
) -> ApprovalStepState | str:
    """The decision stated in ``content`` under the strict grammar, or a refusal reason."""
    words = tokens(content)
    code = normalise(review_code)
    positions = [i for i, w in enumerate(words) if w == code]
    if len(positions) != 1:
        return "review_code_present"
    problem = clarity_problem(content, policy)
    if problem is not None:
        return problem
    found = {policy.decision_words[w] for w in words if w in policy.decision_words}
    if len(found) != 1:
        return NEEDS_CLARIFICATION if found else "decision_matches"
    neighbours = [words[i] for i in (positions[0] - 1, positions[0] + 1) if 0 <= i < len(words)]
    if not any(w in policy.decision_words for w in neighbours):
        return "decision_adjacent"
    return next(iter(found))


def _code_once(words: list[str], code: str | None) -> bool:
    return bool(code) and sum(1 for w in words if w == normalise(str(code))) == 1


def _scores_stated(
    words: list[str], scores: tuple[tuple[QualityDimension, Decimal], ...], policy: VerifierPolicy
) -> bool:
    seen: set[QualityDimension] = set()
    for dimension, points in scores:
        if dimension in seen:
            return False
        seen.add(dimension)
        labels = {normalise(label) for label in policy.dimension_labels.get(dimension, ())}
        stated = []
        for i, word in enumerate(words[:-1]):
            if word in labels:
                try:
                    stated.append(Decimal(words[i + 1]))
                except InvalidOperation:
                    continue
        if stated != [points]:
            return False
    return True


def _scores_in_range(scores: tuple[tuple[QualityDimension, Decimal], ...]) -> bool:
    return all(
        Decimal(0) <= p <= Decimal(d.max_points) and p == p.quantize(Decimal("0.01"))
        for d, p in scores
    )


def verify_owner_event(
    event: SessionEvent | None,
    *,
    evidence: NewEvidence,
    evidence_id: WireId,
    purpose: str,
    quote: str,
    message_at: datetime | None,
    not_before: datetime,
    distinct_from_event_uuid: str | None,
    policy: VerifierPolicy,
    now: datetime,
) -> VerificationOutcome:
    """Pure check of one fetched event against the operator's claims (rules above).

    For ``purpose = RECORD`` pass the evidence's own quote and ``message_at``; for a
    confirmation pass the confirmation quote and ``message_at = None``. A confirmation checks
    authenticity and the subject reference, and for ``DECISION`` kinds the same decision.
    ``not_before`` is exclusive.
    """
    if event is None:
        return EventUnavailable(evidence.session_id, evidence.event_uuid)
    session_id = evidence.session_id if purpose == RECORD else event.session_id
    words = tokens(event.content)
    kind = policy.record_kind_rules.get(evidence.record_kind)
    code_once = _code_once(words, evidence.review_code)
    job_ref = evidence.job_id is not None and evidence.job_id in event.content
    checks: dict[str, bool] = {
        "rule_defined": kind is not None,
        "event_identity": event.session_id == session_id
        and (purpose != RECORD or event.event_uuid == evidence.event_uuid),
        "role_user": event.role == USER_ROLE,
        "not_synthetic": not event.is_synthetic,
        "human_origin": event.inbound_origin in policy.human_inbound_origins,
        "owner_account": event.sender_account in policy.owner_account_ids,
        "top_level_session": not policy.require_top_level_session
        or event.parent_session_id is None,
        "quote_verbatim": bool(quote) and quote in event.content,
        "timestamp_equal": message_at is None or message_at == event.timestamp,
        "message_order": event.timestamp > not_before,
        "distinct_event": distinct_from_event_uuid is None
        or event.event_uuid != distinct_from_event_uuid,
    }
    if kind is VerificationKind.DECISION:
        stated = (
            read_decision(event.content, evidence.review_code, policy)
            if evidence.review_code
            else "review_code_given"
        )
        checks |= {
            "review_code_given": bool(evidence.review_code),
            "decision_given": evidence.parsed_decision is not None,
            "review_code_present": stated not in ("review_code_present", "review_code_given"),
            NEGATION_OR_WITHHOLDING: stated != NEGATION_OR_WITHHOLDING,
            QUESTION_OR_DEFERRED: stated != QUESTION_OR_DEFERRED,
            NEEDS_CLARIFICATION: stated != NEEDS_CLARIFICATION,
            "decision_adjacent": stated != "decision_adjacent",
            "decision_matches": evidence.parsed_decision is not None
            and stated == evidence.parsed_decision,
        }
    elif kind is not None:
        problem = clarity_problem(event.content, policy)
        checks[NEGATION_OR_WITHHOLDING] = problem != NEGATION_OR_WITHHOLDING
        checks[QUESTION_OR_DEFERRED] = problem != QUESTION_OR_DEFERRED
        checks["decision_not_applicable"] = evidence.parsed_decision is None
        checks["subject_reference"] = code_once or (kind is not None and job_ref)
        if kind is VerificationKind.CONTENT and purpose == RECORD:
            reference = {normalise(str(evidence.review_code)), normalise(str(evidence.job_id))}
            carried = [
                w
                for w in tokens(quote)
                if w not in policy.decision_words
                and w not in policy.negation_tokens
                and w not in reference
            ]
            long_enough = (
                evidence.record_kind is not EvidenceRecordKind.CONTRIBUTION
                or len(quote.strip()) >= policy.min_contribution_chars
            )
            checks["content_present"] = bool(carried) and long_enough
        if kind is VerificationKind.SCORE and purpose == RECORD:
            checks["scores_given"] = bool(evidence.scores)
            checks["scores_in_range"] = _scores_in_range(evidence.scores)
            checks["scores_stated"] = bool(evidence.scores) and _scores_stated(
                words, evidence.scores, policy
            )
    frozen = tuple(checks.items())
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        return Refusal(reason=failed[0], checks=frozen)
    return Verified(
        evidence_id=evidence_id,
        event_uuid=event.event_uuid,
        bound_sha256=evidence_sha256(evidence),
        purpose=purpose,
        event_timestamp=event.timestamp,
        checks=frozen,
        verified_at=now,
    )
