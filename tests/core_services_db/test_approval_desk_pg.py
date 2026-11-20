"""The S7 approval desk on real PostgreSQL (3A-13): park, owner reply through the evidence path,
refusals. Each process is its own login (``SET SESSION AUTHORIZATION``): ``amw_app`` is the desk,
``amw_operator`` records and applies, ``amw_verifier`` verifies and confirms.

NOT a claim about the real chat: the transcripts here are synthetic (tests/session_transcript.py)
and the dry-run source is the in-memory fixture. A live owner confirmation has not been shown.
"""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import psycopg
import pytest

from amw_adapters.session_record import ClaudeSessionJsonlSource, JsonlSourceConfig
from amw_core import ids
from amw_core.approval_store_pg import PgApprovalStore
from amw_core.contracts import TaskInput
from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    InstructionSourceKind,
)
from amw_core.errors import (
    ConfigInvalidError,
    IdempotencyConflictError,
    InvalidTransitionError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.exec_context import ExecContext
from amw_core.interfaces import DbRole, EvidenceRecord, NewEvidence, TenantContext
from amw_core.owner_evidence_approvals import ApprovalEvidenceLookup, PgApprovalEvidencePort
from amw_core.owner_evidence_fake import MemorySessionEventSource
from amw_core.owner_evidence_operator import OperatorDesk, locate
from amw_core.owner_evidence_pg import PgDbSession, PgEvidenceDatabase
from amw_core.owner_evidence_real import (
    ConfirmationOutcome,
    EvidenceMode,
    VerifierWorker,
    build_verifier_service,
    dry_run_verifier_service,
)
from amw_core.owner_evidence_status import EvidenceSourceKind, EvidenceStatusLookup
from amw_core.owner_evidence_verifier import SessionEvent, VerifierPolicy
from amw_core.tenancy import PgTenancy, connection_of
from amw_core.tenancy.evidence_keys import install_evidence_mac_key
from amw_orchestrator.approval_desk import PgApprovalDesk
from amw_orchestrator.payloads import ApprovalOutput
from tests.core_services_db.conftest import make_work
from tests.core_services_db.test_owner_evidence_real_path_pg import POLICY, login
from tests.fake_audit import RecordingAuditLog
from tests.pg_fixtures import Tenant, insert_user
from tests.session_transcript import OWNER_ACCOUNT, Transcript

pytestmark = [pytest.mark.integration, pytest.mark.security]
Conn = psycopg.Connection[tuple[Any, ...]]
SHA = "ab" * 32
OTHER_SHA = "cd" * 32


@pytest.fixture(scope="module", autouse=True)
def mac_key(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn:
        loaded = conn.execute("SELECT count(*) FROM evidence_mac_keys").fetchone()
    if loaded == (0,):
        install_evidence_mac_key(pg_dsn, 1, os.urandom(32))


def request(sha: str = SHA, **change: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "subject": {"kind": "render", "id": str(ids.new_id(ids.Prefix.RENDER)), "sha256": sha},
        "approval_kind": "FINAL_VIDEO",
        "workflow_key": "owner_one_tap",
    }
    return data | change


@dataclass
class Job:
    """One approval stage: a task of ``tenant`` and the input the builder would give it."""

    tenant: Tenant
    job: ids.JobId
    task: ids.TaskId
    data: dict[str, Any]

    def task_input(self, org: str | None = None, data: dict[str, Any] | None = None) -> TaskInput:
        payload = SimpleNamespace(data=data if data is not None else self.data)
        return cast(TaskInput, SimpleNamespace(org_id=org or self.tenant.org_id, payload=payload))

    def ctx(self) -> ExecContext:
        return ExecContext(
            tenant=TenantContext(self.tenant.org_id, ids.ActorRef("svc_s07")),
            job_id=self.job,
            task_id=self.task,
            attempt_id=ids.ATTEMPT.new(),
            channel_id=None,
            attempt_no=1,
        )


@dataclass
class World:
    dsn: str
    admin: Conn
    tenant: Tenant
    owner: uuid.UUID
    root: Path
    t: Transcript
    src: ClaudeSessionJsonlSource
    db: PgEvidenceDatabase
    app_db: PgTenancy
    operator_db: PgTenancy
    verifier_db: PgTenancy
    worker: VerifierWorker
    op: OperatorDesk
    base: datetime
    real: PgApprovalDesk
    dry: PgApprovalDesk

    @property
    def ctx(self) -> TenantContext:
        return TenantContext(self.tenant.org_id, ids.ActorRef("sys_operator"))

    def at(self, seconds: int) -> datetime:
        return self.base + timedelta(seconds=seconds)

    def job(self, **change: Any) -> Job:
        work = make_work(self.admin, self.tenant)
        return Job(self.tenant, work.job_id, work.task_id, request(**change))

    def approval(self, job: Job) -> dict[str, Any]:
        row = self.admin.execute(
            "SELECT id, review_code, state, created_at FROM approvals a WHERE id ="
            " (SELECT approval_id FROM tasks WHERE id = %s)",
            (ids.TASK.to_uuid(job.task),),
        ).fetchone()
        assert row is not None
        return {"id": row[0], "code": row[1], "state": row[2], "created_at": row[3]}

    def draft(self, job: Job, uid: str, quote: str, said: datetime, **change: Any) -> NewEvidence:
        info = self.approval(job)
        base = NewEvidence(
            record_kind=EvidenceRecordKind.STEP_DECISION,
            subject_kind="render",
            subject_id=ids.WireId(job.data["subject"]["id"]),
            source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
            session_id=self.t.session_id,
            event_uuid=uid,
            quote=quote,
            message_at=said,
            recorded_by=ids.ActorRef("sys_operator"),
            on_behalf_of=ids.USER.from_uuid(self.owner),
            job_id=job.job,
            approval_id=ids.ApprovalId(ids.format_id(ids.Prefix.APPROVAL, info["id"])),
            step_no=1,
            review_code=info["code"],
            parsed_decision=ApprovalStepState.APPROVED,
        )
        return replace(base, **change)

    def anchors(self, tx: Any, row: EvidenceRecord) -> datetime | None:
        if row.evidence.approval_id is None:
            return None
        got = self.admin.execute(
            "SELECT created_at FROM approvals WHERE id = %s",
            (ids.APPROVAL.to_uuid(row.evidence.approval_id),),
        ).fetchone()
        assert got is not None
        value = got[0]
        assert isinstance(value, datetime)
        return value

    def say(self, job: Job, text: str, at: int, **change: Any) -> EvidenceRecord:
        """The owner types ``text``; the operator records it (the echo is posted to the chat)."""
        self.t.human(text, self.at(at))
        self.t.write(self.root)
        found = locate(self.src, self.t.session_id, text)
        with self.operator_db.transaction(self.ctx) as tx:
            echo = self.op.record(
                tx, self.draft(job, found.event_uuid, text, found.timestamp, **change)
            )
        assert echo.row is not None
        self.t.assistant(echo.text, found.timestamp + timedelta(milliseconds=500))
        self.t.write(self.root)
        return echo.row

    def verify(self, row: EvidenceRecord) -> EvidenceRecord:
        with self.verifier_db.transaction(self.ctx) as tx:
            return self.worker.verify(tx, row.id, self.anchors, datetime.now(UTC))

    def confirm(self, row: EvidenceRecord, text: str, at: int) -> ConfirmationOutcome:
        self.t.human(text, self.at(at))
        self.t.write(self.root)
        with self.verifier_db.transaction(self.ctx) as tx:
            return self.worker.confirm_from_chat(tx, row.id, self.at(60)).outcome

    def apply(self, row: EvidenceRecord) -> None:
        with self.operator_db.transaction(self.ctx) as tx:
            self.db.human_record_apply(PgDbSession(DbRole.OPERATOR), tx, row.id)

    def owner_decides(
        self, job: Job, decision: str = "approve", at: int = 1, **change: Any
    ) -> EvidenceRecord:
        """The whole real path for one decision: record, verify, confirm from the chat, apply."""
        code = self.approval(job)["code"]
        row = self.verify(self.say(job, f"{decision} {code}", at, **change))
        assert self.confirm(row, f"confirm {code}", at + 2) is ConfirmationOutcome.CONFIRMED
        self.apply(row)
        return row

    def lookup(self, tx: Any) -> ApprovalEvidenceLookup:
        return ApprovalEvidenceLookup(self.db, PgApprovalStore(), PgDbSession(DbRole.APP), tx)

    def desk_port(self) -> PgApprovalEvidencePort:
        return self.real.evidence_port()

    def step_evidence(self, job: Job) -> uuid.UUID:
        got = self.admin.execute(
            "SELECT evidence_id FROM approval_steps WHERE approval_id ="
            " (SELECT approval_id FROM tasks WHERE id = %s)",
            (ids.TASK.to_uuid(job.task),),
        ).fetchone()
        assert got is not None
        value = got[0]
        assert isinstance(value, uuid.UUID)
        return value

    def step(self, job: Job) -> tuple[Any, ...]:
        got = self.admin.execute(
            "SELECT state, evidence_id FROM approval_steps WHERE approval_id ="
            " (SELECT approval_id FROM tasks WHERE id = %s)",
            (ids.TASK.to_uuid(job.task),),
        ).fetchone()
        assert got is not None
        return got


@pytest.fixture
def world(pg_dsn: str, admin: Conn, tenant_a: Tenant, tmp_path: Path) -> World:
    t = Transcript()
    src = ClaudeSessionJsonlSource(
        JsonlSourceConfig(tmp_path, OWNER_ACCOUNT, frozenset({t.session_id}))
    )
    db = PgEvidenceDatabase()
    verifier = PgDbSession(DbRole.VERIFIER)
    service = build_verifier_service(EvidenceMode.REAL, db, verifier, src, POLICY)
    app_db = PgTenancy(login(pg_dsn, "amw_app"))
    app = PgDbSession(DbRole.APP)
    return World(
        dsn=pg_dsn,
        admin=admin,
        tenant=tenant_a,
        owner=insert_user(admin, tenant_a),
        root=tmp_path,
        t=t,
        src=src,
        db=db,
        app_db=app_db,
        operator_db=PgTenancy(login(pg_dsn, "amw_operator")),
        verifier_db=PgTenancy(login(pg_dsn, "amw_verifier")),
        worker=VerifierWorker(service, db, verifier, src, POLICY),
        op=OperatorDesk(db, PgDbSession(DbRole.OPERATOR), RecordingAuditLog(), language="mr"),
        base=datetime.now(UTC) + timedelta(seconds=5),
        real=PgApprovalDesk(app_db, db, app, org_id=tenant_a.org_id, mode=EvidenceMode.REAL),
        dry=PgApprovalDesk(app_db, db, app, org_id=tenant_a.org_id, mode=EvidenceMode.DRY_RUN),
    )


@contextmanager
def profile_test(admin: Conn) -> Iterator[None]:
    admin.execute("UPDATE evidence_db_profile SET profile = 'TEST'")
    try:
        yield
    finally:
        admin.execute("UPDATE evidence_db_profile SET profile = 'REAL'")


# ---- park -------------------------------------------------------------------------------
def test_open_creates_the_approval_and_parks_without_a_decision(world: World) -> None:
    job = world.job()
    out = world.real.open(job.task_input(), job.ctx())
    parsed = ApprovalOutput.model_validate(out)  # the CCR-283 provisional shape
    assert (parsed.state, parsed.evidence_ids, parsed.subject_sha256) == ("PENDING", (), SHA)
    info = world.approval(job)
    assert info["state"] == "PENDING"
    assert ids.format_id(ids.Prefix.APPROVAL, info["id"]) == parsed.approval_id
    registry = world.admin.execute(
        "SELECT owner_kind, owner_id FROM review_codes WHERE org_id = %s AND code = %s",
        (world.tenant.org_uuid, info["code"]),
    ).fetchone()
    assert registry == ("APPROVAL", info["id"])  # the review_codes registry (PR 54)
    assert world.step(job) == ("PENDING", None)
    assert world.real.decision(job.task_input(), job.ctx()) is None
    assert not world.real.decided(str(job.job), str(job.task))


def test_open_twice_is_one_approval_and_a_changed_request_is_refused(world: World) -> None:
    job = world.job()
    first = world.real.open(job.task_input(), job.ctx())
    second = world.real.open(job.task_input(), job.ctx())
    assert first == second
    count = world.admin.execute(
        "SELECT count(*) FROM approvals WHERE org_id = %s", (world.tenant.org_uuid,)
    ).fetchone()
    assert count == (1,)
    changed = job.task_input(
        data=request(OTHER_SHA) | {"subject": job.data["subject"] | {"sha256": OTHER_SHA}}
    )
    with pytest.raises(IdempotencyConflictError):
        world.real.open(changed, job.ctx())


def test_workflows_that_are_not_built_are_refused(world: World) -> None:
    job = world.job(workflow_key="owner_sensitive")
    with pytest.raises(ConfigInvalidError):
        world.real.open(job.task_input(), job.ctx())
    count = world.admin.execute(
        "SELECT count(*) FROM approvals WHERE job_id = %s", (ids.JOB.to_uuid(job.job),)
    ).fetchone()
    assert count == (0,)


def test_the_app_login_cannot_write_a_decided_step(world: World) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    with world.app_db.transaction(world.ctx) as tx, pytest.raises(psycopg.Error):
        connection_of(tx).execute(
            "UPDATE approval_steps SET state = 'APPROVED', decided_by = %s,"
            " approval_channel = 'OWNER_CHAT_OPERATOR', recorded_by = 'svc_s07'",
            (world.owner,),
        )
    # migration 0060: the approval row is no free write either (state, hash, task pointer)
    approval = world.approval(job)["id"]
    for stmt, params in (
        ("UPDATE approvals SET state = 'APPROVED' WHERE id = %s", (approval,)),
        (
            "UPDATE approvals SET subject_sha256 = %s WHERE id = %s",
            (bytes.fromhex(OTHER_SHA), approval),
        ),
        ("UPDATE tasks SET approval_id = NULL WHERE id = %s", (ids.TASK.to_uuid(job.task),)),
    ):
        with (
            pytest.raises(PermissionDeniedError),
            world.app_db.transaction(world.ctx) as tx,
        ):
            connection_of(tx).execute(stmt.encode(), params)
    assert world.approval(job)["state"] == "PENDING"


# ---- the owner replies (REAL source) ------------------------------------------------------
@pytest.mark.parametrize("form", ["approve {c}", "{c} मंजूर"])
def test_owner_reply_resumes_the_stage(world: World, form: str) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    code = world.approval(job)["code"]
    row = world.verify(world.say(job, form.format(c=code), 1))
    assert world.real.decision(job.task_input(), job.ctx()) is None  # VERIFIED is not a decision
    assert world.confirm(row, form.format(c=code), 3) is ConfirmationOutcome.CONFIRMED
    assert world.real.decision(job.task_input(), job.ctx()) is None  # applied by nobody yet
    world.apply(row)
    assert world.real.decided(str(job.job), str(job.task))
    out = ApprovalOutput.model_validate(world.real.decision(job.task_input(), job.ctx()))
    assert (out.state, out.evidence_ids) == ("APPROVED", (row.id,))
    assert world.approval(job)["state"] == "APPROVED"
    again = world.real.decision(job.task_input(), job.ctx())  # a re-run is idempotent
    assert again is not None
    assert ApprovalOutput.model_validate(again) == out
    with world.app_db.transaction(world.ctx) as tx:
        status = world.lookup(tx).get(row.id)
    assert status is not None
    assert status.usable
    assert (status.evidence_state, status.mac_valid, status.source_kind) == (
        "CONFIRMED",
        True,
        EvidenceSourceKind.REAL,
    )
    assert (status.approval_id, status.step_no, status.decision) == (out.approval_id, 1, "APPROVED")
    assert status.subject_sha256 == SHA
    assert status.subject == "|".join(
        (
            "APPROVAL_DECISION",
            out.approval_id,
            "render",
            job.data["subject"]["id"],
            SHA,
            status.org_id,
        )
    )


def test_changes_requested_carries_the_stage_word(world: World) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    code = world.approval(job)["code"]
    row = world.verify(
        world.say(
            job,
            f"changes {code} thumbnail",
            1,
            parsed_decision=ApprovalStepState.CHANGES_REQUESTED,
            parsed_target_stage_id="s11_thumbs",
        )
    )
    assert world.confirm(row, f"confirm {code}", 3) is ConfirmationOutcome.CONFIRMED
    world.apply(row)
    out = ApprovalOutput.model_validate(world.real.decision(job.task_input(), job.ctx()))
    assert (out.state, out.parsed_target_stage_id) == ("CHANGES_REQUESTED", "s11_thumbs")


# ---- refusals ---------------------------------------------------------------------------
def test_wrong_code_is_refused_and_nothing_is_decided(world: World) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    code = world.approval(job)["code"]
    wrong = "K9K9" if code != "K9K9" else "M8M8"
    row = world.verify(world.say(job, f"approve {wrong}", 1))
    assert row.state is EvidenceState.REFUSED
    with pytest.raises(PermissionDeniedError):
        world.apply(row)
    assert world.real.decision(job.task_input(), job.ctx()) is None
    assert world.approval(job)["state"] == "PENDING"


def test_replay_and_another_approvals_evidence_decide_nothing(world: World) -> None:
    first, second = world.job(), world.job()
    world.real.open(first.task_input(), first.ctx())
    world.real.open(second.task_input(), second.ctx())
    row = world.owner_decides(first)
    with world.operator_db.transaction(world.ctx) as tx, pytest.raises(IdempotencyConflictError):
        world.db.insert_evidence(PgDbSession(DbRole.OPERATOR), tx, row.evidence)  # replay
    second_info = world.approval(second)
    other = ids.ApprovalId(ids.format_id(ids.Prefix.APPROVAL, second_info["id"]))
    with world.app_db.transaction(world.ctx) as tx:
        lookup = world.lookup(tx)
        assert lookup.get_for_approval(row.id, other) is None
        assert lookup.explain(row.id, other) == "evidence belongs to another approval"
    assert world.real.decision(second.task_input(), second.ctx()) is None
    assert world.approval(second)["state"] == "PENDING"
    with (
        pytest.raises(InvalidTransitionError),  # a second apply of the same evidence
        world.operator_db.transaction(world.ctx) as tx,
    ):
        world.db.human_record_apply(PgDbSession(DbRole.OPERATOR), tx, row.id)


def test_a_later_decision_supersedes_a_confirmed_one(world: World) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    code = world.approval(job)["code"]
    row = world.owner_decides(job)
    later = world.t.human(f"reject {code}", world.at(10))
    world.t.write(world.root)
    said = locate(world.src, world.t.session_id, f"reject {code}").timestamp
    with world.operator_db.transaction(world.ctx) as tx:
        world.db.insert_evidence(
            PgDbSession(DbRole.OPERATOR),
            tx,
            world.draft(
                job, later, f"reject {code}", said, parsed_decision=ApprovalStepState.REJECTED
            ),
        )
    with world.app_db.transaction(world.ctx) as tx:
        assert world.lookup(tx).explain(row.id) == "a later decision supersedes this one"
    with pytest.raises(PermissionDeniedError):
        world.real.decision(job.task_input(), job.ctx())
    assert world.approval(job)["state"] == "PENDING"  # never settled on unusable evidence


def test_superseded_before_confirmation_cannot_be_confirmed(world: World) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    code = world.approval(job)["code"]
    approve = world.verify(world.say(job, f"approve {code}", 1))
    world.say(job, f"reject {code}", 2, parsed_decision=ApprovalStepState.REJECTED)
    assert world.confirm(approve, f"confirm {code}", 4) is ConfirmationOutcome.SUPERSEDED
    assert world.real.decision(job.task_input(), job.ctx()) is None


def test_a_changed_subject_hash_is_not_authorised(world: World) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    world.owner_decides(job)
    changed = job.task_input(
        data=request(OTHER_SHA) | {"subject": job.data["subject"] | {"sha256": OTHER_SHA}}
    )
    with pytest.raises(PermissionDeniedError):
        world.real.decision(changed, job.ctx())
    assert world.approval(job)["state"] == "PENDING"


def test_forged_mac_makes_the_decision_unusable(world: World) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    row = world.owner_decides(job)
    with world.admin.transaction():
        world.admin.execute("SET LOCAL session_replication_role = replica")
        world.admin.execute(
            "UPDATE owner_instruction_evidence SET quote = quote || ' ' WHERE id = %s",
            (ids.OWNER_EVIDENCE.to_uuid(row.id),),
        )
    with world.app_db.transaction(world.ctx) as tx:
        assert world.lookup(tx).get(row.id) is None
    with pytest.raises(PermissionDeniedError):
        world.real.decision(job.task_input(), job.ctx())


# ---- TEST_FIXTURE (dry run) ---------------------------------------------------------------
def dry_decision(world: World, job: Job) -> EvidenceRecord:
    """The dry-run path: in-memory source in a TEST-profile database."""
    code = world.approval(job)["code"]
    said = world.at(1)
    memory = MemorySessionEventSource(
        [
            SessionEvent(world.t.session_id, "d-1", "user", False, "human", f"approve {code}",
                         said, "acct", None),
            SessionEvent(world.t.session_id, "d-2", "user", False, "human", f"confirm {code}",
                         world.at(3), "acct", None),
        ]
    )  # fmt: skip
    policy = VerifierPolicy(frozenset({"human"}), frozenset({"acct"}))
    verifier = PgDbSession(DbRole.VERIFIER)
    with world.operator_db.transaction(world.ctx) as tx:
        row = world.db.insert_evidence(
            PgDbSession(DbRole.OPERATOR), tx, world.draft(job, "d-1", f"approve {code}", said)
        )
    with world.verifier_db.transaction(world.ctx) as tx:
        service = dry_run_verifier_service(world.db, verifier, memory, policy, tx=tx)
        service.verify_recorded(tx, row.id, world.anchors(tx, row), world.at(30))
        done = service.confirm(
            tx, row.id, world.t.session_id, "d-2", f"confirm {code}", world.at(30)
        )
    assert done.state is EvidenceState.CONFIRMED
    world.apply(done)
    return done


def test_real_desk_refuses_test_rows_and_the_dry_run_desk_takes_them(
    world: World, admin: Conn
) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    with profile_test(admin):
        row = dry_decision(world, job)
        with world.app_db.transaction(world.ctx) as tx:
            status = world.lookup(tx).get(row.id)
        assert status is not None
        assert status.source_kind is EvidenceSourceKind.TEST_FIXTURE
        # a REAL desk never works in a TEST-profile database (mode tied to the profile)
        with pytest.raises(ConfigInvalidError):
            world.real.decision(job.task_input(), job.ctx())
        assert world.approval(job)["state"] == "PENDING"
    # the profile cannot be flipped to REAL by a login; as the database owner it is flipped here
    # to prove that the REAL desk still refuses the TEST_FIXTURE row itself (defence in depth)
    admin.execute("UPDATE evidence_db_profile SET profile = 'REAL'")
    with pytest.raises(PermissionDeniedError):
        world.real.decision(job.task_input(), job.ctx())
    with pytest.raises(PermissionDeniedError):
        world.real.decided(str(job.job), str(job.task))
    with pytest.raises(ConfigInvalidError):  # a DRY_RUN desk never touches a REAL database
        world.dry.decision(job.task_input(), job.ctx())
    assert world.approval(job)["state"] == "PENDING"
    with profile_test(admin):
        assert world.dry.decided(str(job.job), str(job.task))
        out = ApprovalOutput.model_validate(world.dry.decision(job.task_input(), job.ctx()))
        assert (out.state, out.evidence_ids) == ("APPROVED", (row.id,))
    assert world.approval(job)["state"] == "APPROVED"


def test_mode_is_tied_to_the_database_profile(world: World, admin: Conn) -> None:
    job = world.job()
    with pytest.raises(ConfigInvalidError):  # DRY_RUN in a REAL database: no write at all
        world.dry.open(job.task_input(), job.ctx())
    count = admin.execute(
        "SELECT count(*) FROM approvals WHERE job_id = %s", (ids.JOB.to_uuid(job.job),)
    ).fetchone()
    assert count == (0,)
    with pytest.raises(ConfigInvalidError):
        world.dry.decided(str(job.job), str(job.task))
    with profile_test(admin):
        with pytest.raises(ConfigInvalidError):  # REAL in a TEST database
            world.real.open(job.task_input(), job.ctx())
        with pytest.raises(ConfigInvalidError):
            world.real.decided(str(job.job), str(job.task))
        world.dry.open(job.task_input(), job.ctx())
    assert world.approval(job)["state"] == "PENDING"


def test_decided_needs_usable_evidence_not_just_a_state(world: World) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    world.owner_decides(job)
    assert world.real.decided(str(job.job), str(job.task))
    later_text = f"reject {world.approval(job)['code']}"
    later = world.t.human(later_text, world.at(10))
    world.t.write(world.root)
    said = locate(world.src, world.t.session_id, later_text).timestamp
    with world.operator_db.transaction(world.ctx) as tx:
        world.db.insert_evidence(
            PgDbSession(DbRole.OPERATOR),
            tx,
            world.draft(job, later, later_text, said, parsed_decision=ApprovalStepState.REJECTED),
        )
    # the decided step is now superseded: no longer a decision
    assert not world.real.decided(str(job.job), str(job.task))
    # a settled approval whose evidence is later superseded is not "decided" either
    other = world.job()
    world.real.open(other.task_input(), other.ctx())
    world.owner_decides(other)
    assert world.real.decision(other.task_input(), other.ctx()) is not None
    assert world.real.decided(str(other.job), str(other.task))
    world.admin.execute("SET session_replication_role = replica")
    world.admin.execute(
        "UPDATE owner_instruction_evidence SET quote = quote || ' ' WHERE id = %s",
        (world.step_evidence(other),),
    )
    world.admin.execute("SET session_replication_role = origin")
    assert not world.real.decided(str(other.job), str(other.task))


# ---- tenant isolation -------------------------------------------------------------------
def test_org_isolation(world: World, tenant_b: Tenant, pg_dsn: str) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    row = world.owner_decides(job)
    # a desk of org A refuses an org B task input before it touches the database
    with pytest.raises(PermissionDeniedError):
        world.real.open(job.task_input(org=tenant_b.org_id), job.ctx())
    # a desk of org B cannot see org A's task, approval or evidence
    app = PgDbSession(DbRole.APP)
    desk_b = PgApprovalDesk(
        world.app_db, world.db, app, org_id=tenant_b.org_id, mode=EvidenceMode.REAL
    )
    with pytest.raises(MissingDependencyError):
        desk_b.decision(job.task_input(org=tenant_b.org_id), job.ctx())
    assert not _decided_or_missing(desk_b, job)
    ctx_b = TenantContext(tenant_b.org_id, ids.ActorRef("svc_s07"))
    with world.app_db.transaction(ctx_b) as tx:
        lookup = ApprovalEvidenceLookup(world.db, PgApprovalStore(), app, tx)
        assert lookup.get(row.id) is None
        assert lookup.explain(row.id) == "evidence not found in this tenant"
        assert PgApprovalStore().pending(tx) == []
    assert isinstance(
        ApprovalEvidenceLookup(world.db, PgApprovalStore(), app, tx), EvidenceStatusLookup
    )


def _decided_or_missing(desk: PgApprovalDesk, job: Job) -> bool:
    try:
        return desk.decided(str(job.job), str(job.task))
    except MissingDependencyError:
        return False


def test_unknown_evidence_ids_are_refused(world: World) -> None:
    job = world.job()
    world.real.open(job.task_input(), job.ctx())
    with world.app_db.transaction(world.ctx) as tx:
        lookup = world.lookup(tx)
        assert lookup.get(str(ids.new_id(ids.Prefix.OWNER_INSTRUCTION_EVIDENCE))) is None
        assert lookup.explain("oie_not-an-id") == "malformed evidence id"
        pending = PgApprovalStore().pending(tx)
    assert [p.review_code for p in pending] == [world.approval(job)["code"]]
