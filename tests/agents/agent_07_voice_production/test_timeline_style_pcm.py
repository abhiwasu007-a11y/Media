"""U-30, U-31, U-44 and the PCM helpers: stem assembly, timeline arithmetic, owner marks, style."""

from array import array
from collections.abc import Sequence

import pytest

from agent_07_voice_production import contracts as c
from agent_07_voice_production.pcm import (
    count_clipped,
    peak_dbfs,
    read_s16,
    rms_dbfs,
    silence_samples,
    trim_silence,
    wav_info,
    write_s16,
)
from agent_07_voice_production.style import (
    StyleDecision,
    applied_ratio,
    distinct_variation,
    map_style,
)
from agent_07_voice_production.timeline import (
    PlacedClip,
    assemble,
    timeline_from_marks,
    timeline_problems,
    validate_marks,
)
from amw_core.errors import CorruptedOutputError, InputInvalidError
from tests.agents.agent_07_voice_production.support import RATE, capabilities, tone_samples

pytestmark = pytest.mark.unit


def script(*scenes: tuple[str, int], texts: int = 3) -> c.ScriptDocument:
    segs = tuple(
        c.ScriptSegment(
            segment_id=f"s{i + 1}",
            text="x",
            pace=c.Pace.NORMAL,
            emotion=c.Emotion.NEUTRAL,
            scene_id=scenes[min(i, len(scenes) - 1)][0],
        )
        for i in range(texts)
    )
    return c.ScriptDocument(
        segments=segs,
        scenes=tuple(c.ScriptScene(scene_id=s, deliberate_pause_ms=p) for s, p in scenes),
    )


def clips(durations: list[int]) -> list[PlacedClip]:
    return [
        PlacedClip(f"s{i + 1}", tone_samples(d), "a" * 64, None, False)
        for i, d in enumerate(durations)
    ]


def styles(n: int) -> dict[str, StyleDecision]:
    return {
        f"s{i + 1}": map_style(c.Pace.NORMAL, c.Emotion.NEUTRAL, capabilities()) for i in range(n)
    }


def test_timeline_arithmetic_gap_and_scene_pause() -> None:
    doc = script(("a", 1000), ("b", 0), texts=3)
    doc = doc.model_copy(
        update={
            "segments": tuple(
                s.model_copy(update={"scene_id": "a" if s.segment_id != "s3" else "b"})
                for s in doc.segments
            )
        }
    )
    asm = assemble(clips([1900, 2000, 1900]), doc, styles(3), gap_ms=300, sample_rate_hz=RATE)
    assert [(s.start_ms, s.end_ms) for s in asm.segments] == [(0, 1900), (2200, 4200), (5500, 7400)]
    assert [(p.kind.value, p.start_ms, p.end_ms) for p in asm.pauses] == [
        ("GAP", 1900, 2200),
        ("GAP", 4200, 4500),
        ("SCENE_PAUSE", 4500, 5500),
    ]
    assert len(asm.samples) * 1000 // RATE == 7400  # the stem ends at the last clip


def test_zero_gap_and_single_segment() -> None:
    asm = assemble(
        clips([500]), script(("a", 0), texts=1), styles(1), gap_ms=0, sample_rate_hz=RATE
    )
    assert asm.pauses == ()
    assert asm.segments[0].end_ms == 500
    two = assemble(
        clips([500, 500]), script(("a", 0), texts=2), styles(2), gap_ms=0, sample_rate_hz=RATE
    )
    assert two.segments[1].start_ms == 500


def timeline_for(
    asm_segments: Sequence[c.TimelineSegment],
    total: int,
    source: c.TimelineSource = c.TimelineSource.PROVIDER_CLIPS,
) -> c.NarrationTimeline:
    return c.NarrationTimeline(
        script_id="scr_98d3acae-b594-7687-8641-4f666d21ff77",
        script_version=1,
        iteration=0,
        source=source,
        total_duration_ms=total,
        segments=tuple(asm_segments),
    )


def test_timeline_problems() -> None:
    doc = script(("a", 0), texts=2)
    asm = assemble(clips([500, 500]), doc, styles(2), gap_ms=100, sample_rate_hz=RATE)
    total = len(asm.samples) * 1000 // RATE
    assert timeline_problems(timeline_for(asm.segments, total), doc, total) == []
    assert timeline_problems(timeline_for(asm.segments, total), doc, total + 10)
    assert timeline_problems(timeline_for(asm.segments[:1], 500), doc, 500)  # a sentence is missing
    reversed_ = list(reversed(asm.segments))
    assert timeline_problems(timeline_for(reversed_, total), doc, total)


def marks(*triples: tuple[str, int, int]) -> list[c.SegmentMark]:
    return [c.SegmentMark(segment_id=s, start_ms=a, end_ms=b) for s, a, b in triples]


def test_marks_validation_refuses_unaligned_recordings() -> None:
    doc = script(("a", 0), texts=3)
    good = marks(("s1", 0, 3000), ("s2", 3200, 6000), ("s3", 6200, 9000))
    validate_marks(good, doc, duration_ms=9000, max_gap_ms=None)
    seg, pauses = timeline_from_marks(good, doc)
    assert [(s.start_ms, s.end_ms, s.duration_ms) for s in seg][1] == (3200, 6000, 2800)
    assert [(p.start_ms, p.end_ms) for p in pauses] == [(3000, 3200), (6000, 6200)]
    bad_sets = [
        marks(("s1", 0, 3000)),  # covers one of three sentences
        marks(("s1", 0, 3000), ("s2", 3200, 6000), ("s9", 6200, 9000)),  # unknown segment
        marks(("s1", 0, 3000), ("s1", 3200, 6000), ("s3", 6200, 9000)),  # duplicate
        marks(("s2", 0, 3000), ("s1", 3200, 6000), ("s3", 6200, 9000)),  # out of order
        marks(("s1", 0, 3000), ("s2", 2900, 6000), ("s3", 6200, 9000)),  # overlap
        marks(("s1", 0, 3000), ("s2", 3200, 6000), ("s3", 6200, 9500)),  # past the recording
        marks(("s1", 0, 3000), ("s2", 3200, 3200), ("s3", 6200, 9000)),  # empty
    ]
    for bad in bad_sets:
        with pytest.raises(InputInvalidError) as err:
            validate_marks(bad, doc, duration_ms=9000, max_gap_ms=None)
        assert err.value.details["violations"]
    with pytest.raises(InputInvalidError):
        validate_marks(
            good, doc, duration_ms=9000, max_gap_ms=100
        )  # gap of 200 ms above the maximum


def test_style_mapping_never_fakes_a_control() -> None:
    both = capabilities()
    none = capabilities(pace="NONE", emotion="NONE")
    assert map_style(c.Pace.FAST, c.Emotion.WARM, both) == StyleDecision(
        c.AppliedPace.FAST, c.AppliedEmotion.WARM
    )
    assert map_style(c.Pace.FAST, c.Emotion.WARM, none) == StyleDecision(
        c.AppliedPace.NONE, c.AppliedEmotion.NONE
    )
    segs = [
        c.ScriptSegment(
            segment_id="s1", text="x", pace=c.Pace.NORMAL, emotion=c.Emotion.WARM, scene_id="a"
        ),
        c.ScriptSegment(
            segment_id="s2", text="x", pace=c.Pace.NORMAL, emotion=c.Emotion.NEUTRAL, scene_id="a"
        ),
    ]
    assert applied_ratio(segs, [map_style(s.pace, s.emotion, none) for s in segs]) == (0, 1)
    assert applied_ratio(segs, [map_style(s.pace, s.emotion, both) for s in segs]) == (1, 1)
    assert distinct_variation(segs)
    assert not distinct_variation(segs[1:])


def test_pcm_helpers(tmp_path) -> None:  # type: ignore[no-untyped-def]
    samples = array("h", [0, 32767, -32768, 100, -100])
    assert count_clipped(samples) == 2
    assert peak_dbfs(samples) == 0.0
    assert peak_dbfs(array("h")) == -120.0
    assert rms_dbfs(array("h")) == -120.0
    assert rms_dbfs(array("h", [0, 0])) == -120.0
    path = tmp_path / "a.wav"
    write_s16(path, samples, RATE, 1)
    info, back = read_s16(path)
    assert (info.sample_rate_hz, info.channels, info.frames) == (RATE, 1, 5)
    assert list(back) == list(samples)
    assert wav_info(path).sample_width == 2
    (tmp_path / "bad.wav").write_bytes(b"nope")
    with pytest.raises(CorruptedOutputError):
        wav_info(tmp_path / "bad.wav")
    padded = silence_samples(100, RATE) + tone_samples(100) + silence_samples(100, RATE)
    trimmed = trim_silence(padded, RATE, 10, -50.0)
    assert len(trimmed) == (100 + 20) * RATE // 1000
    with pytest.raises(CorruptedOutputError):
        trim_silence(silence_samples(100, RATE), RATE, 0, -50.0)
