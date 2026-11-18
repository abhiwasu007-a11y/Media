"""Deterministic check of owner chat evidence (R14): 03 section 11.6 rules 6-7 (CCR-059, the
per-kind table), 04 section 5.16 code check and ``claimed_scores`` (CCR-060), 08 ``sys_operator``.

**The store verifies; nothing built outside the store is trusted.** The operator tool (an LLM
acting as ``sys_operator``) supplies only identifiers and what it read. The evidence store
fetches the event through its own ``SessionEventSource`` and runs ``verify_owner_event`` itself,
when the evidence is recorded and when it is confirmed; it has no method that accepts a
verification result. ``Verified`` is an immutable record of one passed check, bound to the
evidence row, event and evidence hash; Python cannot make a value unforgeable, which is why no
value authorises anything: only the store's own call does.

Authenticity, every kind and every event incl. the confirmation (03 rule 7, ``AUTHENTICITY_TESTS``):
A1 the requested event exists; A2 role ``user``; A3 not synthetic; A4 human inbound origin;
A5 the owner's own account and a top-level (not child / sub-agent) session; A6 verbatim quote
and equal timestamp; A7 order (later than the request and any superseded evidence; a
confirmation is a second, distinct, later event); A8 exactly one subject reference; A9 not a
question, conditional, deferral, quote or forward (``NEEDS_CLARIFICATION``-type refusals,
``Refusal.needs_clarification``: nothing is recorded, the operator asks the owner).

Rule sets (``evidence_verification_kind``; ``DEFAULT_RECORD_KIND_RULES`` equals the 03 table, a
test parses the document):

* ``DECISION`` (``STEP_DECISION``, ``COMPLIANCE_DECISION``, ``KNOWLEDGE_RELEASE_REQUEST``):
  **whitelist grammar**. The message is normalised (NFKC, case-folded, punctuation and emoji
  removed); exactly one review code is removed (zero or two or more -> ``NEEDS_CLARIFICATION``);
  every remaining token must belong to the closed decision list or the tiny neutral list, and
  exactly one decision word (or phrase) must remain. Any other token in any language or script
  (negations, ``except``, ``but``, ``if``, ``tomorrow``, ``would``, names, quote or forward
  markers, questions) -> ``NEEDS_CLARIFICATION``. The accepted forms are what the operator asks
  the owner to type, e.g. ``approve R7K2`` / ``R7K2 मंजूर``. A whole message wrapped in quotation
  marks is also refused. This is stricter than the "closed grammar" sentence of 03 rule 7
  (raised with the contract integrator).
* ``CONTENT`` (``CONTRIBUTION``, ``OWNER_TOPIC``, ``DATASET_INTAKE``): no decision; the quote
  carries content (contributions >= ``min_contribution_chars``); refused for negation or
  withholding language (English, Marathi and Hindi, Devanagari or Romanised and inflected),
  quote / forward markers, questions, past-conditional or deferral words, or more than one
  review code. The stored record text must be a verbatim substring of the quote (store method
  ``authorise_content``, the fake's equivalent of the DB trigger).
* ``SCORE`` (``HUMAN_SCORE``): no decision; ``claimed_scores`` ``{dimension: integer}`` is
  non-empty, part of ``evidence_sha256``, each value ``0..max_points`` (18 section 9) and written
  in the message as ``<dimension label> <integer>`` exactly, each dimension once; the same
  refusals as CONTENT; HUMAN ``quality_scores`` rows must equal it (``authorise_human_score``).

Every list (decision words, neutral words, negation, withholding, quote markers, deferral,
interrogatives, review-code shape, owner accounts, top-level-session test, the rule table) is
configuration (``approvals.owner_chat.*``) with defaults marked **owner to confirm**.

**Limitation (honest status).** The real ``SessionEventSource`` that reads the platform's session
record is ticket 3A-13. Until then only the in-memory fake
(``amw_core.testing.memory.MemorySessionEventSource``) exists, so no 3A approval recorded through
this path may be treated as production-verified.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceVerificationKind,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.ids import ActorRef, ApprovalId, JobId, UserId, WireId

VerificationKind = EvidenceVerificationKind
USER_ROLE: Final = "user"
RECORD: Final = "RECORD"
CONFIRMATION: Final = "CONFIRMATION"
NEEDS_CLARIFICATION: Final = "needs_clarification"
"""A decision message outside the whitelist grammar (03 rule 7 A9 / DECISION)."""
NEGATION_OR_WITHHOLDING: Final = "negation_or_withholding"
QUESTION_OR_DEFERRED: Final = "question_or_deferred"
QUOTED_OR_FORWARDED: Final = "quoted_or_forwarded"
CLARIFICATION_REASONS: Final = frozenset(
    {NEEDS_CLARIFICATION, NEGATION_OR_WITHHOLDING, QUESTION_OR_DEFERRED, QUOTED_OR_FORWARDED}
)
"""Refusals where the operator must ask the owner to restate (nothing is recorded)."""

# ---- configuration defaults: OWNER TO CONFIRM every list below (config approvals.owner_chat.*).
DEFAULT_RECORD_KIND_RULES: Final[Mapping[EvidenceRecordKind, EvidenceVerificationKind]] = {
    EvidenceRecordKind.STEP_DECISION: EvidenceVerificationKind.DECISION,
    EvidenceRecordKind.COMPLIANCE_DECISION: EvidenceVerificationKind.DECISION,
    EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST: EvidenceVerificationKind.DECISION,
    EvidenceRecordKind.CONTRIBUTION: EvidenceVerificationKind.CONTENT,
    EvidenceRecordKind.OWNER_TOPIC: EvidenceVerificationKind.CONTENT,
    EvidenceRecordKind.DATASET_INTAKE: EvidenceVerificationKind.CONTENT,
    EvidenceRecordKind.HUMAN_SCORE: EvidenceVerificationKind.SCORE,
}
AUTHENTICITY_TESTS: Final[Mapping[str, tuple[str, ...]]] = {
    "A1": ("event_identity",),
    "A2": ("role_user",),
    "A3": ("not_synthetic",),
    "A4": ("human_origin",),
    "A5": ("owner_account", "top_level_session"),
    "A6": ("quote_verbatim", "timestamp_equal"),
    "A7": ("message_order", "distinct_event"),
    "A8": ("subject_reference",),
    "A9": ("clarity",),
}
"""03 section 11.6 rule 7 test IDs -> the check names this module records."""
_A = ApprovalStepState.APPROVED
_R = ApprovalStepState.REJECTED
DEFAULT_DECISION_WORDS: Final[Mapping[str, ApprovalStepState]] = {
    # approve side (English, Marathi, Hindi)
    "approve": _A, "approved": _A, "yes": _A, "ok": _A, "okay": _A, "go ahead": _A,
    "release": _A, "confirmed": _A, "मंजूर": _A, "होय": _A, "ठीक": _A, "ठीक आहे": _A, "हाँ": _A,
    # reject side
    "reject": _R, "rejected": _R, "no": _R, "stop": _R, "नामंजूर": _R, "नाही": _R, "नहीं": _R,
    # changes requested (the change itself is a separate CONTENT record)
    "changes": ApprovalStepState.CHANGES_REQUESTED, "बदल": ApprovalStepState.CHANGES_REQUESTED,
}  # fmt: skip
DEFAULT_NEUTRAL_TOKENS: Final = frozenset(
    {"please", "thanks", "the", "this", "it", "कृपया", "धन्यवाद"}
)
DEFAULT_NEGATION_TOKENS: Final = frozenset(
    {
        # English negation, contractions, modals.
        "not", "no", "nope", "never", "without", "cannot", "hold", "wait", "stop", "nor",
        "don't", "dont", "doesn't", "doesnt", "didn't", "didnt", "isn't", "isnt", "aren't",
        "arent", "wasn't", "wasnt", "can't", "cant", "won't", "wont", "wouldn't", "wouldnt",
        "shouldn't", "shouldnt", "couldn't", "couldnt", "mustn't",
        # English withholding.
        "except", "but", "excluding", "apart", "besides", "however", "only",
        # Marathi (Devanagari, inflected).
        "नाही", "नाहीत", "नको", "नकोस", "नकोत", "नकोय", "न", "नये", "नका", "नव्हे", "नव्हता",
        "नव्हती", "नव्हते", "नसेल", "थांबा", "थांब", "थांबवा", "रोखा", "सोडून", "वगळून", "पण",
        # Hindi (Devanagari).
        "नहीं", "मत", "रुको", "रोको", "लेकिन", "सिवाय",
        # Romanised Marathi / Hindi.
        "nahi", "nahin", "nai", "nahiye", "nako", "nakos", "nakot", "naka", "nakko", "mat", "na",
    }
)  # fmt: skip
DEFAULT_QUOTE_MARKER_TOKENS: Final = frozenset(
    {
        "said", "says", "wrote", "writes", "forwarded", "forward", "fwd", "fw", "quote",
        "quoted", "quoting", "म्हणाला", "म्हणाली", "म्हणाले", "म्हणतो", "म्हणते", "कहा", "बोला",
    }
)  # fmt: skip
DEFAULT_DEFERRAL_TOKENS: Final = frozenset(
    {
        # English conditional / deferred / past-conditional.
        "if", "once", "later", "maybe", "perhaps", "probably", "tomorrow", "after", "let",
        "will", "until", "unless", "when", "pending", "soon", "eventually", "would",
        "yesterday", "earlier", "previously", "had",
        # Marathi.
        "नंतर", "उद्या", "कदाचित", "जर", "झाल्यावर", "बघतो", "बघू", "पाहतो", "पाहू", "करेन",
        "काल", "कालच",
        # Hindi.
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
DEFAULT_REVIEW_CODE_PATTERN: Final = r"(?=[a-z0-9]*[a-z])(?=[a-z0-9]*[0-9])[a-z0-9]{4}"
"""Shape of a review code token (letters and digits, four characters); 04 defines no format."""
DEFAULT_DIMENSION_LABELS: Final[Mapping[QualityDimension, tuple[str, ...]]] = {
    d: (d.value.casefold(),) for d in QualityDimension
}
_QUOTES: Final = frozenset(map(chr, (0x22, 0x27, 0x201C, 0x201D, 0x2018, 0x2019, 0xAB, 0xBB)))
_APOSTROPHES: Final = str.maketrans(
    dict.fromkeys(map(chr, (0x2019, 0x2018, 0x02BC, 0x0060, 0x00B4, 0x2032)), "'")
)


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
    claimed_scores: tuple[tuple[QualityDimension, int], ...] = ()
    """``HUMAN_SCORE`` only (CCR-060): the integer points per dimension the owner wrote."""

    @property
    def claimed_scores_json(self) -> dict[str, int] | None:
        """The ``claimed_scores`` jsonb value ``{dimension: points}`` (NULL when empty)."""
        return {d.value: p for d, p in self.claimed_scores} or None


def evidence_sha256(evidence: NewEvidence) -> str:
    """``evidence_sha256`` of 04 section 5.16 over the listed fields (incl. ``claimed_scores``)."""
    material = {
        "session_id": evidence.session_id,
        "event_uuid": evidence.event_uuid,
        "quote": evidence.quote,
        "message_at": evidence.message_at.isoformat(),
        "record_kind": evidence.record_kind.value,
        "subject_kind": evidence.subject_kind,
        "subject_id": evidence.subject_id,
        "review_code": evidence.review_code,
        "parsed_decision": evidence.parsed_decision.value if evidence.parsed_decision else None,
        "claimed_scores": evidence.claimed_scores_json,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class VerifierPolicy:
    """Configuration of the check (from ``amw_core.config``, never from the model). Owner to
    confirm every default."""

    human_inbound_origins: frozenset[str]
    """``inbound_origin`` values that mean "typed by the human owner" in the session store."""
    owner_account_ids: frozenset[str]
    """The owner's own platform account(s) (``approvals.owner_chat.owner_account_ids``)."""
    decision_words: Mapping[str, ApprovalStepState] = field(
        default_factory=lambda: dict(DEFAULT_DECISION_WORDS)
    )
    neutral_tokens: frozenset[str] = DEFAULT_NEUTRAL_TOKENS
    negation_tokens: frozenset[str] = DEFAULT_NEGATION_TOKENS
    quote_marker_tokens: frozenset[str] = DEFAULT_QUOTE_MARKER_TOKENS
    deferral_tokens: frozenset[str] = DEFAULT_DEFERRAL_TOKENS
    interrogative_first_tokens: frozenset[str] = DEFAULT_INTERROGATIVE_FIRST_TOKENS
    interrogative_any_tokens: frozenset[str] = DEFAULT_INTERROGATIVE_ANY_TOKENS
    review_code_pattern: str = DEFAULT_REVIEW_CODE_PATTERN
    require_top_level_session: bool = True
    record_kind_rules: Mapping[EvidenceRecordKind, EvidenceVerificationKind] = field(
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

_DEV_DIGITS = chr(0x0966) + "-" + chr(0x096F)
_DEV_BLOCK = chr(0x0900) + "-" + chr(0x097F)
_TOKEN = re.compile(
    f"[0-9{_DEV_DIGITS}]+\\.[0-9{_DEV_DIGITS}]+(?![\\w{_DEV_BLOCK}])|[\\w'{_DEV_BLOCK}]+"
)


def normalise(text: str) -> str:
    """NFKC (compatibility forms folded, Devanagari composed), case-folded, apostrophes unified."""
    return unicodedata.normalize("NFKC", text).casefold().translate(_APOSTROPHES)


def tokens(content: str) -> list[str]:
    """Whole-word tokens of the normalised text (apostrophes and decimals kept), so a list entry
    never matches a substring of another word."""
    return _TOKEN.findall(normalise(content))


def whitelist_tokens(text: str) -> list[str]:
    """DECISION normalisation: NFKC, case-folded, every punctuation / symbol / emoji character
    removed (only letters, marks and digits remain), split on whitespace."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    kept = "".join(c if unicodedata.category(c)[0] in "LMN" else " " for c in folded)
    return kept.split()


def _wholly_quoted(content: str) -> bool:
    text = content.strip()
    return len(text) >= 2 and text[0] in _QUOTES and text[-1] in _QUOTES


def read_decision(
    content: str, review_code: str, policy: VerifierPolicy
) -> ApprovalStepState | None:
    """The decision of a DECISION-kind message under the whitelist grammar, or ``None``
    (``NEEDS_CLARIFICATION``): exactly one review code, every other token a decision or neutral
    token, exactly one decision word or phrase."""
    if _wholly_quoted(content) or "?" in unicodedata.normalize("NFKC", content):
        return None  # a quoted message or a question (A9), checked before punctuation is removed
    words = whitelist_tokens(content)
    code = " ".join(whitelist_tokens(review_code))
    if not code or words.count(code) != 1:
        return None
    rest = [w for w in words if w != code]
    phrases = sorted(
        ((whitelist_tokens(p), d) for p, d in policy.decision_words.items()),
        key=lambda item: -len(item[0]),
    )
    neutral = {" ".join(whitelist_tokens(n)) for n in policy.neutral_tokens}
    found: list[ApprovalStepState] = []
    i = 0
    while i < len(rest):
        for parts, decision in phrases:
            if parts and rest[i : i + len(parts)] == parts:
                found.append(decision)
                i += len(parts)
                break
        else:
            if rest[i] not in neutral:
                return None
            i += 1
    return found[0] if len(found) == 1 else None


def clarity_problem(content: str, policy: VerifierPolicy) -> str | None:
    """CONTENT / SCORE refusals (A9 and the withholding rule): negation or withholding, quote or
    forward markers (or a wholly quoted message), questions, conditional / deferral / past
    conditional wording."""
    words = tokens(content)
    if any(w in policy.negation_tokens for w in words):
        return NEGATION_OR_WITHHOLDING
    if _wholly_quoted(content) or any(w in policy.quote_marker_tokens for w in words):
        return QUOTED_OR_FORWARDED
    question = unicodedata.normalize("NFKC", content).strip().endswith("?") or (
        bool(words) and words[0] in policy.interrogative_first_tokens
    )
    if question or any(w in policy.interrogative_any_tokens for w in words):
        return QUESTION_OR_DEFERRED
    if any(w in policy.deferral_tokens for w in words):
        return QUESTION_OR_DEFERRED
    return None


def _subject_reference(content: str, evidence: NewEvidence, policy: VerifierPolicy) -> bool:
    """A8 for CONTENT / SCORE: the review code exactly once (and no other code-shaped token) or
    the job wire ID."""
    text = content.replace(evidence.job_id, " ") if evidence.job_id else content
    words = tokens(text)
    code = normalise(evidence.review_code) if evidence.review_code else None
    shape = re.compile(policy.review_code_pattern)
    other_codes = [w for w in words if shape.fullmatch(w) and w != code]
    if other_codes:
        return False
    if code is not None and words.count(code) > 1:
        return False
    if code is not None and words.count(code) == 1:
        return True
    return evidence.job_id is not None and evidence.job_id in content


def _scores_stated(
    words: list[str], scores: tuple[tuple[QualityDimension, int], ...], policy: VerifierPolicy
) -> bool:
    if len({d for d, _ in scores}) != len(scores):
        return False
    for dimension, points in scores:
        labels = {normalise(label) for label in policy.dimension_labels.get(dimension, ())}
        stated = [words[i + 1] for i, word in enumerate(words[:-1]) if word in labels]
        if stated != [str(points)]:
            return False
    return True


def _scores_in_range(scores: tuple[tuple[QualityDimension, int], ...]) -> bool:
    return all(
        isinstance(p, int) and not isinstance(p, bool) and 0 <= p <= d.max_points for d, p in scores
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
    confirmation pass the confirmation quote and ``message_at = None``. A confirmation runs the
    authenticity tests, the subject reference and clarity, and for DECISION kinds the same
    decision. ``not_before`` is exclusive.
    """
    if event is None:
        return EventUnavailable(evidence.session_id, evidence.event_uuid)
    content = event.content
    kind = policy.record_kind_rules.get(evidence.record_kind)
    session_id = evidence.session_id if purpose == RECORD else event.session_id
    checks: dict[str, bool] = {"rule_defined": kind is not None}
    if kind is EvidenceVerificationKind.DECISION:
        checks["review_code_given"] = bool(evidence.review_code)
        checks["decision_given"] = evidence.parsed_decision is not None
    checks |= {
        "event_identity": event.session_id == session_id
        and (purpose != RECORD or event.event_uuid == evidence.event_uuid),
        "role_user": event.role == USER_ROLE,
        "not_synthetic": not event.is_synthetic,
        "human_origin": event.inbound_origin in policy.human_inbound_origins,
        "owner_account": event.sender_account in policy.owner_account_ids,
        "top_level_session": not policy.require_top_level_session
        or event.parent_session_id is None,
        "quote_verbatim": bool(quote) and quote in content,
        "timestamp_equal": message_at is None or message_at == event.timestamp,
        "message_order": event.timestamp > not_before,
        "distinct_event": distinct_from_event_uuid is None
        or event.event_uuid != distinct_from_event_uuid,
    }
    if kind is EvidenceVerificationKind.DECISION:
        stated = read_decision(content, evidence.review_code or "", policy)
        checks[NEEDS_CLARIFICATION] = stated is not None
        checks["subject_reference"] = stated is not None
        checks["clarity"] = stated is not None
        checks["decision_matches"] = stated is not None and stated == evidence.parsed_decision
    elif kind is not None:
        problem = clarity_problem(content, policy)
        checks[NEGATION_OR_WITHHOLDING] = problem != NEGATION_OR_WITHHOLDING
        checks[QUOTED_OR_FORWARDED] = problem != QUOTED_OR_FORWARDED
        checks[QUESTION_OR_DEFERRED] = problem != QUESTION_OR_DEFERRED
        checks["clarity"] = problem is None
        checks["subject_reference"] = _subject_reference(content, evidence, policy)
        checks["decision_not_applicable"] = evidence.parsed_decision is None
        if kind is EvidenceVerificationKind.CONTENT and purpose == RECORD:
            reference = {
                normalise(evidence.review_code or ""),
                normalise(evidence.job_id or ""),
            }
            carried = [
                w for w in tokens(quote) if w not in policy.decision_words and w not in reference
            ]
            long_enough = (
                evidence.record_kind is not EvidenceRecordKind.CONTRIBUTION
                or len(quote.strip()) >= policy.min_contribution_chars
            )
            checks["content_present"] = bool(carried) and long_enough
        if kind is EvidenceVerificationKind.SCORE and purpose == RECORD:
            checks["scores_given"] = bool(evidence.claimed_scores)
            checks["scores_in_range"] = _scores_in_range(evidence.claimed_scores)
            checks["scores_stated"] = bool(evidence.claimed_scores) and _scores_stated(
                tokens(content), evidence.claimed_scores, policy
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
