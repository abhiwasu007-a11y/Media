"""WS-08 / 3A-13 on real PostgreSQL: the operator login records PENDING evidence, the verifier
login (reading the Claude Code transcript itself) marks it VERIFIED / CONFIRMED through the
definer functions that stamp the keyed MAC, and the operator applies the human row.

Each process connects as its own login (``SET SESSION AUTHORIZATION`` from the scratch
superuser, so ``session_user`` really is ``amw_operator`` / ``amw_verifier``).
"""

import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql

from amw_adapters.session_record import HUMAN_ORIGIN, ClaudeSessionJsonlSource, JsonlSourceConfig
from amw_core import ids
from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    InstructionSourceKind,
)
from amw_core.errors import (
    ConfigInvalidError,
    IdempotencyConflictError,
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.interfaces import DbRole, EvidenceRecord, NewEvidence, TenantContext
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_fake import (
    PRODUCTION_MARK,
    TEST_MARK,
    MemorySessionEventSource,
)
from amw_core.owner_evidence_operator import OperatorDesk, locate
from amw_core.owner_evidence_pg import PgDbSession, PgEvidenceDatabase
from amw_core.owner_evidence_real import (
    ConfirmationBinding,
    ConfirmationOutcome,
    ConfirmedEvidenceLookup,
    EvidenceMode,
    VerifierWorker,
    build_verifier_service,
    dry_run_verifier_service,
)
from amw_core.owner_evidence_service import EvidenceVerifierService
from amw_core.owner_evidence_status import EvidenceSourceKind
from amw_core.owner_evidence_verifier import SessionEvent, VerifierPolicy
from amw_core.tenancy import PgTenancy
from amw_core.tenancy.evidence_keys import install_evidence_mac_key
from tests.fake_audit import RecordingAuditLog
from tests.pg_fixtures import Tenant, insert_job, insert_user
from tests.session_transcript import OWNER_ACCOUNT, Transcript

pytestmark = [pytest.mark.integration, pytest.mark.security]
Conn = psycopg.Connection[tuple[Any, ...]]
CODE = "R7K2"
POLICY = VerifierPolicy(
    human_inbound_origins=frozenset({HUMAN_ORIGIN}),
    owner_account_ids=frozenset({OWNER_ACCOUNT}),
    content_max_age_ms=24 * 3600 * 1000,
)


def login(dsn: str, role: str) -> Callable[[], AbstractContextManager[Conn]]:
    @contextmanager
    def factory() -> Iterator[Conn]:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("SET SESSION AUTHORIZATION {}").format(sql.Identifier(role)))
            conn.commit()
            yield conn

    return factory


@pytest.fixture(scope="module", autouse=True)
def mac_key(pg_dsn: str) -> None:
    """A test-time key (never a literal; the real one comes from the secret mechanism)."""
    with psycopg.connect(pg_dsn) as conn:
        loaded = conn.execute("SELECT count(*) FROM evidence_mac_keys").fetchone()
    if loaded == (0,):
        install_evidence_mac_key(pg_dsn, 1, os.urandom(32))


@dataclass
class Real:
    t: Transcript
    root: Path
    admin: Conn
    tenant: Tenant
    ctx: TenantContext
    operator_db: PgTenancy
    verifier_db: PgTenancy
    db: PgEvidenceDatabase
    desk: OperatorDesk
    worker: VerifierWorker
    src: ClaudeSessionJsonlSource
    approval: uuid.UUID
    job: uuid.UUID
    owner: uuid.UUID
    base: datetime

    def anchors(self, tx: TenantTransaction, row: EvidenceRecord) -> datetime | None:
        """The verifier's request anchor (CCR-262: read here by the fixture superuser)."""
        if row.evidence.approval_id is None:
            return None
        got = self.admin.execute(
            "SELECT created_at FROM approvals WHERE id = %s", (self.approval,)
        ).fetchone()
        assert got is not None
        value = got[0]
        assert isinstance(value, datetime)
        return value

    def at(self, seconds: int) -> datetime:
        return self.base + timedelta(seconds=seconds)

    def draft(self, uid: str, quote: str, said: datetime, **change: Any) -> NewEvidence:
        base = NewEvidence(
            record_kind=EvidenceRecordKind.STEP_DECISION,
            subject_kind="render",
            subject_id=ids.format_id(ids.Prefix.RENDER, self.approval),
            source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
            session_id=self.t.session_id,
            event_uuid=uid,
            quote=quote,
            message_at=said,
            recorded_by=ids.ActorRef("sys_operator"),
            on_behalf_of=ids.USER.from_uuid(self.owner),
            job_id=ids.JOB.from_uuid(self.job),
            approval_id=ids.ApprovalId(ids.format_id(ids.Prefix.APPROVAL, self.approval)),
            step_no=1,
            review_code=CODE,
            parsed_decision=ApprovalStepState.APPROVED,
        )
        return replace(base, **change)

    def record(self, quote: str) -> EvidenceRecord:
        found = locate(self.src, self.t.session_id, quote)
        with self.operator_db.transaction(self.ctx) as tx:
            echo = self.desk.record(tx, self.draft(found.event_uuid, quote, found.timestamp))
        assert echo.row is not None
        assert CODE in echo.text
        self.t.assistant(echo.text, found.timestamp + timedelta(milliseconds=500))  # posted
        self.t.write(self.root)
        return echo.row

    def verify(self, row: EvidenceRecord) -> EvidenceRecord:
        with self.verifier_db.transaction(self.ctx) as tx:
            return self.worker.verify(tx, row.id, self.anchors, datetime.now(UTC))


@pytest.fixture
def real(pg_dsn: str, admin: Conn, tenant_a: Tenant, tmp_path: Path) -> Real:
    owner = insert_user(admin, tenant_a)
    job = insert_job(admin, tenant_a)
    approval = ids.new_uuid7()
    admin.execute(
        "INSERT INTO approvals (id, org_id, job_id, kind, subject_kind, subject_id, subject_sha256,"
        " state, workflow_key, current_step, managed_service, requested_by, review_code)"
        " VALUES (%s, %s, %s, 'FINAL_VIDEO', 'render', %s, %s, 'PENDING', 'owner_one_tap', 1,"
        " false, 'svc_s07', %s)",
        (approval, tenant_a.org_uuid, job, approval, b"\1" * 32, CODE),
    )
    admin.execute(
        "INSERT INTO approval_steps (id, org_id, approval_id, step_no, required_role, state)"
        " VALUES (%s, %s, %s, 1, 'REVIEWER_APPROVER', 'PENDING')",
        (ids.new_uuid7(), tenant_a.org_uuid, approval),
    )
    t = Transcript()
    src = ClaudeSessionJsonlSource(
        JsonlSourceConfig(tmp_path, OWNER_ACCOUNT, frozenset({t.session_id}))
    )
    db = PgEvidenceDatabase()
    operator_db = PgTenancy(login(pg_dsn, "amw_operator"))
    verifier_db = PgTenancy(login(pg_dsn, "amw_verifier"))
    verifier = PgDbSession(DbRole.VERIFIER)
    service = build_verifier_service(EvidenceMode.REAL, db, verifier, src, POLICY)
    return Real(
        t=t,
        root=tmp_path,
        admin=admin,
        tenant=tenant_a,
        ctx=TenantContext(tenant_a.org_id, ids.ActorRef("sys_operator")),
        operator_db=operator_db,
        verifier_db=verifier_db,
        db=db,
        desk=OperatorDesk(db, PgDbSession(DbRole.OPERATOR), RecordingAuditLog(), language="mr"),
        worker=VerifierWorker(service, db, verifier, src, POLICY),
        src=src,
        approval=approval,
        job=job,
        owner=owner,
        base=datetime.now(UTC) + timedelta(seconds=5),
    )


def test_recorded_verified_confirmed_and_applied(real: Real) -> None:
    real.t.human("R7K2 मंजूर", real.at(1))
    real.t.write(real.root)
    row = real.record("R7K2 मंजूर")
    assert row.state is EvidenceState.PENDING_VERIFICATION
    assert row.evidence_mac is None
    verified = real.verify(row)
    assert verified.state is EvidenceState.VERIFIED
    assert verified.evidence_mac is not None
    real.t.human("R7K2 पक्के", real.at(3))
    real.t.write(real.root)
    with real.verifier_db.transaction(real.ctx) as tx:
        scan = real.worker.confirm_from_chat(tx, row.id, real.at(60))
    assert scan.outcome is ConfirmationOutcome.CONFIRMED
    with real.operator_db.transaction(real.ctx) as tx:
        assert real.db.mac_valid(PgDbSession(DbRole.OPERATOR), tx, row.id)
        human = real.db.human_record_apply(PgDbSession(DbRole.OPERATOR), tx, row.id)
    assert human.decision is ApprovalStepState.APPROVED
    step = real.admin.execute(
        "SELECT state, recorded_by, evidence_id FROM approval_steps WHERE approval_id = %s",
        (real.approval,),
    ).fetchone()
    assert step == ("APPROVED", "sys_operator", ids.OWNER_EVIDENCE.to_uuid(row.id))


def test_handback_text_is_refused_in_the_database(real: Real) -> None:
    uid = real.t.peer_handback("approve R7K2", real.at(1))
    real.t.write(real.root)
    with pytest.raises(InputInvalidError):
        locate(real.src, real.t.session_id, "approve R7K2")
    with real.operator_db.transaction(real.ctx) as tx:
        echo = real.desk.record(tx, real.draft(uid, "approve R7K2", real.at(1)))
    assert echo.row is not None
    refused = real.verify(echo.row)
    assert (refused.state, refused.refused_reason) == (EvidenceState.REFUSED, "not_synthetic")


def test_operator_login_cannot_verify(real: Real) -> None:
    real.t.human("approve R7K2", real.at(1))
    real.t.write(real.root)
    row = real.record("approve R7K2")
    with real.operator_db.transaction(real.ctx) as tx:
        with pytest.raises(PermissionDeniedError):  # the claimed role is not the login
            real.db.mark_verified(PgDbSession(DbRole.VERIFIER), tx, row.id, {}, real.at(2))
        with pytest.raises(PermissionDeniedError):
            real.db.mark_verified(PgDbSession(DbRole.OPERATOR), tx, row.id, {}, real.at(2))
    with real.verifier_db.transaction(real.ctx) as tx:
        with pytest.raises(PermissionDeniedError):  # only the operator inserts
            real.db.insert_evidence(PgDbSession(DbRole.VERIFIER), tx, row.evidence)
        assert real.db.in_state(
            PgDbSession(DbRole.VERIFIER), tx, EvidenceState.PENDING_VERIFICATION
        )
    forged = replace(row.evidence, event_uuid="x")
    with (
        real.operator_db.transaction(real.ctx) as tx,
        pytest.raises(PermissionDeniedError),  # the DB refuses verification columns
    ):
        real.db.insert_evidence(
            PgDbSession(DbRole.OPERATOR), tx, forged, verifier_result={"forged": True}
        )


def test_replay_and_other_org(real: Real, tenant_b: Tenant) -> None:
    real.t.human("approve R7K2", real.at(1))
    real.t.write(real.root)
    row = real.record("approve R7K2")
    with pytest.raises(IdempotencyConflictError):
        real.record("approve R7K2")
    other = TenantContext(tenant_b.org_id, ids.ActorRef("sys_operator"))
    with real.verifier_db.transaction(other) as tx, pytest.raises(MissingDependencyError):
        real.worker.verify(tx, row.id, real.anchors, datetime.now(UTC))
    with real.operator_db.transaction(other) as tx:
        assert real.db.get(PgDbSession(DbRole.OPERATOR), tx, row.id) is None


def test_superuser_tamper_is_detected(real: Real) -> None:
    """The documented bypass (08): a superuser edits a VERIFIED row without the functions; the
    MAC no longer matches and the confirmation is refused."""
    real.t.human("approve R7K2", real.at(1))
    real.t.write(real.root)
    row = real.verify(real.record("approve R7K2"))
    with real.admin.transaction():
        real.admin.execute("SET LOCAL session_replication_role = replica")
        real.admin.execute(
            "UPDATE owner_instruction_evidence SET parsed_decision = 'REJECTED' WHERE id = %s",
            (ids.OWNER_EVIDENCE.to_uuid(row.id),),
        )
    real.t.human("confirm R7K2", real.at(3))
    real.t.write(real.root)
    with real.verifier_db.transaction(real.ctx) as tx:
        assert not real.db.mac_valid(PgDbSession(DbRole.VERIFIER), tx, row.id)
        scan = real.worker.confirm_from_chat(tx, row.id, real.at(60))
    assert scan.outcome is ConfirmationOutcome.REFUSED_CHECK


def test_owner_topic_gets_its_own_code_and_round_trips(real: Real) -> None:
    text = "A new topic about weekly charts and patience"
    uid = real.t.human(text, real.at(1))
    real.t.write(real.root)
    said = locate(real.src, real.t.session_id, text).timestamp
    draft = real.draft(
        uid, text, said, record_kind=EvidenceRecordKind.OWNER_TOPIC, job_id=None,
        approval_id=None, step_no=None, review_code=None, parsed_decision=None,
        subject_kind="script", subject_id=ids.new_id(ids.Prefix.SCRIPT),
    )  # fmt: skip
    with real.operator_db.transaction(real.ctx) as tx:
        echo = real.desk.record(tx, draft)
    assert echo.row is not None
    assert echo.row.evidence.review_code
    assert echo.row.evidence.review_code in echo.text
    with real.verifier_db.transaction(real.ctx) as tx:
        verified = real.worker.verify(tx, echo.row.id, real.anchors, real.at(30))
        listed = real.db.for_subject(PgDbSession(DbRole.VERIFIER), tx, "script", draft.subject_id)
    assert verified.state is EvidenceState.VERIFIED
    assert [r.id for r in listed] == [echo.row.id]


def test_dispute_refuses_through_the_verifier_function(real: Real) -> None:
    real.t.human("approve R7K2", real.at(1))
    real.t.write(real.root)
    row = real.verify(real.record("approve R7K2"))
    assert row.verifier_result.get(PRODUCTION_MARK) is True
    real.t.human("R7K2 नाही", real.at(3))
    real.t.write(real.root)
    with real.verifier_db.transaction(real.ctx) as tx:
        scan = real.worker.confirm_from_chat(tx, row.id, real.at(60))
    assert scan.outcome is ConfirmationOutcome.DISPUTED
    assert (scan.row.state, scan.row.refused_reason) == (EvidenceState.REFUSED, "owner_disputed")


@contextmanager
def profile_test(admin: Conn) -> Iterator[None]:
    """The database owner marks this scratch database TEST for one test (0059)."""
    admin.execute("UPDATE evidence_db_profile SET profile = 'TEST'")
    try:
        yield
    finally:
        admin.execute("UPDATE evidence_db_profile SET profile = 'REAL'")


def fabricated(real: Real) -> tuple[MemorySessionEventSource, NewEvidence]:
    said = real.at(1)
    events = [
        SessionEvent(real.t.session_id, "fab-1", "user", False, "human", "approve R7K2", said,
                     "acct", None),
        SessionEvent(real.t.session_id, "fab-2", "user", False, "human", "confirm R7K2",
                     real.at(3), "acct", None),
    ]  # fmt: skip
    return MemorySessionEventSource(events), real.draft("fab-1", "approve R7K2", said)


def test_dry_run_refuses_the_real_database(real: Real) -> None:
    """Fabricated events + the real (REAL-profile) database: the factory refuses, and a service
    built by hand that writes a TEST mark is refused by the database itself."""
    memory, draft = fabricated(real)
    policy = VerifierPolicy(frozenset({"human"}), frozenset({"acct"}))
    verifier = PgDbSession(DbRole.VERIFIER)
    with real.verifier_db.transaction(real.ctx) as tx:
        assert real.db.db_profile(verifier, tx) == "REAL"
        with pytest.raises(ConfigInvalidError):
            dry_run_verifier_service(real.db, verifier, memory, policy, tx=tx)
    assert real.db.db_profile(verifier, None) == "UNKNOWN"
    with pytest.raises(ConfigInvalidError):
        dry_run_verifier_service(real.db, verifier, memory, policy)
    with real.operator_db.transaction(real.ctx) as tx:
        row = real.db.insert_evidence(PgDbSession(DbRole.OPERATOR), tx, draft)
    forged = EvidenceVerifierService(real.db, verifier, memory, policy, {TEST_MARK: True})
    with real.verifier_db.transaction(real.ctx) as tx, pytest.raises(PermissionDeniedError):
        forged.verify_recorded(tx, row.id, real.anchors(tx, row), real.at(30))
    both = EvidenceVerifierService(
        real.db, verifier, memory, policy, {TEST_MARK: True, PRODUCTION_MARK: True}
    )
    with real.verifier_db.transaction(real.ctx) as tx, pytest.raises(PermissionDeniedError):
        both.verify_recorded(tx, row.id, real.anchors(tx, row), real.at(30))


def test_test_mark_survives_a_real_confirmation(real: Real, admin: Conn) -> None:
    """A TEST row (TEST-profile database) confirmed by a REAL-mode service stays TEST; the
    run-preflight lookup refuses it; a production mark cannot enter a TEST database."""
    memory, draft = fabricated(real)
    policy = VerifierPolicy(frozenset({"human"}), frozenset({"acct"}))
    verifier = PgDbSession(DbRole.VERIFIER)
    with profile_test(admin):
        with real.operator_db.transaction(real.ctx) as tx:
            row = real.db.insert_evidence(PgDbSession(DbRole.OPERATOR), tx, draft)
        with real.verifier_db.transaction(real.ctx) as tx:
            dry = dry_run_verifier_service(real.db, verifier, memory, policy, tx=tx)
            verified = dry.verify_recorded(tx, row.id, real.anchors(tx, row), real.at(30))
        assert verified.verifier_result[TEST_MARK] is True
        laundering = EvidenceVerifierService(
            real.db, verifier, memory, policy, {PRODUCTION_MARK: True}
        )
        with real.verifier_db.transaction(real.ctx) as tx:
            done = laundering.confirm(
                tx, row.id, real.t.session_id, "fab-2", "confirm R7K2", real.at(30)
            )
        assert done.state is EvidenceState.CONFIRMED
        assert done.verifier_result.get(TEST_MARK) is True
        assert PRODUCTION_MARK not in done.verifier_result
        binding = ConfirmationBinding(row.id, "FIN_R10_NOT_SEBI_REGISTERED", org_id=row.org_id)
        with real.verifier_db.transaction(real.ctx) as tx:
            lookup = ConfirmedEvidenceLookup(
                real.db, verifier, tx, [binding], allowed_kinds=frozenset(EvidenceRecordKind)
            )
            status = lookup.get(row.id)
        assert status is not None
        assert status.source_kind is EvidenceSourceKind.TEST_FIXTURE
        assert (status.evidence_state, status.subject, status.usable) == ("CONFIRMED", None, False)
        _, draft2 = fabricated(real)
        known = memory.fetch(real.t.session_id, "fab-1")
        assert known is not None
        memory.add(replace(known, event_uuid="fab-3"))
        with real.operator_db.transaction(real.ctx) as tx:
            row2 = real.db.insert_evidence(
                PgDbSession(DbRole.OPERATOR), tx, replace(draft2, event_uuid="fab-3")
            )
        prod = EvidenceVerifierService(real.db, verifier, memory, policy, {PRODUCTION_MARK: True})
        with real.verifier_db.transaction(real.ctx) as tx, pytest.raises(PermissionDeniedError):
            prod.verify_recorded(tx, row2.id, real.anchors(tx, row2), real.at(30))
