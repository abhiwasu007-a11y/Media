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

Rules (all mandatory; a missing input is a refusal, never a skipped check):

1. the event exists and is the requested one (same session ID and event UUID);
2. role ``user``; 3. not synthetic;
4. inbound origin is the human owner (``VerifierPolicy.human_inbound_origins``), not a peer
   session, sub-agent, notification, tool result, scheduled message or document;
5. the quote is a non-empty verbatim substring of the content;
6. the recorded message time equals the event timestamp (a confirmation takes its time from
   the event);
7. a review code is given and occurs exactly once as a whole token: the code is unique per
   approval (approval ID + subject hash + nonce), so one message verifies one subject only;
8. a decision is given, and the content states it in the strict grammar below;
9. message order: the event is later than the approval request and than any evidence it
   supersedes; a confirmation is a second, distinct, later event with the same review code and
   the same decision.

Decision grammar (strict, closed): the content is split into word tokens; every token from the
closed decision list (config ``approvals.owner_chat.decision_words.<lang>``; English and Marathi
defaults below) must map to the same decision, one of them must stand directly next to the
review code, and **any** negation token (``VerifierPolicy.negation_tokens``) anywhere in the
message makes it ambiguous (``needs_clarification``: refused; the operator asks the owner).

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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from amw_core.enums import ApprovalStepState, EvidenceRecordKind, InstructionSourceKind
from amw_core.ids import ActorRef, ApprovalId, JobId, UserId, WireId

USER_ROLE: Final = "user"
RECORD: Final = "RECORD"
CONFIRMATION: Final = "CONFIRMATION"
NEEDS_CLARIFICATION: Final = "needs_clarification"

# Design defaults (closed lists; config overrides them; Marathi forms to be confirmed by the owner).
DEFAULT_DECISION_WORDS: Final[Mapping[str, ApprovalStepState]] = {
    "approve": ApprovalStepState.APPROVED,
    "approved": ApprovalStepState.APPROVED,
    "मंजूर": ApprovalStepState.APPROVED,
    "reject": ApprovalStepState.REJECTED,
    "rejected": ApprovalStepState.REJECTED,
    "नामंजूर": ApprovalStepState.REJECTED,
    "changes": ApprovalStepState.CHANGES_REQUESTED,
    "बदल": ApprovalStepState.CHANGES_REQUESTED,
}
DEFAULT_NEGATION_TOKENS: Final = frozenset(
    {"not", "no", "never", "don't", "dont", "do'nt", "nope", "नाही", "नको", "न", "नये"}
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


def evidence_sha256(evidence: NewEvidence) -> str:
    """``evidence_sha256`` of 04 section 5.16: SHA-256 of the canonical evidence fields."""
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
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class VerifierPolicy:
    """Configuration of the check (from ``amw_core.config``, never from the model)."""

    human_inbound_origins: frozenset[str]
    """``inbound_origin`` values that mean "typed by the human owner" in the session store."""
    decision_words: Mapping[str, ApprovalStepState]
    """Closed list of single decision words (all configured languages) -> decision."""
    negation_tokens: frozenset[str] = DEFAULT_NEGATION_TOKENS


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


@dataclass(frozen=True, slots=True)
class EventUnavailable:
    """The event could not be fetched: the evidence stays ``PENDING_VERIFICATION``."""

    session_id: str
    event_uuid: str


type VerificationOutcome = Verified | Refusal | EventUnavailable

_TOKEN = re.compile("[\\w'\u2019\u0900-\u097f]+")


def tokens(content: str) -> list[str]:
    """Lower-cased word tokens (Devanagari vowel signs and virama stay inside the word)."""
    return [t.replace("\u2019", "'") for t in _TOKEN.findall(content.casefold())]


def read_decision(
    content: str, review_code: str, policy: VerifierPolicy
) -> ApprovalStepState | str:
    """The decision stated in ``content`` under the strict grammar, or a refusal reason."""
    words = tokens(content)
    code = review_code.casefold()
    positions = [i for i, w in enumerate(words) if w == code]
    if len(positions) != 1:
        return "review_code_present"
    if any(w in policy.negation_tokens for w in words):
        return NEEDS_CLARIFICATION
    found = {policy.decision_words[w] for w in words if w in policy.decision_words}
    if len(found) != 1:
        return NEEDS_CLARIFICATION if found else "decision_matches"
    neighbours = [words[i] for i in (positions[0] - 1, positions[0] + 1) if 0 <= i < len(words)]
    if not any(w in policy.decision_words for w in neighbours):
        return "decision_adjacent"
    return next(iter(found))


def verify_owner_event(
    event: SessionEvent | None,
    *,
    evidence_id: WireId,
    purpose: str,
    bound_sha256: str,
    session_id: str,
    event_uuid: str,
    quote: str,
    message_at: datetime | None,
    review_code: str | None,
    decision: ApprovalStepState | None,
    not_before: datetime,
    distinct_from_event_uuid: str | None,
    policy: VerifierPolicy,
    now: datetime,
) -> VerificationOutcome:
    """Pure check of one fetched event against the operator's claims (rules 1-9 above).

    ``message_at`` is ``None`` only for a confirmation. ``not_before`` is exclusive.
    """
    if event is None:
        return EventUnavailable(session_id, event_uuid)
    content = event.content
    stated = read_decision(content, review_code, policy) if review_code else "review_code_given"
    checks: dict[str, bool] = {
        "review_code_given": bool(review_code),
        "decision_given": decision is not None,
        "event_identity": event.session_id == session_id and event.event_uuid == event_uuid,
        "role_user": event.role == USER_ROLE,
        "not_synthetic": not event.is_synthetic,
        "human_origin": event.inbound_origin in policy.human_inbound_origins,
        "quote_verbatim": bool(quote) and quote in content,
        "timestamp_equal": message_at is None or message_at == event.timestamp,
        "review_code_present": stated != "review_code_present",
        NEEDS_CLARIFICATION: stated != NEEDS_CLARIFICATION,
        "decision_adjacent": stated != "decision_adjacent",
        "decision_matches": decision is not None and stated == decision,
        "message_order": event.timestamp > not_before,
        "distinct_event": distinct_from_event_uuid is None
        or event.event_uuid != distinct_from_event_uuid,
    }
    frozen = tuple(checks.items())
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        return Refusal(reason=failed[0], checks=frozen)
    return Verified(
        evidence_id=evidence_id,
        event_uuid=event.event_uuid,
        bound_sha256=bound_sha256,
        purpose=purpose,
        event_timestamp=event.timestamp,
        checks=frozen,
        verified_at=now,
    )
