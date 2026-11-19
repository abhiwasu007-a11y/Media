"""Minimal code-controlled graph runner for the 3A video graph (3A_SLICE_SPEC 3A-01 / WS-04).

Every control decision is code reading the registry record (24 section 7.1a / 7.2a) and the
task outputs; an LLM never chooses a route. Per task (03 section 11.3):

T01 create (batch, ``PgJobStore``; ``tasks.stage_id`` persisted, CCR-214) -> T02 validate -> T03
budget reservation (E1) + enqueue (``PgTaskQueue``) -> claim (``amw_queue_claim``) -> T07 +
attempt -> ``TaskExecutor`` (input builder, ``TaskWorker.run(TaskInput, ExecContext)``, payload
validation) -> T08 complete (reservation consumed, queue row DONE, input / output documents
stored) / T10-T12 retry / T11 failed. A paid call inside a worker passes E2 / ledger / E3 in the
metering wrappers. A refused reservation is T05 ``AWAITING_BUDGET`` and stops the job (3A: every
paid task is non-critical, hard stop).

J02 refusals (fail closed, J04 ``FAILED``, typed error raised): a job without ``project_id``
(``PROJECT_MISSING``), a paid stage without its configured cost budget (CCR-205), no ACTIVE
``PER_VIDEO`` budget row for the job (D9 / D10: the per-video cap is a hard stop, never assumed).

Gates (03 section 5.3 rule 4, 24 section 3.3): only a stage the record registers as a gate may
return ``gate: true`` results; a failed gate (``gate_failures``) takes ``on_fail``. ``REVISE``
picks the earliest allowed ``remedy_stage_id`` in topological order (else the primary target) and
applies the 24 section 3.3 rule 1 table (CCR-211) to the target and every stage that depends on
it, by the state of each stage's current task; the count per gate is capped by
``limits.max_revision_loops``, then the job ends ``COMPLETED / BLOCKED_COMPLIANCE``. ``STOP`` ends
the job (``BLOCKED_COMPLIANCE`` for a compliance block).

Approval stages (``svc_s07.request_approval``, an ``ApprovalWorker``) park the task
``CHECKPOINTED / AWAITING_APPROVAL`` (T09) until the ``ApprovalDesk`` reports the owner's decision
as R14 evidence; then T15 resumes it. The desk never infers a decision.

Market hours: a ``HEAVY_CPU`` task is not claimed while the calendar refuses rendering; the run
returns ``RENDER_WINDOW_CLOSED`` (the task stays ``PENDING`` / ``QUEUED``).

Crash-resume: the stage of every task is ``tasks.stage_id``; ``load`` rebuilds the stage map and
the completed outputs (read back from the stored ``output.json``) from the database, ``run``
continues. Not covered (3C hardening, listed in the PR): leases / heartbeats over long renders and
the reaper (a task found ``RUNNING`` after a crash stops the run with ``RUNNING_STALE``), and the
revision feedback of a gate that failed before the crash (kept in memory only).
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from amw_core.contracts import (
    ResourceBudget,
    Stage,
    TaskOutput,
    ValidationResult,
    gate_failures,
    has_gate_results,
    integrity_failures,
    violation,
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
from amw_core.errors import (
    AmwError,
    BudgetExhaustedError,
    ConfigInvalidError,
    InputInvalidError,
    LockConflictError,
    MissingDependencyError,
)
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
from amw_core.interfaces.job_store import JobRecord, JobTransition
from amw_core.interfaces.queue import ClaimedItem
from amw_core.state_machine import check_job, check_task, derive_job
from amw_core.state_machine.machine import TaskView
from amw_orchestrator.executor import (
    ApprovalDesk,
    BuildContext,
    JobFacts,
    PreparedTask,
    TaskExecutor,
)
from amw_orchestrator.metering import MeteredTask, metered_task
from amw_orchestrator.outputs import SpendLike, budget_stop_output, failed_output, usage_dict
from amw_orchestrator.registry import topological_order
from amw_orchestrator.task_io import StoredDoc, TaskIo

ORCH = ActorRef("agent_01")
SCHEDULER = ActorRef("sys_scheduler")
APPROVAL_TASK = "svc_s07.request_approval"
_QUEUE = {
    ResourceClass.LIGHT: QueueName.LIGHT,
    ResourceClass.AI_IO: QueueName.AI,
    ResourceClass.HEAVY_CPU: QueueName.RENDER,
    ResourceClass.PUBLISH: QueueName.PUBLISH,
}
_SAME_ITERATION_CANCEL = (
    TaskState.VALIDATING,
    TaskState.QUEUED,
    TaskState.RETRY_WAIT,
    TaskState.CHECKPOINTED,
)
"""CCR-211: cancelled (T19 ``superseded revision``) and replaced at the same iteration."""
_HUMAN_DECISION = (TaskState.FAILED, TaskState.DEAD_LETTER)
SUPERSEDED = "superseded revision"


class Calendar(Protocol):
    def render_allowed(self, dt: datetime) -> bool: ...


class BudgetPolicy(Protocol):
    def budget_for(self, stage: Stage) -> ResourceBudget: ...

    def validate(self, graph: Sequence[Stage]) -> None:
        """J02: raise ``ConfigInvalidError`` when a paid stage has no configured budget."""
        ...


class SpendReader(Protocol):
    def spend_of(self, attempt_id: str) -> Sequence[SpendLike]: ...


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
    wait_reason: WaitReason | None = None
    key: str = ""
    """The task's stored idempotency key (the Task Input carries exactly this value)."""


@dataclass
class RunReport:
    job_id: str
    status: str
    """DELIVERED / BLOCKED_COMPLIANCE / FAILED / AWAITING_BUDGET / RENDER_WINDOW_CLOSED /
    AWAITING_APPROVAL / REJECTED_BY_APPROVER / AWAITING_DLQ_DECISION / RUNNING_STALE."""
    order: list[str] = field(default_factory=list)
    """Stage IDs in execution order (iteration suffix ``#n`` for n > 0)."""
    gates: list[dict[str, object]] = field(default_factory=list)
    revisions: list[dict[str, object]] = field(default_factory=list)
    stages: dict[str, StageRun] = field(default_factory=dict)
    task_stage: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    detail: str = ""


class GraphRunner:
    def __init__(
        self,
        *,
        tenancy: TenancyContext,
        jobs: JobStore,
        queue: TaskQueue,
        budget: BudgetGuard,
        executor: TaskExecutor,
        approvals: ApprovalDesk,
        budgets: BudgetPolicy,
        calendar: Calendar,
        config: RunnerConfig,
        task_io: TaskIo,
        spend: SpendReader | None = None,
        require_per_video: Callable[[TenantTransaction, str, str], object] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._t, self._jobs, self._q, self._budget = tenancy, jobs, queue, budget
        self._x, self._desk, self._budgets = executor, approvals, budgets
        self._cal, self._cfg, self._now = calendar, config, clock
        self._io, self._spend, self._per_video = task_io, spend, require_per_video
        self._feedback: dict[str, tuple[ValidationResult, ...]] = {}
        self._feedback_src: dict[str, str] = {}
        self._max_loops = 3

    # ------------------------------------------------------------------ helpers
    def _ctx(self, job: JobFacts, actor: str = ORCH) -> TenantContext:
        return TenantContext(job.org_id, ActorRef(actor), job.correlation_id)  # type: ignore[arg-type]

    def _task_key(self, job: JobFacts, stage: Stage, iteration: int, generation: int = 0) -> str:
        """03 section 9 ``task.<task_type>`` key. A task that replaces a cancelled one at the same
        iteration (CCR-211) would repeat the key and hit ``UNIQUE (org_id, idempotency_key)``;
        ``generation`` (the number of cancelled tasks of that stage and iteration) is appended
        only then, so every first-generation key is exactly the contract key (CCR-275
        provisional default, see the PR)."""
        parts: list[str | int] = [job.job_id, stage.stage_id, stage.task_type, iteration]
        if generation:
            parts.append(generation)
        return make_idempotency_key(job.org_id, f"task.{stage.task_type}", parts)

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
        """J02 -> (validation) -> T01 for the whole graph -> J03; the job exists (J01, intake).

        A failed validation ends the job with J04 and raises the typed error (the J04 row is
        committed first): no project, an unconfigured paid stage, no PER_VIDEO budget row."""
        report = RunReport(job.job_id, "RUNNING")
        refusal: AmwError | None = None
        with self._t.transaction(self._ctx(job)) as tx:
            rec = _need(self._jobs.get_job(tx, JobId(job.job_id)))
            rec = self._job_step(tx, rec, TransitionId.J02, JobState.VALIDATING)
            try:
                self._validate_job(tx, job, graph)
            except AmwError as exc:
                refusal = exc
                self._job_step(
                    tx, rec, TransitionId.J04, JobState.FAILED, reason=f"{exc.code}"[:200]
                )
            else:
                self._create(tx, job, graph, [s.stage_id for s in graph], {}, report)
                self._job_step(tx, rec, TransitionId.J03, JobState.QUEUED)
        if refusal is not None:
            report.status = "FAILED"
            report.detail = f"J02 refused: {refusal.code}"
            raise refusal
        return report

    def _job_step(
        self,
        tx: TenantTransaction,
        rec: JobRecord,
        tid: TransitionId,
        to: JobState,
        reason: str | None = None,
    ) -> JobRecord:
        change = JobTransition(
            job_id=rec.id,
            transition_id=tid,
            from_state=rec.state,
            to_state=to,
            expected_state_version=rec.state_version,
            actor=ORCH,
            monetized_destination=False if tid is TransitionId.J02 else None,
            reason=reason,
        )
        check_job(change)
        return self._jobs.transition_job(tx, change)

    def _validate_job(self, tx: TenantTransaction, job: JobFacts, graph: tuple[Stage, ...]) -> None:
        if not job.project_id:
            raise InputInvalidError(
                "a production job needs its project",
                details={"violations": [violation("PROJECT_MISSING", "/project_id")]},
            )
        self._budgets.validate(graph)
        if self._per_video is not None:
            self._per_video(tx, job.job_id, job.currency)
        elif any(self._budgets.budget_for(s).max_cost_micros > 0 for s in graph):
            # a paid graph with no per-video check wired is a configuration error (fail closed)
            raise ConfigInvalidError(
                "the per-video budget check is not wired: no paid run without the cap",
                details={"violations": [violation("PER_VIDEO_CHECK_UNWIRED", "/budgets")]},
            )

    def _create(
        self,
        tx: TenantTransaction,
        job: JobFacts,
        graph: tuple[Stage, ...],
        stage_ids: Sequence[str],
        iterations: Mapping[str, int],
        report: RunReport,
        generations: Mapping[str, int] | None = None,
    ) -> Mapping[str, TaskRecord]:
        """T01 for ``stage_ids`` (a whole graph or a revision batch). Edges inside the batch are
        written by ``create_tasks``; an edge to a stage outside the batch cannot be expressed by
        the JobStore interface (CCR-274 provisional, see the PR): the runner's graph is the truth
        for readiness, the database edges are informational (T02 guard)."""
        by_id = {s.stage_id: s for s in graph}
        wanted = set(stage_ids)
        order = [sid for sid in topological_order(graph) if sid in wanted]
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
                    idempotency_key=self._task_key(  # type: ignore[arg-type]
                        job, st, iterations.get(sid, 0), (generations or {}).get(sid, 0)
                    ),
                    payload_schema=f"{st.task_type}.input",
                    payload_schema_version="1.0.0",
                    resource_budget=self._budgets.budget_for(st),
                    max_attempts=self._cfg.max_attempts,
                    deadline=None,
                    depends_on=tuple(index[d] for d in st.depends_on if d in index),
                    stage_id=sid,
                )
            )
        records = self._jobs.create_tasks(tx, JobId(job.job_id), new)
        made: dict[str, TaskRecord] = {}
        for sid, rec in zip(order, records, strict=True):
            report.stages[sid] = StageRun(
                sid, str(rec.id), iterations.get(sid, 0), rec.state, key=str(rec.idempotency_key)
            )
            report.task_stage[str(rec.id)] = sid
            made[sid] = rec
        return made

    # ------------------------------------------------------------------ resume
    def load(self, job: JobFacts, graph: tuple[Stage, ...]) -> RunReport:
        """Rebuild the stage map from ``tasks.stage_id`` (crash-resume, CCR-214 (a)): per stage the
        live task of the highest iteration, the completed outputs read back from storage and the
        previous iteration's output (``PRIOR_OUTPUT``)."""
        report = RunReport(job.job_id, "RUNNING")
        wanted = {s.stage_id for s in graph}
        with self._t.transaction(self._ctx(job)) as tx:
            tasks = [t for t in self._jobs.list_tasks(tx, JobId(job.job_id)) if t.stage_id]
            by_stage: dict[str, list[TaskRecord]] = {}
            for t in tasks:
                if t.stage_id in wanted:
                    by_stage.setdefault(str(t.stage_id), []).append(t)
            for sid, rows in by_stage.items():
                live = [t for t in rows if t.state is not TaskState.CANCELLED]
                if not live:
                    continue
                cur = max(live, key=lambda t: t.iteration)
                run = StageRun(sid, str(cur.id), cur.iteration, cur.state, None, cur.attempt_count)
                run.wait_reason, run.key = cur.wait_reason, str(cur.idempotency_key)
                if cur.state is TaskState.COMPLETED:
                    run.output = self._read_output(tx, job, cur)
                if cur.iteration > 0:
                    prev = next(
                        (
                            t
                            for t in rows
                            if t.iteration == cur.iteration - 1 and t.state is TaskState.COMPLETED
                        ),
                        None,
                    )
                    if prev is not None:
                        report.stages[f"{sid}#prior"] = StageRun(
                            sid,
                            str(prev.id),
                            prev.iteration,
                            prev.state,
                            self._read_output(tx, job, prev),
                        )
                report.stages[sid] = run
                report.task_stage[str(cur.id)] = sid
        missing = wanted - {k for k in report.stages if "#" not in k}
        if missing:
            raise MissingDependencyError(
                "the job has no live task for stages of its graph",
                details={
                    "violations": [
                        violation("STAGE_TASK_MISSING", f"/{m}") for m in sorted(missing)
                    ]
                },
            )
        return report

    def _read_output(self, tx: TenantTransaction, job: JobFacts, rec: TaskRecord) -> TaskOutput:
        return self._io.get_output(
            TenantContext(job.org_id, ORCH, job.correlation_id),  # type: ignore[arg-type]
            rec.output_ref or "",
            rec.output_sha256 or "",
        )

    # ------------------------------------------------------------------ run loop
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
            blocked = self._blocked(report, by_id, topo)
            if blocked is not None:
                return blocked
            ready = [
                sid
                for sid in topo
                if report.stages[sid].state in _RUNNABLE
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

    def _blocked(
        self, report: RunReport, by_id: Mapping[str, Stage], topo: Sequence[str]
    ) -> RunReport | None:
        """A resumed job can hold tasks the loop must not touch: stop with a stated reason."""
        for sid in topo:
            run = report.stages[sid]
            if run.state is TaskState.RUNNING:
                report.status = "RUNNING_STALE"
                report.detail = f"{sid}: task found RUNNING (lease / reaper is 3C hardening)"
                return report
            if run.state in _HUMAN_DECISION:
                report.status = (
                    "FAILED" if run.state is TaskState.FAILED else "AWAITING_DLQ_DECISION"
                )
                report.detail = f"{sid}: {run.state.value}, waits for the human DLQ decision"
                return report
            if run.state is TaskState.CHECKPOINTED and (
                run.wait_reason is WaitReason.AWAITING_BUDGET
            ):
                report.status = "AWAITING_BUDGET"
                report.detail = f"{sid}: budget hard stop (L3 to the owner)"
                return report
        return None

    # ------------------------------------------------------------------ one task
    def _bc(
        self,
        job: JobFacts,
        stage: Stage,
        report: RunReport,
        attempt_no: int,
        parent: Mapping[str, TaskOutput],
    ) -> BuildContext:
        run = report.stages[stage.stage_id]
        upstream = {
            sid: r.output
            for sid, r in report.stages.items()
            if "#" not in sid and r.output is not None and r.state is TaskState.COMPLETED
        }
        upstream.update({f"parent.{k}": v for k, v in parent.items()})
        prior = report.stages.get(f"{stage.stage_id}#prior")
        return BuildContext(
            job=job,
            stage=stage,
            task_id=run.task_id,
            iteration=run.iteration,
            attempt_no=attempt_no,
            idempotency_key=run.key,
            resource_budget=self._budgets.budget_for(stage),
            upstream=upstream,
            upstream_task_ids={
                sid: r.task_id for sid, r in report.stages.items() if "#" not in sid
            },
            prior_output=prior.output if prior is not None else None,
            revision_feedback=tuple(self._feedback.get(stage.stage_id, ())),
            revision_source_stage_id=self._feedback_src.get(stage.stage_id),
        )

    def _run_task(
        self, job: JobFacts, stage: Stage, report: RunReport, parent: Mapping[str, TaskOutput]
    ) -> RunReport | None:
        run = report.stages[stage.stage_id]
        tid = TaskId(run.task_id)
        if run.state is TaskState.CHECKPOINTED:  # parked approval (resume)
            return self._await_approval(job, stage, report, parent)
        if run.state is TaskState.RETRY_WAIT:  # crash between T10 and T12
            with self._t.transaction(self._ctx(job, SCHEDULER)) as tx:
                rec = _need(self._jobs.get_task(tx, tid))
                rec = self._transition(tx, rec, TransitionId.T12, TaskState.QUEUED, SCHEDULER)
                self._enqueue(tx, job, stage, rec)
                run.state = rec.state
        elif run.state in (TaskState.PENDING, TaskState.VALIDATING):
            outcome = self._admit(job, stage, report, run, tid)
            if outcome is not None:
                return outcome
        return self._attempts(job, stage, report, parent)

    def _admit(
        self, job: JobFacts, stage: Stage, report: RunReport, run: StageRun, tid: TaskId
    ) -> RunReport | None:
        budget = self._budgets.budget_for(stage)
        with self._t.transaction(self._ctx(job)) as tx:
            rec = _need(self._jobs.get_task(tx, tid))
            if rec.state is TaskState.PENDING:
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
        return None

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

    def _claim(self, stage: Stage, task_id: str) -> tuple[WorkerId, ClaimedItem]:
        """Claim the queue row. ``amw_queue_claim`` is cross-tenant and not keyed by task, so the
        runner only proceeds when the claimed row IS this task's. A foreign row is handed back at
        once (its lease is cut to 1 ms; nothing of it runs) and the claim fails with
        ``TEMPORARY.LOCK_CONFLICT`` (retryable): this driver expects to be the only consumer of
        its queues until the worker pool of 3C exists."""
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
            raise MissingDependencyError(
                "no queue row for the task",
                details={"violations": [violation("CLAIM_EMPTY", f"/{stage.stage_id}")]},
            )
        item = claimed[0]
        if str(item.task_id) != task_id:
            self._q.heartbeat(item.queue_item_id, worker, 1)
            raise LockConflictError(
                "the queue returned another task's row",
                details={"violations": [violation("CLAIM_FOREIGN_ROW", "/queue")]},
            )
        return worker, item

    def _attempts(
        self, job: JobFacts, stage: Stage, report: RunReport, parent: Mapping[str, TaskOutput]
    ) -> RunReport | None:
        run = report.stages[stage.stage_id]
        tid = TaskId(run.task_id)
        worker_actor = stage.task_type.split(".", 1)[0]
        while True:
            worker, item = self._claim(stage, run.task_id)
            with self._t.transaction(self._ctx(job)) as tx:
                rec = _need(self._jobs.get_task(tx, tid))
                rec = self._transition(tx, rec, TransitionId.T07, TaskState.RUNNING, worker_actor)
                attempt = self._jobs.start_attempt(tx, tid, worker, None, False)
                self._derive(tx, job, TransitionId.T07)
                attempt_no = attempt.attempt_no
            run.attempts = attempt_no
            report.order.append(stage.stage_id + (f"#{run.iteration}" if run.iteration else ""))
            bc = self._bc(job, stage, report, attempt_no, parent)
            t0 = time.monotonic()
            input_doc, out = self._execute(bc, job, stage, worker_actor, str(attempt.id))
            run.duration_ms += int((time.monotonic() - t0) * 1000)
            stored_out = self._io.put_output(
                self._ctx(job, worker_actor), job.job_id, run.task_id, str(attempt.id), out
            )
            doc_fields: dict[str, object] = {
                "output_ref": stored_out.uri,
                "output_sha256": stored_out.sha256,
            }
            if input_doc is not None:
                doc_fields.update(
                    input_ref=input_doc.uri,
                    input_sha256=input_doc.sha256,
                    input_schema_version="1.0.0",
                )
            with self._t.transaction(self._ctx(job, worker_actor)) as tx:
                rec = _need(self._jobs.get_task(tx, tid))
                verdict = self._judge(stage, out)
                if verdict == "SUSPENDED":
                    self._jobs.finish_attempt(
                        tx,
                        attempt.id,
                        AttemptResult.SUSPENDED,
                        run.duration_ms,
                        stored_out.uri,
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
                        **doc_fields,
                    )
                    self._q.mark_done(tx, item.queue_item_id, worker)
                    run.state, run.wait_reason = rec.state, rec.wait_reason
                    self._derive(tx, job, TransitionId.T09)
                elif verdict == "OK":
                    self._jobs.finish_attempt(
                        tx,
                        attempt.id,
                        AttemptResult.SUCCEEDED,
                        run.duration_ms,
                        stored_out.uri,
                        out.resource_usage,
                        None,
                    )
                    rec = self._transition(
                        tx,
                        rec,
                        TransitionId.T08,
                        TaskState.COMPLETED,
                        worker_actor,
                        **doc_fields,
                    )
                    self._q.mark_done(tx, item.queue_item_id, worker)
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
                        tx,
                        attempt.id,
                        result,
                        run.duration_ms,
                        stored_out.uri,
                        out.resource_usage,
                        out.error,
                    )
                    self._q.mark_done(tx, item.queue_item_id, worker)
                    if retry:
                        rec = self._transition(
                            tx,
                            rec,
                            TransitionId.T10,
                            TaskState.RETRY_WAIT,
                            worker_actor,
                            next_attempt_at=self._now(),
                            error=out.error,
                            **doc_fields,
                        )
                    else:
                        rec = self._transition(
                            tx,
                            rec,
                            TransitionId.T11,
                            TaskState.FAILED,
                            worker_actor,
                            error=out.error,
                            **doc_fields,
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
                return self._await_approval(job, stage, report, parent)
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

    def _execute(
        self, bc: BuildContext, job: JobFacts, stage: Stage, agent: str, attempt_id: str
    ) -> tuple[StoredDoc | None, TaskOutput]:
        """Build, store the Task Input, run the worker. Typed errors become failed outputs that
        carry the real spend of the attempt."""
        meta = MeteredTask(
            job.org_id,
            job.job_id,
            bc.task_id,
            attempt_id,
            stage.stage_id,
            agent,
            job.channel_id,
        )
        stored: StoredDoc | None = None
        try:
            with metered_task(meta):
                prepared: PreparedTask = self._x.prepare(bc, attempt_id)
                stored = self._io.put_input(
                    self._ctx(job, agent), job.job_id, bc.task_id, attempt_id, prepared.task_input
                )
                return stored, self._x.run(prepared)
        except BudgetExhaustedError as exc:
            return stored, budget_stop_output(str(exc), self._usage(attempt_id, job.currency))
        except AmwError as exc:
            return stored, failed_output(
                exc,
                actor=agent,
                attempt_no=bc.attempt_no,
                correlation_id=job.correlation_id,
                usage=self._usage(attempt_id, job.currency),
            )

    def _usage(self, attempt_id: str, currency: str) -> dict[str, object]:
        spend = self._spend.spend_of(attempt_id) if self._spend is not None else ()
        return usage_dict(spend, currency)

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
    def _await_approval(
        self, job: JobFacts, stage: Stage, report: RunReport, parent: Mapping[str, TaskOutput]
    ) -> RunReport | None:
        run = report.stages[stage.stage_id]
        if not self._desk.decided(job.job_id, run.task_id):
            report.status = "AWAITING_APPROVAL"
            report.detail = f"{stage.stage_id}: waiting for the owner's decision (R14 evidence)"
            return report
        with self._t.transaction(self._ctx(job)) as tx:  # T15 resume
            rec = _need(self._jobs.get_task(tx, TaskId(run.task_id)))
            rec = self._transition(tx, rec, TransitionId.T15, TaskState.QUEUED, ORCH)
            self._enqueue(tx, job, stage, rec)
            run.state, run.wait_reason = rec.state, None
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
        waiting = self._revise(job, graph, stage, target, failing, report)
        if waiting is not None:
            entry["waits_for_dlq"] = waiting
            report.status = "AWAITING_DLQ_DECISION"
            report.detail = (
                f"{stage.stage_id}: revision of {target} waits for the human decision on {waiting}"
            )
            return report
        return None

    def _revise(
        self,
        job: JobFacts,
        graph: tuple[Stage, ...],
        gate: Stage,
        target: str,
        failing: Sequence[ValidationResult],
        report: RunReport,
    ) -> str | None:
        """24 section 3.3 rule 1 (CCR-211), by the state of each affected stage's current task:

        ``COMPLETED``                                  new task at n + 1 (``PRIOR_OUTPUT``)
        ``PENDING``                                    kept; its dependencies are re-pointed
        ``VALIDATING`` / ``QUEUED`` / ``RETRY_WAIT`` / ``CHECKPOINTED``
                                                       T19 ``superseded revision``; replaced at the
                                                       same iteration
        ``RUNNING``                                    cancel requested, acknowledged (T20), then as
                                                       above
        ``FAILED`` / ``DEAD_LETTER``                   not touched; the whole revision waits for the
                                                       human decision (returns that stage id)

        Returns the stage a human must decide on, else ``None`` once the revision is created."""
        by_id = {s.stage_id: s for s in graph}
        order = [sid for sid in topological_order(graph) if sid in _dependants(graph, target)]
        with self._t.transaction(self._ctx(job)) as tx:
            current = {
                sid: _need(self._jobs.get_task(tx, TaskId(report.stages[sid].task_id)))
                for sid in order
            }
            for sid in order:
                if current[sid].state in _HUMAN_DECISION:
                    return sid
            replace: dict[str, int] = {}
            keep: list[str] = []
            for sid in order:
                rec = current[sid]
                if rec.state is TaskState.COMPLETED:
                    replace[sid] = rec.iteration + 1
                elif rec.state is TaskState.PENDING:
                    keep.append(sid)
                else:
                    self._supersede(tx, job, by_id[sid], rec)
                    replace[sid] = rec.iteration
            for sid in replace:
                old = report.stages[sid]
                if old.output is not None and old.state is TaskState.COMPLETED:
                    report.stages[f"{sid}#prior"] = StageRun(
                        old.stage_id, old.task_id, old.iteration, old.state, old.output
                    )
            old_ids = {sid: current[sid].id for sid in order}
            every = self._jobs.list_tasks(tx, JobId(job.job_id))
            generations = {
                sid: sum(1 for t in every if t.stage_id == sid and t.iteration == n)
                for sid, n in replace.items()
            }
            made = self._create(tx, job, graph, list(replace), replace, report, generations)
            for sid in keep:  # PENDING dependants: same task, edges moved to the new upstream task
                pending = current[sid]
                for dep in by_id[sid].depends_on:
                    if dep in made and dep in old_ids:
                        try:
                            self._jobs.repoint_dependency(
                                tx, pending.id, old_ids[dep], made[dep].id
                            )
                        except MissingDependencyError:
                            report.notes.append(
                                f"{sid}: no database edge to {dep} to re-point (CCR-274); "
                                "the graph decides readiness"
                            )
        report.revisions.append(
            {
                "gate": gate.stage_id,
                "target": target,
                "iteration": replace.get(target),
                "stages": sorted(replace),
                "kept": sorted(keep),
            }
        )
        self._feedback = {target: tuple(failing)}
        self._feedback_src = {target: gate.stage_id}
        return None

    def _supersede(
        self, tx: TenantTransaction, job: JobFacts, stage: Stage, rec: TaskRecord
    ) -> None:
        """Cancel a live task whose revision replaces it at the same iteration (T19 / T20)."""
        tid = rec.id
        if rec.state is TaskState.RUNNING:
            self._jobs.request_cancel(tx, tid, SUPERSEDED)
            rec = _need(self._jobs.get_task(tx, tid))
            self._transition(
                tx, rec, TransitionId.T20, TaskState.CANCELLED, ORCH, reason=SUPERSEDED
            )
        else:
            self._transition(
                tx, rec, TransitionId.T19, TaskState.CANCELLED, ORCH, reason=SUPERSEDED
            )
        self._q.cancel_for_task(tx, tid)
        if self._budgets.budget_for(stage).max_cost_micros > 0:
            self._budget.release(tx, tid)
        self._derive(tx, job, TransitionId.T19)

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


_RUNNABLE = (
    TaskState.PENDING,
    TaskState.VALIDATING,
    TaskState.QUEUED,
    TaskState.RETRY_WAIT,
    TaskState.CHECKPOINTED,
)
"""States from which the loop (re)enters a task: a fresh one, or one found after a crash."""


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


def _outcome_of(tasks: Sequence[TaskRecord]) -> JobOutcome:
    """J07 outcome: DELIVERED only when the file-delivery task completed (03 J07)."""
    delivered = any(
        t.task_type == "agent_13.file_delivery" and t.state is TaskState.COMPLETED for t in tasks
    )
    return JobOutcome.DELIVERED if delivered else JobOutcome.BLOCKED_COMPLIANCE
