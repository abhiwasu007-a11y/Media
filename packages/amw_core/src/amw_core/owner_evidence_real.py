"""The real owner-evidence path (R14, D5; WS-08 / 3A-13; 08 ``sys_operator``, CCR-100 / CCR-113).

Flow (each step in its own process and database login):

1. **Operator** (``amw_operator`` DSN; the assistant's tool) inserts ``PENDING_VERIFICATION``
   evidence with the owner's verbatim quote and the event's identifiers, then posts the echo
   (``amw_core.owner_evidence_operator``). It never verifies.
2. **Verifier** (``amw_verifier`` DSN; ``VerifierWorker``) reads the event from its own
   ``SessionEventSource``, runs 03 section 11.6 rule 7 (``EvidenceVerifierService``) and calls
   ``amw_evidence_mark_verified`` (MAC stamped in the database) or ``amw_evidence_refuse``.
3. The verifier **finds** the owner's reply itself (``confirm_from_chat``), in time order, among
   owner messages that name the row's code and come after the echo (an assistant message of the
   same session that shows the code and the quote):

   * ``confirm R7K2`` / ``R7K2 पक्के``, or the owner's decision form for the recorded decision
     (``approve R7K2`` / ``R7K2 मंजूर``; PROPOSED CCR-264) -> ``CONFIRMED``; before the echo they
     are ignored;
   * a question or deferral naming the code -> skipped (``NEEDS_CLARIFICATION`` if nothing else
     follows): it does not end the row;
   * the recorded message of another evidence row of the same subject is not a reply;
   * any other message naming the code (a dispute, a correction, another decision) ->
     ``amw_evidence_refuse`` (``VERIFIED -> REFUSED``, reason ``owner_disputed``): the owner
     restates and a new row is recorded.

``EvidenceMode.REAL`` refuses a session source that is not marked ``production_grade``; the
in-memory source is reachable only through the DRY_RUN path, which also refuses any database
whose own profile row (``evidence_db_profile``, migration 0059) is not ``TEST``. Every
``verifier_result`` written through ``build_verifier_service`` carries ``session_source_production``
(REAL) or ``session_source_test_fixture`` (DRY_RUN) inside the MAC; 0059 keeps the stored mark
through confirmation and refusal and refuses a mark the database profile does not allow.
``ConfirmedEvidenceLookup`` returns the shared ``owner_evidence_status.EvidenceStatus``
(``source_kind`` TEST_FIXTURE for any row without the production mark). These marks guard
against wiring mistakes and TEST rows reaching a real run; they are not a security boundary
against a holder of the verifier login (``docs/v4/runtime/EVIDENCE_PATH.md``).
"""

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    EvidenceVerificationKind,
    InstructionSourceKind,
)
from amw_core.errors import (
    ConfigInvalidError,
    IdempotencyConflictError,
    InputInvalidError,
    InvalidTransitionError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import WireId
from amw_core.interfaces.owner_evidence import DbSession, EvidenceDatabase, EvidenceRecord
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_fake import (
    PRODUCTION_MARK,
    TEST_MARK,
    FakeEvidenceDatabase,
    MemorySessionEventSource,
)
from amw_core.owner_evidence_service import EvidenceVerifierService
from amw_core.owner_evidence_status import (
    OWNER_CHAT_OPERATOR,
    EvidenceSourceKind,
    EvidenceStatus,
    subject_key,
)
from amw_core.owner_evidence_verifier import (
    DEFAULT_RECORD_KIND_RULES,
    QUESTION_OR_DEFERRED,
    SessionEventSource,
    VerifierPolicy,
    clarity_problem,
    tokens,
    whitelist_tokens,
)

OWNER_DISPUTED: Final = "owner_disputed"


class EvidenceMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    """TEST fixtures allowed; nothing recorded is production-verified."""
    REAL = "REAL"


def is_production_source(source: SessionEventSource) -> bool:
    return getattr(source, "production_grade", False) is True and not isinstance(
        source, MemorySessionEventSource
    )


@runtime_checkable
class ProfiledDatabase(Protocol):
    """A database that reports its ``evidence_db_profile`` (``REAL`` or ``TEST``; 0059)."""

    def db_profile(self, session: DbSession, tx: TenantTransaction | None) -> str: ...


def _profile(database: EvidenceDatabase, session: DbSession, tx: TenantTransaction | None) -> str:
    if isinstance(database, FakeEvidenceDatabase):
        return database.profile
    if isinstance(database, ProfiledDatabase):
        return database.db_profile(session, tx)
    return "UNKNOWN"


def build_verifier_service(
    mode: EvidenceMode,
    database: EvidenceDatabase,
    session: DbSession,
    source: SessionEventSource,
    policy: VerifierPolicy,
    *,
    tx: TenantTransaction | None = None,
) -> EvidenceVerifierService:
    """The verifier component for ``mode``. REAL refuses a non-production session source.
    DRY_RUN refuses any session source but the in-memory TEST one and any database whose own
    profile row (``evidence_db_profile``, 0059; REAL by default) is not ``TEST``: a dry run can
    never write into the real database (``tx`` is needed to read a PostgreSQL profile)."""
    if mode is EvidenceMode.REAL:
        if not is_production_source(source):
            raise ConfigInvalidError("real mode needs a production session record source (R14)")
        return EvidenceVerifierService(database, session, source, policy, {PRODUCTION_MARK: True})
    if not isinstance(source, MemorySessionEventSource):
        raise ConfigInvalidError("the dry run takes only the in-memory TEST source")
    if _profile(database, session, tx) != "TEST":
        raise ConfigInvalidError("the dry run refuses a database whose profile is not TEST")
    return EvidenceVerifierService(database, session, source, policy, {TEST_MARK: True})


def dry_run_verifier_service(
    database: EvidenceDatabase,
    session: DbSession,
    source: MemorySessionEventSource,
    policy: VerifierPolicy,
    *,
    tx: TenantTransaction | None = None,
) -> EvidenceVerifierService:
    """The explicit TEST factory (owner decision 2026-11-19: TEST fixtures for the dry run
    only); see ``build_verifier_service`` for what it refuses."""
    return build_verifier_service(EvidenceMode.DRY_RUN, database, session, source, policy, tx=tx)


class SessionMessage(Protocol):
    """One message of a session record (owner or assistant)."""

    @property
    def session_id(self) -> str: ...
    @property
    def event_uuid(self) -> str: ...
    @property
    def timestamp(self) -> datetime: ...
    @property
    def content(self) -> str: ...


OwnerMessage = SessionMessage


@runtime_checkable
class OwnerMessageIndex(Protocol):
    """The owner chat messages of one session (e.g. ``ClaudeSessionJsonlSource``)."""

    def owner_messages(self, session_id: str) -> Iterable[SessionMessage]: ...


@runtime_checkable
class SessionMessageIndex(OwnerMessageIndex, Protocol):
    """Owner messages plus the assistant's own messages (to find the echo; never evidence)."""

    def assistant_messages(self, session_id: str) -> Iterable[SessionMessage]: ...


AnchorLookup = Callable[[TenantTransaction, EvidenceRecord], datetime | None]
"""The request time of a row (``approvals.created_at``, the job's creation, ``None`` for
OWNER_TOPIC / DATASET_INTAKE). REQUIRES REVIEW (CCR-262): ``amw_verifier`` has no SELECT on
``approvals`` / ``jobs``, so the verifier process needs a grant or a definer function."""


class ConfirmationOutcome(StrEnum):
    CONFIRMED = "CONFIRMED"
    AWAITING_ECHO = "AWAITING_ECHO"
    """No echo of this row in the session yet: no reply can count."""
    NO_REPLY_YET = "NO_REPLY_YET"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    """Only a question or deferral named the code: the operator asks; the row stays VERIFIED."""
    DISPUTED = "DISPUTED"
    """The owner named the code with anything else: the row is now REFUSED (owner restates)."""
    REFUSED_CHECK = "REFUSED_CHECK"
    """A confirmation-shaped reply failed the authenticity check; the row stays VERIFIED."""
    SUPERSEDED = "SUPERSEDED"
    """A later decision record on the same code exists: this row is now REFUSED."""
    AMBIGUOUS = "AMBIGUOUS"
    """Another open record carries the same code: no reply can say which one it confirms."""


@dataclass(frozen=True, slots=True)
class ConfirmationScan:
    outcome: ConfirmationOutcome
    row: EvidenceRecord
    event_uuid: str | None = None


ECHO_QUOTE_PREFIX: Final = 40
SUPERSEDED: Final = "superseded_by_later_decision"
CONFIRM_FORMS: Final = (("confirm", None), (None, "पक्के"))
"""``confirm <code>`` / ``<code> पक्के``: confirm any record (CCR-101 / CCR-264)."""
APPROVE_FORMS: Final = (("approve", None), (None, "मंजूर"))
"""``approve <code>`` / ``<code> मंजूर``: confirm an APPROVED record only (PROPOSED CCR-264)."""
_SENTENCE_END: Final = frozenset(".!।")


_DEVANAGARI_WORDS: Final = frozenset({"मंजूर", "पक्के"})


def _strict_words(content: str) -> list[str] | None:
    """The two words of a short reply, or ``None``. No compatibility folding: only NFC (so the
    Devanagari words compare in one form), only plain ASCII spaces (leading / trailing ones
    stripped, exactly one between the words), every word either ASCII letters and digits
    (lower-cased) or exactly ``मंजूर`` / ``पक्के``; one final ``.`` / ``!`` / ``।`` is
    allowed. So fullwidth letters, NBSP or em space separators, ``R7K2_``, ``R7<ZWSP>K2``,
    quotes and other punctuation are never a confirmation."""
    text = unicodedata.normalize("NFC", content).strip(" ")
    if text and text[-1] in _SENTENCE_END:
        text = text[:-1].rstrip(" ")
    words = text.split(" ")
    if len(words) != 2:
        return None
    out: list[str] = []
    for word in words:
        if word in _DEVANAGARI_WORDS:
            out.append(word)
        elif word.isascii() and word.isalnum():
            out.append(word.lower())
        else:
            return None
    return out


def exact_confirmation(content: str, code: str, decision: ApprovalStepState | None) -> bool:
    """Exactly one of the confirmation forms (``approve`` forms only for an APPROVED record)."""
    words = _strict_words(content)
    folded = code.lower()
    if words is None or not folded or not (code.isascii() and code.isalnum()):
        return False
    forms = CONFIRM_FORMS + (APPROVE_FORMS if decision is ApprovalStepState.APPROVED else ())
    for before, after in forms:
        if (before is not None and words == [before, folded]) or (
            after is not None and words == [folded, after]
        ):
            return True
    return False


def _names_code(content: str, code: str) -> bool:
    folded = " ".join(whitelist_tokens(code))
    return bool(folded) and folded in whitelist_tokens(content)


def _is_echo(text: str, row: EvidenceRecord) -> bool:
    """An assistant message that shows this row's code and the start of its quote."""
    code = row.evidence.review_code or ""
    shown = row.evidence.quote.replace("\r", " ").replace("\n", " ")[:ECHO_QUOTE_PREFIX]
    return _names_code(text, code) and bool(shown.strip()) and shown in text


def superseded(row: EvidenceRecord, siblings: Iterable[EvidenceRecord]) -> bool:
    """A decision record is superseded by any other decision record on the same subject, code,
    approval and step whose owner message is as late or later, in any state (fail closed, also
    for a tie)."""
    e = row.evidence
    code = (e.review_code or "").upper()
    return any(
        r.id != row.id
        and (r.evidence.review_code or "").upper() == code
        and r.evidence.approval_id == e.approval_id
        and r.evidence.step_no == e.step_no
        and DEFAULT_RECORD_KIND_RULES.get(r.evidence.record_kind)
        is EvidenceVerificationKind.DECISION
        and r.evidence.message_at >= row.evidence.message_at
        for r in siblings
    )


class VerifierWorker:
    """Runs in the verifier process only (``amw_verifier`` login, the session-record reader)."""

    def __init__(
        self,
        service: EvidenceVerifierService,
        database: EvidenceDatabase,
        session: DbSession,
        index: SessionMessageIndex,
        policy: VerifierPolicy,
    ) -> None:
        self._service = service
        self._db = database
        self._session = session
        self._index = index
        self._policy = policy

    def verify(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        anchors: AnchorLookup,
        now: datetime,
        allowed_stages: frozenset[str] | None = None,
    ) -> EvidenceRecord:
        """``PENDING_VERIFICATION -> VERIFIED / REFUSED`` (anchor from the verifier's own
        lookup, never from the operator)."""
        row = self._db.get(self._session, tx, evidence_id)
        if row is None:
            raise MissingDependencyError("evidence not found")
        return self._service.verify_recorded(tx, evidence_id, anchors(tx, row), now, allowed_stages)

    def _echo_at(self, row: EvidenceRecord, now: datetime) -> datetime | None:
        times = [
            m.timestamp
            for m in self._index.assistant_messages(row.evidence.session_id)
            if row.evidence.message_at < m.timestamp <= now and _is_echo(m.content, row)
        ]
        return min(times) if times else None

    def confirm_from_chat(
        self, tx: TenantTransaction, evidence_id: WireId, now: datetime
    ) -> ConfirmationScan:
        """Look for the owner's reply to the echo in the record's own session (time order;
        messages stamped later than ``now`` are not considered yet)."""
        row = self._db.get(self._session, tx, evidence_id)
        if row is None:
            raise MissingDependencyError("evidence not found")
        if row.state is not EvidenceState.VERIFIED:
            raise InvalidTransitionError("only VERIFIED evidence can be confirmed")
        code = row.evidence.review_code or ""
        echo_at = self._echo_at(row, now)
        e = row.evidence
        siblings = [
            r
            for r in self._db.for_subject(self._session, tx, e.subject_kind, e.subject_id)
            if r.id != row.id and (r.evidence.review_code or "").upper() == code.upper()
        ]
        live = [r for r in siblings if r.state is not EvidenceState.REFUSED]
        others = {r.evidence.event_uuid for r in live} - {e.event_uuid}
        if self._policy.record_kind_rules.get(e.record_kind) is EvidenceVerificationKind.DECISION:
            if superseded(row, siblings):
                # only the latest decision on a code counts (CCR-264); fail closed: a later or
                # simultaneous decision record on the code supersedes this one whatever its
                # state (a refused later reject still means the owner did not stay at this one)
                ended = self._db.refuse(self._session, tx, row.id, SUPERSEDED, {SUPERSEDED: False})
                return ConfirmationScan(ConfirmationOutcome.SUPERSEDED, ended)
        elif any(r.state is EvidenceState.VERIFIED for r in live):
            # `confirm <code>` cannot tell two open records of one code apart
            return ConfirmationScan(ConfirmationOutcome.AMBIGUOUS, row)
        replies = sorted(
            (
                m
                for m in self._index.owner_messages(e.session_id)
                if e.message_at < m.timestamp <= now
                and m.event_uuid != e.event_uuid
                and m.event_uuid not in others  # another record's own message, not a reply
                and _names_code(m.content, code)
            ),
            key=lambda m: m.timestamp,
        )
        question: str | None = None
        refused: str | None = None
        for message in replies:
            confirms = exact_confirmation(message.content, code, row.evidence.parsed_decision)
            if confirms:
                if echo_at is None or message.timestamp <= echo_at:
                    continue  # a repeat before the owner saw the echo is not a confirmation
                try:
                    done = self._service.confirm(
                        tx,
                        evidence_id,
                        message.session_id,
                        message.event_uuid,
                        message.content,
                        now,
                        decision_form=True,
                    )
                except PermissionDeniedError, IdempotencyConflictError:
                    refused = refused or message.event_uuid  # the check refused this reply
                    continue
                return ConfirmationScan(ConfirmationOutcome.CONFIRMED, done, message.event_uuid)
            if clarity_problem(message.content, self._policy) == QUESTION_OR_DEFERRED:
                question = question or message.event_uuid
                continue
            ended = self._db.refuse(
                self._session, tx, row.id, OWNER_DISPUTED, {OWNER_DISPUTED: False}
            )
            return ConfirmationScan(ConfirmationOutcome.DISPUTED, ended, message.event_uuid)
        if refused is not None:
            return ConfirmationScan(ConfirmationOutcome.REFUSED_CHECK, row, refused)
        if question is not None:
            return ConfirmationScan(ConfirmationOutcome.NEEDS_CLARIFICATION, row, question)
        if echo_at is None:
            return ConfirmationScan(ConfirmationOutcome.AWAITING_ECHO, row)
        return ConfirmationScan(ConfirmationOutcome.NO_REPLY_YET, row)


PROVIDER_LIMIT: Final = "PROVIDER_LIMIT"
FIN_R10: Final = "FIN_R10_NOT_SEBI_REGISTERED"
DEFAULT_CURRENCY_WORDS: Final[Mapping[str, tuple[str, ...]]] = {
    "USD": ("usd", "$", "dollar", "dollars", "डॉलर"),
    "INR": ("inr", "₹", "rs", "rupee", "rupees", "रुपये", "रुपया"),
}
"""Words that name a currency in the owner's message (owner to confirm)."""
DEFAULT_FIN_R10_WORDS: Final = ("sebi", "सेबी")


@dataclass(frozen=True, slots=True)
class ConfirmationBinding:
    """What one run-preflight confirmation claims; the evidence row must say exactly that."""

    evidence_id: str
    kind: str
    provider: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    org_id: str | None = None
    """The org the confirmation is for; the evidence row must belong to it."""


_NUMBER = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")


def _states_amount(quote: str, amount_minor: int, exponent: int) -> bool:
    expected = Decimal(amount_minor).scaleb(-exponent)
    for raw in _NUMBER.findall(quote):
        try:
            if Decimal(raw.replace(",", "")) == expected:
                return True
        except InvalidOperation:  # pragma: no cover - the pattern only yields numbers
            continue
    return False


class ConfirmedEvidenceLookup:
    """Evidence status for a run preflight, read inside one tenant transaction.

    ``EvidenceStatus.kind`` / ``subject`` are set only when every one of these holds: the MAC
    verifies; the row was verified through a production session source; it belongs to the
    binding's org; its kind is in ``allowed_kinds`` and its quote states what the binding claims
    (provider, amount and currency of a limit, or the FIN-R10 statement). One evidence row backs
    exactly one binding (a second binding for the same row is a configuration error).
    ``allowed_kinds`` defaults to none (fail closed): no record kind exists yet for these owner
    statements (CCR-260)."""

    def __init__(
        self,
        database: EvidenceDatabase,
        session: DbSession,
        tx: TenantTransaction,
        bindings: Sequence[ConfirmationBinding],
        *,
        allowed_kinds: frozenset[EvidenceRecordKind] = frozenset(),
        currency_exponents: Mapping[str, int] | None = None,
        currency_words: Mapping[str, tuple[str, ...]] = DEFAULT_CURRENCY_WORDS,
        fin_r10_words: tuple[str, ...] = DEFAULT_FIN_R10_WORDS,
    ) -> None:
        ids_ = [b.evidence_id for b in bindings]
        if len(ids_) != len(set(ids_)):
            raise ConfigInvalidError("one evidence row may back one confirmation only")
        self._db = database
        self._session = session
        self._tx = tx
        self._bindings = {b.evidence_id: b for b in bindings}
        self._kinds = allowed_kinds
        self._exponents = dict(currency_exponents or {})
        """``finance.currency_minor_exponent`` from config (CCR-133: no code default; a currency
        without an exponent never binds)."""
        self._currency_words = currency_words
        self._fin_words = fin_r10_words

    @classmethod
    def for_confirmations(
        cls,
        database: EvidenceDatabase,
        session: DbSession,
        tx: TenantTransaction,
        confirmations: Iterable[Any],
        *,
        allowed_kinds: frozenset[EvidenceRecordKind] = frozenset(),
        currency_exponents: Mapping[str, int] | None = None,
    ) -> ConfirmedEvidenceLookup:
        """Bindings built from the run's confirmation records themselves (``kind``,
        ``provider``, ``amount_minor``, ``currency``, ``evidence_id``), so two confirmations
        naming one evidence row are a ``ConfigInvalidError``; records without an evidence id
        are left to the preflight (it refuses them)."""
        bindings = [
            ConfirmationBinding(
                str(c.evidence_id),
                str(c.kind),
                getattr(c, "provider", None),
                getattr(c, "amount_minor", None),
                getattr(c, "currency", None),
                getattr(c, "org_id", None),
            )
            for c in confirmations
            if getattr(c, "evidence_id", None)
        ]
        return cls(
            database,
            session,
            tx,
            bindings,
            allowed_kinds=allowed_kinds,
            currency_exponents=currency_exponents,
        )

    def _bound(self, row: EvidenceRecord, binding: ConfirmationBinding) -> bool:
        if row.evidence.record_kind not in self._kinds:
            return False
        quote = row.evidence.quote
        words = set(tokens(quote)) | set(quote.casefold().split())
        if binding.kind == FIN_R10:
            return any(w.casefold() in words for w in self._fin_words)
        if binding.kind != PROVIDER_LIMIT or not binding.provider:
            return False
        exponent = self._exponents.get(binding.currency or "")
        names = self._currency_words.get(binding.currency or "", ())
        return (
            binding.provider.casefold() in words
            and binding.amount_minor is not None
            and exponent is not None
            and _states_amount(quote, binding.amount_minor, exponent)
            and any(n.casefold() in words or n in quote for n in names)
        )

    def get(self, evidence_id: str) -> EvidenceStatus | None:
        """The row's status. ``kind`` and ``subject`` are set only when the row is MAC-valid,
        production-marked and states what its confirmation claims, so a consumer that compares
        ``subject`` can never accept a TEST, tampered or unbound row."""
        binding = self._bindings.get(evidence_id)
        if binding is None:
            return None
        try:
            row = self._db.get(self._session, self._tx, WireId(evidence_id))
        except InputInvalidError, ValueError:
            return None
        if row is None:
            return None
        e = row.evidence
        channel = (
            OWNER_CHAT_OPERATOR
            if e.source_kind is InstructionSourceKind.OWNER_CHAT_MESSAGE
            else e.source_kind.value
        )
        mac_valid = self._db.mac_valid(self._session, self._tx, row.id)
        result = row.verifier_result
        real = result.get(PRODUCTION_MARK) is True and not result.get(TEST_MARK)
        source = EvidenceSourceKind.REAL if real else EvidenceSourceKind.TEST_FIXTURE
        bound = mac_valid and real and binding.org_id == row.org_id and self._bound(row, binding)
        if (
            bound
            and DEFAULT_RECORD_KIND_RULES.get(e.record_kind) is EvidenceVerificationKind.DECISION
        ):
            siblings = self._db.for_subject(self._session, self._tx, e.subject_kind, e.subject_id)
            bound = not superseded(row, siblings)  # a newer decision makes a confirmed one unusable
        subject = (
            subject_key(
                binding.kind, binding.provider, binding.amount_minor, binding.currency, row.org_id
            )
            if bound
            else None
        )
        return EvidenceStatus(
            evidence_id=row.id,
            evidence_state=row.state.value,
            recorded_from=channel,
            org_id=row.org_id,
            kind=binding.kind if bound else None,
            subject_kind=e.subject_kind,
            subject_id=e.subject_id,
            subject=subject,
            source_kind=source,
            mac_valid=mac_valid,
        )
