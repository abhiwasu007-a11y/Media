# ruff: noqa: PT018
"""The executor with the real allow-listed agent payload models (ticket "agent payload
registration"): a registered payload is accepted, an unregistered or mismatching one is refused
(fail closed), both on the way in and on the way out. Payloads are the ones the agents' own test
fakes emit and the orchestrator's real input builder builds."""

import pytest

from amw_core.contracts import TaskOutput
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.payloads import PayloadSchemaRegistry
from amw_core.enums import OutputStatus
from amw_core.errors import SchemaInvalidError
from amw_core.ids import ATTEMPT
from amw_orchestrator.executor import ChannelCategory, TaskExecutor
from amw_orchestrator.input_builders import BuilderTable
from tests.agents.agent_04_research_knowledge.conftest import build_world, exec_ctx
from tests.agents.agent_16_compliance_qa.test_stages import ctx_of, gate_world
from tests.orchestrator.test_executor import _Builder, _Registry, _Worker
from tests.orchestrator.test_input_builders import _ctx, _Reg

pytestmark = pytest.mark.unit


def _real_agent_04_output() -> TaskOutput:
    w = build_world()
    ti = w.task_input()
    out = w.step().run(ti, exec_ctx(ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    return out


def _with_payload(out: TaskOutput, payload: PayloadObject) -> TaskOutput:
    return out.model_copy(update={"payload": payload})


def test_registered_input_and_real_output_pass_through_the_default_executor() -> None:
    out = _real_agent_04_output()
    worker = _Worker(out)
    ex = TaskExecutor(_Reg(BuilderTable(), worker), schemas=PayloadSchemaRegistry())
    assert "agent_04_research_knowledge" in ex.plugins
    result = ex.run(ex.prepare(_ctx(ChannelCategory.NON_FINANCE), str(ATTEMPT.new())))
    ((task_input, _),) = worker.seen
    assert task_input.payload.payload_schema == "agent_04.research_pack.input"
    assert result.status is OutputStatus.SUCCEEDED and result.error is None


def test_a_registered_output_that_does_not_match_its_model_is_refused_with_the_real_cost() -> None:
    out = _real_agent_04_output()
    assert out.payload is not None and out.payload.data is not None
    broken = {k: v for k, v in out.payload.data.items() if k != "topic_verdict"}
    bad = _with_payload(out, out.payload.model_copy(update={"data": broken})).model_copy(
        update={"resource_usage": out.resource_usage.model_copy(update={"cost_estimate_micros": 5})}
    )
    ex = TaskExecutor(_Reg(BuilderTable(), _Worker(bad)), schemas=PayloadSchemaRegistry())
    result = ex.run(ex.prepare(_ctx(ChannelCategory.NON_FINANCE), str(ATTEMPT.new())))
    assert result.status is OutputStatus.FAILED and result.error is not None
    assert result.error.code == "PERMANENT.SCHEMA_INVALID"
    assert result.resource_usage.cost_estimate_micros == 5


def test_an_output_without_a_registered_model_is_refused_fail_closed() -> None:
    """Agent 16 builds its three outputs as plain mappings: no model, so no registration."""
    w = gate_world()
    real = w.stage.run(w.ti, ctx_of(w.ti))
    assert real.status is OutputStatus.SUCCEEDED and real.payload is not None
    assert real.payload.payload_schema == "agent_16.compliance_gate.output"
    ex = TaskExecutor(_Reg(BuilderTable(), _Worker(real)), schemas=PayloadSchemaRegistry())
    result = ex.run(ex.prepare(_ctx(ChannelCategory.NON_FINANCE), str(ATTEMPT.new())))
    assert result.status is OutputStatus.FAILED and result.error is not None
    assert result.error.code == "PERMANENT.SCHEMA_INVALID"


@pytest.mark.parametrize(
    "schema", ["agent_12.metadata.input", "svc_s02.uniqueness_check.input", "agent_99.x.input"]
)
def test_an_unregistered_input_never_reaches_the_worker(schema: str) -> None:
    worker = _Worker()
    ex = TaskExecutor(_Registry(_Builder(schema), worker), schemas=PayloadSchemaRegistry())
    from tests.orchestrator.test_executor import _bc, _job

    with pytest.raises(SchemaInvalidError):
        ex.prepare(_bc(_job()), str(ATTEMPT.new()))
    assert worker.seen == []
