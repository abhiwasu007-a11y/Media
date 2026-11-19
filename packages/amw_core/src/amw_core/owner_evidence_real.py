"""The real owner-evidence path (R14, D5; WS-08 / 3A-13; 08 ``sys_operator``, CCR-100 / CCR-113).

Flow (each step in its own process and database login):

1. **Operator** (``amw_operator`` DSN; the assistant's tool) inserts ``PENDING_VERIFICATION``
   evidence with the owner's verbatim quote and the event's identifiers, then echoes it to the
   owner (``amw_core.owner_evidence_operator``). It never verifies.
2. **Verifier** (``amw_verifier`` DSN; this module's ``VerifierWorker``) reads the event from its
   own ``SessionEventSource``, runs 03 section 11.6 rule 7 (``EvidenceVerifierService``) and calls
   ``amw_evidence_mark_verified`` (MAC stamped in the database) or ``amw_evidence_refuse``.
3. The owner replies ``confirm <code>`` (or ``<code> पक्के``). The verifier **finds** that reply in
   the session record itself (``confirm_from_chat``): it is not told which message it is. The
   first later owner message that names the code decides: a confirmation -> ``CONFIRMED``; any
   other mention (a dispute, a correction) -> the row stays ``VERIFIED`` and the operator must
   ask the owner again.

``EvidenceMode.REAL`` refuses a session source that is not marked ``production_grade`` (the
in-memory fake is the TEST path and is reachable only through ``dry_run_verifier_service``).
The mark is a guard against wiring mistakes, not a security boundary (any object can carry it).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from amw_core.enums import EvidenceState, InstructionSourceKind
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
from amw_core.owner_evidence_fake import MemorySessionEventSource
from amw_core.owner_evidence_service import EvidenceVerifierService
from amw_core.owner_evidence_verifier import (
    SessionEventSource,
    VerifierPolicy,
    is_confirmation,
    whitelist_tokens,
)


class EvidenceMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    """TEST fixtures allowed; nothing recorded is production-verified."""
    REAL = "REAL"


def is_production_source(source: SessionEventSource) -> bool:
    return getattr(source, "production_grade", False) is True and not isinstance(
        source, MemorySessionEventSource
    )


def build_verifier_service(
    mode: EvidenceMode,
    database: EvidenceDatabase,
    session: DbSession,
    source: SessionEventSource,
    policy: VerifierPolicy,
) -> EvidenceVerifierService:
    """The verifier component for ``mode``; REAL refuses a non-production session source."""
    if mode is EvidenceMode.REAL and not is_production_source(source):
        raise ConfigInvalidError("real mode needs a production session record source (R14)")
    return EvidenceVerifierService(database, session, source, policy)


def dry_run_verifier_service(
    database: EvidenceDatabase,
    session: DbSession,
    source: MemorySessionEventSource,
    policy: VerifierPolicy,
) -> EvidenceVerifierService:
    """The explicit TEST factory: an in-memory session source, dry run only. Rows it verifies
    are not production-verified (owner decision 2026-11-19: TEST fixtures for the dry run only)."""
    if not isinstance(source, MemorySessionEventSource):
        raise ConfigInvalidError("the dry-run factory takes only the in-memory TEST source")
    return build_verifier_service(EvidenceMode.DRY_RUN, database, session, source, policy)


class OwnerMessage(Protocol):
    """One accepted owner chat message of a session record."""

    @property
    def session_id(self) -> str: ...
    @property
    def event_uuid(self) -> str: ...
    @property
    def timestamp(self) -> datetime: ...
    @property
    def content(self) -> str: ...


@runtime_checkable
class OwnerMessageIndex(Protocol):
    """The owner chat messages of one session, in order (e.g. ``ClaudeSessionJsonlSource``)."""

    def owner_messages(self, session_id: str) -> Iterable[OwnerMessage]: ...


AnchorLookup = Callable[[TenantTransaction, EvidenceRecord], datetime | None]
"""The request time of a row (``approvals.created_at``, the job's creation, ``None`` for
OWNER_TOPIC / DATASET_INTAKE). REQUIRES REVIEW (CCR-262): ``amw_verifier`` has no SELECT on
``approvals`` / ``jobs``, so the verifier process needs a grant or a definer function."""


class ConfirmationOutcome(StrEnum):
    CONFIRMED = "CONFIRMED"
    NO_REPLY_YET = "NO_REPLY_YET"
    DISPUTED = "DISPUTED"
    """The first later owner message naming the code is not a confirmation: ask again."""
    REFUSED_CHECK = "REFUSED_CHECK"


@dataclass(frozen=True, slots=True)
class ConfirmationScan:
    outcome: ConfirmationOutcome
    row: EvidenceRecord
    event_uuid: str | None = None


def _names_code(content: str, code: str) -> bool:
    folded = " ".join(whitelist_tokens(code))
    return bool(folded) and folded in whitelist_tokens(content)


class VerifierWorker:
    """Runs in the verifier process only (``amw_verifier`` login, the session-record reader)."""

    def __init__(
        self,
        service: EvidenceVerifierService,
        database: EvidenceDatabase,
        session: DbSession,
        index: OwnerMessageIndex,
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

    def confirm_from_chat(
        self, tx: TenantTransaction, evidence_id: WireId, now: datetime
    ) -> ConfirmationScan:
        """Look for the owner's reply to the echo in the record's own session."""
        row = self._db.get(self._session, tx, evidence_id)
        if row is None:
            raise MissingDependencyError("evidence not found")
        if row.state is not EvidenceState.VERIFIED:
            raise InvalidTransitionError("only VERIFIED evidence can be confirmed")
        code = row.evidence.review_code or ""
        for message in self._index.owner_messages(row.evidence.session_id):
            if message.timestamp <= row.evidence.message_at:
                continue
            if message.event_uuid == row.evidence.event_uuid or not _names_code(
                message.content, code
            ):
                continue
            if not is_confirmation(message.content, code, self._policy):
                return ConfirmationScan(ConfirmationOutcome.DISPUTED, row, message.event_uuid)
            try:
                done = self._service.confirm(
                    tx,
                    evidence_id,
                    message.session_id,
                    message.event_uuid,
                    message.content,
                    now,
                )
            except PermissionDeniedError, IdempotencyConflictError:  # the check refused it
                return ConfirmationScan(ConfirmationOutcome.REFUSED_CHECK, row, message.event_uuid)
            return ConfirmationScan(ConfirmationOutcome.CONFIRMED, done, message.event_uuid)
        return ConfirmationScan(ConfirmationOutcome.NO_REPLY_YET, row)


OWNER_CHAT_OPERATOR = "OWNER_CHAT_OPERATOR"
MAC_INVALID = "MAC_INVALID"


@dataclass(frozen=True, slots=True)
class EvidenceStatus:
    """What a run preflight needs of one evidence row (``amw_runtime`` ``EvidenceView``)."""

    evidence_state: str
    recorded_from: str


class ConfirmedEvidenceLookup:
    """Evidence status for a run preflight, read inside one tenant transaction. A row whose MAC
    does not verify reports ``MAC_INVALID`` (never ``CONFIRMED``); a row from any source but the
    owner chat reports that source, so a preflight that requires ``CONFIRMED`` from
    ``OWNER_CHAT_OPERATOR`` refuses both."""

    def __init__(
        self, database: EvidenceDatabase, session: DbSession, tx: TenantTransaction
    ) -> None:
        self._db = database
        self._session = session
        self._tx = tx

    def get(self, evidence_id: str) -> EvidenceStatus | None:
        try:
            row = self._db.get(self._session, self._tx, WireId(evidence_id))
        except InputInvalidError, ValueError:
            return None
        if row is None:
            return None
        valid = self._db.mac_valid(self._session, self._tx, row.id)
        source = row.evidence.source_kind
        channel = (
            OWNER_CHAT_OPERATOR if source is InstructionSourceKind.OWNER_CHAT_MESSAGE else source
        )
        return EvidenceStatus(row.state.value if valid else MAC_INVALID, channel)
