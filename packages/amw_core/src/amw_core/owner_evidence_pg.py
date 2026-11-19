"""``EvidenceDatabase`` on PostgreSQL (04 sections 3.1 / 3.6a / 5.16; CCR-100 / CCR-101 / CCR-116;
migrations 0009 and 0055). The real path of R14 (WS-08 / 3A-13).

Identity is the **login role of the connection**: every call first reads ``session_user`` of the
tenant transaction's connection and refuses (``PermissionDeniedError``) unless it is the role the
caller's ``PgDbSession`` names. So an operator process (``amw_operator`` DSN) cannot use a
verifier session, and the state changes and the keyed MAC happen only inside the ``amw_verifier_fn``
definer functions (``amw_evidence_mark_verified`` / ``_mark_confirmed`` / ``_refuse``), which
check ``session_user = 'amw_verifier'`` themselves. This module holds no MAC key and computes no
MAC; ``mac_valid`` asks the database.

Wire IDs are stored as UUIDs; ``subject_prefixes`` maps each ``subject_kind`` to the ID prefix
of its subject so that the evidence read back hashes to the stored ``evidence_sha256`` (an
unknown subject kind is refused, fail closed).
"""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final

import psycopg

from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    EvidenceVerificationKind,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.errors import (
    IdempotencyConflictError,
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import (
    JOB,
    ORG,
    OWNER_EVIDENCE,
    USER,
    ActorRef,
    ApprovalId,
    Prefix,
    WireId,
    format_id,
    new_uuid7,
    parse_id,
    prefix_of,
)
from amw_core.interfaces.owner_evidence import DbRole, DbSession, EvidenceRecord, HumanRecord
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_review_code import generate_review_code
from amw_core.owner_evidence_verifier import (
    DEFAULT_RECORD_KIND_RULES,
    NewEvidence,
    evidence_sha256,
)
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

DEFAULT_SUBJECT_PREFIXES: Final[Mapping[str, Prefix]] = {p.name.lower(): p for p in Prefix}
"""``subject_kind`` -> wire prefix: the entity names of GLOSSARY 2.2, the same closed set the audit
keeps (``owner_evidence_audit.SUBJECT_KINDS``)."""
_COLUMNS: Final = (
    "id, org_id, job_id, approval_id, step_no, record_kind, subject_kind, subject_id,"
    " review_code, parsed_decision, parsed_target_stage_id, claimed_scores, source_kind,"
    " session_id, event_uuid, quote, message_at, state, evidence_mac, mac_key_version,"
    " event_verified_at, verifier_result, confirmation_event_uuid, confirmation_quote,"
    " confirmation_message_at, recorded_by, on_behalf_of, evidence_sha256, refused_reason,"
    " supersedes_id"
)
_UNIQUE_VIOLATION: Final = "23505"


@dataclass(frozen=True, slots=True)
class PgDbSession:
    """The role a caller claims; every call checks it against the connection's ``session_user``."""

    role: DbRole


def _uuid(wire: str) -> uuid.UUID:
    return parse_id(wire, prefix_of(wire))


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


class PgEvidenceDatabase:
    """Implements ``amw_core.interfaces.owner_evidence.EvidenceDatabase`` on PostgreSQL."""

    def __init__(
        self,
        subject_prefixes: Mapping[str, Prefix] = DEFAULT_SUBJECT_PREFIXES,
        *,
        review_code_length: int = 4,
    ) -> None:
        self._prefixes = dict(subject_prefixes)
        self._code_length = review_code_length

    # ---- helpers ------------------------------------------------------------------------
    def _conn(self, session: DbSession, tx: TenantTransaction, *roles: DbRole) -> Any:
        if session.role not in roles:
            raise PermissionDeniedError("this role may not call this function")
        conn = connection_of(tx)
        row = conn.execute("SELECT session_user::text").fetchone()
        if row is None or row[0] != session.role.value:
            raise PermissionDeniedError("the connection's login is not the session's role")
        return conn

    def _call(self, conn: Any, query: str, params: Sequence[Any]) -> Any:
        try:
            with conn.transaction():  # a savepoint: a refused call leaves the caller's tx usable
                return conn.execute(query, params)
        except psycopg.Error as exc:
            if exc.sqlstate == _UNIQUE_VIOLATION:
                raise IdempotencyConflictError("evidence key already used") from exc
            raise translate_db_error(exc) from exc

    def _record(self, row: Sequence[Any]) -> EvidenceRecord:
        (
            rid, org, job, approval, step_no, kind, subject_kind, subject_id, code, decision,
            stage, scores, source, session_id, event_uuid, quote, message_at, state, mac,
            mac_version, verified_at, result, conf_uuid, conf_quote, conf_at, recorded_by,
            on_behalf_of, sha, refused, supersedes,
        ) = row  # fmt: skip
        prefix = self._prefixes.get(subject_kind)
        if prefix is None:
            raise InputInvalidError("unknown subject_kind (no wire prefix configured)")
        claimed = tuple(sorted((QualityDimension(d), int(p)) for d, p in (scores or {}).items()))
        evidence = NewEvidence(
            record_kind=EvidenceRecordKind(kind),
            subject_kind=subject_kind,
            subject_id=format_id(prefix, subject_id),
            source_kind=InstructionSourceKind(source),
            session_id=session_id,
            event_uuid=event_uuid,
            quote=quote,
            message_at=_utc(message_at),
            recorded_by=ActorRef(recorded_by),
            on_behalf_of=USER.from_uuid(on_behalf_of),
            job_id=JOB.from_uuid(job) if job else None,
            approval_id=ApprovalId(format_id(Prefix.APPROVAL, approval)) if approval else None,
            step_no=step_no,
            review_code=code,
            parsed_decision=ApprovalStepState(decision) if decision else None,
            parsed_target_stage_id=stage,
            supersedes_id=OWNER_EVIDENCE.from_uuid(supersedes) if supersedes else None,
            claimed_scores=claimed,
        )
        return EvidenceRecord(
            id=OWNER_EVIDENCE.from_uuid(rid),
            org_id=ORG.from_uuid(org),
            evidence=evidence,
            state=EvidenceState(state),
            evidence_sha256=bytes(sha).hex(),
            event_verified_at=_utc(verified_at) if verified_at else None,
            verifier_result={str(k): bool(v) for k, v in (result or {}).items()},
            confirmation_event_uuid=conf_uuid,
            confirmation_quote=conf_quote,
            confirmation_message_at=_utc(conf_at) if conf_at else None,
            refused_reason=refused,
            evidence_mac=bytes(mac) if mac is not None else None,
            mac_key_version=mac_version,
        )

    def _fetch(self, conn: Any, evidence_id: WireId) -> EvidenceRecord | None:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM owner_instruction_evidence"  # noqa: S608
            " WHERE id = %s AND org_id = amw_current_org()",
            (OWNER_EVIDENCE.to_uuid(evidence_id),),
        ).fetchone()
        return self._record(row) if row else None

    def _required(self, conn: Any, evidence_id: WireId) -> EvidenceRecord:
        row = self._fetch(conn, evidence_id)
        if row is None:
            raise MissingDependencyError("evidence not found")
        return row

    def _own_code(self, conn: Any, tx: TenantTransaction, evidence: NewEvidence) -> NewEvidence:
        """CCR-116: CONTENT / SCORE evidence without an approval gets its own code (the DB
        registers it in ``review_codes`` and refuses a collision)."""
        kind = DEFAULT_RECORD_KIND_RULES.get(evidence.record_kind)
        own = kind in (EvidenceVerificationKind.CONTENT, EvidenceVerificationKind.SCORE)
        if not own or evidence.approval_id is not None or evidence.review_code is not None:
            return evidence
        org = org_uuid_of(tx)

        def taken(code: str) -> bool:
            hit = conn.execute("SELECT 1 FROM amw_review_code_owner(%s, %s)", (org, code))
            return hit.fetchone() is not None

        return replace(evidence, review_code=generate_review_code(taken, length=self._code_length))

    # ---- amw_operator -------------------------------------------------------------------
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
        """Plain ``INSERT`` as ``amw_operator``; the database's CHECKs and triggers refuse any
        verification, confirmation or MAC column and any state but pending / refused."""
        conn = self._conn(session, tx, DbRole.OPERATOR)
        evidence = replace(
            evidence, message_at=_utc(evidence.message_at), recorded_by=ActorRef("sys_operator")
        )
        if state is not EvidenceState.REFUSED:
            evidence = self._own_code(conn, tx, evidence)
        rid = new_uuid7()
        self._call(
            conn,
            "INSERT INTO owner_instruction_evidence (id, org_id, job_id, approval_id, step_no,"
            " record_kind, subject_kind, subject_id, review_code, parsed_decision,"
            " parsed_target_stage_id, claimed_scores, source_kind, session_id, event_uuid, quote,"
            " message_at, state, evidence_mac, mac_key_version, event_verified_at,"
            " verifier_result, confirmation_event_uuid, recorded_by, on_behalf_of,"
            " evidence_sha256, refused_reason, supersedes_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                rid,
                org_uuid_of(tx),
                JOB.to_uuid(evidence.job_id) if evidence.job_id else None,
                _uuid(evidence.approval_id) if evidence.approval_id else None,
                evidence.step_no,
                evidence.record_kind.value,
                evidence.subject_kind,
                _uuid(evidence.subject_id),
                evidence.review_code,
                evidence.parsed_decision.value if evidence.parsed_decision else None,
                evidence.parsed_target_stage_id,
                json.dumps(evidence.claimed_scores_json) if evidence.claimed_scores else None,
                evidence.source_kind.value,
                evidence.session_id,
                evidence.event_uuid,
                evidence.quote,
                evidence.message_at,
                state.value,
                evidence_mac,
                mac_key_version,
                event_verified_at,
                json.dumps(dict(verifier_result)) if verifier_result is not None else None,
                confirmation_event_uuid,
                evidence.recorded_by,
                USER.to_uuid(evidence.on_behalf_of),
                bytes.fromhex(evidence_sha256(evidence)),
                refused_reason,
                _uuid(evidence.supersedes_id) if evidence.supersedes_id else None,
            ),
        )
        return self._required(conn, OWNER_EVIDENCE.from_uuid(rid))

    def human_record_apply(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        text: str | None = None,
        *,
        contribution_type: str | None = None,
        rubric_version: str | None = None,
    ) -> HumanRecord:
        """``amw_human_record_apply``: the database writes the one human row (CONFIRMED + valid
        MAC checked there). ``contribution_type`` for a contribution, ``rubric_version`` for a
        human score."""
        conn = self._conn(session, tx, DbRole.OPERATOR)
        row = self._required(conn, evidence_id)
        e = row.evidence
        kind = DEFAULT_RECORD_KIND_RULES.get(e.record_kind)
        if kind is EvidenceVerificationKind.CONTENT and (not text or text not in e.quote):
            raise PermissionDeniedError("record text is not a verbatim substring of the quote")
        self._call(
            conn,
            "SELECT amw_human_record_apply(%s, %s, %s, %s)",
            (OWNER_EVIDENCE.to_uuid(evidence_id), contribution_type, text, rubric_version),
        )
        return HumanRecord(
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

    # ---- amw_verifier (definer functions) -----------------------------------------------
    def mark_verified(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        verifier_result: Mapping[str, bool],
        at: datetime,
    ) -> EvidenceRecord:
        """``at`` is informational: the database stamps ``event_verified_at = now()``."""
        conn = self._conn(session, tx, DbRole.VERIFIER)
        self._call(
            conn,
            "SELECT amw_evidence_mark_verified(%s, %s)",
            (OWNER_EVIDENCE.to_uuid(evidence_id), json.dumps(dict(verifier_result))),
        )
        return self._required(conn, evidence_id)

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
        conn = self._conn(session, tx, DbRole.VERIFIER)
        self._call(
            conn,
            "SELECT amw_evidence_mark_confirmed(%s, %s, %s, %s, %s)",
            (
                OWNER_EVIDENCE.to_uuid(evidence_id),
                confirmation_event_uuid,
                confirmation_quote,
                _utc(confirmation_message_at),
                json.dumps(dict(verifier_result)),
            ),
        )
        return self._required(conn, evidence_id)

    def refuse(
        self,
        session: DbSession,
        tx: TenantTransaction,
        evidence_id: WireId,
        reason: str,
        verifier_result: Mapping[str, bool],
    ) -> EvidenceRecord:
        conn = self._conn(session, tx, DbRole.VERIFIER)
        self._call(
            conn,
            "SELECT amw_evidence_refuse(%s, %s, %s)",
            (OWNER_EVIDENCE.to_uuid(evidence_id), reason, json.dumps(dict(verifier_result))),
        )
        return self._required(conn, evidence_id)

    # ---- reads --------------------------------------------------------------------------
    def mac_valid(self, session: DbSession, tx: TenantTransaction, evidence_id: WireId) -> bool:
        conn = self._conn(session, tx, DbRole.APP, DbRole.OPERATOR, DbRole.VERIFIER)
        row = self._call(
            conn, "SELECT amw_evidence_mac_valid(%s)", (OWNER_EVIDENCE.to_uuid(evidence_id),)
        ).fetchone()
        return bool(row and row[0])

    def get(
        self, session: DbSession, tx: TenantTransaction, evidence_id: WireId
    ) -> EvidenceRecord | None:
        conn = self._conn(session, tx, DbRole.APP, DbRole.OPERATOR, DbRole.VERIFIER)
        return self._fetch(conn, evidence_id)

    def for_subject(
        self, session: DbSession, tx: TenantTransaction, subject_kind: str, subject_id: WireId
    ) -> Sequence[EvidenceRecord]:
        conn = self._conn(session, tx, DbRole.APP, DbRole.OPERATOR, DbRole.VERIFIER)
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM owner_instruction_evidence"  # noqa: S608
            " WHERE subject_kind = %s AND subject_id = %s AND org_id = amw_current_org()"
            " ORDER BY created_at, id",
            (subject_kind, _uuid(subject_id)),
        ).fetchall()
        return [self._record(r) for r in rows]

    def in_state(
        self, session: DbSession, tx: TenantTransaction, state: EvidenceState, limit: int = 100
    ) -> Sequence[EvidenceRecord]:
        """Rows of this tenant in ``state`` (oldest first): the verifier worker's queue."""
        conn = self._conn(session, tx, DbRole.VERIFIER)
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM owner_instruction_evidence"  # noqa: S608
            " WHERE state = %s AND org_id = amw_current_org() ORDER BY created_at, id LIMIT %s",
            (state.value, limit),
        ).fetchall()
        return [self._record(r) for r in rows]
