"""F-16, F-22, F-23: command construction and parsers against recorded FFmpeg/ffprobe output."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_07_voice_production.config import DenoiseMode
from agent_07_voice_production.ffmpeg import (
    FfmpegAudioTools,
    ProcessResult,
    ebur128_command,
    encode_command,
    limiter_limit,
    parse_ebur128,
    parse_ffmpeg_version,
    parse_ffprobe,
    parse_silencedetect,
    render_command,
    render_filter_chain,
    silencedetect_command,
    working_format_command,
)
from amw_core.errors import AgentCrashError, RenderCrashError

FIX = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.unit


def test_ebur128_command_is_the_exact_18_command() -> None:
    cmd = ebur128_command("ffmpeg", Path("/s/in.wav"))
    assert cmd == [
        "ffmpeg",
        "-nostats",
        "-hide_banner",
        "-i",
        "/s/in.wav",
        "-map",
        "0:a:0",
        "-af",
        "ebur128=peak=true:framelog=quiet",
        "-f",
        "null",
        "-",
    ]


def test_silencedetect_command_voice_parameters() -> None:
    cmd = silencedetect_command("ffmpeg", Path("/s/in.wav"), noise_db=-50.0, min_s=0.3)
    assert "silencedetect=n=-50dB:d=0.3" in cmd
    assert cmd[-3:] == ["-f", "null", "-"]
    assert (
        silencedetect_command("f", Path("x"), noise_db=-50, min_s=1)[8]
        == "silencedetect=n=-50dB:d=1"
    )


def test_no_shell_string_anywhere() -> None:
    for cmd in (
        working_format_command("ffmpeg", Path("a"), Path("b")),
        encode_command("ffmpeg", Path("a"), Path("b"), bitrate_bps=384_000),
        render_command(
            "ffmpeg",
            Path("a"),
            Path("b"),
            gain_db=1,
            ceiling_dbtp=-1.5,
            input_channels=1,
            denoise=DenoiseMode.OFF,
        ),
    ):
        assert isinstance(cmd, list)
        assert all(isinstance(p, str) for p in cmd)


def test_render_chain_gain_then_limiter_and_dual_mono() -> None:
    chain = render_filter_chain(
        gain_db=9.0, ceiling_dbtp=-1.5, input_channels=1, denoise=DenoiseMode.OFF
    )
    parts = chain.split(",")
    assert parts[0] == "pan=stereo|c0=c0|c1=c0"
    assert parts[1] == "volume=9.000dB"
    assert parts[2].startswith("alimiter=limit=0.841395:level=disabled")
    assert "afftdn" not in chain
    stereo = render_filter_chain(
        gain_db=-6, ceiling_dbtp=-2, input_channels=2, denoise=DenoiseMode.LIGHT
    )
    assert stereo.split(",")[0] == "afftdn=nr=6"
    assert "pan=" not in stereo


def test_limiter_limit_is_clamped_to_the_filter_range() -> None:
    assert limiter_limit(0.0) == 1.0
    assert limiter_limit(-60.0) == 0.0625


def test_encode_command_is_aac_lc_48k_stereo() -> None:
    cmd = encode_command("ffmpeg", Path("a.wav"), Path("b.m4a"), bitrate_bps=384_000)
    joined = " ".join(cmd)
    assert "-c:a aac -profile:a aac_low -b:a 384000 -ar 48000 -ac 2" in joined


def test_parse_ebur128_recorded_output() -> None:
    loud = parse_ebur128((FIX / "ebur128_tone.txt").read_text())
    assert (loud.integrated_lufs, loud.lra_lu, loud.true_peak_dbtp) == (-33.8, 0.0, -30.1)


def test_parse_ebur128_missing_summary_is_agent_crash() -> None:
    with pytest.raises(AgentCrashError):
        parse_ebur128("size=N/A time=00:00:02.90 bitrate=N/A\n")


def test_parse_ebur128_incomplete_summary_is_agent_crash() -> None:
    with pytest.raises(AgentCrashError):
        parse_ebur128("Summary:\n  Integrated loudness:\n    I:   -20.0 LUFS\n")


def test_parse_ebur128_inf_is_unmeasurable_not_a_number() -> None:
    text = (FIX / "ebur128_tone.txt").read_text().replace("-33.8 LUFS", "-inf LUFS", 1)
    assert parse_ebur128(text).integrated_lufs is None


def test_parse_silencedetect_recorded_output() -> None:
    spans = parse_silencedetect((FIX / "silencedetect_gap.txt").read_text(), 4000)
    assert [(s.start_ms, s.end_ms) for s in spans] == [(1000, 3000)]


def test_parse_silencedetect_open_run_and_negative_start() -> None:
    text = "[silencedetect @ 0x1] silence_start: -0.0017\n"
    assert [(s.start_ms, s.end_ms) for s in parse_silencedetect(text, 5000)] == [(0, 5000)]
    assert parse_silencedetect("", 1000) == ()


def test_parse_ffprobe_recorded_output() -> None:
    wav = parse_ffprobe((FIX / "ffprobe_tone.json").read_text())
    assert (wav.sample_rate_hz, wav.channels, wav.duration_samples) == (48_000, 1, 96_000)
    aac = parse_ffprobe((FIX / "ffprobe_aac.json").read_text())
    assert (aac.codec, aac.profile, aac.channels) == ("aac", "LC", 2)
    assert aac.duration_ms == 2000


def test_parse_ffprobe_garbage_is_agent_crash() -> None:
    with pytest.raises(AgentCrashError):
        parse_ffprobe("{}")


def test_parse_version() -> None:
    assert parse_ffmpeg_version((FIX / "ffmpeg_version.txt").read_text()).startswith("ffmpeg 6.")
    assert parse_ffmpeg_version("") == "ffmpeg unknown"


class _Runner:
    def __init__(self, results: list[ProcessResult]) -> None:
        self.results = results
        self.calls: list[list[str]] = []

    def run(self, args: Sequence[str], *, timeout_s: float | None = None) -> ProcessResult:
        self.calls.append(list(args))
        return self.results.pop(0)


def test_nonzero_exit_is_render_crash(tmp_path: Path) -> None:
    tools = FfmpegAudioTools(_Runner([ProcessResult(1, "", "boom")]))
    with pytest.raises(RenderCrashError):
        tools.loudness(tmp_path / "x.wav")


def test_tools_loudness_uses_the_runner(tmp_path: Path) -> None:
    runner = _Runner([ProcessResult(0, "", (FIX / "ebur128_tone.txt").read_text())])
    loud = FfmpegAudioTools(runner).loudness(tmp_path / "x.wav")
    assert loud.integrated_lufs == -33.8
    assert runner.calls[0][0] == "ffmpeg"
