"""Minimal code-controlled graph runner for the 3A video graph (3A_SLICE_SPEC 3A-01 / WS-04).

Every control decision is code reading the registry record (24 section 7.1a / 7.2a) and the
task outputs; an LLM never chooses a route. Per task (03 section 11.3):

T01 create (batch, ``PgJobStore``) -> T02 validate -> T03 budget reservation (E1) + enqueue
(``PgTaskQueue``) -> claim (``amw_queue_claim``) -> T07 + attempt -> executor -> T08 complete
(reservation consumed, queue row DONE) / T10-T12 retry / T11 failed. A paid call inside the
executor passes E2 / ledger / E3 in the metering wrappers. A refused reservation is T05
``AWAITING_BUDGET`` and stops the job (3A: every paid task is non-critical, hard stop).

Gates (03 section 5.3 rule 4, 24 section 3.3): only a stage the record registers as a gate may
return ``gate: true`` results; a failed gate (``gate_failures``) takes ``on_fail``. ``REVISE``
picks the earliest allowed ``remedy_stage_id`` in topological order (else the primary target)
and creates iteration n+1 tasks for the target and every stage that depends on it; the count per
gate is capped by ``limits.max_revision_loops``, then the job ends ``COMPLETED /
BLOCKED_COMPLIANCE``. ``STOP`` ends the job (``BLOCKED_COMPLIANCE`` for a compliance block).

Approval stages (``svc_s07.request_approval``) park the task ``CHECKPOINTED /
AWAITING_APPROVAL`` (T09) until the ``ApprovalDesk`` reports the owner's decision as R14
evidence; then T15 resumes it. The desk never infers a decision.

Market hours: a ``HEAVY_CPU`` task is not claimed while the calendar refuses rendering; the
run returns ``RENDER_WINDOW_CLOSED`` (the task stays ``QUEUED``).

Known limits (stated in the PR): the stage of a task is kept in the runner's map (the ``tasks``
table has no stage column); a crash-resume of the runner itself and leases / heartbeats over
long renders are 3C hardening (the reaper exists in ``amw_core.retries``).
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError

from amw_core.contracts import (
    ResourceBudget,
    Stage,
    TaskOutput,
    ValidationResult,
    error_object_from_exception,
    gate_failures,
    has_gate_results,
    integrity_failures,
)
from amw_core.contracts.envelope import Envelope
from amw_core.contracts.production_type import ReviseOnFail
from amw_core.enums import (
    AttemptResult,
    Capability,
    JobOutcome,
    JobState,
    OutputStatus,
    Priority,
    QueueName,
    ResourceClass,
    TaskState,
    TransitionId,
    WaitReason,
)
from amw_core.errors import AmwError, BudgetExhaustedError, MissingDependencyError
from amw_core.ids import (
    MESSAGE,
    ActorRef,
    ExecutorId,
    JobId,
    TaskId,
    WorkerId,
    make_idempotency_key,
)
from amw_core.interfaces import (
    BudgetGuard,
    ClaimRequest,
    JobStore,
    NewQueueItem,
    NewTask,
    TaskQueue,
    TaskRecord,
    TaskTransition,
    TenancyContext,
    TenantContext,
    TenantTransaction,
)
from amw_core.interfaces.job_store import JobTransition
from amw_core.state_machine import check_job, check_task, derive_job
from amw_core.state_machine.machine import TaskView
from amw_orchestrator.executor import ExecutorRegistry, JobFacts, StageCall
from amw_orchestrator.metering import MeteredTask, metered_task
from amw_orchestrator.registry import topological_order
from amw_orchestrator.runtime_iface import Calendar

ORCH = ActorRef("agent_01")
SCHEDULER = ActorRef("sys_scheduler")
APPROVAL_TASK = "svc_s07.request_approval"
_QUEUE = {
    ResourceClass.LIGHT: QueueName.LIGHT,
    ResourceClass.AI_IO: QueueName.AI,
    ResourceClass.HEAVY_CPU: QueueName.RENDER,
    ResourceClass.PUBLISH: QueueName.PUBLISH,
}


class ApprovalDesk(Protocol):
    """S7 boundary: open the approval request and report the owner's decision.

    ``decision`` returns ``None`` while no confirmed owner evidence exists (the task stays
    ``CHECKPOINTED``), else the approval payload (``state`` APPROVED / REJECTED /
    CHANGES_REQUESTED, the approval and evidence IDs)."""

    def open(self, call: StageCall) -> Mapping[str, object]: ...

    def decision(self, call: StageCall) -> Mapping[str, object] | None: ...


class BudgetPolicy(Protocol):
    def budget_for(self, stage: Stage) -> ResourceBudget: ...


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    max_attempts: int
    lease_ms: int
    workers: Mapping[ResourceClass, WorkerId]
    capabilities: tuple[Capability, ...]


@dataclass
class StageRun:
    stage_id: str
    task_id: str
    iteration: int
    state: TaskState
    output: TaskOutput | None = None
    attempts: int = 0
    duration_ms: int = 0


@dataclass
class RunReport:
    job_id: str
    status: str
    """DELIVERED / BLOCKED_COMPLIANCE / FAILED / AWAITING_BUDGET / RENDER_WINDOW_CLOSED /
    AWAITING_APPROVAL / REJECTED_BY_APPROVER."""
    order: list[str] = field(default_factory=list)
    """Stage IDs in execution order (iteration suffix ``#n`` for n > 0)."""
    gates: list[dict[str, object]] = field(default_factory=list)
    revisions: list[dict[str, object]] = field(default_factory=list)
    stages: dict[str, StageRun] = field(default_factory=dict)
    task_stage: dict[str, str] = field(default_factory=dict)
    detail: str = ""


class GraphRunner:
    def __init__(
        self,
        *,
        tenancy: TenancyContext,
        jobs: JobStore,
        queue: TaskQueue,
        budget: BudgetGuard,
        executors: ExecutorRegistry,
        approvals: ApprovalDesk,
        budgets: BudgetPolicy,
        calendar: Calendar,
        config: RunnerConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._t, self._jobs, self._q, self._budget = tenancy, jobs, queue, budget
        self._x, self._desk, self._budgets = executors, approvals, budgets
        self._cal, self._cfg, self._now = calendar, config, clock
        self._feedback: dict[str, tuple[ValidationResult, ...]] = {}
        self._feedback_src: dict[str, str] = {}
        self._max_loops = 3

    # ------------------------------------------------------------------ helpers
    def _ctx(self, job: JobFacts, actor: str = ORCH) -> TenantContext:
        return TenantContext(job.org_id, ActorRef(actor), job.correlation_id)  # type: ignore[arg-type]

    def _task_key(self, job: JobFacts, stage: Stage, iteration: int) -> str:
        return make_idempotency_key(
            job.org_id,
            f"task.{stage.task_type}",
            [job.job_id, stage.stage_id, stage.task_type, iteration],
        )

    def _transition(
        self,
        tx: TenantTransaction,
        rec: TaskRecord,
        tid: TransitionId,
        to: TaskState,
        actor: str,
        **kw: object,
    ) -> TaskRecord:
        change = TaskTransition(
            task_id=rec.id,
            transition_id=tid,
            from_state=rec.state,
            to_state=to,
            expected_state_version=rec.state_version,
            actor=ActorRef(actor),
            **kw,  # type: ignore[arg-type]
        )
        check_task(change)
        return self._jobs.transition_task(tx, change)

    def _derive(
        self,
        tx: TenantTransaction,
        job: JobFacts,
        cause: TransitionId | None,
        outcome: JobOutcome | None = None,
        failed: TaskId | None = None,
    ) -> JobState:
        rec = _need(self._jobs.get_job(tx, JobId(job.job_id)))
        tasks = self._jobs.list_tasks(tx, JobId(job.job_id))
        d = derive_job(rec.state, [TaskView(t.state, t.is_required) for t in tasks], cause)
        if d is None:
            return rec.state
        change = JobTransition(
            job_id=rec.id,
            transition_id=d.transition_id,
            from_state=rec.state,
            to_state=d.to_state,
            expected_state_version=rec.state_version,
            actor=ORCH,
            outcome=(outcome or _outcome_of(tasks)) if d.to_state is JobState.COMPLETED else None,
            failed_task_id=failed
            or next((t.id for t in tasks if t.state is TaskState.FAILED and t.is_required), None)
            if d.transition_id is TransitionId.J08
            else None,
        )
        check_job(change)
        return self._jobs.transition_job(tx, change).state

    # ------------------------------------------------------------------ graph
    def start(self, job: JobFacts, graph: tuple[Stage, ...]) -> RunReport:
        """J02 -> T01 for the whole graph -> J03 (job already created by the intake, J01)."""
        report = RunReport(job.job_id, "RUNNING")
        with self._t.transaction(self._ctx(job)) as tx:
            rec = _need(self._jobs.get_job(tx, JobId(job.job_id)))
            change = JobTransition(
                job_id=rec.id,
                transition_id=TransitionId.J02,
                from_state=rec.state,
                to_state=JobState.VALIDATING,
                expected_state_version=rec.state_version,
                actor=ORCH,
                monetized_destination=False,
            )
            check_job(change)
            rec = self._jobs.transition_job(tx, change)
            self._create(tx, job, graph, [s.stage_id for s in graph], {}, report)
            change = JobTransition(
                job_id=rec.id,
                transition_id=TransitionId.J03,
                from_state=rec.state,
                to_state=JobState.QUEUED,
                expected_state_version=rec.state_version,
                actor=ORCH,
            )
            check_job(change)
            self._jobs.transition_job(tx, change)
        return report

    def _create(
        self,
        tx: TenantTransaction,
        job: JobFacts,
        graph: tuple[Stage, ...],
        stage_ids: Sequence[str],
        iterations: Mapping[str, int],
        report: RunReport,
    ) -> None:
        by_id = {s.stage_id: s for s in graph}
        order = [sid for sid in topological_order(graph) if sid in set(stage_ids)]
        index = {sid: i for i, sid in enumerate(order)}
        new = []
        for sid in order:
            st = by_id[sid]
            new.append(
                NewTask(
                    task_type=st.task_type,
                    agent_id=ExecutorId(st.task_type.split(".", 1)[0]),
                    iteration=iterations.get(sid, 0),
                    is_required=st.required,
                    priority=Priority.NORMAL,
                    resource_class=st.resource_class,
                    required_capabilities=st.capabilities,
                    idempotency_key=self._task_key(job, st, iterations.get(sid, 0)),  # type: ignore[arg-type]
                    payload_schema=f"{st.task_type}.input",
                    payload_schema_version="1.0.0",
                    resource_budget=self._budgets.budget_for(st),
                    max_attempts=self._cfg.max_attempts,
                    deadline=None,
                    depends_on=tuple(index[d] for d in st.depends_on if d in index),
                )
            )
        records = self._jobs.create_tasks(tx, JobId(job.job_id), new)
        for sid, rec in zip(order, records, strict=True):
            report.stages[sid] = StageRun(sid, str(rec.id), iterations.get(sid, 0), rec.state)
            report.task_stage[str(rec.id)] = sid

    def run(
        self,
        job: JobFacts,
        graph: tuple[Stage, ...],
        report: RunReport,
        limit_s: float | None = None,
        parent: Mapping[str, TaskOutput] | None = None,
    ) -> RunReport:
        topo = topological_order(graph)
        by_id = {s.stage_id: s for s in graph}
        loops: dict[str, int] = {}
        started = time.monotonic()
        while True:
            ready = [
                sid
                for sid in topo
                if report.stages[sid].state is TaskState.PENDING
                and all(
                    report.stages[d].state is TaskState.COMPLETED for d in by_id[sid].depends_on
                )
            ]
            if not ready:
                break
            sid = ready[0]
            stage = by_id[sid]
            if stage.resource_class is ResourceClass.HEAVY_CPU and not self._cal.render_allowed(
                self._now()
            ):
                report.status = "RENDER_WINDOW_CLOSED"
                report.detail = f"{sid}: the market calendar refuses rendering now"
                return report
            outcome = self._run_task(job, stage, report, parent or {})
            if outcome is not None:
                return outcome
            out = _need(report.stages[sid].output)
            if stage.gate is not None and gate_failures(out):
                end = self._on_gate_fail(job, graph, stage, out, report, loops)
                if end is not None:
                    return end
            if limit_s is not None and time.monotonic() - started > limit_s:
                report.status = "TIME_LIMIT"
                return report
        with self._t.transaction(self._ctx(job)) as tx:
            delivered = report.stages.get("s13_deliver")
            outcome_kind = (
                JobOutcome.DELIVERED
                if delivered is not None and delivered.state is TaskState.COMPLETED
                else JobOutcome.BLOCKED_COMPLIANCE
            )
            state = self._derive(tx, job, None, outcome_kind)
        report.status = outcome_kind.value if state is JobState.COMPLETED else state.value
        return report

    # ------------------------------------------------------------------ one task
    def _call(
        self,
        job: JobFacts,
        stage: Stage,
        report: RunReport,
        attempt_id: str,
        attempt_no: int,
        parent: Mapping[str, TaskOutput],
    ) -> StageCall:
        run = report.stages[stage.stage_id]
        upstream = {
            sid: r.output
            for sid, r in report.stages.items()
            if r.output is not None and r.state is TaskState.COMPLETED
        }
        upstream.update({f"parent.{k}": v for k, v in parent.items()})
        prior = report.stages.get(f"{stage.stage_id}#prior")
        return StageCall(
            job=job,
            stage=stage,
            task_id=run.task_id,
            attempt_id=attempt_id,
            attempt_no=attempt_no,
            iteration=run.iteration,
            idempotency_key=self._task_key(job, stage, run.iteration),
            resource_budget=self._budgets.budget_for(stage),
            upstream=upstream,
            prior_output=prior.output if prior is not None else None,
            revision_feedback=tuple(self._feedback.get(stage.stage_id, ())),
            revision_source_stage_id=self._feedback_src.get(stage.stage_id),
            upstream_task_ids={
                sid: r.task_id for sid, r in report.stages.items() if "#" not in sid
            },
        )

    def _run_task(
        self, job: JobFacts, stage: Stage, report: RunReport, parent: Mapping[str, TaskOutput]
    ) -> RunReport | None:
        run = report.stages[stage.stage_id]
        tid = TaskId(run.task_id)
        budget = self._budgets.budget_for(stage)
        with self._t.transaction(self._ctx(job)) as tx:
            rec = _need(self._jobs.get_task(tx, tid))
            rec = self._transition(tx, rec, TransitionId.T02, TaskState.VALIDATING, ORCH)
            if budget.max_cost_micros > 0:
                granted = self._budget.reserve(
                    tx, tid, budget.max_cost_micros, budget.currency
                ).granted
                if not granted:
                    rec = self._transition(
                        tx,
                        rec,
                        TransitionId.T05,
                        TaskState.CHECKPOINTED,
                        ORCH,
                        wait_reason=WaitReason.AWAITING_BUDGET,
                    )
                    run.state = rec.state
                    self._derive(tx, job, TransitionId.T05)
            if run.state is not TaskState.CHECKPOINTED:
                rec = self._transition(tx, rec, TransitionId.T03, TaskState.QUEUED, ORCH)
                self._enqueue(tx, job, stage, rec)
                run.state = rec.state
        if run.state is TaskState.CHECKPOINTED:
            report.status = "AWAITING_BUDGET"
            report.detail = (
                f"{stage.stage_id}: budget reservation refused (hard stop, L3 to the owner)"
            )
            return report
        return self._attempts(job, stage, report, parent)

    def _enqueue(self, tx: TenantTransaction, job: JobFacts, stage: Stage, rec: TaskRecord) -> None:
        self._q.enqueue(
            tx,
            NewQueueItem(
                task_id=rec.id,
                job_id=JobId(job.job_id),
                queue_name=_QUEUE[stage.resource_class],
                priority=Priority.NORMAL,
                resource_class=stage.resource_class,
                required_capabilities=stage.capabilities,
                scheduled_at=self._now(),
                envelope=Envelope.model_validate(
                    {
                        "org_id": job.org_id,
                        "message_id": MESSAGE.new(),
                        "sender": ORCH,
                        "receiver": stage.task_type.split(".", 1)[0],
                        "job_id": job.job_id,
                        "task_id": str(rec.id),
                        "payload_ref": {
                            "uri": f"amw-blob://{job.org_id}/jobs/{job.job_id}/tasks/{rec.id}/input.json",
                            "schema": "amw.task_input",
                            "schema_version": "1.0.0",
                            "sha256": "0" * 64,
                            "size_bytes": 2,
                            "media_type": "application/json",
                        },
                        "priority": "NORMAL",
                        "timestamp": self._now()
                        .isoformat(timespec="milliseconds")
                        .replace("+00:00", "Z"),
                        "correlation_id": job.correlation_id,
                        "schema_version": "1.0.0",
                    }
                ),
            ),
        )

    def _claim(self, stage: Stage) -> tuple[WorkerId, object]:
        worker = self._cfg.workers[stage.resource_class]
        claimed = self._q.claim(
            ClaimRequest(
                worker_id=worker,
                queue_names=(_QUEUE[stage.resource_class],),
                capabilities=self._cfg.capabilities,
                resource_classes=(stage.resource_class,),
                lease_ms=self._cfg.lease_ms,
                limit=1,
            )
        )
        if not claimed:
            raise RuntimeError(f"{stage.stage_id}: queue claim returned nothing")
        return worker, claimed[0]

    def _attempts(
        self, job: JobFacts, stage: Stage, report: RunReport, parent: Mapping[str, TaskOutput]
    ) -> RunReport | None:
        run = report.stages[stage.stage_id]
        tid = TaskId(run.task_id)
        worker_actor = stage.task_type.split(".", 1)[0]
        while True:
            worker, item = self._claim(stage)
            with self._t.transaction(self._ctx(job)) as tx:
                rec = _need(self._jobs.get_task(tx, tid))
                rec = self._transition(tx, rec, TransitionId.T07, TaskState.RUNNING, worker_actor)
                attempt = self._jobs.start_attempt(tx, tid, worker, None, False)
                self._derive(tx, job, TransitionId.T07)
            run.attempts += 1
            report.order.append(stage.stage_id + (f"#{run.iteration}" if run.iteration else ""))
            call = self._call(job, stage, report, str(attempt.id), run.attempts, parent)
            t0 = time.monotonic()
            out = self._execute(call, job, stage, worker_actor)
            run.duration_ms += int((time.monotonic() - t0) * 1000)
            with self._t.transaction(self._ctx(job, worker_actor)) as tx:
                rec = _need(self._jobs.get_task(tx, tid))
                verdict = self._judge(stage, out)
                if verdict == "SUSPENDED":
                    self._jobs.finish_attempt(
                        tx,
                        attempt.id,
                        AttemptResult.SUSPENDED,
                        run.duration_ms,
                        None,
                        out.resource_usage,
                        None,
                    )
                    rec = self._transition(
                        tx,
                        rec,
                        TransitionId.T09,
                        TaskState.CHECKPOINTED,
                        worker_actor,
                        wait_reason=out.next_action.wait_reason or WaitReason.AWAITING_APPROVAL,
                    )
                    self._q.mark_done(tx, item.queue_item_id, worker)  # type: ignore[attr-defined]
                    run.state = rec.state
                    self._derive(tx, job, TransitionId.T09)
                elif verdict == "OK":
                    self._jobs.finish_attempt(
                        tx,
                        attempt.id,
                        AttemptResult.SUCCEEDED,
                        run.duration_ms,
                        None,
                        out.resource_usage,
                        None,
                    )
                    rec = self._transition(
                        tx, rec, TransitionId.T08, TaskState.COMPLETED, worker_actor
                    )
                    self._q.mark_done(tx, item.queue_item_id, worker)  # type: ignore[attr-defined]
                    if self._budgets.budget_for(stage).max_cost_micros > 0:
                        self._budget.consume(tx, tid)
                    run.state, run.output = rec.state, out
                    self._derive(tx, job, TransitionId.T08)
                else:
                    retry = (
                        run.attempts < self._cfg.max_attempts
                        and out.error is not None
                        and out.error.retryable
                    )
                    result = AttemptResult.FAILED_RETRYABLE if retry else AttemptResult.FAILED_FINAL
                    self._jobs.finish_attempt(
                        tx, attempt.id, result, run.duration_ms, None, out.resource_usage, out.error
                    )
                    self._q.mark_done(tx, item.queue_item_id, worker)  # type: ignore[attr-defined]
                    if retry:
                        rec = self._transition(
                            tx,
                            rec,
                            TransitionId.T10,
                            TaskState.RETRY_WAIT,
                            worker_actor,
                            next_attempt_at=self._now(),
                            error=out.error,
                        )
                    else:
                        rec = self._transition(
                            tx,
                            rec,
                            TransitionId.T11,
                            TaskState.FAILED,
                            worker_actor,
                            error=out.error,
                        )
                        if self._budgets.budget_for(stage).max_cost_micros > 0:
                            self._budget.release(tx, tid)
                        run.state, run.output = rec.state, out
                        self._derive(tx, job, TransitionId.T11)
            if verdict == "OK":
                return None
            if verdict == "SUSPENDED":
                if out.next_action.wait_reason is WaitReason.AWAITING_BUDGET:
                    report.status = "AWAITING_BUDGET"
                    report.detail = (
                        f"{stage.stage_id}: budget breach during the task (hard stop, L3)"
                    )
                    return report
                return self._await_approval(job, stage, report, parent, call)
            if run.state is TaskState.FAILED:
                report.status = "FAILED"
                code = out.error.code if out.error is not None else "AGENT.INCOMPLETE_OUTPUT"
                msg = out.error.message if out.error is not None else ""
                report.detail = f"{stage.stage_id}: {code}: {msg}"
                return report
            with self._t.transaction(self._ctx(job, SCHEDULER)) as tx:  # T12 re-queue
                rec = _need(self._jobs.get_task(tx, tid))
                rec = self._transition(tx, rec, TransitionId.T12, TaskState.QUEUED, SCHEDULER)
                self._enqueue(tx, job, stage, rec)

    def _execute(self, call: StageCall, job: JobFacts, stage: Stage, agent: str) -> TaskOutput:
        meta = MeteredTask(
            job.org_id,
            job.job_id,
            call.task_id,
            call.attempt_id,
            stage.stage_id,
            agent,
            job.channel_id,
        )
        try:
            with metered_task(meta):
                if stage.task_type == APPROVAL_TASK:
                    return self._approval_output(call)
                return self._x.executor_for(stage).execute(call)
        except BudgetExhaustedError as exc:
            return _budget_stop(call, str(exc))
        except AmwError as exc:
            return _failed(exc, call, agent)

    def _judge(self, stage: Stage, out: TaskOutput) -> str:
        """03 section 5.3: SUCCEEDED + no integrity failure (+ gate results only from a gate)."""
        if out.status is OutputStatus.SUSPENDED:
            return "SUSPENDED"
        if out.status is not OutputStatus.SUCCEEDED or integrity_failures(out):
            return "FAILED"
        if has_gate_results(out) and stage.gate is None:
            return "FAILED"
        return "OK"

    # ------------------------------------------------------------------ approvals (S7)
    def _approval_output(self, call: StageCall) -> TaskOutput:
        decided = self._desk.decision(call)
        if decided is None:
            opened = self._desk.open(call)
            return _suspended(call, dict(opened))
        return _approval_done(call, dict(decided))

    def _await_approval(
        self,
        job: JobFacts,
        stage: Stage,
        report: RunReport,
        parent: Mapping[str, TaskOutput],
        call: StageCall,
    ) -> RunReport | None:
        if self._desk.decision(call) is None:
            report.status = "AWAITING_APPROVAL"
            report.detail = f"{stage.stage_id}: waiting for the owner's decision (R14 evidence)"
            return report
        run = report.stages[stage.stage_id]
        with self._t.transaction(self._ctx(job)) as tx:  # T15 resume
            rec = _need(self._jobs.get_task(tx, TaskId(run.task_id)))
            rec = self._transition(tx, rec, TransitionId.T15, TaskState.QUEUED, ORCH)
            self._enqueue(tx, job, stage, rec)
            run.state = rec.state
            self._derive(tx, job, TransitionId.T15)
        result = self._attempts(job, stage, report, parent)
        if result is None:
            out = run.output
            state = (
                (out.payload.data or {}).get("state") if out is not None and out.payload else None
            )
            if state == "REJECTED":
                self._cancel_pending(job, report, "owner rejected the final video")
                with self._t.transaction(self._ctx(job)) as tx:
                    self._derive(tx, job, None, JobOutcome.REJECTED_BY_APPROVER)
                report.status = "REJECTED_BY_APPROVER"
                return report
        return result

    # ------------------------------------------------------------------ gates
    def _on_gate_fail(
        self,
        job: JobFacts,
        graph: tuple[Stage, ...],
        stage: Stage,
        out: TaskOutput,
        report: RunReport,
        loops: dict[str, int],
    ) -> RunReport | None:
        failing = gate_failures(out)
        on_fail = _need(stage.gate).on_fail
        entry: dict[str, object] = {
            "stage_id": stage.stage_id,
            "failed": [r.check_id for r in failing],
        }
        report.gates.append(entry)
        if not isinstance(on_fail, ReviseOnFail):
            self._cancel_pending(job, report, f"gate {stage.stage_id} STOP")
            with self._t.transaction(self._ctx(job)) as tx:
                self._derive(tx, job, None, JobOutcome.BLOCKED_COMPLIANCE)
            report.status = "BLOCKED_COMPLIANCE"
            report.detail = f"{stage.stage_id}: STOP"
            return report
        topo = topological_order(graph)
        allowed = {on_fail.target_stage_id, *(on_fail.alt_target_stage_ids or ())}
        named = [r.remedy_stage_id for r in failing if r.remedy_stage_id in allowed]
        target = min(named, key=topo.index) if named else on_fail.target_stage_id
        loops[stage.stage_id] = loops.get(stage.stage_id, 0) + 1
        entry["target"] = target
        entry["loop"] = loops[stage.stage_id]
        if loops[stage.stage_id] > self._limits(graph):
            self._cancel_pending(job, report, f"revision cap reached at {stage.stage_id}")
            with self._t.transaction(self._ctx(job)) as tx:
                self._derive(tx, job, None, JobOutcome.BLOCKED_COMPLIANCE)
            report.status = "BLOCKED_COMPLIANCE"
            report.detail = f"{stage.stage_id}: max_revision_loops reached"
            return report
        # Rule 1 of 24 section 3.3: the target and every dependant that already ran get a new
        # iteration; a dependant still PENDING has read nothing stale and simply waits for the
        # new upstream task (an iteration >= 1 without a previous output would be refused by
        # Agent 09, PREVIOUS_PLAN_REF).
        affected = {
            sid
            for sid in _dependants(graph, target)
            if sid == target or report.stages[sid].state is TaskState.COMPLETED
        }
        iterations = {sid: report.stages[sid].iteration + 1 for sid in affected}
        report.revisions.append(
            {
                "gate": stage.stage_id,
                "target": target,
                "iteration": iterations[target],
                "stages": sorted(affected),
            }
        )
        for sid in affected:
            old = report.stages[sid]
            if old.output is not None:
                report.stages[f"{sid}#prior"] = old
        self._feedback = {target: tuple(failing)}
        self._feedback_src = {target: stage.stage_id}
        with self._t.transaction(self._ctx(job)) as tx:
            self._create(tx, job, graph, sorted(affected), iterations, report)
        return None

    def _limits(self, graph: tuple[Stage, ...]) -> int:
        return self._max_loops

    def set_max_revision_loops(self, value: int) -> None:
        """``limits.max_revision_loops`` of the job's registry record (24 section 3.3)."""
        self._max_loops = value

    def _cancel_pending(self, job: JobFacts, report: RunReport, reason: str) -> None:
        with self._t.transaction(self._ctx(job)) as tx:
            for sid, run in list(report.stages.items()):
                if "#" in sid or run.state is not TaskState.PENDING:
                    continue
                rec = _need(self._jobs.get_task(tx, TaskId(run.task_id)))
                rec = self._transition(
                    tx, rec, TransitionId.T19, TaskState.CANCELLED, ORCH, reason=reason
                )
                run.state = rec.state


def _need[T](value: T | None) -> T:
    """A row the runner itself created must exist (else the DB lost it: typed error)."""
    if value is None:
        raise MissingDependencyError("row not found in this tenant")
    return value


def _dependants(graph: tuple[Stage, ...], target: str) -> set[str]:
    out = {target}
    changed = True
    while changed:
        changed = False
        for s in graph:
            if s.stage_id not in out and out & set(s.depends_on):
                out.add(s.stage_id)
                changed = True
    return out


def _now_z() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _usage(currency: str = "USD") -> dict[str, object]:
    return {
        "cpu_ms": 0,
        "peak_rss_bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "tokens_cached_in": 0,
        "llm_calls": 0,
        "provider_calls": 0,
        "cost_estimate_micros": 0,
        "currency": currency,
        "cost_entry_ids": [],
    }


def _failed(exc: AmwError, call: StageCall, agent: str) -> TaskOutput:
    try:
        err = error_object_from_exception(
            exc,
            actor=agent,
            attempt_no=call.attempt_no,
            occurred_at=datetime.now(UTC),
            correlation_id=call.job.correlation_id,
        )
    except ValidationError:  # details of a non-contract shape: keep the code, drop details
        exc.details = {}
        err = error_object_from_exception(
            exc,
            actor=agent,
            attempt_no=call.attempt_no,
            occurred_at=datetime.now(UTC),
            correlation_id=call.job.correlation_id,
            extra_details={"checks": [str(exc)[:200]]},
        )
    return TaskOutput.model_validate(
        {
            "status": "FAILED",
            "payload": None,
            "output_refs": [],
            "quality_score": None,
            "confidence": None,
            "validation_results": [],
            "duration": 0,
            "resource_usage": _usage(),
            "error": err.to_doc(),
            "next_action": {
                "type": "ESCALATE",
                "wait_reason": None,
                "escalation_level": "L3",
                "reason": "stage raised a typed error",
            },
            "downstream_agent": None,
            "timestamp": _now_z(),
        }
    )


def _suspended(call: StageCall, opened: dict[str, object]) -> TaskOutput:
    return TaskOutput.model_validate(
        {
            "status": "SUSPENDED",
            "payload": {
                "payload_schema": "svc_s07.request_approval.output",
                "payload_schema_version": "1.0.0",
                "data": opened,
            },
            "output_refs": [],
            "quality_score": None,
            "confidence": None,
            "validation_results": [],
            "duration": 0,
            "resource_usage": _usage(),
            "error": None,
            "next_action": {
                "type": "WAIT",
                "wait_reason": "AWAITING_APPROVAL",
                "escalation_level": None,
                "reason": "waiting for the owner's decision",
            },
            "downstream_agent": None,
            "timestamp": _now_z(),
        }
    )


def _approval_done(call: StageCall, decided: dict[str, object]) -> TaskOutput:
    return TaskOutput.model_validate(
        {
            "status": "SUCCEEDED",
            "payload": {
                "payload_schema": "svc_s07.request_approval.output",
                "payload_schema_version": "1.0.0",
                "data": decided,
            },
            "output_refs": [],
            "quality_score": None,
            "confidence": None,
            "validation_results": [],
            "duration": 0,
            "resource_usage": _usage(),
            "error": None,
            "next_action": {
                "type": "CONTINUE",
                "wait_reason": None,
                "escalation_level": None,
                "reason": "owner decision recorded with R14 evidence",
            },
            "downstream_agent": None,
            "timestamp": _now_z(),
        }
    )


def _budget_stop(call: StageCall, reason: str) -> TaskOutput:
    return TaskOutput.model_validate(
        {
            "status": "SUSPENDED",
            "payload": None,
            "output_refs": [],
            "quality_score": None,
            "confidence": None,
            "validation_results": [],
            "duration": 0,
            "resource_usage": _usage(),
            "error": None,
            "next_action": {
                "type": "WAIT",
                "wait_reason": "AWAITING_BUDGET",
                "escalation_level": "L3",
                "reason": f"RESOURCE.BUDGET_EXHAUSTED: {reason}"[:1000],
            },
            "downstream_agent": None,
            "timestamp": _now_z(),
        }
    )


def _outcome_of(tasks: Sequence[TaskRecord]) -> JobOutcome:
    """J07 outcome: DELIVERED only when the file-delivery task completed (03 J07)."""
    delivered = any(
        t.task_type == "agent_13.file_delivery" and t.state is TaskState.COMPLETED for t in tasks
    )
    return JobOutcome.DELIVERED if delivered else JobOutcome.BLOCKED_COMPLIANCE
