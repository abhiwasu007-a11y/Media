# ruff: noqa: PT018
"""Agent 07 payload registration: the registered models accept what the stages really emit."""

import copy
from pathlib import Path

import pytest

from agent_07_voice_production import contracts as c
from amw_core.enums import OutputStatus
from tests.agents.agent_07_voice_production.master_world import build as build_master
from tests.agents.agent_07_voice_production.test_contracts import cases
from tests.agents.agent_07_voice_production.voice_world import build as build_voice
from tests.agents.payload_support import round_trip

pytestmark = pytest.mark.contract


def test_voice_synthesis_input_and_output_round_trip(tmp_path: Path) -> None:
    w = build_voice(copy.deepcopy(cases("voice_synthesis")[0]), tmp_path)
    assert isinstance(round_trip(w.task_input.payload), c.VoiceSynthesisInput)
    out = w.run()
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == c.SCHEMA_VOICE_OUTPUT
    assert isinstance(round_trip(out.payload), c.VoiceSynthesisOutput)


def test_audio_master_input_and_output_round_trip(tmp_path: Path) -> None:
    m = build_master(copy.deepcopy(cases("audio_master")[0]), tmp_path)
    assert isinstance(round_trip(m.task_input.payload), c.AudioMasterInput)
    out = m.run()
    assert out.status is OutputStatus.SUCCEEDED and out.payload is not None
    assert out.payload.payload_schema == c.SCHEMA_MASTER_OUTPUT
    assert isinstance(round_trip(out.payload), c.AudioMasterOutput)
