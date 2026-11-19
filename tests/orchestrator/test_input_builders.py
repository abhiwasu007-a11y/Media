# ruff: noqa: PT018
"""Input builders (PASS6-B1): every builder output validates against the agent's payload input
model and ``amw.task_input``; no builder imports another agent's package."""

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from agent_04_research_knowledge.models.pack_input import ResearchPackInput
from amw_core.contracts.payloads import PayloadSchemaRegistry
from amw_core.errors import InputInvalidError, UnsupportedTaskError
from amw_core.ids import ATTEMPT
from amw_orchestrator import input_builders
from amw_orchestrator.executor import BuildContext, ChannelCategory, TaskExecutor
from amw_orchestrator.input_builders import BuilderTable
from tests.orchestrator.test_executor import _bc, _job, _Worker
from tests.orchestrator.world import LONG, ok_output

pytestmark = pytest.mark.unit
RESEARCH = (
    __import__("amw_orchestrator.registry", fromlist=["record"]).record(LONG).stage("s04_research")
)


class _Reg:
    def __init__(self, table: BuilderTable, worker: _Worker) -> None:
        self.t, self.w = table, worker

    def worker_for(self, stage: object) -> _Worker:
        return self.w

    def builder_for(self, stage: object) -> BuilderTable:
        return self.t


def _ctx(category: ChannelCategory, iteration: int = 0) -> BuildContext:
    return replace(_bc(_job(category), iteration=iteration), stage=RESEARCH)


def test_agent_04_builder_output_validates_for_both_categories() -> None:
    table = BuilderTable()
    for category, packs in (
        (ChannelCategory.FINANCE, ["rp.youtube_general", "rp.finance_sebi_in"]),
        (ChannelCategory.NON_FINANCE, ["rp.youtube_general"]),
    ):
        built = table.build(_ctx(category))
        model = ResearchPackInput.model_validate(dict(built.data))  # the agent's own input model
        assert built.payload_schema == "agent_04.research_pack.input"
        assert list(model.active_rule_packs) == packs and model.channel_category == category.value
        assert model.topic.language == "mr-IN" and model.revision is None


def test_the_whole_path_through_the_executor_with_the_real_model() -> None:
    reg = PayloadSchemaRegistry()
    reg.register("agent_04.research_pack.input", "1.0.0", ResearchPackInput)
    reg.register(
        "agent_04.research_pack.output",
        "1.0.0",
        __import__("tests.orchestrator.world", fromlist=["Open"]).Open,
    )
    worker = _Worker(ok_output("agent_04.research_pack.output", {"pack": 1}))
    ex = TaskExecutor(_Reg(BuilderTable(), worker), schemas=reg)
    out = ex.run(ex.prepare(_ctx(ChannelCategory.NON_FINANCE), str(ATTEMPT.new())))
    ((task_input, ctx),) = worker.seen
    assert out.status.value == "SUCCEEDED"
    assert task_input.payload.payload_schema == "agent_04.research_pack.input"
    assert ctx.stage_id == "s04_research"


def test_unmapped_revision_and_unknown_task_type_are_typed_refusals() -> None:
    table = BuilderTable()
    with pytest.raises(InputInvalidError):
        table.build(_ctx(ChannelCategory.FINANCE, iteration=1))
    with pytest.raises(UnsupportedTaskError):
        # Agent 12 has no builder (not built, stage disabled by default); s05_script has one now
        table.build(
            replace(
                _bc(_job()),
                stage=_bc(_job()).stage.model_copy(update={"task_type": "agent_12.metadata"}),
            )
        )


def test_no_builder_imports_an_agent_package() -> None:
    root = Path(input_builders.__file__).parent
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(n.startswith("agent_") for n in names), path.name
