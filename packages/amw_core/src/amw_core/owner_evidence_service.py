"""The evidence verifier component (03 section 11.6 rule 7; 04 section 3.6a; CCR-100 / CCR-101).

It runs under the ``amw_verifier`` database role: it fetches the owner's event through its own
``SessionEventSource``, runs ``verify_owner_event`` itself and calls the definer functions
(``mark_verified`` / ``mark_confirmed`` / ``refuse``), which stamp the keyed MAC. It accepts no
verification result, event or check list from a caller, and it is the only component that holds
the verifier session; the operator tool holds only an ``amw_operator`` session.

**Limitation:** the real session-store adapter is ticket 3A-13; until then only the in-memory
fake exists, and 3A approvals recorded through it are not production-verified.
"""

from datetime import datetime

from amw_core.enums import EvidenceState, InstructionSourceKind
from amw_core.errors import (
    InvalidTransitionError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import WireId
from amw_core.interfaces.owner_evidence import (
    DbRole,
    DbSession,
    EvidenceDatabase,
    EvidenceRecord,
)
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_verifier import (
    CONFIRMATION,
    RECORD,
    EventUnavailable,
    Refusal,
    SessionEventSource,
    Verified,
    VerifierPolicy,
    verify_owner_event,
)


class EvidenceVerifierService:
    def __init__(
        self,
        database: EvidenceDatabase,
        session: DbSession,
        source: SessionEventSource,
        policy: VerifierPolicy,
    ) -> None:
        if session.role is not DbRole.VERIFIER:
            raise PermissionDeniedError("the verifier component runs as amw_verifier")
        self._db = database
        self._session = session
        self._source = source
        self._policy = policy

    def _bound(self, outcome: Verified, row: EvidenceRecord, event_uuid: str, purpose: str) -> None:
        if (
            outcome.evidence_id != row.id
            or outcome.event_uuid != event_uuid
            or outcome.bound_sha256 != row.evidence_sha256
            or outcome.purpose != purpose
        ):
            raise InvalidTransitionError("verification is not bound to this evidence row")

    def _pending(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceRecord:
        row = self._db.get(self._session, tx, evidence_id)
        if row is None:
            raise MissingDependencyError("evidence not found")
        return row

    def verify_recorded(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        anchor: datetime | None,
        now: datetime,
        allowed_stages: frozenset[str] | None = None,
    ) -> EvidenceRecord:
        """``PENDING_VERIFICATION -> VERIFIED`` or ``-> REFUSED``. ``anchor``: the request
        (``approvals.created_at``), the job's creation for CONTRIBUTION / HUMAN_SCORE, ``None``
        for OWNER_TOPIC / DATASET_INTAKE (freshness window); a later superseded evidence time
        wins. ``allowed_stages``: the stages the approval's workflow allows for
        ``CHANGES_REQUESTED``. Unfetchable event -> ``MissingDependencyError`` (stays pending)."""
        row = self._pending(tx, evidence_id)
        if row.state is not EvidenceState.PENDING_VERIFICATION:
            raise InvalidTransitionError("only pending evidence can be verified")
        e = row.evidence
        if e.source_kind is not InstructionSourceKind.OWNER_CHAT_MESSAGE:
            checks = {"source_owner_chat": False}
            return self._db.refuse(self._session, tx, row.id, "source_owner_chat", checks)
        if e.supersedes_id is not None:
            older = self._db.get(self._session, tx, e.supersedes_id)
            if older is None:
                raise MissingDependencyError("superseded evidence not found")
            if anchor is None or older.evidence.message_at > anchor:
                anchor = older.evidence.message_at
        outcome = verify_owner_event(
            self._source.fetch(e.session_id, e.event_uuid),
            evidence=e,
            evidence_id=row.id,
            purpose=RECORD,
            quote=e.quote,
            message_at=e.message_at,
            anchor=anchor,
            distinct_from_event_uuid=None,
            policy=self._policy,
            now=now,
            allowed_stages=allowed_stages,
        )
        if isinstance(outcome, EventUnavailable):
            raise MissingDependencyError("owner event cannot be fetched; evidence stays pending")
        if isinstance(outcome, Refusal):
            return self._db.refuse(self._session, tx, row.id, outcome.reason, dict(outcome.checks))
        self._bound(outcome, row, e.event_uuid, RECORD)
        return self._db.mark_verified(
            self._session, tx, row.id, dict(outcome.checks), outcome.verified_at
        )

    def confirm(
        self,
        tx: TenantTransaction,
        evidence_id: WireId,
        session_id: str,
        event_uuid: str,
        quote: str,
        now: datetime,
    ) -> EvidenceRecord:
        """``VERIFIED -> CONFIRMED`` only for a second, distinct, later owner event that passes
        the authenticity tests and the confirmation whitelist (``confirm R7K2``). Anything else
        (a dispute, correction, new decision) leaves the row ``VERIFIED``: unfetchable ->
        ``MissingDependencyError``, failed check -> ``PermissionDeniedError``."""
        row = self._pending(tx, evidence_id)
        if row.state is not EvidenceState.VERIFIED:
            raise InvalidTransitionError("only VERIFIED evidence can be confirmed")
        if not self._db.mac_valid(self._session, tx, row.id):
            raise PermissionDeniedError("evidence MAC is not valid")
        outcome = verify_owner_event(
            self._source.fetch(session_id, event_uuid),
            evidence=row.evidence,
            evidence_id=row.id,
            purpose=CONFIRMATION,
            quote=quote,
            message_at=None,
            anchor=row.evidence.message_at,
            distinct_from_event_uuid=row.evidence.event_uuid,
            policy=self._policy,
            now=now,
        )
        if isinstance(outcome, EventUnavailable):
            raise MissingDependencyError("confirmation event cannot be fetched")
        if isinstance(outcome, Refusal):
            raise PermissionDeniedError(outcome.reason, details={"checks": dict(outcome.checks)})
        self._bound(outcome, row, event_uuid, CONFIRMATION)
        return self._db.mark_confirmed(
            self._session,
            tx,
            row.id,
            outcome.event_uuid,
            quote,
            outcome.event_timestamp,
            dict(outcome.checks),
        )
