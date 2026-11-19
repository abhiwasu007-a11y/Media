"""PASS6-E (CCR-203): both steps are ``TaskWorker`` entry points taking ``(task, ctx)``."""

import dataclasses
import inspect
from typing import Any

import pytest

from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import OutputStatus
from amw_core.exec_context import ExecContext
from amw_core.ids import JobId, OrgId, TaskId
from amw_core.interfaces import TaskWorker
from amw_core.interfaces.tenancy_context import TenantContext
from tests.agents.agent_06_fact_checker.support import (
    SCRIPT_SHA,
    MemoryKnowledge,
    RecordedLlm,
    World,
    extraction_step,
    run_context,
    task_input,
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
        assert [p.name for p in params] == ["task_input", "ctx"]  # the TaskWorker protocol names
        assert params[1].annotation in (ExecContext, "ExecContext")


def test_run_context_helper_builds_an_exec_context() -> None:
    ctx = run_context("s06_verify", 2)
    assert isinstance(ctx, ExecContext)
    assert (ctx.stage_id, ctx.iteration, ctx.attempt_no) == ("s06_verify", 2, 1)


_OTHER_ORG = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8eaa"
_OTHER_JOB = "job_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8eab"
_OTHER_TASK = "tsk_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8eac"


def _extraction_task() -> TaskInput:
    # The guard runs before the payload is read, so a minimal payload is enough here.
    return task_input("agent_06.claim_extraction.input", {}, version="1.1.0", script_sha=SCRIPT_SHA)


def _verification_task() -> TaskInput:
    # The guard runs before the payload is read, so a minimal payload is enough here.
    return task_input("agent_06.claim_verification.input", {}, version="1.0.0")


def _calls() -> list[tuple[str, Any, TaskInput]]:
    world = World(llm=RecordedLlm([]))
    return [
        ("extraction", extraction_step(world), _extraction_task()),
        ("verification", verification_step(world, MemoryKnowledge([])), _verification_task()),
    ]


def test_entry_points_accept_task_input_by_keyword() -> None:
    """The TaskWorker protocol names the first parameter ``task_input``; keyword callers work."""
    for _name, step, task in _calls():
        out = step.run(task_input=task, ctx=run_context())
        assert isinstance(out, TaskOutput)  # the keyword call reached the entry point


def _ctx_with(**over: Any) -> ExecContext:
    ctx = run_context()
    if "org" in over:
        tenant = TenantContext(
            org_id=OrgId(over["org"]),
            actor=ctx.tenant.actor,
            correlation_id=ctx.tenant.correlation_id,
        )
        return dataclasses.replace(ctx, tenant=tenant)
    return dataclasses.replace(ctx, **over)


@pytest.mark.parametrize(
    "over",
    [
        {"org": _OTHER_ORG},
        {"job_id": JobId(_OTHER_JOB)},
        {"task_id": TaskId(_OTHER_TASK)},
    ],
    ids=["org", "job", "task"],
)
def test_ctx_must_match_the_task_input(over: dict[str, Any]) -> None:
    for name, step, task in _calls():
        out = step.run(task_input=task, ctx=_ctx_with(**over))
        assert out.status is OutputStatus.REJECTED, name
        assert out.error is not None, name
        assert out.error.code == "PERMANENT.TENANT_MISMATCH", name


def test_matching_ctx_is_not_rejected_as_a_mismatch() -> None:
    for _name, step, task in _calls():
        out = step.run(task_input=task, ctx=run_context())
        assert out.error is None or out.error.code != "PERMANENT.TENANT_MISMATCH"
