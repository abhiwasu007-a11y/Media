"""``approvals`` / ``approval_steps`` on PostgreSQL for the S7 approval desk (04 section 5.16;
03 section 11.6; ticket 3A-13).

What this store writes, as ``amw_app``: the approval row (with its ``review_code``, CCR-010/090,
registered in ``review_codes`` by the 0055 trigger), its undecided step rows, the pointer
``tasks.approval_id`` and, through ``amw_approval_settle`` (0060), the derived final
``approvals.state``. What it never writes: a decided
step or any other human row. Those are written only by ``amw_human_record_apply`` inside the
database (the human-row trigger refuses everyone else, 0009), through the operator login.

Every query filters ``org_id = amw_current_org()`` on top of RLS (blueprint tenancy rule).

PROVISIONAL (CCR-297, PROPOSED): only the workflow ``owner_one_tap`` (24 section 3.4: one step,
``REVIEWER_APPROVER``) is built. ``owner_sensitive`` needs a finance-channel condition the
task input does not carry and a step-advance rule nobody has written, and ``client_two_step`` is
a 3C portal flow: both are refused (``ConfigInvalidError``, fail closed).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg

from amw_core.enums import ApprovalKind, ApprovalState, ApprovalStepState
from amw_core.errors import (
    ConfigInvalidError,
    IdempotencyConflictError,
    InputInvalidError,
    MissingDependencyError,
    PermissionDeniedError,
)
from amw_core.ids import (
    APPROVAL,
    JOB,
    TASK,
    USER,
    ApprovalId,
    JobId,
    Prefix,
    TaskId,
    UserId,
    WireId,
    format_id,
    new_uuid7,
    parse_id,
    prefix_of,
)
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_pg import DEFAULT_SUBJECT_PREFIXES
from amw_core.owner_evidence_review_code import DEFAULT_LENGTH, generate_review_code
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

WORKFLOW_STEPS: Final[Mapping[str, tuple[str, ...]]] = {"owner_one_tap": ("REVIEWER_APPROVER",)}
"""``workflow_key`` -> the ``required_role`` of each step (24 section 3.4). Only what is built."""
REQUESTED_BY: Final = "svc_s07"
FINAL_STATES: Final = frozenset({"APPROVED", "REJECTED", "CHANGES_REQUESTED"})
"""The states the owner's decision can settle (an ``approval_step_state`` that is also an
``approval_state``)."""
_UNIQUE_VIOLATION: Final = "23505"
_CODE_RETRIES: Final = 8

_APPROVAL_COLUMNS: Final = (
    "id, org_id, job_id, kind, subject_kind, subject_id, subject_sha256, subject_ref, state,"
    " workflow_key, current_step, review_code, requested_by, decided_at, created_at"
)
_STEP_COLUMNS: Final = (
    "approval_id, step_no, required_role, state, decided_by, decided_at, approval_channel,"
    " recorded_by, evidence_id"
)


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    id: ApprovalId
    org_id: str
    job_id: JobId | None
    kind: ApprovalKind
    subject_kind: str
    subject_id: WireId
    subject_sha256: str | None
    """Lower-case hex of ``approvals.subject_sha256`` (03 section 11.6 rule 1)."""
    subject_ref: str | None
    state: ApprovalState
    workflow_key: str
    current_step: int
    review_code: str
    requested_by: str
    decided_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StepRecord:
    approval_id: ApprovalId
    step_no: int
    required_role: str
    state: ApprovalStepState
    decided_by: UserId | None
    decided_at: datetime | None
    approval_channel: str | None
    recorded_by: str | None
    evidence_id: WireId | None

    @property
    def decided(self) -> bool:
        return self.state in {
            ApprovalStepState.APPROVED,
            ApprovalStepState.REJECTED,
            ApprovalStepState.CHANGES_REQUESTED,
        }


class PgApprovalStore:
    """Approvals of one tenant transaction (``amw_app`` login)."""

    def __init__(
        self,
        *,
        subject_prefixes: Mapping[str, Prefix] = DEFAULT_SUBJECT_PREFIXES,
        review_code_length: int = DEFAULT_LENGTH,
        workflows: Mapping[str, tuple[str, ...]] = WORKFLOW_STEPS,
        choice: Callable[[str], str] | None = None,
    ) -> None:
        self._prefixes = dict(subject_prefixes)
        self._code_length = review_code_length
        self._workflows = dict(workflows)
        self._choice = choice

    # ---- mapping ------------------------------------------------------------------------
    def _approval(self, row: Sequence[Any]) -> ApprovalRecord:
        (
            rid, org, job, kind, subject_kind, subject_id, sha, ref, state, workflow, step, code,
            requested_by, decided_at, created_at,
        ) = row  # fmt: skip
        prefix = self._prefixes.get(subject_kind)
        if prefix is None:
            raise InputInvalidError("unknown subject_kind (no wire prefix configured)")
        return ApprovalRecord(
            id=APPROVAL.from_uuid(rid),
            org_id=f"org_{org}",
            job_id=JOB.from_uuid(job) if job else None,
            kind=ApprovalKind(kind),
            subject_kind=subject_kind,
            subject_id=WireId(format_id(prefix, subject_id)),
            subject_sha256=bytes(sha).hex() if sha is not None else None,
            subject_ref=ref,
            state=ApprovalState(state),
            workflow_key=workflow,
            current_step=step,
            review_code=code,
            requested_by=requested_by,
            decided_at=decided_at,
            created_at=created_at,
        )

    @staticmethod
    def _step(row: Sequence[Any]) -> StepRecord:
        approval, no, role, state, by, at, channel, recorded_by, evidence = row
        return StepRecord(
            approval_id=APPROVAL.from_uuid(approval),
            step_no=no,
            required_role=role,
            state=ApprovalStepState(state),
            decided_by=USER.from_uuid(by) if by else None,
            decided_at=at,
            approval_channel=channel,
            recorded_by=recorded_by,
            evidence_id=WireId(format_id(Prefix.OWNER_INSTRUCTION_EVIDENCE, evidence))
            if evidence
            else None,
        )

    # ---- reads --------------------------------------------------------------------------
    def get(self, tx: TenantTransaction, approval_id: ApprovalId) -> ApprovalRecord | None:
        conn = connection_of(tx)
        row = conn.execute(
            f"SELECT {_APPROVAL_COLUMNS} FROM approvals"  # noqa: S608
            " WHERE id = %s AND org_id = amw_current_org()",
            (APPROVAL.to_uuid(approval_id),),
        ).fetchone()
        return self._approval(row) if row else None

    def steps(self, tx: TenantTransaction, approval_id: ApprovalId) -> Sequence[StepRecord]:
        conn = connection_of(tx)
        rows = conn.execute(
            f"SELECT {_STEP_COLUMNS} FROM approval_steps"  # noqa: S608
            " WHERE approval_id = %s AND org_id = amw_current_org() ORDER BY step_no",
            (APPROVAL.to_uuid(approval_id),),
        ).fetchall()
        return [self._step(r) for r in rows]

    def step(
        self, tx: TenantTransaction, approval_id: ApprovalId, step_no: int
    ) -> StepRecord | None:
        return next((s for s in self.steps(tx, approval_id) if s.step_no == step_no), None)

    def approval_of_task(self, tx: TenantTransaction, task_id: TaskId) -> ApprovalRecord | None:
        """The approval a task opened (``tasks.approval_id``), or ``None`` if it opened none."""
        conn = connection_of(tx)
        row = conn.execute(
            "SELECT approval_id FROM tasks WHERE id = %s AND org_id = amw_current_org()",
            (TASK.to_uuid(task_id),),
        ).fetchone()
        if row is None:
            raise MissingDependencyError("task not found in this tenant")
        if row[0] is None:
            return None
        return self.get(tx, APPROVAL.from_uuid(row[0]))

    def pending(self, tx: TenantTransaction, limit: int = 100) -> Sequence[ApprovalRecord]:
        """``PENDING`` approvals of this tenant, oldest first (what the operator reminds the
        owner of; ``review_code`` is what he types)."""
        conn = connection_of(tx)
        rows = conn.execute(
            f"SELECT {_APPROVAL_COLUMNS} FROM approvals"  # noqa: S608
            " WHERE state = 'PENDING' AND org_id = amw_current_org() ORDER BY created_at, id"
            " LIMIT %s",
            (limit,),
        ).fetchall()
        return [self._approval(r) for r in rows]

    # ---- writes (amw_app) ---------------------------------------------------------------
    def _code(self, conn: Any, org: Any) -> str:
        def taken(code: str) -> bool:
            hit = conn.execute("SELECT 1 FROM amw_review_code_owner(%s, %s)", (org, code))
            return hit.fetchone() is not None

        if self._choice is None:
            return generate_review_code(taken, length=self._code_length)
        return generate_review_code(taken, length=self._code_length, choice=self._choice)

    def open_for_task(
        self,
        tx: TenantTransaction,
        *,
        task_id: TaskId,
        job_id: JobId,
        kind: ApprovalKind,
        subject_kind: str,
        subject_id: WireId,
        subject_sha256: str,
        subject_ref: str | None,
        workflow_key: str,
        requested_by: str = REQUESTED_BY,
    ) -> ApprovalRecord:
        """The approval of ``task_id``: the existing one, or a new ``PENDING`` approval with its
        step rows and a fresh review code, linked through ``tasks.approval_id``. Calling it again
        for the same task returns the same approval (a re-run of a parked task creates nothing).
        An existing approval that differs from the request is a ``IdempotencyConflictError``."""
        roles = self._workflows.get(workflow_key)
        if roles is None:
            raise ConfigInvalidError(f"approval workflow {workflow_key!r} is not built (CCR-297)")
        prefix = self._prefixes.get(subject_kind)
        if prefix is None or prefix_of(subject_id) is not prefix:
            raise InputInvalidError("the subject id does not belong to the subject kind")
        sha = bytes.fromhex(subject_sha256)
        if len(sha) != 32:
            raise InputInvalidError("subject_sha256 must be a SHA-256")
        conn = connection_of(tx)
        org = org_uuid_of(tx)
        locked = conn.execute(
            "SELECT approval_id, job_id FROM tasks WHERE id = %s AND org_id = %s FOR UPDATE",
            (TASK.to_uuid(task_id), org),
        ).fetchone()
        if locked is None:
            raise MissingDependencyError("task not found in this tenant")
        if locked[1] != JOB.to_uuid(job_id):
            raise PermissionDeniedError("the task belongs to another job")
        if locked[0] is not None:
            existing = self.get(tx, APPROVAL.from_uuid(locked[0]))
            if existing is None:  # pragma: no cover - the FK makes the row exist
                raise MissingDependencyError("approval of the task not found")
            same = (
                existing.kind is kind
                and existing.subject_kind == subject_kind
                and existing.subject_id == subject_id
                and existing.subject_sha256 == subject_sha256
                and existing.workflow_key == workflow_key
            )
            if not same:
                raise IdempotencyConflictError("the task already opened a different approval")
            return existing
        approval_uuid = new_uuid7()
        for _ in range(_CODE_RETRIES):
            code = self._code(conn, org)
            try:
                with conn.transaction():  # savepoint: a lost code race leaves the tx usable
                    conn.execute(
                        "INSERT INTO approvals (id, org_id, job_id, kind, subject_kind, subject_id,"
                        " subject_sha256, subject_ref, state, workflow_key, current_step,"
                        " managed_service, requested_by, review_code)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, 1, false, %s, %s)",
                        (
                            approval_uuid, org, JOB.to_uuid(job_id), kind.value, subject_kind,
                            parse_id(subject_id, prefix), sha, subject_ref, workflow_key,
                            requested_by, code,
                        ),
                    )  # fmt: skip
                break
            except psycopg.Error as exc:
                if exc.sqlstate in {_UNIQUE_VIOLATION, "AMW02"}:
                    continue  # the code was taken meanwhile: draw another
                raise translate_db_error(exc) from exc
        else:
            raise IdempotencyConflictError("could not register a free review code")
        for number, role in enumerate(roles, start=1):
            conn.execute(
                "INSERT INTO approval_steps (id, org_id, approval_id, step_no, required_role,"
                " state) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    new_uuid7(),
                    org,
                    approval_uuid,
                    number,
                    role,
                    "PENDING" if number == 1 else "NOT_STARTED",
                ),
            )
        conn.execute(
            "UPDATE tasks SET approval_id = %s WHERE id = %s AND org_id = %s",
            (approval_uuid, TASK.to_uuid(task_id), org),
        )
        made = self.get(tx, APPROVAL.from_uuid(approval_uuid))
        if made is None:  # pragma: no cover - just inserted in this transaction
            raise MissingDependencyError("approval not found after insert")
        return made

    def settle(
        self, tx: TenantTransaction, approval_id: ApprovalId, state: ApprovalStepState
    ) -> bool:
        """Derive the final ``approvals.state`` from the decided step (04 section 5.16: the
        approval's state follows its steps). ``True`` when this call changed it, ``False`` when
        it was already that state; another final state is ``PermissionDeniedError``. Since migration
        0060 the write goes through ``amw_approval_settle`` (``amw_app`` has no direct write on
        ``approvals.state``); the database re-checks the confirmed evidence of the step itself
        (``amw_approval_backed``) and refuses otherwise (``PermissionDeniedError``)."""
        if state.value not in FINAL_STATES:
            raise InputInvalidError("a step that is not decided cannot settle an approval")
        conn = connection_of(tx)
        try:
            row = conn.execute(
                "SELECT amw_approval_settle(%s)", (APPROVAL.to_uuid(approval_id),)
            ).fetchone()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        if row is not None and row[0] is True:
            return True
        current = self.get(tx, approval_id)
        if current is None:
            raise MissingDependencyError("approval not found in this tenant")
        if current.state.value != state.value:
            raise PermissionDeniedError("the approval is already settled to another state")
        return False
