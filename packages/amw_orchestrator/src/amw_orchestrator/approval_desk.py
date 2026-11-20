"""The S7 approval desk (3A-13): ``svc_s07.request_approval`` over PostgreSQL.

``PgApprovalDesk`` is the ``ApprovalDesk`` the ``ApprovalWorker`` calls:

* ``open`` creates (once per task) the ``approvals`` row with its review code and the
  ``approval_steps`` rows, and reports ``PENDING``; the worker then parks the stage
  (``SUSPENDED`` / ``AWAITING_APPROVAL``, T09).
* the owner's decision arrives by the evidence path only (owner chat -> operator records ->
  verifier confirms -> operator ``amw_human_record_apply`` decides the step). This desk never
  writes a decided step and never infers a decision.
* ``decision`` returns the approval payload (CCR-283 provisional shape) only when the decided step
  is backed by evidence that ``ApprovalEvidenceLookup`` accepts (CONFIRMED, MAC valid, bound to
  this approval and subject, not superseded) and whose source is permitted by the mode: ``REAL``
  accepts only the production source; ``DRY_RUN`` also accepts ``TEST_FIXTURE``. A decided step
  with evidence that fails any check is a loud ``PermissionDeniedError`` (never a decision, never
  a silent wait). Only then is ``approvals.state`` derived from the step.

* the mode is tied to the database profile (``evidence_db_profile``, 0059): a ``REAL`` desk refuses
  a ``TEST`` database and a ``DRY_RUN`` desk refuses a ``REAL`` one (``ConfigInvalidError``,
  checked in every transaction before anything is read or written).
* ``approvals.state`` is written only by ``amw_approval_settle`` (0060), which the database
  re-checks against the evidence; ``decided`` is true only for a step whose evidence the lookup
  accepts (or an approval already settled with that evidence still valid).
* ``evidence_port`` is the long-lived read port for consumers (``ApprovalEvidencePort``).

Not proven: that any of this works against the real chat. A live owner confirmation has not been
demonstrated (EVIDENCE_PATH section 5).

Tenant isolation: the desk is built for one org; a task of another org is refused, every query
filters ``org_id`` and RLS applies.
"""

from collections.abc import Mapping

from amw_core.approval_store_pg import PgApprovalStore
from amw_core.contracts import TaskInput
from amw_core.errors import ConfigInvalidError, InputInvalidError, PermissionDeniedError
from amw_core.exec_context import ExecContext
from amw_core.ids import ActorRef, ApprovalId, JobId, OrgId, TaskId, WireId
from amw_core.interfaces.owner_evidence import DbRole, DbSession, EvidenceDatabase
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext, TenantTransaction
from amw_core.owner_evidence_approvals import (
    ApprovalEvidenceLookup,
    ApprovalEvidenceStatus,
    PgApprovalEvidencePort,
)
from amw_core.owner_evidence_real import EvidenceMode, ProfiledDatabase
from amw_core.owner_evidence_status import EvidenceSourceKind
from amw_orchestrator.payloads import ApprovalOutput, ApprovalRequestInput

_DESK = ActorRef("svc_s07")


class PgApprovalDesk:
    def __init__(
        self,
        tenancy: TenancyContext,
        database: EvidenceDatabase,
        session: DbSession,
        *,
        org_id: OrgId,
        mode: EvidenceMode,
        store: PgApprovalStore | None = None,
    ) -> None:
        if session.role is not DbRole.APP:
            raise InputInvalidError("the approval desk reads evidence as amw_app")
        self._t, self._db, self._session = tenancy, database, session
        self._org, self._mode = org_id, mode
        self._store = store or PgApprovalStore()

    def _ctx(self, org_id: str) -> TenantContext:
        if org_id != self._org:
            raise PermissionDeniedError("the task belongs to another tenant than this desk")
        return TenantContext(self._org, _DESK)

    # ---- ApprovalDesk -------------------------------------------------------------------
    def open(self, task_input: TaskInput, ctx: ExecContext) -> Mapping[str, object]:
        request = ApprovalRequestInput.model_validate(dict(task_input.payload.data or {}))
        with self._t.transaction(self._ctx(task_input.org_id)) as tx:
            self._profile_matches_mode(tx)
            approval = self._store.open_for_task(
                tx,
                task_id=TaskId(str(ctx.task_id)),
                job_id=JobId(str(ctx.job_id)),
                kind=request.approval_kind,
                subject_kind=request.subject.kind,
                subject_id=WireId(request.subject.id),
                subject_sha256=request.subject.sha256,
                subject_ref=request.subject.ref,
                workflow_key=request.workflow_key,
            )
            return self._output(approval.id, request, "PENDING", (), None)

    def decision(self, task_input: TaskInput, ctx: ExecContext) -> Mapping[str, object] | None:
        request = ApprovalRequestInput.model_validate(dict(task_input.payload.data or {}))
        with self._t.transaction(self._ctx(task_input.org_id)) as tx:
            self._profile_matches_mode(tx)
            approval = self._store.approval_of_task(tx, TaskId(str(ctx.task_id)))
            if approval is None:
                return None
            if approval.subject_sha256 != request.subject.sha256:
                raise PermissionDeniedError("the approval is bound to another subject hash")
            step = self._store.step(tx, approval.id, approval.current_step)
            if step is None or not step.decided or step.evidence_id is None:
                return None
            status = self._lookup(tx).get_for_approval(step.evidence_id, approval.id)
            if status is None:
                raise PermissionDeniedError("the step decision has no usable owner evidence")
            self._source_allowed(status)
            self._store.settle(tx, approval.id, step.state)
            return self._output(
                approval.id,
                request,
                step.state.value,
                (status.evidence_id,),
                status.parsed_target_stage_id,
            )

    def decided(self, job_id: str, task_id: str) -> bool:
        """True only when the task's approval has a decided step whose evidence the lookup accepts
        for this mode (a step or an approvals row written by anything else is not a decision)."""
        with self._t.transaction(TenantContext(self._org, _DESK)) as tx:
            self._profile_matches_mode(tx)
            approval = self._store.approval_of_task(tx, TaskId(task_id))
            if approval is None:
                return False
            step = self._store.step(tx, approval.id, approval.current_step)
            if step is None or not step.decided or step.evidence_id is None:
                return False
            status = self._lookup(tx).get_for_approval(
                step.evidence_id, approval.id, subject_sha256=approval.subject_sha256
            )
            if status is None or status.decision != step.state.value:
                return False
            self._source_allowed(status)
            return True

    def evidence_port(self) -> PgApprovalEvidencePort:
        """A long-lived read port over this desk's database (``ApprovalEvidencePort``): what the
        orchestrator's approval binding (PR 107) uses to check that an approval was APPROVED with
        usable evidence for a subject hash."""
        return PgApprovalEvidencePort(
            self._t, self._db, self._session, org_id=self._org, store=self._store
        )

    # ---- helpers ------------------------------------------------------------------------
    def _profile_matches_mode(self, tx: TenantTransaction) -> None:
        """REAL needs a REAL database, DRY_RUN a TEST one (0059); anything else fails closed."""
        profile = self._db_profile(tx)
        wanted = "REAL" if self._mode is EvidenceMode.REAL else "TEST"
        if profile != wanted:
            raise ConfigInvalidError(
                f"{self._mode.value} mode needs a {wanted} database profile, found {profile}"
            )

    def _db_profile(self, tx: TenantTransaction) -> str:
        if isinstance(self._db, ProfiledDatabase):
            return self._db.db_profile(self._session, tx)
        return "UNKNOWN"

    def _lookup(self, tx: TenantTransaction) -> ApprovalEvidenceLookup:
        return ApprovalEvidenceLookup(self._db, self._store, self._session, tx)

    def _source_allowed(self, status: ApprovalEvidenceStatus) -> None:
        if status.source_kind is EvidenceSourceKind.REAL:
            return
        if (
            self._mode is EvidenceMode.DRY_RUN
            and status.source_kind is EvidenceSourceKind.TEST_FIXTURE
        ):
            return
        raise PermissionDeniedError("TEST_FIXTURE evidence is refused in a real run")

    @staticmethod
    def _output(
        approval_id: ApprovalId,
        request: ApprovalRequestInput,
        state: str,
        evidence_ids: tuple[str, ...],
        target: str | None,
    ) -> Mapping[str, object]:
        out = ApprovalOutput.model_validate(
            {
                "approval_id": approval_id,
                "approval_kind": request.approval_kind,
                "state": state,
                "subject_sha256": request.subject.sha256,
                "evidence_ids": evidence_ids,
                "parsed_target_stage_id": target,
            }
        )
        return out.model_dump(mode="json")
