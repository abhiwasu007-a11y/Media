# ruff: noqa: PT018
"""Agent 04 payload registration: the registered models accept what the stage really emits."""

import pytest

from agent_04_research_knowledge.models.pack_input import ResearchPackInput
from agent_04_research_knowledge.models.pack_output import ResearchPack
from amw_core.enums import OutputStatus
from tests.agents.agent_04_research_knowledge.conftest import build_world, exec_ctx
from tests.agents.payload_support import round_trip

pytestmark = pytest.mark.contract


def test_real_input_and_output_round_trip_through_the_registry() -> None:
    w = build_world()
    ti = w.task_input()
    assert isinstance(round_trip(ti.payload), ResearchPackInput)
    out = w.step().run(ti, exec_ctx(ti))
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_04.research_pack.output"
    assert isinstance(round_trip(out.payload), ResearchPack)
