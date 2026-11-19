# ruff: noqa: PT018
"""Agent 09 payload registration: the registered models accept what the worker really emits."""

import pytest

from agent_09_video_director.contracts import ShotPlanInput
from agent_09_video_director.output import ShotPlanPayload
from amw_core.enums import OutputStatus
from tests.agents.agent_09_video_director.test_entry_point import World, build, worker
from tests.agents.payload_support import round_trip

pytestmark = pytest.mark.contract


def test_shot_plan_input_and_output_round_trip() -> None:
    w = World()
    task, ctx = build(w)
    # the model fills the defaults of the optional fields (limits, revision_feedback)
    assert isinstance(round_trip(task.payload, exact=False), ShotPlanInput)
    out = worker(w).run(task_input=task, ctx=ctx)
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_09.shot_plan.output"
    assert isinstance(round_trip(out.payload), ShotPlanPayload)
