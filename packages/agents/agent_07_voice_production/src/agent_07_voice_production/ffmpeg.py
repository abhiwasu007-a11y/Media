"""Thin FFmpeg / ffprobe wrapper behind a runner Protocol (blueprint 12.2, F-16, F-22, F-23).

Command construction and output parsing are pure and tested against recorded tool-output
fixtures; the only process call is ``SubprocessRunner.run`` (an argument list, never a shell
string: no injection surface, 19.1 control 3). The measurement commands follow 18 sections 7.2
and 7.5 (INF-09) but are not verbatim: ``-map 0:a:0`` is added, and ebur128 runs behind the
master's channel map when the stem is mono (see ``channel_map_filters``). The processing filters
(``volume``, ``alimiter``, ``afftdn``) and the AAC encode options are PROPOSALS: REQUIRES REVIEW
(Phase 1) - verify against the official FFmpeg documentation and record them in RESEARCH_LOG
(blueprint 6.4, F-23).
"""

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_07_voice_production.config import AgentSevenConfig, DenoiseMode
from agent_07_voice_production.pcm import count_clipped, peak_dbfs, read_s16, rms_dbfs, wav_info
from agent_07_voice_production.ports import (
    AudioAnalysis,
    Loudness,
    SilenceSpan,
    StreamFacts,
)
from amw_core.errors import AgentCrashError, InputInvalidError, RenderCrashError

LIMITER_MIN_LINEAR = 0.0625
"""``alimiter`` lower bound of ``limit`` (FFmpeg 6.1 filter help)."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


@runtime_checkable
class ProcessRunner(Protocol):
    def run(self, args: Sequence[str], *, timeout_s: float | None = None) -> ProcessResult: ...


class SubprocessRunner:
    """Runs a local binary without a shell. ``timeout_s`` bounds one pass (07 section 9 cap)."""

    def run(self, args: Sequence[str], *, timeout_s: float | None = None) -> ProcessResult:
        try:
            done = subprocess.run(  # noqa: S603 - argument list built by this module only
                list(args), capture_output=True, text=True, check=False, timeout=timeout_s
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderCrashError("an FFmpeg pass timed out") from exc
        except OSError as exc:
            raise RenderCrashError("FFmpeg could not be started") from exc
        return ProcessResult(done.returncode, done.stdout, done.stderr)


# --- command construction ---------------------------------------------------------------

_COMMON = ("-nostats", "-hide_banner")


CHANNEL_MAP_MONO_TO_STEREO = "pan=stereo|c0=c0|c1=c0"
"""A mono stem becomes dual-mono stereo (AM-11). BS.1770 sums channel powers, so the same signal
in two channels measures +3.01 LU: loudness is therefore always measured after this map."""


def channel_map_filters(input_channels: int) -> list[str]:
    return [CHANNEL_MAP_MONO_TO_STEREO] if input_channels == 1 else []


def ebur128_command(ffmpeg: str, path: Path, *, input_channels: int | None = None) -> list[str]:
    """18 section 7.2: loudness, loudness range and true peak (``peak=true``). With
    ``input_channels`` the stem is measured through the master's channel map (the layout the
    master really has), so the gain solved from it lands on the target."""
    ebur = "ebur128=peak=true:framelog=quiet"
    chain = ",".join([*channel_map_filters(input_channels or 0), ebur])
    return [
        ffmpeg,
        *_COMMON,
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-af",
        chain,
        "-f",
        "null",
        "-",
    ]


def silencedetect_command(ffmpeg: str, path: Path, *, noise_db: float, min_s: float) -> list[str]:
    """18 section 7.5: ``silencedetect=n=<noise>dB:d=<min>`` (voice stem: -50 dB, 0.3 s)."""
    return [
        ffmpeg,
        *_COMMON,
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-af",
        f"silencedetect=n={noise_db:g}dB:d={min_s:g}",
        "-vn",
        "-f",
        "null",
        "-",
    ]


def ffprobe_command(ffprobe: str, path: Path) -> list[str]:
    return [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,profile,sample_rate,channels,duration_ts,time_base,bit_rate,duration",
        "-of",
        "json",
        str(path),
    ]


def working_format_command(ffmpeg: str, src: Path, dst: Path) -> list[str]:
    """Any decodable input to PCM 16-bit mono 48 kHz (the working format, FR-10/FR-12)."""
    return [
        ffmpeg,
        "-nostdin",
        *_COMMON,
        "-y",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]


def gain_db_to_text(gain_db: float) -> str:
    return f"{gain_db:.3f}dB"


def limiter_limit(ceiling_dbtp: float) -> float:
    """Linear ``alimiter`` limit for a ceiling in dB, clamped to the filter's range."""
    return min(1.0, max(LIMITER_MIN_LINEAR, 10 ** (ceiling_dbtp / 20)))


def render_filter_chain(
    *, gain_db: float, ceiling_dbtp: float, input_channels: int, denoise: DenoiseMode
) -> str:
    """Gain then limiter (6.4 step 3). A mono stem becomes dual mono (stereo master, AM-11).
    Duration is never changed: no resampling, no trim, ``latency`` compensated."""
    chain: list[str] = channel_map_filters(input_channels)
    if denoise is DenoiseMode.LIGHT:
        chain.append("afftdn=nr=6")
    chain.append(f"volume={gain_db_to_text(gain_db)}")
    chain.append(
        f"alimiter=limit={limiter_limit(ceiling_dbtp):.6f}:level=disabled:attack=5:release=50:latency=true"
    )
    return ",".join(chain)


def render_command(
    ffmpeg: str,
    src: Path,
    dst: Path,
    *,
    gain_db: float,
    ceiling_dbtp: float,
    input_channels: int,
    denoise: DenoiseMode,
) -> list[str]:
    chain = render_filter_chain(
        gain_db=gain_db, ceiling_dbtp=ceiling_dbtp, input_channels=input_channels, denoise=denoise
    )
    return [
        ffmpeg,
        "-nostdin",
        *_COMMON,
        "-y",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-af",
        chain,
        "-c:a",
        "pcm_s24le",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(dst),
    ]


def encode_command(ffmpeg: str, src: Path, dst: Path, *, bitrate_bps: int) -> list[str]:
    """Verification encode in the delivery profile: AAC-LC, 48 kHz, stereo (INF-10)."""
    return [
        ffmpeg,
        "-nostdin",
        *_COMMON,
        "-y",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-c:a",
        "aac",
        "-profile:a",
        "aac_low",
        "-b:a",
        str(bitrate_bps),
        "-ar",
        "48000",
        "-ac",
        "2",
        str(dst),
    ]


def decode_command(ffmpeg: str, src: Path, dst: Path) -> list[str]:
    return [
        ffmpeg,
        "-nostdin",
        *_COMMON,
        "-y",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-c:a",
        "pcm_s24le",
        str(dst),
    ]


# --- parsers ----------------------------------------------------------------------------

_NUM = r"(-?\d+(?:\.\d+)?|-?inf)"
_I_RE = re.compile(rf"^\s*I:\s+{_NUM}\s+LUFS\s*$", re.MULTILINE)
_LRA_RE = re.compile(rf"^\s*LRA:\s+{_NUM}\s+LU\s*$", re.MULTILINE)
_PEAK_RE = re.compile(rf"^\s*Peak:\s+{_NUM}\s+dBFS\s*$", re.MULTILINE)
_SIL_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SIL_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


ABSOLUTE_GATE_LUFS = -70.0
"""BS.1770 absolute gate: ebur128 prints ``-70.0 LUFS`` (not ``-inf``) for digital silence."""


def _number(text: str) -> float | None:
    return None if text.endswith("inf") else float(text)


def parse_ebur128(stderr: str) -> Loudness:
    """Parse the ``Summary:`` block at the end of the ebur128 output (18 section 7.2).

    A missing summary or an unparsable value is ``AGENT.CRASH`` (18 section 7.0.3): a measurement
    that cannot be made is never a PASS. ``-inf``, or a loudness at or below the -70 LUFS absolute
    gate (what FFmpeg prints for digital silence), is ``None``.
    """
    marker = stderr.rfind("Summary:")
    if marker < 0:
        raise AgentCrashError("FFmpeg ebur128 produced no Summary block")
    block = stderr[marker:]
    i_m, lra_m, peak_m = _I_RE.search(block), _LRA_RE.search(block), _PEAK_RE.search(block)
    if i_m is None or lra_m is None or peak_m is None:
        raise AgentCrashError("FFmpeg ebur128 Summary block is incomplete")
    integrated = _number(i_m.group(1))
    if integrated is not None and integrated <= ABSOLUTE_GATE_LUFS:
        integrated = None  # nothing above the absolute gate: not measurable (M2)
    return Loudness(integrated, _number(peak_m.group(1)), _number(lra_m.group(1)))


def parse_silencedetect(stderr: str, total_ms: int) -> tuple[SilenceSpan, ...]:
    """Silence spans in ms. A start without an end runs to the end of the file; a start of a
    hair below zero is clamped to 0."""
    spans: list[SilenceSpan] = []
    open_start: int | None = None
    for line in stderr.splitlines():
        if "silencedetect" not in line:
            continue
        start = _SIL_START.search(line)
        if start is not None:
            open_start = max(0, round(float(start.group(1)) * 1000))
            continue
        end = _SIL_END.search(line)
        if end is not None and open_start is not None:
            spans.append(SilenceSpan(open_start, min(total_ms, round(float(end.group(1)) * 1000))))
            open_start = None
    if open_start is not None:
        spans.append(SilenceSpan(open_start, total_ms))
    return tuple(s for s in spans if s.end_ms > s.start_ms)


def parse_ffprobe(stdout: str) -> StreamFacts:
    try:
        stream = json.loads(stdout)["streams"][0]
        rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
        time_base = str(stream.get("time_base", ""))
        if time_base == f"1/{rate}" and "duration_ts" in stream:
            samples = int(stream["duration_ts"])
        else:
            samples = round(float(stream["duration"]) * rate)
        bit_rate = int(stream["bit_rate"]) if "bit_rate" in stream else None
        return StreamFacts(
            rate, channels, samples, str(stream["codec_name"]), bit_rate, stream.get("profile")
        )
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise AgentCrashError("ffprobe output is not parsable") from exc


def parse_ffmpeg_version(stdout: str) -> str:
    first = stdout.splitlines()[0] if stdout else ""
    match = re.match(r"ffmpeg version (\S+)", first)
    return f"ffmpeg {match.group(1)}" if match else "ffmpeg unknown"


# --- the tools --------------------------------------------------------------------------


class FfmpegAudioTools:
    """``AudioTools`` over FFmpeg/ffprobe (voice step) and the measurement half of the master."""

    def __init__(
        self, runner: ProcessRunner, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"
    ) -> None:
        self._runner = runner
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def _run(self, args: Sequence[str]) -> ProcessResult:
        result = self._runner.run(args)
        if result.returncode != 0:
            raise RenderCrashError(
                "FFmpeg exited abnormally", details={"returncode": result.returncode}
            )
        return result

    def build(self) -> str:
        return parse_ffmpeg_version(self._runner.run([self.ffmpeg, "-version"]).stdout)

    def probe(self, path: Path) -> StreamFacts:
        if path.suffix.lower() == ".wav":
            info = wav_info(path)  # exact frame count from the header
            return StreamFacts(info.sample_rate_hz, info.channels, info.frames, "pcm_s16le")
        return parse_ffprobe(self._run(ffprobe_command(self.ffprobe, path)).stdout)

    def loudness(self, path: Path, *, input_channels: int | None = None) -> Loudness:
        cmd = ebur128_command(self.ffmpeg, path, input_channels=input_channels)
        return parse_ebur128(self._run(cmd).stderr)

    def silence(
        self, path: Path, total_ms: int, *, noise_db: float, min_s: float
    ) -> tuple[SilenceSpan, ...]:
        result = self._run(silencedetect_command(self.ffmpeg, path, noise_db=noise_db, min_s=min_s))
        return parse_silencedetect(result.stderr, total_ms)

    def analyse(
        self, path: Path, *, silence_noise_db: float, silence_min_s: float
    ) -> AudioAnalysis:
        """Loudness (ebur128), silence runs, clipping and noise floor of a 16-bit WAV stem."""
        info, samples = read_s16(path)
        stream = StreamFacts(info.sample_rate_hz, info.channels, info.frames, "pcm_s16le")
        loudness = self.loudness(path)
        runs = self.silence(
            path, stream.duration_ms, noise_db=silence_noise_db, min_s=silence_min_s
        )
        floor: float | None = None
        if runs:
            per_ms = info.sample_rate_hz * info.channels // 1000
            inside: list[int] = []
            for run in runs:
                inside.extend(samples[run.start_ms * per_ms : run.end_ms * per_ms])
            floor = rms_dbfs(inside)
        return AudioAnalysis(
            stream, loudness, count_clipped(samples), peak_dbfs(samples), runs, floor
        )

    def to_working_format(self, src: Path, dst: Path) -> None:
        self._run(working_format_command(self.ffmpeg, src, dst))


def require_working_format(stream: StreamFacts, config: AgentSevenConfig) -> None:
    """The voice step always writes 48 000 Hz mono; the master never resamples (AM-31)."""
    if stream.sample_rate_hz != config.sample_rate_hz:
        raise InputInvalidError(
            "the stem is not at the delivery sample rate; the master never resamples",
            details={"sample_rate_hz": stream.sample_rate_hz},
        )
