# ruff: noqa: PT018
"""``TaskExecutor`` (CCR-203): builds TaskInput + ExecContext, calls ``TaskWorker.run``, validates
every input and output payload through the payload registry (03 section 6 row 6)."""

from typing import Any

import pytest
from pydantic import ConfigDict

from amw_core.contracts import ResourceBudget, Stage, TaskInput, TaskOutput
from amw_core.contracts.payloads import PayloadSchemaRegistry
from amw_core.errors import SchemaInvalidError, SchemaVersionUnsupportedError
from amw_core.exec_context import ExecContext
from amw_core.ids import ATTEMPT, CHANNEL, CORRELATION, JOB, ORG, PROJECT, TASK, WORKSPACE
from amw_orchestrator import executor as executor_module
from amw_orchestrator.executor import (
    BuildContext,
    BuiltInput,
    ChannelCategory,
    JobFacts,
    TaskExecutor,
    resolve_channel_category,
)
from amw_orchestrator.registry import record
from tests.orchestrator.world import LONG, Open, no_plugins, ok_output

pytestmark = pytest.mark.unit
STAGE: Stage = record(LONG).stage("s05_script")


class Strict(Open):
    model_config = ConfigDict(extra="forbid")
    stage: str


def _job(category: ChannelCategory = ChannelCategory.NON_FINANCE) -> JobFacts:
    from amw_core.contracts import OwnerTopic

    topic = OwnerTopic.model_validate(
        {
            "schema_version": "1.0.0",
            "title": "Seneca test",
            "brief": None,
            "angle": None,
            "language": "mr-IN",
            "video_kind": "GENERAL",
            "course_chapter_pointer": None,
            "owner_references": [],
            "target_duration_ms": 60_000,
            "shorts_wanted": False,
        }
    )
    return JobFacts(
        org_id=str(ORG.new()),
        workspace_id=str(WORKSPACE.new()),
        project_id=str(PROJECT.new()),
        channel_id=str(CHANNEL.new()),
        job_id=str(JOB.new()),
        parent_job_id=None,
        correlation_id=str(CORRELATION.new()),
        production_type_key=LONG,
        production_type_version=2,
        language="mr-IN",
        owner_topic=topic,
        currency="USD",
        channel_category=category,
    )


def _bc(job: JobFacts, attempt_no: int = 1, iteration: int = 0) -> BuildContext:
    return BuildContext(
        job=job,
        stage=STAGE,
        task_id=str(TASK.new()),
        iteration=iteration,
        attempt_no=attempt_no,
        idempotency_key="idk_" + "a" * 64,
        resource_budget=ResourceBudget(
            max_cost_micros=0, currency="USD", max_wall_ms=1000, max_llm_calls=0
        ),
        upstream={},
    )


class _Builder:
    def __init__(self, schema: str = "agent_05.script_draft.input", version: str = "1.0.0") -> None:
        self.schema, self.version = schema, version
        self.data: dict[str, Any] = {"stage": "s05_script"}

    def build(self, ctx: BuildContext) -> BuiltInput:
        return BuiltInput(self.schema, self.version, self.data)


class _Worker:
    def __init__(self, out: TaskOutput | None = None) -> None:
        self.out = out
        self.seen: list[tuple[TaskInput, ExecContext]] = []

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        self.seen.append((task_input, ctx))
        return self.out or ok_output("agent_05.script_draft.output", {"stage": "s05_script"})


class _Registry:
    def __init__(self, builder: _Builder, worker: _Worker) -> None:
        self.b, self.w = builder, worker

    def worker_for(self, stage: Stage) -> _Worker:
        return self.w

    def builder_for(self, stage: Stage) -> _Builder:
        return self.b


def _schemas(model: type = Open) -> PayloadSchemaRegistry:
    reg = PayloadSchemaRegistry()
    reg.register("agent_05.script_draft.input", "1.0.0", model)
    reg.register("agent_05.script_draft.output", "1.0.0", Strict)
    return reg


def test_worker_gets_task_input_and_exec_context_with_stage_and_iteration() -> None:
    worker = _Worker()
    ex = TaskExecutor(_Registry(_Builder(), worker), schemas=_schemas(), load_plugins=no_plugins)
    job = _job()
    bc = _bc(job, attempt_no=3, iteration=2)
    attempt = str(ATTEMPT.new())
    out = ex.run(ex.prepare(bc, attempt))
    ((ti, ctx),) = worker.seen
    assert out.status.value == "SUCCEEDED"
    assert ti.agent_id == "agent_05" and ti.source_agent == "agent_01"
    assert ti.task_id == bc.task_id and ti.retry_count == 2 and ti.project_id == job.project_id
    assert ti.idempotency_key == bc.idempotency_key and ti.org_id == job.org_id
    assert ctx.stage_id == "s05_script" and ctx.iteration == 2 and ctx.attempt_no == 3
    assert str(ctx.attempt_id) == attempt and str(ctx.task_id) == bc.task_id


def test_unregistered_schema_fails_closed_before_the_worker_runs() -> None:
    worker = _Worker()
    ex = TaskExecutor(
        _Registry(_Builder(), worker), schemas=PayloadSchemaRegistry(), load_plugins=no_plugins
    )
    with pytest.raises(SchemaInvalidError):
        ex.prepare(_bc(_job()), str(ATTEMPT.new()))
    assert worker.seen == []


def test_default_executor_validates_with_the_real_agent_models_and_refuses_a_mismatch() -> None:
    """The allow-list now registers the agents' models (it was empty before): the stand-in data of
    this file is no ``ScriptDraftInput``, so it is still refused, now by the agent's own model.
    The accept path with real payloads is in ``test_agent_payloads.py``."""
    ex = TaskExecutor(_Registry(_Builder(), _Worker()), schemas=PayloadSchemaRegistry())
    assert "agent_05_scriptwriter" in ex.plugins
    with pytest.raises(SchemaInvalidError):
        ex.prepare(_bc(_job()), str(ATTEMPT.new()))


def test_unsupported_major_version_is_schema_version_unsupported() -> None:
    ex = TaskExecutor(
        _Registry(_Builder(version="2.0.0"), _Worker()), schemas=_schemas(), load_plugins=no_plugins
    )
    with pytest.raises(SchemaVersionUnsupportedError):
        ex.prepare(_bc(_job()), str(ATTEMPT.new()))


def test_input_failing_its_model_names_locations_not_values() -> None:
    builder = _Builder("agent_05.script_draft.output")  # Strict: needs `stage`, forbids extras
    builder.data = {"unexpected": "SECRET-VALUE"}
    ex = TaskExecutor(_Registry(builder, _Worker()), schemas=_schemas(), load_plugins=no_plugins)
    with pytest.raises(SchemaInvalidError) as exc:
        ex.prepare(_bc(_job()), str(ATTEMPT.new()))
    assert "SECRET-VALUE" not in repr(exc.value.details)


def test_invalid_output_payload_becomes_a_failed_output_that_keeps_the_real_cost() -> None:
    bad = ok_output("agent_05.script_draft.output", {"stage": "s05_script", "extra": 1})
    spent = bad.model_copy(
        update={
            "resource_usage": bad.resource_usage.model_copy(
                update={"cost_estimate_micros": 777, "provider_calls": 1}
            )
        }
    )
    ex = TaskExecutor(
        _Registry(_Builder(), _Worker(spent)), schemas=_schemas(), load_plugins=no_plugins
    )
    out = ex.run(ex.prepare(_bc(_job()), str(ATTEMPT.new())))
    assert out.status.value == "FAILED" and out.error is not None
    assert out.error.code == "PERMANENT.SCHEMA_INVALID" and not out.error.retryable
    assert out.resource_usage.cost_estimate_micros == 777  # never a silent 0


def test_start_up_loads_the_payload_schema_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[PayloadSchemaRegistry] = []

    def fake_loader(registry: PayloadSchemaRegistry | None = None) -> tuple[str, ...]:
        assert registry is not None
        calls.append(registry)
        return ("agent_99_demo",)

    monkeypatch.setattr(executor_module, "load_payload_schema_plugins", fake_loader)
    reg = _schemas()
    ex = TaskExecutor(_Registry(_Builder(), _Worker()), schemas=reg)
    assert calls == [reg] and ex.plugins == ("agent_99_demo",)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("finance", ChannelCategory.FINANCE),
        ("non-finance", ChannelCategory.NON_FINANCE),
        (" Non_Finance ", ChannelCategory.NON_FINANCE),
        (None, ChannelCategory.FINANCE),
        ("", ChannelCategory.FINANCE),
        ("philosophy", ChannelCategory.FINANCE),  # unknown label: fail closed
        ("nonfinance", ChannelCategory.FINANCE),
    ],
)
def test_channel_category_fails_closed(raw: str | None, expected: ChannelCategory) -> None:
    assert resolve_channel_category(raw) is expected


def test_job_facts_default_is_finance() -> None:
    assert _job(ChannelCategory.FINANCE).finance_rules_apply
    assert not _job(ChannelCategory.NON_FINANCE).finance_rules_apply
