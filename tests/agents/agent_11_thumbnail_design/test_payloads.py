# ruff: noqa: PT018
"""Agent 11 payload registration: the registered models accept what the stage really emits."""

import pytest

from agent_11_thumbnail_design.payload import OutputPayload, ThumbnailInput
from amw_core.enums import OutputStatus
from tests.agents.agent_11_thumbnail_design.env import make_env, run_att
from tests.agents.payload_support import round_trip

pytestmark = pytest.mark.contract


def test_thumbnail_variants_input_and_output_round_trip() -> None:
    env = make_env(owner_assets=1)
    assert isinstance(round_trip(env.ti.payload), ThumbnailInput)
    out = run_att(env, env.ti)
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == "agent_11.thumbnail_variants.output"
    assert isinstance(round_trip(out.payload), OutputPayload)
