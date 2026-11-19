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
from datetime import datetime, timedelta
from typing import Final, Protocol, runtime_checkable

from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceVerificationKind,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.ids import ActorRef, ApprovalId, JobId, UserId, WireId
from amw_core.text_normalise import normalise_for_matching

VerificationKind = EvidenceVerificationKind
USER_ROLE: Final = "user"
RECORD: Final = "RECORD"
CONFIRMATION: Final = "CONFIRMATION"
NEEDS_CLARIFICATION: Final = "needs_clarification"
"""A decision message outside the whitelist grammar (03 rule 7 A9 / DECISION)."""
NEGATION_OR_WITHHOLDING: Final = "negation_or_withholding"
QUESTION_OR_DEFERRED: Final = "question_or_deferred"
QUOTED_OR_FORWARDED: Final = "quoted_or_forwarded"
EMBEDDED_PART_UNMARKED: Final = "embedded_part_unmarked"
"""A6 (CCR-125): a reply embeds an earlier message and the event source does not mark which part
the owner wrote: ``NEEDS_CLARIFICATION``, nothing is recorded."""
OWNER_PART_MISMATCH: Final = "owner_part_not_in_event"
"""A6 (CCR-125): the marked owner-authored part is not a part of the event content."""
CLARIFICATION_REASONS: Final = frozenset(
    {
        NEEDS_CLARIFICATION,
        NEGATION_OR_WITHHOLDING,
        QUESTION_OR_DEFERRED,
        QUOTED_OR_FORWARDED,
        EMBEDDED_PART_UNMARKED,
    }
)
"""Refusals where the operator must ask the owner to restate (nothing is recorded)."""

# ---- configuration defaults: OWNER TO CONFIRM every list below (config approvals.owner_chat.*).
DEFAULT_RECORD_KIND_RULES: Final[Mapping[EvidenceRecordKind, EvidenceVerificationKind]] = {
    EvidenceRecordKind.STEP_DECISION: EvidenceVerificationKind.DECISION,
    EvidenceRecordKind.COMPLIANCE_DECISION: EvidenceVerificationKind.DECISION,
    EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST: EvidenceVerificationKind.DECISION,
    EvidenceRecordKind.CONTRIBUTION: EvidenceVerificationKind.CONTENT,
    EvidenceRecordKind.REVISION_NOTE: EvidenceVerificationKind.CONTENT,
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
    "release": _A, "मंजूर": _A, "होय": _A, "ठीक": _A, "ठीक आहे": _A, "हाँ": _A,
    # reject side
    "reject": _R, "rejected": _R, "no": _R, "stop": _R, "नामंजूर": _R, "नाही": _R, "नहीं": _R,
    # changes requested (the change itself is a separate CONTENT record)
    "changes": ApprovalStepState.CHANGES_REQUESTED, "बदल": ApprovalStepState.CHANGES_REQUESTED,
}  # fmt: skip
DEFAULT_CONFIRM_WORDS: Final = frozenset({"confirm", "confirmed", "पक्के", "पक्का", "पक्की"})
"""``approvals.owner_chat.confirm_words.<lang>`` (CCR-101); disjoint from the decision words."""
DEFAULT_STAGE_WORDS: Final[Mapping[str, tuple[str, ...]]] = {
    "script": ("s05_script", "s05_shorts"),
    "स्क्रिप्ट": ("s05_script", "s05_shorts"),
    "visuals": ("s09_plan",),
    "thumbnail": ("s11_thumbs",),
    "थंबनेल": ("s11_thumbs",),
}
"""``approvals.owner_chat.stage_words.<lang>`` (CCR-089): word -> candidate stages; the one the
approval's workflow allows is chosen (``script`` is ``s05_script`` or ``s05_shorts``)."""
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
DEFAULT_REVIEW_CODE_PATTERN: Final = (
    r"(?=[2-9a-hjkmnp-z]*[a-hjkmnp-z])(?=[2-9a-hjkmnp-z]*[2-9])[2-9a-hjkmnp-z]{4}"
)
"""Case-folded shape of a review code (CCR-090: 4 characters of ``23456789ABCDEFGHJKMNPQRSTUVWXYZ``
with at least one letter and one digit); see ``amw_core.owner_evidence_review_code``."""
DEFAULT_DIMENSION_LABELS: Final[Mapping[QualityDimension, tuple[str, ...]]] = {
    d: (d.value.casefold(),) for d in QualityDimension
}
_NO_ANCHOR_KINDS: Final = frozenset(
    {EvidenceRecordKind.OWNER_TOPIC, EvidenceRecordKind.DATASET_INTAKE}
)
"""A7 (CCR-091): kinds that precede the job and have no request anchor."""
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
    embeds_earlier_message: bool = False
    """The platform marks this event as a reply that embeds an earlier message (CCR-125)."""
    owner_authored_content: str | None = None
    """The part of ``content`` the owner wrote, as marked by the event source (CCR-125). ``None``
    = the source marks nothing: valid only for an event with no embedded text."""


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
    parsed_target_stage_id: str | None = None
    """``CHANGES_REQUESTED`` only (CCR-089): the stage code maps from the message's stage word."""
    supersedes_id: WireId | None = None
    claimed_scores: tuple[tuple[QualityDimension, int], ...] = ()
    """``HUMAN_SCORE`` only (CCR-060): the integer points per dimension the owner wrote."""

    @property
    def claimed_scores_json(self) -> dict[str, int] | None:
        """The ``claimed_scores`` jsonb value ``{dimension: points}`` (NULL when empty)."""
        return {d.value: p for d, p in self.claimed_scores} or None


def evidence_sha256(evidence: NewEvidence) -> str:
    """``evidence_sha256`` of 04 section 5.16 over the listed fields (incl. ``claimed_scores`` and
    ``parsed_target_stage_id``)."""
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
        "parsed_target_stage_id": evidence.parsed_target_stage_id,
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
    confirm_words: frozenset[str] = DEFAULT_CONFIRM_WORDS
    stage_words: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_STAGE_WORDS)
    )
    content_max_age_ms: int | None = None
    """``approvals.owner_chat.content_max_age_ms`` (CCR-091): freshness window for OWNER_TOPIC /
    DATASET_INTAKE events; no default (unset = those kinds are refused, fail closed)."""
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


_EMBED_START = re.compile(
    r"^(?:[>\u203a\u00bb\u2265|]|-{2,}\s*(?:original|forwarded)\s+message|-\s*original\s+message"
    r"\s*-|_{5,}|={5,}|begin forwarded message|on\s.{1,200}\swrote:?$)",
)
_EMBED_END = re.compile(
    r"(?:wrote|writes|said|\u092e\u094d\u0939\u0923\u093e\u0932\u0947|"
    r"\u092e\u094d\u0939\u0923\u093e\u0932\u093e|\u0932\u093f\u0916\u093e|"
    r"\u0915\u0939\u093e)\s*:$"
)
_HEADER_FROM = re.compile(r"^(?:from|de|von)\s*:\s*\S")
_HEADER_OTHER = re.compile(r"^(?:sent|date|to|cc|subject|\u0935\u093f\u0937\u092f)\s*:\s*\S")


def _lines_for_embed_check(content: str) -> list[str]:
    """Each line normalised on its own (``amw_core.text_normalise``: NFKC, casefold, invisible and
    format characters such as U+200B / U+2060 / U+200E / U+FEFF removed, look-alikes folded), so a
    quote marker hidden behind an invisible prefix is still at the start of its line."""
    lines = re.split(r"[\r\n\u2028\u2029\u0085]+", content)
    return [normalise_for_matching(line).text for line in lines if line.strip()]


def _looks_embedded(content: str) -> bool:
    """Quote-prefix lines (greater-than, single / double angle quotes, pipe), a forwarded or
    original-message rule, an "On ... wrote:" header, a line ending "... wrote:", or an
    Outlook-style ``From:`` header block (``From:`` plus ``Sent:`` / ``To:`` / ``Subject:``)."""
    lines = _lines_for_embed_check(content)
    if any(_EMBED_START.match(line) or _EMBED_END.search(line) for line in lines):
        return True
    return any(_HEADER_FROM.match(line) for line in lines) and any(
        _HEADER_OTHER.match(line) for line in lines
    )


def owner_part(event: SessionEvent) -> tuple[str | None, str]:
    """``(problem, text)``: the owner-authored text every check reads (CCR-125). ``problem`` is
    ``EMBEDDED_PART_UNMARKED`` (embedded text, no marking), ``OWNER_PART_MISMATCH`` (the marked
    part is not in the content) or ``None``; the embedded text never counts."""
    marked = event.owner_authored_content
    if marked is None:
        if event.embeds_earlier_message or _looks_embedded(event.content):
            return EMBEDDED_PART_UNMARKED, ""
        return None, event.content
    if not marked.strip() or marked not in event.content:
        return OWNER_PART_MISMATCH, ""
    if _looks_embedded(marked):
        return EMBEDDED_PART_UNMARKED, ""  # the marked part itself carries embedded text
    return None, marked


def _wholly_quoted(content: str) -> bool:
    text = content.strip()
    return len(text) >= 2 and text[0] in _QUOTES and text[-1] in _QUOTES


def _without_code(content: str, review_code: str) -> list[str] | None:
    """Whitelist tokens with exactly one review code removed; ``None`` for a question, a wholly
    quoted message, or zero / several copies of the code."""
    if _wholly_quoted(content) or "?" in unicodedata.normalize("NFKC", content):
        return None  # A9, checked before punctuation is removed
    words = whitelist_tokens(content)
    code = " ".join(whitelist_tokens(review_code))
    if not code or words.count(code) != 1:
        return None
    return [w for w in words if w != code]


def read_decision_message(
    content: str,
    review_code: str,
    policy: VerifierPolicy,
    allowed_stages: frozenset[str] | None = None,
) -> tuple[ApprovalStepState, str | None] | None:
    """The ``(decision, target stage)`` of a DECISION-kind message under the whitelist grammar
    (CCR-087 / CCR-089), or ``None`` (``NEEDS_CLARIFICATION``): exactly one review code; every
    other token a decision, neutral or (with ``CHANGES_REQUESTED`` only) stage token; exactly
    one decision word; ``CHANGES_REQUESTED`` needs exactly one stage word that maps to one stage
    in ``allowed_stages`` (``None`` = any stage of the map)."""
    rest = _without_code(content, review_code)
    if rest is None:
        return None
    phrases: list[tuple[list[str], tuple[str, str]]] = [
        (whitelist_tokens(p), ("decision", d.value)) for p, d in policy.decision_words.items()
    ]
    phrases += [(whitelist_tokens(w), ("stage", w)) for w in policy.stage_words]
    phrases.sort(key=lambda item: -len(item[0]))
    neutral = {" ".join(whitelist_tokens(n)) for n in policy.neutral_tokens}
    decisions: list[ApprovalStepState] = []
    stage_words: list[str] = []
    i = 0
    while i < len(rest):
        for parts, (kind, value) in phrases:
            if parts and rest[i : i + len(parts)] == parts:
                if kind == "decision":
                    decisions.append(ApprovalStepState(value))
                else:
                    stage_words.append(str(value))
                i += len(parts)
                break
        else:
            if rest[i] not in neutral:
                return None
            i += 1
    if len(decisions) != 1:
        return None
    decision = decisions[0]
    if decision is not ApprovalStepState.CHANGES_REQUESTED:
        return None if stage_words else (decision, None)
    if len(stage_words) != 1:
        return None
    candidates = [
        stage
        for stage in policy.stage_words[stage_words[0]]
        if allowed_stages is None or stage in allowed_stages
    ]
    return (decision, candidates[0]) if len(candidates) == 1 else None


def read_decision(
    content: str, review_code: str, policy: VerifierPolicy
) -> ApprovalStepState | None:
    """The decision only (see ``read_decision_message``); ``None`` = ``NEEDS_CLARIFICATION``."""
    reading = read_decision_message(content, review_code, policy)
    return reading[0] if reading else None


def is_confirmation(content: str, review_code: str | None, policy: VerifierPolicy) -> bool:
    """Confirmation whitelist (CCR-101): exactly the record's own review code, exactly one confirm
    word, every other token neutral. A dispute, correction, new decision or second code is never a
    confirmation."""
    if not review_code:
        return False
    rest = _without_code(content, review_code)
    if rest is None:
        return False
    confirm = {" ".join(whitelist_tokens(w)) for w in policy.confirm_words}
    neutral = {" ".join(whitelist_tokens(n)) for n in policy.neutral_tokens}
    hits = [w for w in rest if w in confirm]
    return len(hits) == 1 and all(w in confirm or w in neutral for w in rest)


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
    anchor: datetime | None,
    distinct_from_event_uuid: str | None,
    policy: VerifierPolicy,
    now: datetime,
    allowed_stages: frozenset[str] | None = None,
) -> VerificationOutcome:
    """Pure check of one fetched event against the operator's claims (03 section 11.6 rule 7).

    ``purpose = RECORD``: the evidence's own quote and ``message_at``; ``anchor`` is the request
    (``approvals.created_at``; the job's creation for CONTRIBUTION / HUMAN_SCORE; the superseded
    evidence if later) or ``None`` for OWNER_TOPIC / DATASET_INTAKE, which use the freshness
    window instead (A7, CCR-091). ``purpose = CONFIRMATION``: the confirmation quote,
    ``message_at = None``, ``anchor`` = the recorded event time, and the confirmation whitelist
    (CCR-101) replaces the kind rules. ``anchor`` is exclusive.
    """
    if event is None:
        return EventUnavailable(evidence.session_id, evidence.event_uuid)
    part_problem, content = owner_part(event)
    kind = policy.record_kind_rules.get(evidence.record_kind)
    session_id = evidence.session_id if purpose == RECORD else event.session_id
    checks: dict[str, bool] = {"rule_defined": kind is not None}
    if purpose == RECORD and kind is EvidenceVerificationKind.DECISION:
        checks["review_code_given"] = bool(evidence.review_code)
        checks["decision_given"] = evidence.parsed_decision is not None
    if purpose == RECORD and evidence.record_kind in _NO_ANCHOR_KINDS:
        window = policy.content_max_age_ms  # no request anchor: freshness window (CCR-091)
        order_ok = window is not None and (
            timedelta(0) <= now - event.timestamp <= timedelta(milliseconds=window)
        )
    else:
        order_ok = anchor is not None and event.timestamp > anchor
    checks |= {
        "event_identity": event.session_id == session_id
        and (purpose != RECORD or event.event_uuid == evidence.event_uuid),
        "role_user": event.role == USER_ROLE,
        "not_synthetic": not event.is_synthetic,
        "human_origin": event.inbound_origin in policy.human_inbound_origins,
        "owner_account": event.sender_account in policy.owner_account_ids,
        "top_level_session": not policy.require_top_level_session
        or event.parent_session_id is None,
        EMBEDDED_PART_UNMARKED: part_problem != EMBEDDED_PART_UNMARKED,
        OWNER_PART_MISMATCH: part_problem != OWNER_PART_MISMATCH,
        "quote_verbatim": part_problem is None and bool(quote) and quote in content,
        "timestamp_equal": message_at is None or message_at == event.timestamp,
        "message_order": order_ok,
        "distinct_event": distinct_from_event_uuid is None
        or event.event_uuid != distinct_from_event_uuid,
    }
    if purpose == CONFIRMATION:
        confirmed = is_confirmation(content, evidence.review_code, policy)
        checks["confirmation_grammar"] = confirmed
        checks["subject_reference"] = confirmed
        checks["clarity"] = confirmed
    elif kind is EvidenceVerificationKind.DECISION:
        reading = read_decision_message(content, evidence.review_code or "", policy, allowed_stages)
        checks[NEEDS_CLARIFICATION] = reading is not None
        checks["subject_reference"] = reading is not None
        checks["clarity"] = reading is not None
        checks["decision_matches"] = reading is not None and reading[0] == evidence.parsed_decision
        checks["target_stage_matches"] = (
            reading is not None and reading[1] == evidence.parsed_target_stage_id
        )
    elif kind is not None:
        problem = clarity_problem(content, policy)
        checks[NEGATION_OR_WITHHOLDING] = problem != NEGATION_OR_WITHHOLDING
        checks[QUOTED_OR_FORWARDED] = problem != QUOTED_OR_FORWARDED
        checks[QUESTION_OR_DEFERRED] = problem != QUESTION_OR_DEFERRED
        checks["clarity"] = problem is None
        checks["subject_reference"] = _subject_reference(content, evidence, policy)
        checks["decision_not_applicable"] = (
            evidence.parsed_decision is None and evidence.parsed_target_stage_id is None
        )
        if kind is EvidenceVerificationKind.CONTENT:
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
        if kind is EvidenceVerificationKind.SCORE:
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
