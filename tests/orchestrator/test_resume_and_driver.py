# ruff: noqa: PT018
"""Crash-resume from ``tasks.stage_id`` (CCR-214 (a)), failure paths and the budget hard stop of the
real driver, on the real PostgreSQL tables with fake workers. PLUMBING TEST - NOT QUALITY."""

from pathlib import Path

import pytest

from amw_core.errors import ConfigInvalidError, LockConflictError, MissingDependencyError
from amw_core.ids import TaskId
from amw_orchestrator.driver import GraphRunner
from amw_orchestrator.registry import job_graph
from amw_orchestrator.services import StageBudgets
from tests.orchestrator.world import LONG, PAID, M, build_rig, db_rows

pytestmark = pytest.mark.integration


class Crash(BaseException):
    pass


def _job_id_rows(dsn: str, sql: str) -> list[tuple[object, ...]]:
    return db_rows(
        dsn, sql.replace("<JOB>", "(SELECT id FROM jobs ORDER BY created_at DESC LIMIT 1)")
    )


def test_resume_rebuilds_the_stage_map_and_outputs_from_the_database(
    pg_dsn: str, tmp_path: Path
) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake()
    graph = job_graph(LONG)
    first = rig.runner.run(job, graph, rig.runner.start(job, graph))
    assert first.status == "AWAITING_APPROVAL"
    parked = first.stages["a_final"].task_id
    # a brand-new runner, no memory of the first one: the stage map comes from tasks.stage_id
    runner2: GraphRunner = rig.make_runner()
    report = runner2.load(job, graph)
    assert {k for k in report.stages if "#" not in k} == {s.stage_id for s in graph}
    assert report.stages["a_final"].task_id == parked
    assert report.stages["s16_score"].output is not None  # read back from the stored output.json
    assert rig.desk.decided(job.job_id, parked) is False
    assert runner2.run(job, graph, report).status == "AWAITING_APPROVAL"
    rig.desk.decisions.add(parked)
    rig.world.calls.clear()
    done = runner2.run(job, graph, report)
    assert done.status == "DELIVERED", done.detail
    assert done.order == ["a_final", "s16_auth", "s13_deliver"]  # nothing finished is redone
    assert [c[0] for c in rig.world.calls] == ["s16_auth", "s13_deliver"]


def test_resume_finds_a_crashed_running_task_and_stops_with_a_stated_reason(
    pg_dsn: str, tmp_path: Path
) -> None:
    rig = build_rig(pg_dsn, tmp_path)

    def die(stage: str) -> None:
        if stage == "s06_claims":
            raise Crash

    rig.world.on_call = die
    job = rig.intake()
    graph = job_graph(LONG)
    with pytest.raises(Crash):
        rig.runner.run(job, graph, rig.runner.start(job, graph))
    report = rig.make_runner().load(job, graph)
    assert report.stages["s06_claims"].state.value == "RUNNING"
    assert report.stages["s05_script"].output is not None
    result = rig.make_runner().run(job, graph, report)
    assert result.status == "RUNNING_STALE" and "s06_claims" in result.detail


def test_load_refuses_a_job_without_the_tasks_of_its_graph(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job = rig.intake()
    with pytest.raises(MissingDependencyError):
        rig.runner.load(job, job_graph(LONG))  # never started: no task rows


def test_budget_reservation_refused_stops_the_job_before_any_work(
    pg_dsn: str, tmp_path: Path
) -> None:
    paid = {**PAID, "agent_04.research_pack": 6 * M}  # above the USD 5 per-video hard cap
    rig = build_rig(pg_dsn, tmp_path, paid=paid)
    job = rig.intake()
    graph = job_graph(LONG)
    report = rig.runner.run(job, graph, rig.runner.start(job, graph))
    assert report.status == "AWAITING_BUDGET" and "s04_research" in report.detail
    assert rig.world.calls == []  # no worker ran, no spend
    assert report.stages["s04_research"].state.value == "CHECKPOINTED"
    rows = _job_id_rows(pg_dsn, "SELECT state FROM jobs WHERE id = <JOB>")
    assert rows == [("CHECKPOINTED",)]


def test_render_window_closed_leaves_the_task_untouched(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path, calendar_allows=False)
    job = rig.intake()
    graph = job_graph(LONG)
    report = rig.runner.run(job, graph, rig.runner.start(job, graph))
    assert report.status == "RENDER_WINDOW_CLOSED" and "s07_master" in report.detail
    assert report.stages["s07_master"].state.value == "PENDING"


def test_retryable_failure_retries_and_a_permanent_one_stops(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    attempts: list[int] = []
    real_run = rig.world.run

    def flaky(task_input, ctx):  # type: ignore[no-untyped-def]
        if ctx.stage_id == "s04_research":
            attempts.append(ctx.attempt_no)
            if ctx.attempt_no == 1:
                from amw_core.errors import NetworkError

                raise NetworkError("scripted")
        return real_run(task_input, ctx)

    rig.world.run = flaky  # type: ignore[method-assign]
    job = rig.intake()
    graph = job_graph(LONG)
    report = rig.runner.run(job, graph, rig.runner.start(job, graph))
    assert attempts == [1, 2] and report.stages["s04_research"].state.value == "COMPLETED"
    assert report.status == "AWAITING_APPROVAL"

    rig2 = build_rig(pg_dsn, tmp_path / "b")

    def bad(task_input, ctx):  # type: ignore[no-untyped-def]
        raise ConfigInvalidError("scripted permanent")

    rig2.world.run = bad  # type: ignore[method-assign]
    job2 = rig2.intake()
    r2 = rig2.runner.run(job2, graph, rig2.runner.start(job2, graph))
    assert r2.status == "FAILED" and "PERMANENT.CONFIG_INVALID" in r2.detail
    rows = _job_id_rows(pg_dsn, "SELECT state FROM jobs WHERE id = <JOB>")
    assert rows == [("FAILED",)]


def test_failed_attempt_reports_the_real_cost_of_its_calls(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    real_run = rig.world.run

    def spend_then_fail(task_input, ctx):  # type: ignore[no-untyped-def]
        out = real_run(task_input, ctx)  # one metered LLM call for s05_script
        if ctx.stage_id == "s05_script":
            raise ConfigInvalidError("fails after spending")
        return out

    rig.world.run = spend_then_fail  # type: ignore[method-assign]
    job = rig.intake()
    graph = job_graph(LONG)
    report = rig.runner.run(job, graph, rig.runner.start(job, graph))
    out = report.stages["s05_script"].output
    assert report.status == "FAILED" and out is not None
    assert out.resource_usage.cost_estimate_micros > 0 and out.resource_usage.provider_calls == 1
    assert len(out.resource_usage.cost_entry_ids) == 1


def test_a_foreign_queue_row_is_never_run(pg_dsn: str, tmp_path: Path) -> None:
    rig = build_rig(pg_dsn, tmp_path)
    job_a, job_b = rig.intake(title="A job"), rig.intake(title="B job")
    graph = job_graph(LONG)
    report_a = rig.runner.start(job_a, graph)
    report_b = rig.runner.start(job_b, graph)
    stage = next(s for s in graph if s.stage_id == "s04_research")
    # both jobs' first tasks get queued; runner A may only run its own row
    for job, report in ((job_b, report_b), (job_a, report_a)):
        run = report.stages["s04_research"]
        rig.runner._admit(job, stage, report, run, TaskId(run.task_id))
    with pytest.raises(LockConflictError):
        rig.runner._claim(stage, report_a.stages["s04_research"].task_id)


def test_stage_budgets_zero_for_unpaid_and_fail_closed_for_paid() -> None:
    graph = job_graph(LONG)
    budgets = StageBudgets(dict(PAID), "USD", 1000, 40)
    by_id = {s.stage_id: s for s in graph}
    assert budgets.budget_for(by_id["s10_render"]).max_cost_micros == 0
    assert budgets.budget_for(by_id["s10_render"]).max_llm_calls == 0
    assert budgets.budget_for(by_id["s05_script"]).max_cost_micros == PAID["agent_05.script_draft"]
    assert budgets.budget_for(by_id["s07_voice"]).max_llm_calls == 0  # tts only, no llm calls
    assert budgets.missing(graph) == ()
    empty = StageBudgets({}, "USD", 1000, 40)
    assert "agent_05.script_draft" in empty.missing(graph)
    with pytest.raises(ConfigInvalidError):
        empty.budget_for(by_id["s05_script"])
    with pytest.raises(ConfigInvalidError):
        empty.validate(graph)
    zero = StageBudgets({**PAID, "agent_05.script_draft": 0}, "USD", 1000, 40)
    with pytest.raises(ConfigInvalidError):  # an explicit 0 is not a configuration either
        zero.validate(graph)
