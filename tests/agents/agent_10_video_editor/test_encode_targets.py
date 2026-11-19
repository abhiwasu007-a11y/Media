"""ADR-014 / owner decision D10: the bitrate is an encoder target, never a measured floor.

Unit: the encode table and its resolution rules. Real FFmpeg (tiny renders): code-made still
graphics encode under the delivery settings with no padding and pass the encoder-settings check;
the SSIM against the lossless reference is computed and reported; a wrong encode (Baseline
profile, wrong frame rate) fails the settings check.
"""

import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from agent_10_video_editor.config import AgentTenConfig
from agent_10_video_editor.contracts import TechnicalQcOutput
from agent_10_video_editor.encode import encode_table, resolve
from agent_10_video_editor.errors import violations_of
from agent_10_video_editor.ffmpeg import ArgvBuilder, ProcessFfmpegRunner, RunLimits
from agent_10_video_editor.media import ProbeService
from agent_10_video_editor.probe import SsimParser, X264SeiParser
from agent_10_video_editor.qc import checks as C  # noqa: N812
from agent_10_video_editor.qc.selftest import SelfTestRecord
from agent_10_video_editor.qc.stage import QcStage
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.testing import make_config
from amw_core.enums import CheckVerdict, OutputStatus
from amw_core.errors import ConfigInvalidError
from tests.agents.agent_10_video_editor.media import FFMPEG, HAVE_FFMPEG, LavfiMedia
from tests.agents.agent_10_video_editor.support import (
    World,
    licensed_snapshot,
    payload_data,
    run_chain,
)

F30 = Fraction(30)


def _resolve(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "width_px": 1920,
        "height_px": 1080,
        "fps": F30,
        "video_bitrate_bps": None,
        "video_maxrate_bps": None,
        "video_bufsize_bps": None,
        "gop_frames": None,
        "x264_preset": "faster",
    }
    return resolve(**{**base, **kw})


@pytest.mark.unit
def test_table_rows_are_the_inf12_1080p_values_with_their_source() -> None:
    table = encode_table()
    std = table.target_for(1920, 1080, Fraction(30))
    high = table.target_for(1920, 1080, Fraction(60))
    assert std is not None
    assert std.target_bps == 8_000_000
    assert "INF-12" in std.source
    assert high is not None
    assert high.target_bps == 12_000_000
    assert "INF-12" in high.source
    for fps in (Fraction(24), Fraction(25)):
        assert table.target_for(1920, 1080, fps) == std
    for fps in (Fraction(48), Fraction(50)):
        assert table.target_for(1920, 1080, fps) == high
    # REQUIRES REVIEW: no row for other sizes, vertical video or fractional rates
    assert table.target_for(2560, 1440, F30) is None
    assert table.target_for(1080, 1920, F30) is None
    assert table.target_for(1920, 1080, Fraction(30000, 1001)) is None
    assert (table.bframes, table.cabac, table.closed_gop) == (2, True, True)


@pytest.mark.unit
def test_resolution_rules() -> None:
    s = _resolve()
    assert (s.target_bps, s.gop_frames, s.bframes, s.maxrate_bps) == (8_000_000, 15, 2, None)
    assert s.recorded()["mode"] == "ABR"
    assert s.recorded()["filler"] is False
    assert _resolve(fps=Fraction(60)).gop_frames == 30
    assert _resolve(fps=Fraction(60)).target_bps == 12_000_000
    assert _resolve(video_bitrate_bps=8_000_000).target_bps == 8_000_000  # equal: accepted
    capped = _resolve(video_maxrate_bps=12_000_000, video_bufsize_bps=16_000_000)
    assert (capped.maxrate_bps, capped.bufsize_bps) == (12_000_000, 16_000_000)
    operator = _resolve(width_px=1080, height_px=1920, video_bitrate_bps=8_000_000)
    assert operator.target_source.startswith("OPERATOR_CONFIG")
    cases: list[tuple[dict[str, Any], str]] = [
        ({"video_bitrate_bps": 20_000_000}, "ENCODE_TARGET_CONFLICT"),
        ({"width_px": 2560, "height_px": 1440}, "ENCODE_TARGET_REQUIRES_REVIEW"),
        ({"x264_preset": "ultrafast"}, "X264_PRESET_NOT_ALLOWED"),
        ({"x264_preset": "veryfast"}, "X264_PRESET_NOT_ALLOWED"),
        ({"video_maxrate_bps": 8_000_000, "video_bufsize_bps": 16_000_000},
         "VBR_MAXRATE_NOT_ABOVE_TARGET"),
        ({"video_maxrate_bps": 12_000_000}, "VBV_MAXRATE_WITHOUT_BUFSIZE"),
        ({"video_bufsize_bps": 16_000_000}, "VBV_BUFSIZE_WITHOUT_MAXRATE"),
        ({"gop_frames": 60}, "GOP_CONFLICT"),
        ({"fps": Fraction(25), "gop_frames": None}, "GOP_REQUIRES_REVIEW"),
    ]  # fmt: skip
    for change, reason in cases:
        with pytest.raises(ValueError, match=reason):
            _resolve(**change)
    assert _resolve(fps=Fraction(25), gop_frames=12).gop_frames == 12  # operator value


@pytest.mark.unit
def test_config_refuses_an_unresolvable_encode_at_load() -> None:
    with pytest.raises(ConfigInvalidError) as info:
        make_config(render={"video_bitrate_bps": 20_000_000})
    assert "REASON:ENCODE_TARGET_CONFLICT" in violations_of(info.value)
    with pytest.raises(ConfigInvalidError):
        make_config(render={"x264_preset": "ultrafast"})
    with pytest.raises(ConfigInvalidError):
        make_config(render={"preset_key": "shorts_9x16"})  # no row: REQUIRES REVIEW
    shorts = make_config(render={"preset_key": "shorts_9x16", "video_bitrate_bps": 8_000_000})
    assert shorts.render.encode.target_bps == 8_000_000


@pytest.mark.unit
def test_segment_argv_has_the_target_a_lossless_reference_and_never_filler(
    tmp_path: Path,
) -> None:
    world = World(tmp_path, shots=2)
    out = RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert out.status is OutputStatus.SUCCEEDED
    segments = [c.argv for c in world.runner.calls if c.kind == "segment"]
    assert segments
    for argv in segments:
        a = list(argv)
        assert a[a.index("-b:v") + 1] == "8000000"
        assert "-maxrate" not in a
        assert "-minrate" not in a
        assert "-bufsize" not in a
        params = a[a.index("-x264-params") + 1]
        assert "nal-hrd" not in params
        assert "filler" not in params
        assert "bframes=2" in params
        assert "cabac=1" in params
        assert "keyint=15" in params
        assert a[a.index("-preset") + 1] == "faster"
        assert a[-1] == "segment_ref.part"
        assert "ffv1" in a
    assert [c.kind for c in world.runner.calls].count("ssim") == len(segments)
    quality = payload_data(out)["encoder"]["quality_metric"]
    assert quality["ssim_all"] == "0.990000"
    assert quality["frames_measured"] == payload_data(out)["frame_count"]
    assert not list(tmp_path.rglob("segment_ref.part"))  # scratch only, deleted


# ----------------------------------------------------------------------------- real FFmpeg

real = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")


class _StillMedia(LavfiMedia):
    """Every shot is a code-made still graphic (a PNG), the content of dry-run break 8."""

    def shot(self, label: str, duration_ms: int) -> tuple[bytes, str]:
        return self.still(f"still-{label}"), "png"


class _PassingSelfTests:
    def record_for(self, build_id: str) -> SelfTestRecord:
        return SelfTestRecord(build_id, ())


@pytest.fixture(scope="module")
def stills(tmp_path_factory: pytest.TempPathFactory) -> _StillMedia:
    return _StillMedia(tmp_path_factory.mktemp("stills"))


def _cfg() -> AgentTenConfig:
    return make_config(render={"segment_target_ms": 2000, "x264_preset": "faster"})


@real
@pytest.mark.integration
def test_still_graphics_encode_at_the_target_without_padding_and_pass_qc(
    tmp_path: Path, stills: _StillMedia
) -> None:
    world = World(tmp_path, shots=2, shot_ms=1000, config=_cfg(), media=stills)
    world.runner = ProcessFfmpegRunner()  # type: ignore[assignment]
    world.licences.snapshot_value = licensed_snapshot(world)
    chain = run_chain(world)
    data = payload_data(chain["render"])
    rc = data["encoder"]["rate_control"]
    assert rc["mode"] == "ABR"
    assert rc["target_bps"] == 8_000_000
    assert rc["filler"] is False
    assert rc["maxrate_bps"] is None
    assert "INF-12" in rc["target_source"]
    # a still picture needs far fewer bits than the target: no padding up to it
    assert data["probe"]["video_bitrate_bps"] < 8_000_000
    quality = data["encoder"]["quality_metric"]
    assert quality["metric"] == "SSIM"
    assert quality["frames_measured"] == data["frame_count"]
    assert quality["ssim_all"] is not None
    assert 0.9 < float(quality["ssim_all"]) <= 1.0
    assert quality["vmaf"] is None
    assert quality["vmaf_status"] in (
        "LIBVMAF_NOT_IN_BUILD",
        "LIBVMAF_IN_BUILD_NOT_USED",
    )
    final = world.storage.blobs[data["render_ref"]["uri"]]
    at = final.find(b"x264 - core ")
    sei = X264SeiParser.find(final[at:])
    assert sei is not None
    assert (sei["rc"], sei["bitrate"], sei["bframes"], sei["cabac"]) == ("abr", "8000", "2", "1")
    assert (sei["open_gop"], sei["keyint"]) == ("0", "15")
    assert "filler" not in sei or sei["filler"] == "0"
    qc = QcStage(world.deps(), _PassingSelfTests()).run(chain["qc_input"], world.attempt)
    assert qc.status is OutputStatus.SUCCEEDED
    by_id = {r.check_id: r for r in qc.validation_results}
    assert by_id["qc.video.encoder_settings"].verdict == "PASS"
    assert by_id["qc.video.encoder_settings"].blocking
    metric = by_id["qc.video.quality_metric"]
    assert metric.verdict == "WARN"
    assert not metric.blocking
    assert metric.threshold is None
    assert metric.measured == float(quality["ssim_all"])
    assert "REPORT_ONLY" in metric.message
    assert "qc.video.bitrate" not in by_id
    out = TechnicalQcOutput.model_validate(payload_data(qc))
    assert "qc.video.quality_metric" not in {f.check_id for f in out.failures}
    report = world.storage.blobs[out.evidence.report_ref.uri].decode()
    assert "qc.video.quality_metric" in report
    assert quality["ssim_all"] in report


def _encode(work: Path, name: str, *extra: str) -> Path:
    subprocess.run(  # noqa: S603
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-t", "1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1", *extra, name],
        check=True, cwd=work,
    )  # fmt: skip
    return work / name


def _settings_of(work: Path, name: str) -> Any:
    probe = ProbeService(ProcessFfmpegRunner(), ArgvBuilder(make_config().render), work)
    video = probe.full(name).video
    enc = make_config().render.encode
    return C.qc_video_encoder_settings(
        codec_name=video.codec_name,
        profile=video.profile,
        pix_fmt=video.pix_fmt,
        field_order=video.field_order,
        r_frame_rate=video.r_frame_rate,
        level=video.level,
        sei=X264SeiParser.scan_file(work / name),
        fps_num=30,
        fps_den=1,
        gop_frames=enc.gop_frames,
        bframes=enc.bframes,
        cabac=enc.cabac,
        target_bps=enc.target_bps,
        maxrate_bps=None,
        bufsize_bps=None,
    )


@real
@pytest.mark.integration
def test_a_wrong_encode_fails_the_settings_check(tmp_path: Path) -> None:
    x264 = "keyint=15:min-keyint=15:scenecut=0:open-gop=0:bframes=2:cabac=1"
    good = ["-r", "30", "-preset", "faster", "-profile:v", "high", "-b:v", "8000000",
            "-bf", "2", "-x264-params", x264]  # fmt: skip
    _encode(tmp_path, "good.mp4", *good)
    assert _settings_of(tmp_path, "good.mp4").verdict is CheckVerdict.PASS
    _encode(tmp_path, "baseline.mp4", "-r", "25", "-profile:v", "baseline", "-b:v", "8000000")
    bad = _settings_of(tmp_path, "baseline.mp4")
    assert bad.verdict is CheckVerdict.FAIL
    assert bad.blocking
    assert {"profile", "fps", "sei.bframes", "sei.cabac"} <= set(bad.offending)
    cbr = [*good[:-1], f"{x264}:nal-hrd=cbr", "-maxrate", "8000000", "-bufsize", "16000000"]
    _encode(tmp_path, "cbr.mp4", *cbr)
    padded = _settings_of(tmp_path, "cbr.mp4")
    assert padded.verdict is CheckVerdict.FAIL
    assert {"sei.rc", "sei.nal_hrd"} <= set(padded.offending)


@real
@pytest.mark.integration
def test_ssim_is_computed_against_a_lossless_reference(tmp_path: Path) -> None:
    _encode(tmp_path, "enc.mp4", "-preset", "faster", "-b:v", "8000000")
    subprocess.run(  # noqa: S603
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-t", "1",
         "-c:v", "ffv1", "-pix_fmt", "yuv420p", "-f", "matroska", "ref.mkv"],
        check=True, cwd=tmp_path,
    )  # fmt: skip
    argv = ArgvBuilder(make_config().render).ssim("enc.mp4", "ref.mkv")
    res = ProcessFfmpegRunner().run(argv, cwd=tmp_path, limits=RunLimits())
    assert res.exit_code == 0
    value = SsimParser.parse(res.stderr)
    assert 0.9 < float(value) <= 1.0
    same = ProcessFfmpegRunner().run(
        ArgvBuilder(make_config().render).ssim("ref.mkv", "ref.mkv"),
        cwd=tmp_path,
        limits=RunLimits(),
    )
    assert SsimParser.parse(same.stderr) == "1.000000"
