"""Integration tests with the real local FFmpeg/ffprobe on synthetic ``lavfi`` media (IT-01..IT-04,
FI-01, FI-13, S-07, R-02). Nothing real, nothing from the network; skipped if FFmpeg is absent."""

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from agent_10_video_editor.config import AgentTenConfig
from agent_10_video_editor.contracts import TechnicalQcOutput
from agent_10_video_editor.ffmpeg import ArgvBuilder, ProcessFfmpegRunner, ProcessResult, RunLimits
from agent_10_video_editor.qc.gate import PROFILE_CHECKS
from agent_10_video_editor.qc.selftest import QcSelfTest, SelfTestRecord
from agent_10_video_editor.qc.stage import QcStage
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.testing import make_config
from amw_core.enums import OutputStatus, RenderStatus
from amw_core.errors import InputInvalidError
from tests.agents.agent_10_video_editor.media import HAVE_FFMPEG, LavfiMedia
from tests.agents.agent_10_video_editor.support import (
    World,
    licensed_snapshot,
    payload_data,
    run_chain,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed"),
]


def _config() -> AgentTenConfig:
    # test values: 4 s segments; the closed GOP (15 frames, half of 30 fps) and the 8 Mbps
    # target come from data/encode_targets.json (ADR-014); "faster" keeps x264 at High
    return make_config(render={"segment_target_ms": 4000, "x264_preset": "faster"})


@pytest.fixture(scope="module")
def media(tmp_path_factory: pytest.TempPathFactory) -> LavfiMedia:
    return LavfiMedia(tmp_path_factory.mktemp("lavfi"))


def _world(tmp: Path, media: LavfiMedia, **kw: Any) -> World:
    world = World(tmp, shots=4, shot_ms=2000, chart=True, config=_config(), media=media, **kw)
    world.runner = ProcessFfmpegRunner()  # type: ignore[assignment]
    return world


class _SelfTests:
    def __init__(self, world: World, tmp: Path) -> None:
        self._world, self._tmp = world, tmp
        self.calls = 0

    def record_for(self, build_id: str) -> SelfTestRecord:
        self.calls += 1
        work = self._tmp / "selftest"
        work.mkdir(exist_ok=True)
        return QcSelfTest.run(
            ProcessFfmpegRunner(), ArgvBuilder(self._world.cfg.render), work, build_id
        )


def _final_bytes(world: World, out: Any) -> bytes:
    return world.storage.blobs[payload_data(out)["render_ref"]["uri"]]


@pytest.mark.integration
def test_it01_it03_whole_render_and_qc_on_synthetic_media(
    tmp_path: Path, media: LavfiMedia
) -> None:
    world = _world(tmp_path, media)
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    data = payload_data(chain["render"])
    assert data["frame_count"] == 240
    assert data["duration_ms"] == 8000
    assert data["probe"]["width_px"] == 1920
    assert data["probe"]["height_px"] == 1080
    assert data["probe"]["audio_sample_rate_hz"] == 48000
    assert data["probe"]["channels"] == 2
    assert data["encoder"]["audio_bitrate_nominal_bps"] == 384000
    assert data["probe"]["audio_bitrate_avg_bps"] < 384000  # the average is reported, not gated
    assert {r.check_id for r in chain["render"].validation_results} >= {
        "a10.q.colour_tags",
        "a10.q.gop_settings",
    }
    assert all(r.verdict == "PASS" for r in chain["render"].validation_results)
    qc = QcStage(world.deps(), _SelfTests(world, tmp_path)).run(chain["qc_input"], world.attempt)
    assert qc.status is OutputStatus.SUCCEEDED
    out = TechnicalQcOutput.model_validate(payload_data(qc))
    assert out.gate_verdict == "PASSED", out.failures
    assert {r.check_id for r in qc.validation_results if r.gate} == set(PROFILE_CHECKS)
    by_id = {r.check_id: r for r in qc.validation_results}
    for check in ("qc.video.codec_profile", "qc.video.cfr", "qc.video.fps_matches_project",
                  "qc.audio.true_peak", "qc.audio.codec", "qc.duration.vs_timeline"):  # fmt: skip
        assert by_id[check].verdict == "PASS", check
    assert out.selftest.passed
    # the evidence pack exists as real images
    frame_bytes = [world.storage.blobs[f.uri] for f in out.evidence.sample_frames_ref]
    assert frame_bytes
    assert all(b.startswith(b"\x89PNG") for b in frame_bytes)
    assert world.storage.blobs[out.evidence.contact_sheet_ref.uri].startswith(b"\x89PNG")
    manifest = json.loads(world.storage.blobs[out.evidence.manifest_ref.uri])
    assert next(f["frame_id"] for f in manifest["frames"]) == "f01"
    assert (
        hashlib.sha256(_final_bytes(world, chain["render"])).hexdigest()
        == data["render_ref"]["sha256"]
    )


@pytest.mark.integration
def test_it04_revision_iteration_reuses_unchanged_segments(
    tmp_path: Path, media: LavfiMedia
) -> None:
    world = _world(tmp_path, media)
    first = RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert payload_data(first)["segments"]["encoded"] == 2
    data, ext = media.shot("sh04-revised", 2000)
    world.revise_shot(3, data, ext)  # only the last shot changes
    second = RenderStage(world.deps()).run(world.render_input(iteration=1), world.attempt)
    segs = payload_data(second)["segments"]
    assert segs["reused"] == 1
    assert segs["encoded"] == 1
    assert (
        payload_data(second)["render_ref"]["sha256"] != payload_data(first)["render_ref"]["sha256"]
    )


class _StoppingRunner:
    """Real runner whose first segment encode is stopped after ``after_s`` seconds (SIGTERM)."""

    def __init__(self, after_s: float) -> None:
        self._inner = ProcessFfmpegRunner(poll_ms=10)
        self._after = after_s
        self.armed = True
        self.stopped = 0

    def run(self, argv: Any, *, cwd: Path, limits: RunLimits, stop: Any = None) -> ProcessResult:
        is_segment = "-filter_complex" in argv and "segment.part" in argv
        if not (is_segment and self.armed):
            return self._inner.run(argv, cwd=cwd, limits=limits, stop=stop)
        self.armed = False
        started = threading.Event()
        timer = threading.Timer(self._after, started.set)
        timer.start()
        result = self._inner.run(argv, cwd=cwd, limits=limits, stop=lambda: started.is_set())
        timer.cancel()
        if result.killed_by == "SIGTERM":
            self.stopped += 1
        return result


@pytest.mark.failure_injection
def test_fi01_kill_mid_segment_resume_is_byte_identical(tmp_path: Path, media: LavfiMedia) -> None:
    reference = _world(tmp_path / "ref", media)
    ref_out = RenderStage(reference.deps()).run(reference.render_input(), reference.attempt)
    world = _world(tmp_path / "run", media)
    killer = _StoppingRunner(after_s=0.3)
    world.runner = killer  # type: ignore[assignment]
    stage = RenderStage(world.deps())
    interrupted = stage.run(world.render_input(), world.attempt)
    assert killer.stopped == 1
    assert interrupted.status is OutputStatus.SUSPENDED
    assert not any(
        "segments" in uri for uri in world.storage.blobs
    )  # the .part never became a blob
    done = stage.run(world.render_input(), world.attempt)
    assert done.status is OutputStatus.SUCCEEDED
    assert _final_bytes(world, done) == _final_bytes(reference, ref_out)
    assert (
        payload_data(done)["render_ref"]["sha256"] == payload_data(ref_out)["render_ref"]["sha256"]
    )


@pytest.mark.failure_injection
def test_fi13_self_drain_timer_stops_a_running_segment_before_the_window(
    tmp_path: Path, media: LavfiMedia
) -> None:
    world = _world(tmp_path, media)

    class _TimerRunner(_StoppingRunner):
        def run(
            self, argv: Any, *, cwd: Path, limits: RunLimits, stop: Any = None
        ) -> ProcessResult:
            if "-filter_complex" in argv and self.armed:
                self.armed = False
                threading.Timer(0.3, world.timers.fire_all).start()  # act_by reached mid-encode
            return ProcessFfmpegRunner(poll_ms=10).run(argv, cwd=cwd, limits=limits, stop=stop)

    world.runner = _TimerRunner(0)  # type: ignore[assignment]
    stage = RenderStage(world.deps())
    out = stage.run(world.render_input(), world.attempt)
    assert out.status is OutputStatus.SUSPENDED
    assert out.next_action.wait_reason is not None
    assert not list((world.scratch).rglob("segment.part"))  # the .part was discarded
    done = RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert done.status is OutputStatus.SUCCEEDED


@pytest.mark.security
def test_s07_network_and_playlist_inputs_are_refused_by_the_protocol_whitelist(
    tmp_path: Path,
) -> None:
    (tmp_path / "concat.txt").write_text("file 'http://127.0.0.1:9/a.mp4'\n")
    result = ProcessFfmpegRunner().run(
        ["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-f", "concat",
         "-safe", "0", "-i", "concat.txt", "-f", "null", "-"],
        cwd=tmp_path, limits=RunLimits(timeout_ms=20_000),
    )  # fmt: skip
    assert result.exit_code != 0


@pytest.mark.integration
def test_r02_selftest_fixtures_yield_their_asserted_verdicts(tmp_path: Path) -> None:
    record = QcSelfTest.run(ProcessFfmpegRunner(), ArgvBuilder(_config().render), tmp_path, "build")
    assert record.passed, [c for c in record.cases if not c.ok]
    assert {c.name for c in record.cases} >= {
        "clean.true_peak",
        "hot.true_peak",
        "black.black",
        "frozen.freeze",
        "silent.silence",
        "offset.av_start",
        "srt.overlap",
        "settings.encoder_settings",
        "baseline.encoder_settings",
        "settings.quality_metric",
    }


class _HotMedia(LavfiMedia):
    """Audio master far over full scale (clipped): the true-peak gate must FAIL."""

    def master(self, duration_ms: int) -> bytes:
        out = self._root / f"hot{duration_ms}.wav"
        self._ff(
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-af", "volume=30dB",
            "-t", f"{duration_ms / 1000:.3f}", "-ac", "2", str(out),
        )  # fmt: skip
        return out.read_bytes()


class _SilentMedia(LavfiMedia):
    def master(self, duration_ms: int) -> bytes:
        out = self._root / f"silent{duration_ms}.wav"
        self._ff(
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{duration_ms / 1000:.3f}",
            str(out),
        )  # fmt: skip
        return out.read_bytes()


@pytest.mark.integration
def test_failing_gate_end_to_end_with_real_ffmpeg(tmp_path: Path) -> None:
    hot = _HotMedia(tmp_path / "media")
    (tmp_path / "media").mkdir()
    world = _world(tmp_path, hot)
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    qc = QcStage(world.deps(), _SelfTests(world, tmp_path)).run(chain["qc_input"], world.attempt)
    assert qc.status is OutputStatus.SUCCEEDED  # a failed gate is not a failed task
    out = TechnicalQcOutput.model_validate(payload_data(qc))
    assert out.gate_verdict == "FAILED"
    failed = {f.check_id: f for f in out.failures}
    assert "qc.audio.true_peak" in failed
    assert failed["qc.audio.true_peak"].remedy_stage == "s07_voice"
    assert failed["qc.audio.true_peak"].measured is not None
    assert out.measurements.true_peak_dbtp > -1.0
    row = world.renders.rows[(world.org, payload_data(chain["render"])["render_id"])]
    assert row.status is RenderStatus.QC_FAILED
    assert any(r.check_id == "qc.audio.true_peak" and r.verdict == "FAIL"
               for r in world.qc_results.rows.values())  # fmt: skip


@pytest.mark.integration
def test_silent_audio_end_to_end_is_a_gate_fail_not_a_crash(tmp_path: Path) -> None:
    silent = _SilentMedia(tmp_path / "media")
    (tmp_path / "media").mkdir()
    world = _world(tmp_path, silent)
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    qc = QcStage(world.deps(), _SelfTests(world, tmp_path)).run(chain["qc_input"], world.attempt)
    assert qc.status is OutputStatus.SUCCEEDED
    out = TechnicalQcOutput.model_validate(payload_data(qc))
    assert out.gate_verdict == "FAILED"
    assert "qc.audio.integrated_lufs" in {f.check_id for f in out.failures}


@pytest.mark.integration
def test_a_source_clip_shorter_than_its_shot_is_refused_not_frozen(
    tmp_path: Path, media: LavfiMedia
) -> None:
    world = _world(tmp_path, media)
    data, ext = media.shot("too-short", 800)  # the last shot needs 2 s
    world.revise_shot(3, data, ext)
    with pytest.raises(InputInvalidError) as err:
        RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert "SOURCE_TOO_SHORT:sh04" in err.value.details["violations"]
