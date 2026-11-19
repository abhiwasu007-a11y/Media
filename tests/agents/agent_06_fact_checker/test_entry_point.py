"""PASS6-E (CCR-203): both steps are ``TaskWorker`` entry points taking ``(task, ctx)``."""

import inspect

import pytest

from amw_core.exec_context import ExecContext
from amw_core.interfaces import TaskWorker
from tests.agents.agent_06_fact_checker.support import (
    MemoryKnowledge,
    RecordedLlm,
    World,
    extraction_step,
    run_context,
    verification_step,
)

pytestmark = pytest.mark.contract


def _steps() -> list[TaskWorker]:
    world = World(llm=RecordedLlm([]))
    return [extraction_step(world), verification_step(world, MemoryKnowledge([]))]


def test_both_steps_satisfy_task_worker() -> None:
    for step in _steps():
        assert isinstance(step, TaskWorker)


def test_run_signature_is_task_then_exec_context() -> None:
    for step in _steps():
        params = list(inspect.signature(step.run).parameters.values())
        assert [p.name for p in params] == ["task", "ctx"]
        assert params[1].annotation in (ExecContext, "ExecContext")


def test_run_context_helper_builds_an_exec_context() -> None:
    ctx = run_context("s06_verify", 2)
    assert isinstance(ctx, ExecContext)
    assert (ctx.stage_id, ctx.iteration, ctx.attempt_no) == ("s06_verify", 2, 1)
