"""Deterministic verifier of owner chat evidence (R14; 03 section 11.6 rule 6; 04 section 5.16
code check; 08 ``sys_operator``; CCR-010, decision D5).

The operator tool (an LLM acting as ``sys_operator``) supplies only identifiers and the words it
read: session ID, event UUID, the quote, the message time, the review code and the decision.
Nothing it says is trusted. Code fetches the event from the platform's session event store
(``SessionEventSource``) and ``verify_owner_event`` checks, in code, never by a model:

1. the event exists and is the requested one (same session ID and event UUID);
2. its role is ``user``;
3. it is not synthetic;
4. its inbound origin is the human owner (``VerifierPolicy.human_inbound_origins``), not a peer
   session, sub-agent, notification, tool result, scheduled message or document;
5. the quote is a non-empty verbatim substring of the event content;
6. the recorded message time equals the event timestamp;
7. the content contains the review code (where required): the code is unique per approval
   (approval ID + subject hash + nonce), so one owner message cannot be replayed for another
   subject;
8. the content contains decision words that map to exactly the recorded decision (config
   ``approvals.owner_chat.decision_words.<lang>``), never two different decisions;
9. message order: the event is later than the approval request and than any evidence it
   supersedes; a confirmation is a second, distinct event later than the recorded one.

Only this module can construct ``VerifiedEvidence`` (sealed constructor), and the evidence store
accepts nothing else for ``mark_verified``; ``confirm`` fetches and verifies its event itself.

**Limitation (honest status).** The real ``SessionEventSource`` adapter that reads the platform's
session record is a later ticket (3A-13). Until it exists only the in-memory fake
(``amw_core.testing.memory.MemorySessionEventSource``) is available, so no 3A approval recorded
through this path may be treated as production-verified. The ``inbound_origin`` and ``role``
vocabularies of the real store are not yet confirmed; they are configuration
(``VerifierPolicy``), not hard-coded.
"""

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

from amw_core.enums import ApprovalStepState, EvidenceRecordKind, InstructionSourceKind
from amw_core.ids import ActorRef, ApprovalId, JobId, UserId, WireId

USER_ROLE: Final = "user"
RECORD: Final = "RECORD"
CONFIRMATION: Final = "CONFIRMATION"


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
    """Read access to the platform's session event store (one event by ID).

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
    """Configuration of the check (values come from ``amw_core.config``, never from the model)."""

    human_inbound_origins: frozenset[str]
    """``inbound_origin`` values that mean "typed by the human owner" in the session store."""
    decision_words: Mapping[str, ApprovalStepState]
    """Lower-case decision words / phrases of every configured language -> decision."""


_SEAL: Final = object()


class VerifiedEvidence:
    """Proof that ``verify_owner_event`` passed for one event. Not constructible elsewhere."""

    __slots__ = (
        "_checks",
        "bound_sha256",
        "content",
        "event_timestamp",
        "event_uuid",
        "purpose",
        "session_id",
        "verified_at",
    )

    def __init__(
        self,
        seal: object,
        *,
        purpose: str,
        bound_sha256: str,
        event: SessionEvent,
        checks: Mapping[str, bool],
        verified_at: datetime,
    ) -> None:
        if seal is not _SEAL:
            raise TypeError("VerifiedEvidence is created only by verify_owner_event")
        self.purpose = purpose
        self.bound_sha256 = bound_sha256
        self.session_id = event.session_id
        self.event_uuid = event.event_uuid
        self.event_timestamp = event.timestamp
        self.content = event.content
        self._checks = MappingProxyType(dict(checks))
        self.verified_at = verified_at

    @property
    def checks(self) -> Mapping[str, bool]:
        """Each test and its result (stored as ``verifier_result``: no extra text)."""
        return self._checks


@dataclass(frozen=True, slots=True)
class Refusal:
    """The check failed; the evidence is refused with ``reason`` (first failing test)."""

    reason: str
    checks: Mapping[str, bool]


@dataclass(frozen=True, slots=True)
class EventUnavailable:
    """The event could not be fetched: the evidence stays ``PENDING_VERIFICATION``."""

    session_id: str
    event_uuid: str


type VerificationOutcome = VerifiedEvidence | Refusal | EventUnavailable


def _boundary(text: str, index: int) -> bool:
    if index < 0 or index >= len(text):
        return True
    return unicodedata.category(text[index])[0] not in "LMN"


def _contains_phrase(text: str, phrase: str) -> bool:
    start = text.find(phrase)
    while start != -1:
        if _boundary(text, start - 1) and _boundary(text, start + len(phrase)):
            return True
        start = text.find(phrase, start + 1)
    return False


def decisions_in(content: str, policy: VerifierPolicy) -> frozenset[ApprovalStepState]:
    """Every decision whose configured word or phrase occurs as a whole word in ``content``."""
    folded = content.casefold()
    return frozenset(
        decision
        for word, decision in policy.decision_words.items()
        if word and _contains_phrase(folded, word.casefold())
    )


def verify_owner_event(
    event: SessionEvent | None,
    *,
    purpose: str,
    bound_sha256: str,
    session_id: str,
    event_uuid: str,
    quote: str,
    message_at: datetime | None,
    review_code: str | None,
    parsed_decision: ApprovalStepState | None,
    not_before: datetime,
    distinct_from_event_uuid: str | None,
    policy: VerifierPolicy,
    now: datetime,
) -> VerificationOutcome:
    """Pure check of one fetched event against the operator's claims (rules 1-9 above).

    ``message_at`` is ``None`` only for a confirmation, whose time is taken from the event.
    ``not_before`` is exclusive: the event must be strictly later.
    """
    if event is None:
        return EventUnavailable(session_id, event_uuid)
    content = event.content
    checks: dict[str, bool] = {
        "event_identity": event.session_id == session_id and event.event_uuid == event_uuid,
        "role_user": event.role == USER_ROLE,
        "not_synthetic": not event.is_synthetic,
        "human_origin": event.inbound_origin in policy.human_inbound_origins,
        "quote_verbatim": bool(quote) and quote in content,
        "timestamp_equal": message_at is None or message_at == event.timestamp,
        "review_code_present": review_code is None or _contains_phrase(content, review_code),
        "decision_matches": parsed_decision is None
        or decisions_in(content, policy) == {parsed_decision},
        "message_order": event.timestamp > not_before,
        "distinct_event": distinct_from_event_uuid is None
        or event.event_uuid != distinct_from_event_uuid,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        return Refusal(reason=f"owner event check failed: {failed[0]}", checks=checks)
    return VerifiedEvidence(
        _SEAL,
        purpose=purpose,
        bound_sha256=bound_sha256,
        event=event,
        checks=checks,
        verified_at=now,
    )


def verify_recorded_evidence(
    source: SessionEventSource,
    evidence: NewEvidence,
    policy: VerifierPolicy,
    *,
    request_created_at: datetime,
    superseded_message_at: datetime | None,
    now: datetime,
) -> VerificationOutcome:
    """Fetch the event named by ``evidence`` and verify it (the ``VERIFIED`` step).

    A source other than ``OWNER_CHAT_MESSAGE`` is refused without a fetch.
    """
    if evidence.source_kind is not InstructionSourceKind.OWNER_CHAT_MESSAGE:
        return Refusal(reason="source is not an owner chat message", checks={"source": False})
    not_before = max(request_created_at, superseded_message_at or request_created_at)
    return verify_owner_event(
        source.fetch(evidence.session_id, evidence.event_uuid),
        purpose=RECORD,
        bound_sha256=evidence_sha256(evidence),
        session_id=evidence.session_id,
        event_uuid=evidence.event_uuid,
        quote=evidence.quote,
        message_at=evidence.message_at,
        review_code=evidence.review_code,
        parsed_decision=evidence.parsed_decision,
        not_before=not_before,
        distinct_from_event_uuid=None,
        policy=policy,
        now=now,
    )


def verify_confirmation(
    source: SessionEventSource,
    evidence: NewEvidence,
    policy: VerifierPolicy,
    *,
    session_id: str,
    event_uuid: str,
    quote: str,
    now: datetime,
) -> VerificationOutcome:
    """Fetch and verify the owner's confirmation: a second, distinct event, later than the
    recorded one, carrying the same review code (no decision word is required)."""
    return verify_owner_event(
        source.fetch(session_id, event_uuid),
        purpose=CONFIRMATION,
        bound_sha256=evidence_sha256(evidence),
        session_id=session_id,
        event_uuid=event_uuid,
        quote=quote,
        message_at=None,
        review_code=evidence.review_code,
        parsed_decision=None,
        not_before=evidence.message_at,
        distinct_from_event_uuid=evidence.event_uuid,
        policy=policy,
        now=now,
    )
