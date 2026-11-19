"""PASS6-C (CCR-203, CCR-208, CCR-214): the one worker entry point ``run(task_input, ctx)``."""
# ruff: noqa: PT018

import dataclasses
from pathlib import Path

import pytest

from agent_04_research_knowledge.protocol import ResearchStage
from agent_04_research_knowledge.steps.research_pack import ResearchPackStep, ResolverFactory
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import OutputStatus
from amw_core.exec_context import ExecContext
from amw_core.ids import TASK
from amw_core.interfaces import TaskWorker
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy.storage_paths import check_jobs_subpath
from tests.agents.agent_04_research_knowledge.conftest import build_world, exec_ctx

pytestmark = pytest.mark.contract


def test_step_conforms_to_task_worker_and_stage_protocol() -> None:
    step = build_world().step()
    assert isinstance(step, TaskWorker)
    assert isinstance(step, ResearchStage)
    assert isinstance(step, ResearchPackStep)


def test_run_takes_the_context_attempt_and_stage_fields() -> None:
    w = build_world()
    ti = w.task_input()
    ctx = dataclasses.replace(exec_ctx(ti), stage_id="s04_research", iteration=0)
    out = w.step().run(ti, ctx)
    assert out.status is OutputStatus.SUCCEEDED
    # the attempt of the context is the attempt of the written files
    assert any(str(ctx.attempt_id) in r.uri for r in out.output_refs)


def test_context_for_another_job_or_task_is_refused_before_any_step() -> None:
    w = build_world()
    ti = w.task_input()
    ctx: ExecContext = dataclasses.replace(exec_ctx(ti), task_id=TASK.new())
    out = w.step().run(ti, ctx)
    assert out.error is not None and out.error.code == "PERMANENT.TENANT_MISMATCH"
    assert out.status is OutputStatus.REJECTED
    assert not w.llm.requests


def test_null_project_is_refused_with_a_typed_violation() -> None:
    w = build_world()
    ti = w.task_input(project_id=None)
    out = w.step().run(ti, exec_ctx(ti))
    assert out.status is OutputStatus.REJECTED
    assert out.error is not None and out.error.code == "PERMANENT.INPUT_INVALID"
    violations = out.error.details.violations
    assert violations and violations[0].keyword == "PROJECT_MISSING"
    assert violations[0].path == "/project_id"
    assert not w.llm.requests


def test_every_write_is_accepted_by_the_real_backend(tmp_path: Path) -> None:
    w = build_world()
    real = LocalDiskStorage(tmp_path)
    deps = dataclasses.replace(
        w.deps, storage=real, resolver_factory=ResolverFactory(w.library, real)
    )
    ti = w.task_input()
    out = ResearchPackStep(deps).run(ti, exec_ctx(ti))
    assert out.status is OutputStatus.SUCCEEDED, out.error
    files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    jobs = [p for p in files if f"/{w.job}/" in p.as_posix()]
    assert jobs
    for p in jobs:
        rel = p.as_posix().split("/jobs/", 1)[1]
        check_jobs_subpath(rel)  # the 03 section 8 rule 5 sub-path check
    names = [p.as_posix() for p in jobs]
    assert any("/artifacts/research_pack.json" in n and "/attempts/" in n for n in names)
    assert any("/checkpoints/" in n for n in names)
    assert any(n.endswith("/output.json") for n in names)
    assert isinstance(out, TaskOutput)
