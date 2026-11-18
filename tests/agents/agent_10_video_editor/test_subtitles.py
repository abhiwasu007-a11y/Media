"""Subtitles: cue builder, SRT writer/parser/validator and the ``agent_10.subtitles`` stage."""

from pathlib import Path

import pytest

from agent_10_video_editor.config import GuardConfig  # noqa: F401
from agent_10_video_editor.guard import LocalTime
from agent_10_video_editor.inputs import NarrationTimeline
from agent_10_video_editor.subtitle_stage import SubtitleStage
from agent_10_video_editor.subtitles import (
    Cue,
    CueBuilder,
    SrtParser,
    SrtValidator,
    SrtWriter,
    SubtitleStageCore,
)
from amw_core.enums import OutputStatus
from amw_core.errors import IncompleteOutputError, InputInvalidError
from tests.agents.agent_10_video_editor.support import World, payload_data, run_chain


@pytest.mark.unit
def test_srt_roundtrip_is_utf8_lf_no_bom_and_numbered() -> None:
    cues = [Cue(1, 0, 1500, "आज आपण"), Cue(2, 1500, 3000, "चार्ट वाचू")]
    data = SrtWriter.write(cues)
    assert not data.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in data
    parsed = SrtParser.parse(data)
    assert [(c.index, c.start_ms, c.end_ms, c.text) for c in parsed] == [
        (c.index, c.start_ms, c.end_ms, c.text) for c in cues
    ]
    assert SrtValidator.validate(parsed, 3000) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "data",
    [
        b"\xef\xbb\xbf1\n00:00:00,000 --> 00:00:01,000\na\n",
        b"1\r\n00:00:00,000 --> 00:00:01,000\na\n",
        b"x\n",
        b"1\nbad\na\n",
        b"\xff\xfe",
    ],
)
def test_srt_parser_is_strict(data: bytes) -> None:
    with pytest.raises(InputInvalidError):
        SrtParser.parse(data)


@pytest.mark.unit
def test_validator_rejects_empty_cue_list() -> None:
    assert SrtValidator.validate([], 1000) == ["NO_CUES"]


@pytest.mark.unit
def test_cue_builder_never_changes_text_and_rejects_bad_limit() -> None:
    built = CueBuilder.build("s1", 0, 6000, "alpha beta gamma delta", 11)
    assert " ".join(c.text for c in built.cues) == "alpha beta gamma delta"
    assert built.cues[0].start_ms == 0
    assert built.cues[-1].end_ms == 6000
    with pytest.raises(InputInvalidError):
        CueBuilder.build("s1", 0, 1000, "text", 0)
    with pytest.raises(InputInvalidError):
        CueBuilder.build("s1", 0, 1000, "   ", 10)


@pytest.mark.unit
def test_core_build_requires_text_for_every_segment_and_refuses_unaligned() -> None:
    timeline = NarrationTimeline.model_validate(
        {"source": "OWNER_MARKS", "segments": [{"segment_id": "s1", "start_ms": 0, "end_ms": 2000}]}
    )
    with pytest.raises(InputInvalidError):
        SubtitleStageCore.build(timeline, {}, 20, 5000)
    unaligned = NarrationTimeline.model_validate({"source": "UNALIGNED", "segments": []})
    with pytest.raises(InputInvalidError):
        SubtitleStageCore.build(unaligned, {}, 20, 5000)
    ok = SubtitleStageCore.build(timeline, {"s1": "hello world"}, 20, 5000)
    assert ok.errors == ()
    assert len(ok.cues) == 1


@pytest.mark.unit
def test_subtitle_stage_writes_one_srt_and_one_asset_row(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = run_chain(world)
    out = chain["subtitles"]
    assert out.status is OutputStatus.SUCCEEDED
    entry = payload_data(out)["srt"][0]
    assert entry["language"] == "mr"
    assert entry["cue_count"] == 4
    assert payload_data(out)["sync_basis"] == "NARRATION_TIMELINE"
    assert {r.check_id for r in out.validation_results} == {
        "a10.sub.format",
        "a10.sub.coverage",
        "a10.sub.text_from_script",
    }
    assert all(r.verdict == "PASS" and not r.gate for r in out.validation_results)
    assert len(world.assets.subtitles) == 1
    # replay: byte-identical SRT finds the existing asset row (UNIQUE org + content sha256)
    again = SubtitleStage(world.deps()).run(
        world.task_input(
            "subtitles",
            {
                "render_id": payload_data(chain["render"])["render_id"],
                "language": "mr",
                "iteration": 1,
                "verified_script_sha256": world.script_blob_sha,
                "caption_style": None,
            },
            schemas=[
                "agent_10.render.output",
                "agent_07.voice_synthesis.output",
                "agent_05.script_document",
            ],
        ),
        world.attempt,
    )
    assert payload_data(again)["srt"][0]["asset_id"] == entry["asset_id"]
    assert len(world.assets.subtitles) == 1


@pytest.mark.unit
def test_subtitle_stage_rejects_script_hash_and_caption_style(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = run_chain(world)
    rid = payload_data(chain["render"])["render_id"]
    schemas = [
        "agent_10.render.output",
        "agent_07.voice_synthesis.output",
        "agent_05.script_document",
    ]
    base = {
        "render_id": rid,
        "language": "mr",
        "iteration": 0,
        "verified_script_sha256": world.script_blob_sha,
        "caption_style": None,
    }
    with pytest.raises(InputInvalidError):
        SubtitleStage(world.deps()).run(
            world.task_input(
                "subtitles", {**base, "verified_script_sha256": "7" * 64}, schemas=schemas
            ),
            world.attempt,
        )
    from amw_core.errors import SchemaInvalidError

    with pytest.raises(SchemaInvalidError):
        SubtitleStage(world.deps()).run(
            world.task_input("subtitles", {**base, "caption_style": {"x": 1}}, schemas=schemas),
            world.attempt,
        )


@pytest.mark.unit
def test_subtitle_stage_is_blocked_by_market_hours(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = run_chain(world)
    world.probe.now = LocalTime.parse("WED", "11:00")
    out = SubtitleStage(world.deps()).run(
        world.task_input(
            "subtitles",
            {
                "render_id": payload_data(chain["render"])["render_id"],
                "language": "mr",
                "iteration": 0,
                "verified_script_sha256": world.script_blob_sha,
                "caption_style": None,
            },
            schemas=[
                "agent_10.render.output",
                "agent_07.voice_synthesis.output",
                "agent_05.script_document",
            ],
        ),
        world.attempt,
    )
    assert out.status is OutputStatus.SUSPENDED


@pytest.mark.unit
def test_subtitle_checks_fail_when_text_would_differ(tmp_path: Path) -> None:
    world = World(tmp_path)
    chain = run_chain(world)
    # a segment shorter than its cue count triggers CUE_TOO_SHORT
    world.docs["agent_07.voice_synthesis.output"]["segments"][0]["end_ms"] = 3
    import json

    uri, sha = world.put(
        "tiny.json",
        json.dumps(world.docs["agent_07.voice_synthesis.output"], sort_keys=True).encode(),
    )
    world.refs["agent_07.voice_synthesis.output"] = (uri, sha)
    world.cfg = world.cfg.model_copy(
        update={"sub": world.cfg.sub.model_copy(update={"max_chars_per_cue": 3})}
    )
    with pytest.raises((InputInvalidError, IncompleteOutputError)):
        SubtitleStage(world.deps()).run(
            world.task_input(
                "subtitles",
                {
                    "render_id": payload_data(chain["render"])["render_id"],
                    "language": "mr",
                    "iteration": 0,
                    "verified_script_sha256": world.script_blob_sha,
                    "caption_style": None,
                },
                schemas=[
                    "agent_10.render.output",
                    "agent_07.voice_synthesis.output",
                    "agent_05.script_document",
                ],
            ),
            world.attempt,
        )
