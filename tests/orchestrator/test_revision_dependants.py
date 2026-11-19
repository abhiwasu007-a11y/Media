# ruff: noqa: PT018
"""24 section 3.3 rule 1 (CCR-211): revision by the state of each dependant's current task, one case
per row of the table, on the real PostgreSQL tables; plus a full-graph REVISE loop through the
runner (new iterations, PENDING dependants kept and re-pointed, PRIOR_OUTPUT, loop cap)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from amw_core.contracts import Stage, error_object_from_exception
from amw_core.enums import ResourceClass, TaskState, TransitionId, WaitReason
from amw_core.errors import AgentCrashError
from amw_core.ids import ActorRef, JobId, TaskId
from amw_core.interfaces import TenantContext
from amw_orchestrator.driver import ORCH, RunReport
from amw_orchestrator.executor import JobFacts
from amw_orchestrator.registry import job_graph
from tests.orchestrator.world import LONG, Rig, build_rig, db_rows, gate_fail

pytestmark = pytest.mark.integration
TT = {
    "r1": "agent_04.research_pack",
    "r2": "agent_05.script_draft",
    "r3": "agent_09.shot_plan",
    "r4": "agent_11.thumbnail_variants",
}


def _stage(sid: str, deps: list[str], gate: bool = False) -> Stage:
    return Stage.model_validate(
        {
            "stage_id": sid,
            "task_type": TT[sid],
            "required": True,
            "resource_class": "LIGHT",
            "capabilities": [],
            "depends_on": deps,
            "gate": {"blocking": True, "on_fail": {"action": "REVISE", "target_stage_id": "r1"}}
            if gate
            else None,
            "approval": None,
        }
    )


GRAPH = (_stage("r1", []), _stage("r2", ["r1"]), _stage("r3", ["r2"]), _stage("r4", ["r3"], True))
PATHS: dict[str, tuple[TransitionId, ...]] = {
    "VALIDATING": (TransitionId.T02,),
    "QUEUED": (TransitionId.T02, TransitionId.T03),
    "RUNNING": (TransitionId.T02, TransitionId.T03, TransitionId.T07),
    "RETRY_WAIT": (TransitionId.T02, TransitionId.T03, TransitionId.T07, TransitionId.T10),
    "CHECKPOINTED": (TransitionId.T02, TransitionId.T03, TransitionId.T07, TransitionId.T09),
    "COMPLETED": (TransitionId.T02, TransitionId.T03, TransitionId.T07, TransitionId.T08),
    "FAILED": (TransitionId.T02, TransitionId.T03, TransitionId.T07, TransitionId.T11),
}
TO = {
    TransitionId.T02: TaskState.VALIDATING,
    TransitionId.T03: TaskState.QUEUED,
    TransitionId.T07: TaskState.RUNNING,
    TransitionId.T08: TaskState.COMPLETED,
    TransitionId.T09: TaskState.CHECKPOINTED,
    TransitionId.T10: TaskState.RETRY_WAIT,
    TransitionId.T11: TaskState.FAILED,
}


def force(rig: Rig, job: JobFacts, report: RunReport, sid: str, state: str) -> None:
    """Drive one task to ``state`` through the real transitions, queue claim and attempt (no SQL
    shortcuts), exactly as the runner does."""
    run = report.stages[sid]
    stage = next(s for s in GRAPH if s.stage_id == sid)
    actor = TT[sid].split(".", 1)[0]
    ctx = TenantContext(job.org_id, ORCH, job.correlation_id)  # type: ignore[arg-type]
    worker = rig.seed.workers[ResourceClass.LIGHT]
    item = None
    for tid in PATHS[state]:
        if tid is TransitionId.T07:
            worker, item = rig.runner._claim(stage, run.task_id)
        with rig.tenancy.transaction(ctx) as tx:
            rec = rig.jobs.get_task(tx, TaskId(run.task_id))
            assert rec is not None
            kw: dict[str, Any] = {}
            if tid is TransitionId.T09:
                kw["wait_reason"] = WaitReason.AWAITING_APPROVAL
            if tid in (TransitionId.T10, TransitionId.T11):
                kw["error"] = error_object_from_exception(
                    AgentCrashError("scripted"),
                    actor=actor,
                    attempt_no=1,
                    occurred_at=datetime.now(UTC),
                    correlation_id=job.correlation_id,
                )
            if tid is TransitionId.T10:
                kw["next_attempt_at"] = datetime.now(UTC)
            who = actor if tid in WORKER_STEPS else "agent_01"
            rec = rig.runner._transition(tx, rec, tid, TO[tid], who, **kw)
            if tid is TransitionId.T03:
                rig.runner._enqueue(tx, job, stage, rec)
            if tid is TransitionId.T07:
                rig.jobs.start_attempt(tx, rec.id, worker, None, False)
            rig.runner._derive(tx, job, tid)
            if tid in WORKER_STEPS - {TransitionId.T07} and item is not None:
                rig.queue.mark_done(tx, item.queue_item_id, worker)
    run.state = TO[PATHS[state][-1]]


WORKER_STEPS = {
    TransitionId.T07,
    TransitionId.T08,
    TransitionId.T09,
    TransitionId.T10,
    TransitionId.T11,
}


def _tasks(dsn: str) -> list[tuple[str, int, str, str | None]]:
    return [
        (r[0], r[1], r[2], r[3])
        for r in db_rows(
            dsn,
            "SELECT stage_id, iteration, state, cancel_reason FROM tasks WHERE job_id ="
            " (SELECT id FROM jobs ORDER BY created_at DESC LIMIT 1) ORDER BY stage_id,"
            " iteration, state",
        )
    ]


def _setup(pg_dsn: str, tmp_path: Path, r2_state: str) -> tuple[Rig, JobFacts, RunReport]:
    rig = build_rig(pg_dsn, tmp_path, graph=GRAPH, paid={})
    job = rig.intake()
    report = rig.runner.start(job, GRAPH)
    force(rig, job, report, "r1", "COMPLETED")
    if r2_state != "PENDING":
        force(rig, job, report, "r2", r2_state)
    return rig, job, report


def _revise(rig: Rig, job: JobFacts, report: RunReport) -> str | None:
    return rig.runner._revise(job, GRAPH, GRAPH[3], "r1", (), report)


@pytest.mark.parametrize("state", ["COMPLETED"])
def test_completed_dependant_gets_a_new_iteration_and_pending_ones_are_kept(
    pg_dsn: str, tmp_path: Path, state: str
) -> None:
    rig, job, report = _setup(pg_dsn, tmp_path, state)
    old_r3 = report.stages["r3"].task_id
    assert _revise(rig, job, report) is None
    rows = _tasks(pg_dsn)
    assert ("r1", 0, "COMPLETED", None) in rows and ("r1", 1, "PENDING", None) in rows
    assert ("r2", 0, "COMPLETED", None) in rows and ("r2", 1, "PENDING", None) in rows
    assert [r for r in rows if r[0] == "r3"] == [("r3", 0, "PENDING", None)]  # kept, not recreated
    assert report.stages["r3"].task_id == old_r3
    with rig.tenancy.transaction(TenantContext(job.org_id, ORCH, job.correlation_id)) as tx:  # type: ignore[arg-type]
        deps = rig.jobs.dependencies(tx, TaskId(old_r3))
    assert [str(d) for d in deps] == [report.stages["r2"].task_id]  # re-pointed to the new r2
    assert report.revisions[0]["kept"] == ["r3", "r4"]


def test_pending_dependant_is_kept_and_repointed(pg_dsn: str, tmp_path: Path) -> None:
    rig, job, report = _setup(pg_dsn, tmp_path, "PENDING")
    old_r2 = report.stages["r2"].task_id
    assert _revise(rig, job, report) is None
    rows = _tasks(pg_dsn)
    assert [r for r in rows if r[0] == "r2"] == [("r2", 0, "PENDING", None)]
    assert [r for r in rows if r[0] == "r1"] == [
        ("r1", 0, "COMPLETED", None),
        ("r1", 1, "PENDING", None),
    ]
    with rig.tenancy.transaction(TenantContext(job.org_id, ORCH, job.correlation_id)) as tx:  # type: ignore[arg-type]
        deps = rig.jobs.dependencies(tx, TaskId(old_r2))
    assert [str(d) for d in deps] == [report.stages["r1"].task_id]
    assert report.stages["r1"].iteration == 1


@pytest.mark.parametrize("state", ["VALIDATING", "QUEUED", "RETRY_WAIT", "CHECKPOINTED", "RUNNING"])
def test_live_dependant_is_cancelled_and_replaced_at_the_same_iteration(
    pg_dsn: str, tmp_path: Path, state: str
) -> None:
    rig, job, report = _setup(pg_dsn, tmp_path, state)
    assert _revise(rig, job, report) is None
    r2 = [r[:3] for r in _tasks(pg_dsn) if r[0] == "r2"]
    assert ("r2", 0, "CANCELLED") in r2
    assert ("r2", 0, "PENDING") in r2  # replaced at the SAME iteration (n, not n + 1)
    moved = db_rows(
        pg_dsn,
        "SELECT s.transition_id FROM state_transitions s JOIN tasks t ON t.id = s.entity_id"
        " WHERE t.stage_id = 'r2' AND s.to_state = 'CANCELLED' AND t.job_id ="
        " (SELECT id FROM jobs ORDER BY created_at DESC LIMIT 1)",
    )
    assert moved == [("T20" if state == "RUNNING" else "T19",)]
    assert report.stages["r2"].iteration == 0 and report.stages["r2"].state is TaskState.PENDING


def test_failed_dependant_waits_for_the_human_decision(pg_dsn: str, tmp_path: Path) -> None:
    rig, job, report = _setup(pg_dsn, tmp_path, "FAILED")
    before = _tasks(pg_dsn)
    assert _revise(rig, job, report) == "r2"
    assert _tasks(pg_dsn) == before  # nothing touched, nothing created
    assert not report.revisions


def test_invariant_iteration_n_needs_n_minus_one_completed(pg_dsn: str, tmp_path: Path) -> None:
    rig, job, report = _setup(pg_dsn, tmp_path, "QUEUED")
    _revise(rig, job, report)
    rows = db_rows(
        pg_dsn,
        "SELECT t.stage_id, t.iteration FROM tasks t WHERE t.job_id ="
        " (SELECT id FROM jobs ORDER BY created_at DESC LIMIT 1) AND t.iteration > 0 AND"
        " t.state <> 'CANCELLED' AND NOT EXISTS (SELECT 1 FROM tasks p WHERE p.job_id = t.job_id"
        " AND p.stage_id = t.stage_id AND p.iteration = t.iteration - 1 AND p.state = 'COMPLETED')",
    )
    assert rows == []


def test_full_graph_revise_loop_runs_to_delivery(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    rig.world.fail_gate["s10_qc"] = [[gate_fail("qc.loudness", "s10_render")]]
    job = rig.intake()
    graph = job_graph(LONG)
    report = rig.runner.run(job, graph, rig.runner.start(job, graph))
    assert report.status == "AWAITING_APPROVAL"
    rig.desk.decisions.add(report.stages["a_final"].task_id)
    report = rig.runner.run(job, graph, report)
    assert report.status == "DELIVERED", report.detail
    assert report.revisions[0]["target"] == "s10_render"
    stages, kept = report.revisions[0]["stages"], report.revisions[0]["kept"]
    assert isinstance(stages, list) and isinstance(kept, list)
    assert {"s10_render", "s10_subs", "s10_qc"} <= set(stages)
    assert "s02u_unique" in kept
    assert ("s10_render", 1, 1) in rig.world.calls
    rows = db_rows(
        pg_dsn,
        "SELECT stage_id, iteration FROM tasks WHERE stage_id IN ('s10_render','s02u_unique')"
        " AND job_id = (SELECT id FROM jobs ORDER BY created_at DESC LIMIT 1)"
        " ORDER BY stage_id, iteration",
    )
    assert rows == [("s02u_unique", 0), ("s10_render", 0), ("s10_render", 1)]


def test_revision_cap_ends_the_job_blocked(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    rig.world.fail_gate["s10_qc"] = [[gate_fail("qc.loudness", "s10_render")] for _ in range(5)]
    job = rig.intake()
    graph = job_graph(LONG)
    report = rig.runner.run(job, graph, rig.runner.start(job, graph))
    assert report.status == "BLOCKED_COMPLIANCE" and "max_revision_loops" in report.detail
    state = db_rows(pg_dsn, "SELECT state, outcome FROM jobs ORDER BY created_at DESC LIMIT 1")
    assert state == [("COMPLETED", "BLOCKED_COMPLIANCE")]


_ = (ActorRef, JobId)
