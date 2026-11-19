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

from agent_10_video_editor.canonical import canonical_json, sha256_hex
from agent_10_video_editor.config import AgentTenConfig
from agent_10_video_editor.contracts import TechnicalQcOutput
from agent_10_video_editor.encode import encode_table, resolve
from agent_10_video_editor.errors import violations_of
from agent_10_video_editor.ffmpeg import ArgvBuilder, ProcessFfmpegRunner, RunLimits
from agent_10_video_editor.media import ProbeService
from agent_10_video_editor.probe import EditListChecker, SsimParser, X264SeiParser
from agent_10_video_editor.qc import checks as C  # noqa: N812
from agent_10_video_editor.qc.selftest import SelfTestRecord
from agent_10_video_editor.qc.stage import QcStage
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.testing import make_config
from amw_core.enums import CheckVerdict, OutputStatus
from amw_core.errors import AmwError, ConfigInvalidError, RenderCrashError
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
    assert (s.target_bps, s.gop_frames, s.bframes) == (8_000_000, 15, 2)
    # the row's measured VBV proposal applies when no override is configured (ADR-014 3.4)
    assert (s.maxrate_bps, s.bufsize_bps) == (12_000_000, 16_000_000)
    assert (_resolve(fps=Fraction(60)).maxrate_bps, _resolve(fps=Fraction(60)).bufsize_bps) == (
        18_000_000,
        24_000_000,
    )
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
        assert a[a.index("-maxrate") + 1] == "12000000"
        assert a[a.index("-bufsize") + 1] == "16000000"
        assert "-minrate" not in a
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
    assert payload_data(out)["encoder"]["settings_sha256"] is not None
    mux = next(c.argv for c in world.runner.calls if c.kind == "mux")
    assert list(mux)[list(mux).index("-use_editlist") + 1] == "0"


@pytest.mark.unit
def test_reference_is_deleted_when_the_encode_fails(tmp_path: Path) -> None:
    world = World(tmp_path, shots=2)
    world.runner.crash_on_encode = {1}
    with pytest.raises(AmwError):
        RenderStage(world.deps()).run(world.render_input(), world.attempt)
    assert not list(tmp_path.rglob("segment_ref.part"))


@pytest.mark.unit
def test_an_ssim_pair_count_mismatch_is_not_measured(tmp_path: Path) -> None:
    world = World(tmp_path, shots=2)
    world.runner.ssim_pair_offset = 1  # one pair too many: frames are not aligned
    out = RenderStage(world.deps()).run(world.render_input(), world.attempt)
    quality = payload_data(out)["encoder"]["quality_metric"]
    assert quality["ssim_all"] is None
    assert quality["frames_measured"] == 0


@pytest.mark.unit
def test_a_segment_with_other_settings_fails_the_render(tmp_path: Path) -> None:
    world = World(tmp_path, shots=2)
    world.runner.strip_sei = True  # a segment without the x264 settings record
    with pytest.raises(RenderCrashError):
        RenderStage(world.deps()).run(world.render_input(), world.attempt)


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
    assert (rc["maxrate_bps"], rc["bufsize_bps"]) == (12_000_000, 16_000_000)
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
    assert sei["filler"] == "0"
    assert sei["nal_hrd"] == "none"
    assert (sei["vbv_maxrate"], sei["vbv_bufsize"]) == ("12000", "16000")
    final_path = tmp_path / "final_copy.mp4"
    final_path.write_bytes(final)
    assert not EditListChecker.has_edit_list(final_path)  # INF-13 "No Edit Lists"
    texts = X264SeiParser.texts_in_file(final_path)
    assert len(texts) == data["segments"]["planned"]  # one SEI per segment
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


def _encode(work: Path, name: str, *extra: str, src: str = "testsrc2=size=320x180:rate=30") -> Path:
    subprocess.run(  # noqa: S603
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", src, "-t", "1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1", *extra, name],
        check=True, cwd=work,
    )  # fmt: skip
    return work / name


X264 = "keyint=15:scenecut=0:open-gop=0:bframes=2:cabac=1"
GOOD = ["-r", "30", "-preset", "faster", "-profile:v", "high", "-b:v", "8000000",
        "-maxrate", "12000000", "-bufsize", "16000000", "-bf", "2", "-g", "15",
        "-sc_threshold", "0", "-x264-params", X264]  # fmt: skip
NO_ELST = ["-use_editlist", "0", "-movflags", "+faststart+negative_cts_offsets"]


def _concat(work: Path, names: list[str], out: str) -> Path:
    (work / "list.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
    subprocess.run(  # noqa: S603
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-f", "concat",
         "-safe", "0", "-i", "list.txt", "-c:v", "copy", *NO_ELST, "-f", "mp4", out],
        check=True, cwd=work,
    )  # fmt: skip
    return work / out


def _settings_of(work: Path, name: str, segments: int = 1, recorded: str | None = "same") -> Any:
    probe = ProbeService(ProcessFfmpegRunner(), ArgvBuilder(make_config().render), work)
    video = probe.full(name).video
    enc = make_config().render.encode
    texts = X264SeiParser.texts_in_file(work / name)
    measured = sha256_hex(canonical_json([sha256_hex(t.encode()) for t in texts]))
    keys = probe.keyframes(name)
    return C.qc_video_encoder_settings(
        codec_name=video.codec_name,
        profile=video.profile,
        pix_fmt=video.pix_fmt,
        field_order=video.field_order,
        r_frame_rate=video.r_frame_rate,
        level=video.level,
        has_b_frames=video.has_b_frames,
        edit_list=EditListChecker.has_edit_list(work / name),
        seis=[X264SeiParser.parse_text(t) for t in texts],
        expected_segments=segments,
        keyframes=keys,
        segment_starts=[30 * i for i in range(segments)],
        total_frames=30 * segments,
        settings_sha256_recorded=measured if recorded == "same" else recorded,
        settings_sha256_measured=measured,
        fps_num=30,
        fps_den=1,
        gop_frames=enc.gop_frames,
        bframes=enc.bframes,
        cabac=enc.cabac,
        target_bps=enc.target_bps,
        maxrate_bps=enc.maxrate_bps,
        bufsize_bps=enc.bufsize_bps,
    )


@real
@pytest.mark.integration
def test_a_wrong_encode_fails_the_settings_check(tmp_path: Path) -> None:
    _encode(tmp_path, "good.mp4", *GOOD, *NO_ELST)
    assert _settings_of(tmp_path, "good.mp4").verdict is CheckVerdict.PASS
    _encode(tmp_path, "elst.mp4", *GOOD)  # default MP4 mux writes an edit list
    assert "container.edit_list" in _settings_of(tmp_path, "elst.mp4").offending
    _encode(tmp_path, "baseline.mp4", "-r", "25", "-profile:v", "baseline", "-b:v", "8000000")
    bad = _settings_of(tmp_path, "baseline.mp4")
    assert bad.verdict is CheckVerdict.FAIL
    assert bad.blocking
    assert {"profile", "fps", "has_b_frames", "sei.bframes", "sei.cabac"} <= set(bad.offending)
    cbr = [*GOOD[:-1], f"{X264}:nal-hrd=cbr", *NO_ELST]
    _encode(tmp_path, "cbr.mp4", *cbr)
    padded = _settings_of(tmp_path, "cbr.mp4")
    assert padded.verdict is CheckVerdict.FAIL
    assert "sei.nal_hrd" in padded.offending  # x264 keeps rc=abr; nal-hrd=cbr would pad


@real
@pytest.mark.integration
def test_every_segment_is_checked_and_doctored_settings_text_fails(tmp_path: Path) -> None:
    _encode(tmp_path, "s0.mp4", *GOOD)
    _encode(tmp_path, "s1.mp4", "-r", "30", "-preset", "faster", "-crf", "30", "-bf", "0",
            "-g", "15", "-x264-params", "cabac=0")  # fmt: skip
    _concat(tmp_path, ["s0.mp4", "s0.mp4"], "both_good.mp4")
    assert _settings_of(tmp_path, "both_good.mp4", segments=2).verdict is CheckVerdict.PASS
    _concat(tmp_path, ["s0.mp4", "s1.mp4"], "mixed.mp4")
    mixed = _settings_of(tmp_path, "mixed.mp4", segments=2)
    assert mixed.verdict is CheckVerdict.FAIL  # a right FIRST segment is not enough
    assert {"sei.rc", "sei.bframes", "sei.cabac"} <= set(mixed.offending)
    assert mixed.details["segments_failing"] == [1]
    # a 2 Mbps encode whose SEI text is edited to say bitrate=8000: the declared text matches
    # the expectation, but the hash the render recorded of the real text does not
    _encode(tmp_path, "low.mp4", *[("2000000" if a == "8000000" else a) for a in GOOD], *NO_ELST)
    recorded = sha256_hex(
        canonical_json(
            [sha256_hex(t.encode()) for t in X264SeiParser.texts_in_file(tmp_path / "low.mp4")]
        )
    )
    data = (tmp_path / "low.mp4").read_bytes()
    assert b"bitrate=2000 " in data
    (tmp_path / "doctored.mp4").write_bytes(data.replace(b"bitrate=2000 ", b"bitrate=8000 ", 1))
    doctored = _settings_of(tmp_path, "doctored.mp4", recorded=recorded)
    assert doctored.verdict is CheckVerdict.FAIL
    assert doctored.offending == ("sei.binding",)


def _raw(work: Path, src: str, out: str) -> None:
    subprocess.run(  # noqa: S603
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", src,
         "-f", "rawvideo", "-pix_fmt", "yuv420p", out],
        check=True, cwd=work,
    )  # fmt: skip


@real
@pytest.mark.integration
def test_ssim_pairs_the_same_frames_as_an_independent_computation(tmp_path: Path) -> None:
    src = "testsrc2=size=64x48:rate=30,noise=alls=20:allf=t:all_seed=7"
    subprocess.run(  # noqa: S603
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", src, "-t", "1", "-c:v", "ffv1", "-pix_fmt", "yuv420p",
         "-f", "matroska", "ref.mkv"],
        check=True, cwd=tmp_path,
    )  # fmt: skip
    subprocess.run(  # noqa: S603
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", "ref.mkv",
         "-c:v", "libx264", "-preset", "faster", "-b:v", "150000", "-bf", "2", "-threads", "1",
         "enc.mp4"],
        check=True, cwd=tmp_path,
    )  # fmt: skip
    builder = ArgvBuilder(make_config().render)
    res = ProcessFfmpegRunner().run(
        builder.ssim("enc.mp4", "ref.mkv"), cwd=tmp_path, limits=RunLimits()
    )
    assert res.exit_code == 0
    ours = [line for line in res.stdout.splitlines() if line.startswith("n:")]
    assert len(ours) == 30  # one pair per frame, no repeated or skipped frame
    # independent: both decoded to raw frames, which carry no container timestamps at all
    _raw(tmp_path, "enc.mp4", "enc.yuv")
    _raw(tmp_path, "ref.mkv", "ref.yuv")
    raw_in = ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", "64x48", "-framerate", "30"]
    independent = ProcessFfmpegRunner().run(
        [str(FFMPEG), "-hide_banner", "-nostdin", "-nostats", *raw_in, "-i", "enc.yuv",
         *raw_in, "-i", "ref.yuv", "-lavfi", "[0:v][1:v]ssim=stats_file=-", "-f", "null", "-"],
        cwd=tmp_path, limits=RunLimits(),
    )  # fmt: skip
    theirs = [line for line in independent.stdout.splitlines() if line.startswith("n:")]
    assert ours == theirs  # per-frame values identical
    assert SsimParser.parse(res.stderr) == SsimParser.parse(independent.stderr)
    same = ProcessFfmpegRunner().run(
        builder.ssim("ref.mkv", "ref.mkv"), cwd=tmp_path, limits=RunLimits()
    )
    assert SsimParser.parse(same.stderr) == "1.000000"
    # sampling every 2nd frame (agent_10.render.quality_sample_every = 2)
    subprocess.run(  # noqa: S603
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", "ref.mkv",
         "-vf", "select='not(mod(n,2))',setpts=N/FRAME_RATE/TB", "-c:v", "ffv1",
         "-f", "matroska", "ref2.mkv"],
        check=True, cwd=tmp_path,
    )  # fmt: skip
    half = ProcessFfmpegRunner().run(
        builder.ssim("enc.mp4", "ref2.mkv", 2), cwd=tmp_path, limits=RunLimits()
    )
    halves = [line.split(" ", 1)[1] for line in half.stdout.splitlines() if line.startswith("n:")]
    assert halves == [line.split(" ", 1)[1] for line in theirs[::2]]


@real
@pytest.mark.integration
def test_mux_without_edit_lists_keeps_audio_in_sync(tmp_path: Path) -> None:
    """INF-13 "No Edit Lists": the B-frame delay and the AAC priming are compensated."""
    from agent_10_video_editor.inputs import CodecProfile

    _encode(tmp_path, "s0.mp4", *GOOD)
    _encode(tmp_path, "s1.mp4", *GOOD)
    subprocess.run(  # noqa: S603
        [str(FFMPEG), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "aevalsrc=exprs='if(between(t,0.5,0.5005),0.9,0)|if(between(t,0.5,0.5005),0.9,0)'"
         ":s=48000:d=2", "master.wav"],
        check=True, cwd=tmp_path,
    )  # fmt: skip
    profile = CodecProfile(
        codec="aac", profile="LC", sample_rate_hz=48000, channels=2, bitrate_bps=384000,
        encoder="aac", rate_mode="CBR",
    )  # fmt: skip
    argv, listing = ArgvBuilder(make_config().render).mux_argv(
        ["s0.mp4", "s1.mp4"], "master.wav", profile, 2000
    )
    (tmp_path / "concat.txt").write_text(listing, encoding="utf-8")
    assert ProcessFfmpegRunner().run(argv, cwd=tmp_path, limits=RunLimits()).exit_code == 0
    final = tmp_path / "final.part"
    assert not EditListChecker.has_edit_list(final)
    probe = ProbeService(ProcessFfmpegRunner(), ArgvBuilder(make_config().render), tmp_path)
    result = probe.full("final.part")
    assert result.video.start_time == "0.000000"
    assert result.audio is not None
    assert result.audio.start_time == "0.000000"
    assert result.audio.duration == result.video.duration == "2.000000"
    pcm = subprocess.run(  # noqa: S603
        [str(FFMPEG), "-v", "error", "-i", "final.part", "-map", "0:a", "-f", "s16le", "-ac", "1",
         "-"],
        check=True, cwd=tmp_path, capture_output=True,
    ).stdout  # fmt: skip
    samples = [int.from_bytes(pcm[i : i + 2], "little", signed=True) for i in range(0, len(pcm), 2)]
    peak = max(range(len(samples)), key=lambda k: abs(samples[k]))
    assert abs(peak - 24_000) <= 48  # the click decodes within 1 ms of 500 ms
