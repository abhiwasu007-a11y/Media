# ruff: noqa: PT018
"""Agent 08 payload registration: the registered models accept what the stage really emits."""

import pytest

from agent_08_visual_assets.models.output import SourcingOutput
from agent_08_visual_assets.models.task_input import SourcingInput
from amw_core.enums import OutputStatus
from tests.agents.agent_08_visual_assets.test_entry_point import Rig
from tests.agents.payload_support import round_trip

pytestmark = pytest.mark.contract


def test_asset_sourcing_input_and_output_round_trip() -> None:
    rig = Rig()
    ti = rig.task_input()
    assert isinstance(round_trip(ti.payload), SourcingInput)
    out = rig.stage.run(ti, rig.ctx)
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_08.asset_sourcing.output"
    assert isinstance(round_trip(out.payload), SourcingOutput)
