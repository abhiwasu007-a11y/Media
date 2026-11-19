"""In-memory model of the owner-evidence database objects (04 sections 3.1 / 3.6a / 5.16,
CCR-100 / CCR-101) for tests of every lane. Lane L1a implements the real PostgreSQL roles,
definer functions and triggers; this fake must refuse exactly what they refuse.

What it models:

* **Roles and identity.** ``login(role, password)`` returns a session whose role is the
  ``session_user``; every operation checks that role. ``TenantContext.actor`` (``app.actor``) is
  only used for the tenant (``org_id``), never as identity.
* **Initial-state rule.** An insert (``amw_operator`` only) must be ``PENDING_VERIFICATION`` or
  ``REFUSED`` with every verification, confirmation and MAC column empty.
* **Definer functions.** Only ``amw_verifier`` can mark ``VERIFIED`` / ``CONFIRMED`` /
  ``REFUSED``; these functions stamp ``evidence_mac`` with the private ``MacKeyring`` (the
  ``evidence_mac_keys`` table, readable by no role).
* **Keys.** One live row per ``event_uuid``; unique ``confirmation_event_uuid``; an event is
  never both a row's event and another row's confirmation (one message = one subject = one step).
* **Human rows.** ``human_record_apply`` (``amw_operator``) requires ``CONFIRMED`` and a valid
  MAC and writes the one human row the evidence names, once.
* **Own review codes (CCR-116, migration 0055).** An ``OWNER_TOPIC`` / ``DATASET_INTAKE``
  evidence, and any other ``CONTENT`` / ``SCORE`` evidence without ``approval_id``, carries its
  own review code (CCR-090 format, upper case), unique per org across approval codes
  (``register_approval_code`` models ``approvals.review_code``) and evidence codes, compared
  case-insensitively. The fake plays the evidence store too: an insert without one is issued a
  fresh code (``generate_review_code``) before ``evidence_sha256`` is computed; PostgreSQL
  refuses a live row without one, because its store supplies the code with the INSERT.
* ``superuser_tamper`` models the documented superuser bypass (08): it changes a row without
  the functions, which ``mac_valid`` then detects.
"""

import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from amw_core.enums import (
    EvidenceRecordKind,
    EvidenceState,
    EvidenceVerificationKind,
    InstructionSourceKind,
)
from amw_core.errors import (
    IdempotencyConflictError,
    InvalidTransitionError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import OWNER_EVIDENCE, OrgId, WireId
from amw_core.interfaces.owner_evidence import DbRole, DbSession, EvidenceRecord, HumanRecord
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_mac import MacKeyring
from amw_core.owner_evidence_review_code import (
    ALPHABET,
    DEFAULT_LENGTH,
    DIGITS,
    MAX_LENGTH,
    MIN_LENGTH,
    generate_review_code,
)
from amw_core.owner_evidence_verifier import (
    DEFAULT_RECORD_KIND_RULES,
    NewEvidence,
    SessionEvent,
    evidence_sha256,
)


def needs_own_review_code(kind: EvidenceRecordKind) -> bool:
    """CONTENT / SCORE kinds (03 section 11.6 rule 7 table): without an approval they carry their
    own review code (CCR-116; PostgreSQL: ``amw_evidence_own_code_kind``)."""
    return DEFAULT_RECORD_KIND_RULES[kind] in (
        EvidenceVerificationKind.CONTENT,
        EvidenceVerificationKind.SCORE,
    )


class MemorySessionEventSource:
    """In-memory stand-in for the platform session event store (the real one is ticket 3A-13)."""

    def __init__(self, events: Sequence[SessionEvent] = ()) -> None:
        self._events: dict[tuple[str, str], SessionEvent] = {}
        for event in events:
            self.add(event)

    def add(self, event: SessionEvent) -> None:
        self._events[(event.session_id, event.event_uuid)] = event

    def fetch(self, session_id: str, event_uuid: str) -> SessionEvent | None:
        return self._events.get((session_id, event_uuid))


@dataclass(frozen=True, slots=True, eq=False)
class FakeDbSession:
    """A login session; only ``FakeEvidenceDatabase.login`` makes one it accepts."""

    role: DbRole
    _database_id: int


def _mac_fields(row: EvidenceRecord) -> dict[str, Any]:
    """The canonical fields the MAC covers (04 section 3.6a): identity, state, the evidence hash,
    the verification and the confirmation."""
    return {
        "org_id": row.org_id,
        "id": row.id,
        "state": row.state.value,
        "evidence_sha256": evidence_sha256(row.evidence),  # recomputed: content edits show
        "record_kind": row.evidence.record_kind.value,
        "subject_kind": row.evidence.subject_kind,
        "subject_id": row.evidence.subject_id,
        "on_behalf_of": row.evidence.on_behalf_of,
        "event_verified_at": row.event_verified_at,
        "verifier_result": sorted(row.verifier_result.items()),
        "confirmation_event_uuid": row.confirmation_event_uuid,
        "confirmation_quote": row.confirmation_quote,
        "confirmation_message_at": row.confirmation_message_at,
        "mac_key_version": row.mac_key_version,
    }


class FakeEvidenceDatabase:
    """Implements ``amw_core.interfaces.owner_evidence.EvidenceDatabase`` in memory."""

    def __init__(
        self,
        passwords: Mapping[DbRole, str],
        keyring: MacKeyring,
        *,
        review_code_length: int = DEFAULT_LENGTH,
    ) -> None:
        self.__passwords = dict(passwords)
        self.__keyring = keyring
        self._review_code_length = review_code_length
        """``approvals.review_code.length`` (default 4, owner-confirmable, Q-O11)."""
        self._rows: dict[tuple[OrgId, WireId], EvidenceRecord] = {}
        self._applied: dict[tuple[OrgId, WireId], HumanRecord] = {}
        self._approval_codes: dict[OrgId, set[str]] = {}
        self._approval_code_of: dict[tuple[OrgId, str], str] = {}

    # --- sessions -----------------------------------------------------------------------
    def login(self, role: DbRole, password: str) -> FakeDbSession:
        expected = self.__passwords.get(role)
        if expected is None or not hmac.compare_digest(expected, password):
            raise PermissionDeniedError("authentication failed")
        return FakeDbSession(role, id(self))

    def _require(self, session: DbSession, *roles: DbRole) -> None:
        if (
            not isinstance(session, FakeDbSession)
            or session._database_id != id(self)
            or session.role not in roles
        ):
            raise PermissionDeniedError("this role may not call this function")

    def _row(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceRecord:
        row = self._rows.get((tx.context.org_id, evidence_id))
        if row is None:
            raise MissingDependencyError("evidence not found")
        return row

    def _stamp(self, row: EvidenceRecord) -> EvidenceRecord:
        version = self.__keyring.current_version
        row = replace(row, mac_key_version=version, evidence_mac=None)
        return replace(row, evidence_mac=self.__keyring.sign(version, _mac_fields(row)))

    def _valid(self, row: EvidenceRecord) -> bool:
        if row.evidence_sha256 != evidence_sha256(row.evidence):
            return False
        return self.__keyring.verify(row.mac_key_version, _mac_fields(row), row.evidence_mac)

    def _live_events(self, org: OrgId, exclude: WireId | None = None) -> set[str]:
        return {
            r.evidence.event_uuid
            for (o, i), r in self._rows.items()
            if o == org and i != exclude and r.state is not EvidenceState.REFUSED
        }

    def _confirmation_events(self, org: OrgId) -> set[str]:
        return {
            r.confirmation_event_uuid
            for (o, _), r in self._rows.items()
            if o == org and r.confirmation_event_uuid is not None
        }

    # --- review codes (CCR-116) -----------------------------------------------------------
    def _codes_in_use(self, org: OrgId) -> set[str]:
        own = {
            r.evidence.review_code.upper()
            for (o, _), r in self._rows.items()
            if o == org and r.evidence.approval_id is None and r.evidence.review_code
        }
        return own | self._approval_codes.get(org, set())

    def register_approval_code(
        self, tx: TenantTransaction, code: str, approval_id: str | None = None
    ) -> None:
        """Models an ``approvals`` row's ``review_code`` (the 0055 ``review_codes`` registry):
        refused when any approval or evidence code of the org equals it, case-insensitively.
        With ``approval_id``, evidence tied to that approval must carry exactly this code."""
        org = tx.context.org_id
        if code.upper() in self._codes_in_use(org):
            raise IdempotencyConflictError("review code already used in this org")
        self._approval_codes.setdefault(org, set()).add(code.upper())
        if approval_id is not None:
            self._approval_code_of[(org, approval_id)] = code.upper()

    def _check_approval_code(self, org: OrgId, evidence: NewEvidence, state: EvidenceState) -> None:
        """0055: evidence tied to an approval carries that approval's code and never another
        row's code (an own code, or another approval's), so a code resolves to one row."""
        code = (evidence.review_code or "").upper()
        if not code:
            return
        expected = self._approval_code_of.get((org, str(evidence.approval_id)))
        if expected is not None and code != expected:
            raise PermissionDeniedError("evidence must carry its approval's review code")
        own = {
            r.evidence.review_code.upper()
            for (o, _), r in self._rows.items()
            if o == org and r.evidence.approval_id is None and r.evidence.review_code
        }
        if code in own:
            raise PermissionDeniedError("evidence must carry its approval's review code")

    def _own_code(self, org: OrgId, evidence: NewEvidence, state: EvidenceState) -> NewEvidence:
        """The store's own review code for evidence without an approval (CCR-116)."""
        if evidence.approval_id is not None:
            self._check_approval_code(org, evidence, state)
            return evidence
        if not needs_own_review_code(evidence.record_kind):
            return evidence
        taken = self._codes_in_use(org)
        code = evidence.review_code
        if code is None:
            if state is EvidenceState.REFUSED:
                return evidence
            fresh = generate_review_code(
                lambda c: c.upper() in taken, length=self._review_code_length
            )
            return replace(evidence, review_code=fresh)
        well_formed = (
            MIN_LENGTH <= len(code) <= MAX_LENGTH
            and all(c in ALPHABET for c in code)
            and any(c in DIGITS for c in code)
            and any(c not in DIGITS for c in code)
        )
        if not well_formed:
            raise PermissionDeniedError("malformed own review code (CCR-090 format, upper case)")
        if code.upper() in taken:
            raise IdempotencyConflictError("review code already used in this org")
        return evidence

    # --- amw_operator ---------------------------------------------------------------------
    def insert_evidence(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence: NewEvidence,
        *,
        state: EvidenceState = EvidenceState.PENDING_VERIFICATION,
        refused_reason: str | None = None,
        verifier_result: Mapping[str, bool] | None = None,
        event_verified_at: datetime | None = None,
        confirmation_event_uuid: str | None = None,
        evidence_mac: bytes | None = None,
        mac_key_version: int | None = None,
    ) -> EvidenceRecord:
        self._require(session, DbRole.OPERATOR)
        if state not in (EvidenceState.PENDING_VERIFICATION, EvidenceState.REFUSED):
            raise PermissionDeniedError("evidence may only be inserted pending or refused")
        verification_columns = (
            verifier_result,
            event_verified_at,
            confirmation_event_uuid,
            evidence_mac,
            mac_key_version,
        )
        if any(value is not None for value in verification_columns):
            raise PermissionDeniedError("verification, confirmation and MAC columns must be NULL")
        if (state is EvidenceState.REFUSED) != (refused_reason is not None):
            raise PermissionDeniedError("refused_reason is set exactly for REFUSED rows")
        org = tx.context.org_id
        if state is not EvidenceState.REFUSED:
            if evidence.event_uuid in self._live_events(org):
                raise IdempotencyConflictError("one owner message backs one evidence row")
            if evidence.event_uuid in self._confirmation_events(org):
                raise IdempotencyConflictError("this message already confirmed another record")
        evidence = self._own_code(org, evidence, state)
        row = EvidenceRecord(
            id=OWNER_EVIDENCE.new(),
            org_id=org,
            evidence=evidence,
            state=state,
            evidence_sha256=evidence_sha256(evidence),
            refused_reason=refused_reason,
        )
        self._rows[(org, row.id)] = row
        return row

    def human_record_apply(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        text: str | None = None,
    ) -> HumanRecord:
        self._require(session, DbRole.OPERATOR)
        row = self._row(tx, evidence_id)
        if row.state is not EvidenceState.CONFIRMED or not self._valid(row):
            raise PermissionDeniedError("human rows need CONFIRMED evidence with a valid MAC")
        key = (row.org_id, row.id)
        if key in self._applied:
            raise IdempotencyConflictError("this evidence already backs a human row")
        e = row.evidence
        kind = DEFAULT_RECORD_KIND_RULES.get(e.record_kind)
        if kind is EvidenceVerificationKind.CONTENT and (not text or text not in e.quote):
            raise PermissionDeniedError("record text is not a verbatim substring of the quote")
        record = HumanRecord(
            evidence_id=row.id,
            org_id=row.org_id,
            record_kind=e.record_kind,
            subject_kind=e.subject_kind,
            subject_id=e.subject_id,
            decided_by=e.on_behalf_of,
            decision=e.parsed_decision,
            target_stage_id=e.parsed_target_stage_id,
            text=text if kind is EvidenceVerificationKind.CONTENT else None,
            scores=e.claimed_scores if e.record_kind is EvidenceRecordKind.HUMAN_SCORE else (),
        )
        self._applied[key] = record
        return record

    # --- amw_verifier (definer functions) ------------------------------------------------
    def mark_verified(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        verifier_result: Mapping[str, bool],
        at: datetime,
    ) -> EvidenceRecord:
        self._require(session, DbRole.VERIFIER)
        row = self._row(tx, evidence_id)
        if row.state is not EvidenceState.PENDING_VERIFICATION:
            raise InvalidTransitionError("only pending evidence can be verified")
        if row.evidence.source_kind is not InstructionSourceKind.OWNER_CHAT_MESSAGE:
            raise PermissionDeniedError("only an owner chat message can be verified")
        row = self._stamp(
            replace(
                row,
                state=EvidenceState.VERIFIED,
                event_verified_at=at,
                verifier_result=dict(verifier_result),
            )
        )
        self._rows[(row.org_id, row.id)] = row
        return row

    def mark_confirmed(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        confirmation_event_uuid: str,
        confirmation_quote: str,
        confirmation_message_at: datetime,
        verifier_result: Mapping[str, bool],
    ) -> EvidenceRecord:
        self._require(session, DbRole.VERIFIER)
        row = self._row(tx, evidence_id)
        if row.state is not EvidenceState.VERIFIED or not self._valid(row):
            raise InvalidTransitionError("only VERIFIED evidence with a valid MAC is confirmed")
        org = row.org_id
        if confirmation_event_uuid in self._confirmation_events(org):
            raise IdempotencyConflictError("this message already confirmed a record")
        if confirmation_event_uuid in self._live_events(org) | {row.evidence.event_uuid}:
            raise IdempotencyConflictError("a record's own event cannot confirm a record")
        if confirmation_message_at <= row.evidence.message_at:
            raise InvalidTransitionError("the confirmation must be later than the event")
        row = self._stamp(
            replace(
                row,
                state=EvidenceState.CONFIRMED,
                confirmation_event_uuid=confirmation_event_uuid,
                confirmation_quote=confirmation_quote,
                confirmation_message_at=confirmation_message_at,
                verifier_result=dict(row.verifier_result) | dict(verifier_result),
            )
        )
        self._rows[(org, row.id)] = row
        return row

    def refuse(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        reason: str,
        verifier_result: Mapping[str, bool],
    ) -> EvidenceRecord:
        self._require(session, DbRole.VERIFIER)
        row = self._row(tx, evidence_id)
        if row.state not in (EvidenceState.PENDING_VERIFICATION, EvidenceState.VERIFIED):
            raise InvalidTransitionError("evidence state change not allowed")
        row = replace(
            row,
            state=EvidenceState.REFUSED,
            refused_reason=reason,
            verifier_result=dict(verifier_result),
            evidence_mac=None,
            mac_key_version=None,
        )
        self._rows[(row.org_id, row.id)] = row
        return row

    # --- any role ------------------------------------------------------------------------
    def mac_valid(self, session: DbSession, tx: TenantTransaction, evidence_id: WireId) -> bool:
        self._require(session, DbRole.APP, DbRole.OPERATOR, DbRole.VERIFIER)
        row = self._rows.get((tx.context.org_id, evidence_id))
        return row is not None and self._valid(row)

    def get(
        self, session: DbSession, tx: TenantTransaction, evidence_id: WireId
    ) -> EvidenceRecord | None:
        self._require(session, DbRole.APP, DbRole.OPERATOR, DbRole.VERIFIER)
        return self._rows.get((tx.context.org_id, evidence_id))

    def for_subject(
        self, session: DbSession, tx: TenantTransaction, subject_kind: str, subject_id: WireId
    ) -> Sequence[EvidenceRecord]:
        self._require(session, DbRole.APP, DbRole.OPERATOR, DbRole.VERIFIER)
        org = tx.context.org_id
        return [
            r
            for (o, _), r in self._rows.items()
            if o == org
            and (r.evidence.subject_kind, r.evidence.subject_id) == (subject_kind, subject_id)
        ]

    def human_records(self, tx: TenantTransaction) -> Sequence[HumanRecord]:
        """Test inspection of the written human rows."""
        return [r for (o, _), r in self._applied.items() if o == tx.context.org_id]

    # --- model of the documented bypass ---------------------------------------------------
    def superuser_tamper(self, tx: TenantTransaction, evidence_id: WireId, **changes: Any) -> None:
        """A shared superuser editing a row directly (08): no function, no new MAC."""
        key = (tx.context.org_id, evidence_id)
        self._rows[key] = replace(self._rows[key], **changes)
