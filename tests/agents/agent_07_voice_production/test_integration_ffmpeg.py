"""IT-02: ``s07_master`` on a synthetic tone with the real FFmpeg of the dev environment.

The stem is generated at test time (bursts of a synthetic tone with silences): no real voice
recording is ever used. Skipped when ffmpeg or ffprobe is not installed.
"""

import hashlib
import json
import math
import shutil
from array import array
from pathlib import Path
from typing import Any

import pytest

from agent_07_voice_production import contracts as c
from agent_07_voice_production.ffmpeg import FfmpegAudioTools, SubprocessRunner
from agent_07_voice_production.master import FfmpegMasteringBackend
from agent_07_voice_production.master_stage import AudioMasterStage, MasterDeps
from agent_07_voice_production.pcm import wav_info, write_s16
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import OutputStatus
from amw_core.ids import CHANNEL
from amw_core.testing.memory import MemoryCheckpointStore
from tests.agents.agent_07_voice_production.master_world import ORG
from tests.agents.agent_07_voice_production.support import (
    RATE,
    FakeClock,
    FakeControl,
    FakeFacts,
    MemoryBlobs,
    MemoryTenancy,
    config,
)
from tests.agents.agent_07_voice_production.voice_world import make_task_input

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
        reason="ffmpeg not installed",
    ),
]


def synthetic_stem(
    path: Path, *, amplitude: float, clip: bool = False, long_gap_s: float = 0.0
) -> int:
    """Tone bursts with 0.4 s gaps (and optionally one long gap); returns the sample count."""
    samples: array[int] = array("h")
    peak = int(32767 * amplitude)
    for burst in range(6):
        for i in range(RATE):
            samples.append(int(peak * math.sin(2 * math.pi * 220 * i / RATE)))
        gap = 0.4 + (long_gap_s if burst == 2 else 0.0)
        samples.extend(array("h", bytes(2 * int(RATE * gap))))
    if clip:
        for i in range(5):
            samples[RATE // 2 + i] = 32767
    write_s16(path, samples, RATE, 1)
    return len(samples)


def run_master(tmp: Path, stem_path: Path, **cfg: Any) -> tuple[TaskOutput, MemoryBlobs, int]:
    blobs = MemoryBlobs()
    data = stem_path.read_bytes()
    info = wav_info(stem_path)
    narration = f"amw-blob://{ORG}/jobs/j/s07_voice/narration.wav"
    timeline_ref = f"amw-blob://{ORG}/jobs/j/s07_voice/timeline.json"
    blobs.seed(narration, data)
    total_ms = info.frames * 1000 // info.sample_rate_hz
    timeline = c.NarrationTimeline(
        script_id="scr_98d3acae-b594-7687-8641-4f666d21ff77",
        script_version=1,
        iteration=0,
        source=c.TimelineSource.PROVIDER_CLIPS,
        total_duration_ms=total_ms,
        segments=(
            c.TimelineSegment(
                segment_id="s1",
                start_ms=0,
                end_ms=total_ms,
                duration_ms=total_ms,
                pace_requested=c.Pace.NORMAL,
                emotion_requested=c.Emotion.NEUTRAL,
                pace_applied=c.AppliedPace.NONE,
                emotion_applied=c.AppliedEmotion.NONE,
                spoken_text_sha256=None,
                reused_clip=False,
                idempotency_key=None,
            ),
        ),
    )
    tl_bytes = timeline.model_dump_json().encode()
    blobs.seed(timeline_ref, tl_bytes)
    payload = {
        "iteration": 0,
        "narration_ref": narration,
        "narration_sha256": hashlib.sha256(data).hexdigest(),
        "timeline_ref": timeline_ref,
        "timeline_sha256": hashlib.sha256(tl_bytes).hexdigest(),
        "music_stem": None,
        "deliberate_pause_spans": [],
    }
    tools = FfmpegAudioTools(SubprocessRunner())
    deps = MasterDeps(
        config=config(**cfg),
        storage=blobs,
        tenancy=MemoryTenancy(),
        checkpoints=MemoryCheckpointStore(),
        facts=FakeFacts(),
        tools=tools,
        backend=FfmpegMasteringBackend(SubprocessRunner(), tools),
        clock=FakeClock(),
        control=FakeControl(),
        scratch_root=tmp / "scratch",
    )
    task = make_task_input(ORG, CHANNEL.new(), payload, "agent_07.audio_master.input", "agent_07")
    out = AudioMasterStage(deps).run(task, "att_01939e5a-7c3b-7d1e-8a4f-0123456789a1")
    return out, blobs, info.frames


def test_quiet_stem_is_mastered_to_the_delivery_spec(tmp_path: Path) -> None:
    stem = tmp_path / "stem.wav"
    frames = synthetic_stem(stem, amplitude=0.05)
    out, blobs, _ = run_master(tmp_path, stem, tolerance_lu=1.0, max_silence_ms=2000)
    assert out.status is OutputStatus.SUCCEEDED, out.error
    assert out.payload is not None
    assert out.payload.data is not None
    data = out.payload.data
    post = data["codec_verification"]["post_codec"]
    assert data["gate_verdict"] == "PASSED", data["gate_reasons"]
    assert post["true_peak_dbtp"] <= -1.0  # measured after the AAC-LC encode and decode
    assert abs(post["integrated_lufs"] - (-14.0)) <= 1.0
    assert data["measurements"]["duration_delta_samples"] == 0  # sample-exact, never resampled
    assert data["master"]["sample_rate_hz"] == 48000
    assert data["master"]["channels"] == 2
    assert data["codec_verification"]["bitrate_bps"] >= 384_000
    assert data["measurements"]["pre"]["integrated_lufs"] < -20  # the stem really was quiet
    master_uri = data["master"]["master_uri"]
    master_file = tmp_path / "master.wav"
    master_file.write_bytes(blobs.data[master_uri])
    info = wav_info(master_file)
    assert (info.sample_rate_hz, info.channels, info.frames) == (48_000, 2, frames)
    assert data["codec_profile"]["encoder"].startswith("aac (ffmpeg")


def test_loud_stem_is_limited_below_the_ceiling(tmp_path: Path) -> None:
    stem = tmp_path / "stem.wav"
    synthetic_stem(stem, amplitude=0.98)
    out, _, _ = run_master(tmp_path, stem, tolerance_lu=2.0)
    assert out.payload is not None
    assert out.payload.data is not None
    post = out.payload.data["codec_verification"]["post_codec"]
    assert out.status is OutputStatus.SUCCEEDED
    assert post["true_peak_dbtp"] <= -1.0 or out.payload.data["gate_verdict"] == "FAILED"
    assert out.payload.data["mastering"]["passes"] <= 3


def test_clipped_stem_fails_the_gate_with_the_remedy_stage(tmp_path: Path) -> None:
    stem = tmp_path / "stem.wav"
    synthetic_stem(stem, amplitude=0.2, clip=True)
    out, _, _ = run_master(tmp_path, stem)
    assert out.status is OutputStatus.SUCCEEDED  # a failed gate is not an error
    assert out.payload is not None
    assert out.payload.data is not None
    assert out.payload.data["gate_verdict"] == "FAILED"
    assert [g["check_id"] for g in out.payload.data["gate_reasons"]] == ["qc.voice.clipping"]
    failing = [r for r in out.validation_results if r.gate and r.verdict.value == "FAIL"]
    assert failing
    assert failing[0].remedy_stage_id == "s07_voice"
    assert out.next_action.reason == "gate FAILED: qc.voice.clipping"


def test_dead_air_outside_a_pause_fails_and_is_measured_by_silencedetect(tmp_path: Path) -> None:
    stem = tmp_path / "stem.wav"
    synthetic_stem(stem, amplitude=0.1, long_gap_s=3.0)
    out, _, _ = run_master(tmp_path, stem, max_silence_ms=2000)
    assert out.payload is not None
    assert out.payload.data is not None
    assert [g["check_id"] for g in out.payload.data["gate_reasons"]] == ["a07.silence.max_run"]
    runs = out.payload.data["measurements"]["silence_runs"]
    assert any(r["end_ms"] - r["start_ms"] >= 3000 and not r["in_deliberate_pause"] for r in runs)
    assert out.payload.data["measurements"]["noise_floor_dbfs"] is not None


def test_real_tools_measure_a_known_tone(tmp_path: Path) -> None:
    stem = tmp_path / "stem.wav"
    synthetic_stem(stem, amplitude=0.1)
    tools = FfmpegAudioTools(SubprocessRunner())
    result = tools.analyse(stem, silence_noise_db=-50.0, silence_min_s=0.3)
    assert result.stream.sample_rate_hz == 48_000
    assert result.clipping_samples == 0
    assert result.loudness.integrated_lufs is not None
    assert -40 < result.loudness.integrated_lufs < -10
    assert result.loudness.true_peak_dbtp is not None
    assert result.loudness.true_peak_dbtp < -15
    assert len(result.silence_runs) == 6  # five gaps of 0.4 s and the trailing one
    assert tools.build().startswith("ffmpeg ")
    assert json.loads(json.dumps(result.stream.duration_ms)) == result.stream.duration_ms
