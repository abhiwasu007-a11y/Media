# ruff: noqa: PT018
"""Agent 10 payload registration: the registered models accept what the stages really emit."""

from pathlib import Path

import pytest

from agent_10_video_editor.contracts import (
    RenderInput,
    RenderOutput,
    SubtitlesInput,
    SubtitlesOutput,
    TechnicalQcInput,
    TechnicalQcOutput,
)
from agent_10_video_editor.qc.selftest import SelfTestCase, SelfTestRecord
from agent_10_video_editor.qc.stage import QcStage
from amw_core.enums import OutputStatus
from tests.agents.agent_10_video_editor.support import World, licensed_snapshot, run_chain
from tests.agents.payload_support import round_trip

pytestmark = pytest.mark.contract


class _SelfTests:
    def record_for(self, build_id: str) -> SelfTestRecord:
        return SelfTestRecord(build_id, (SelfTestCase("clean", "PASS", "PASS"),))


def test_render_subtitles_and_qc_payloads_round_trip(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.licences.snapshot_value = licensed_snapshot(world)
    render_in = world.render_input().payload
    chain = run_chain(world)
    render, subs, qc_in = chain["render"], chain["subtitles"], chain["qc_input"]
    assert render_in.payload_schema == "agent_10.render.input"
    assert isinstance(round_trip(render_in), RenderInput)
    assert render.payload is not None and render.payload.payload_schema == "agent_10.render.output"
    assert isinstance(round_trip(render.payload), RenderOutput)

    # the subtitles input as the orchestrator will build it from the render output
    rdata = render.payload.data
    assert rdata is not None
    subs_in = world.task_input(
        "subtitles",
        {
            "render_id": rdata["render_id"],
            "language": "mr",
            "iteration": 0,
            "verified_script_sha256": world.script_blob_sha,
            "caption_style": None,
        },
    ).payload
    assert subs_in.payload_schema == "agent_10.subtitles.input"
    assert isinstance(round_trip(subs_in), SubtitlesInput)
    assert subs.payload is not None and subs.payload.payload_schema == "agent_10.subtitles.output"
    assert isinstance(round_trip(subs.payload), SubtitlesOutput)

    assert qc_in.payload.payload_schema == "agent_10.technical_qc.input"
    assert isinstance(round_trip(qc_in.payload), TechnicalQcInput)
    qc = QcStage(world.deps(), _SelfTests()).execute(qc_in, world.attempt)
    assert qc.status is OutputStatus.SUCCEEDED and qc.payload is not None
    assert qc.payload.payload_schema == "agent_10.technical_qc.output"
    assert isinstance(round_trip(qc.payload), TechnicalQcOutput)
