"""Loudness solver, mastering pass loop and codec verification (F-21, F-22, F-23; blueprint 6.4).

The loop is a pure function of the measurements the backend returns. ``gain_db = target - I``;
pass ``k`` renders gain plus a true-peak limiter at ceiling ``C``, re-measures, runs the
verification encode in the delivery codec, and steps ``C`` down by ``codec_headroom_step_db`` while
the post-codec true peak exceeds the ceiling of the spec. After ``max_passes`` without meeting the
targets the gate results fail (the task still succeeds, 03 5.3 rule 4). Duration is never changed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_07_voice_production.config import AgentSevenConfig, DenoiseMode
from agent_07_voice_production.ports import AudioAnalysis, Loudness, StreamFacts
from amw_core.errors import InputInvalidError


@dataclass(frozen=True, slots=True)
class CodecFacts:
    """The verification encode, decoded again and measured."""

    codec: str
    profile: str | None
    sample_rate_hz: int
    channels: int
    bitrate_bps: int
    """The nominal rate the encode was asked for: what ``qc.audio.bitrate`` gates (CCR-055)."""
    post_codec: Loudness
    measured_bitrate_bps: int | None = None
    """The average the encode really has (ffprobe, else file size over duration); reported in
    the stage report. The payload block cannot carry it: see CONTRACT_CHANGE_REQUESTS."""


@runtime_checkable
class MasteringBackend(Protocol):
    """FFmpeg behind a Protocol (the wrapper of ``ffmpeg.py`` in production, a descriptor-driven
    stub in the golden datasets)."""

    def render(
        self,
        src: Path,
        dst: Path,
        *,
        gain_db: float,
        ceiling_dbtp: float,
        input_channels: int,
        denoise: DenoiseMode,
    ) -> None: ...

    def measure_mapped(self, stem: Path, *, input_channels: int) -> Loudness:
        """Loudness of the stem measured through the channel map ``render`` applies, so the gain
        is solved against the layout the master really has (a mono stem becomes dual-mono and
        measures +3.01 LU louder under BS.1770)."""
        ...

    def analyse_master(self, path: Path) -> tuple[StreamFacts, Loudness]: ...

    def count_clipping(self, path: Path) -> int:
        """Samples of the rendered master at digital full scale (``qc.audio.clipping``)."""
        ...

    def codec_verify(self, master: Path, workdir: Path, *, bitrate_bps: int) -> CodecFacts: ...

    def build(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PassState:
    """What a checkpoint ``master.pass_<k>`` stores (IDs and numbers only)."""

    pass_no: int
    gain_db: float
    ceiling_dbtp: float
    next_gain_db: float
    next_ceiling_dbtp: float
    satisfied: bool


@dataclass(frozen=True, slots=True)
class MasterRun:
    passes: int
    gain_db: float
    ceiling_dbtp: float
    limiter_gain_reduction_db: float
    master_stream: StreamFacts
    master_loudness: Loudness
    codec: CodecFacts
    master_path: Path
    targets_met: bool
    master_clipping_samples: int = 0


def solve_gain(pre: Loudness, target_lufs: float) -> float:
    """M5: ``gain = target - I``. A stem with no content above the absolute gate cannot be
    normalised (``PERMANENT.INPUT_INVALID``)."""
    if pre.integrated_lufs is None:
        raise InputInvalidError("the stem has no measurable loudness (silent stem)")
    return round(target_lufs - pre.integrated_lufs, 3)


def predicted_peak(pre: Loudness, gain_db: float) -> float | None:
    return None if pre.true_peak_dbtp is None else pre.true_peak_dbtp + gain_db


def limiter_reduction(pre: Loudness, gain_db: float, measured_tp: float | None) -> float:
    """How far the limiter pulled the peak down: predicted peak after gain minus the peak the
    rendered master really has (never negative)."""
    predicted = predicted_peak(pre, gain_db)
    if predicted is None or measured_tp is None:
        return 0.0
    return round(max(0.0, predicted - measured_tp), 3)


def loudness_in_tolerance(loudness: float | None, cfg: AgentSevenConfig) -> bool | None:
    """None when the tolerance is not calibrated yet (verdict WARN, 18 7.0.4)."""
    if cfg.tolerance_lu is None:
        return None
    return loudness is not None and abs(loudness - cfg.target_lufs) <= cfg.tolerance_lu


def run_passes(
    backend: MasteringBackend,
    *,
    stem: Path,
    pre: AudioAnalysis,
    cfg: AgentSevenConfig,
    workdir: Path,
    resume: PassState | None = None,
    after_pass: Callable[[PassState], None] | None = None,
) -> MasterRun:
    """M5 to M8. ``after_pass`` runs after each pass's measurements (checkpoint, drain check)
    and before the pass is judged, so a DRAIN stops at the pass boundary (FR-20)."""
    cfg.require_master()
    solve_gain(pre.loudness, cfg.target_lufs)  # a silent stem is refused before any render
    mapped = backend.measure_mapped(stem, input_channels=pre.stream.channels)
    gain = solve_gain(mapped, cfg.target_lufs)
    assert cfg.limiter_ceiling_dbtp is not None  # noqa: S101 - require_master()
    step = cfg.codec_headroom_step_db
    assert step is not None  # noqa: S101 - require_master()
    ceiling = cfg.limiter_ceiling_dbtp
    first = 1
    if resume is not None:
        if resume.satisfied:
            first, gain, ceiling = resume.pass_no, resume.gain_db, resume.ceiling_dbtp
        else:
            first, gain, ceiling = resume.pass_no + 1, resume.next_gain_db, resume.next_ceiling_dbtp
    last: MasterRun | None = None
    for k in range(first, cfg.max_passes + 1):
        dst = workdir / f"master_pass_{k}.wav"
        backend.render(
            stem,
            dst,
            gain_db=gain,
            ceiling_dbtp=ceiling,
            input_channels=pre.stream.channels,
            denoise=cfg.denoise_mode,
        )
        stream, post = backend.analyse_master(dst)
        codec = backend.codec_verify(dst, workdir, bitrate_bps=cfg.min_bitrate_bps)
        reduction = limiter_reduction(pre.loudness, gain, post.true_peak_dbtp)
        tp = codec.post_codec.true_peak_dbtp
        peak_ok = tp is not None and tp <= cfg.true_peak_max_dbtp
        loud_ok = loudness_in_tolerance(codec.post_codec.integrated_lufs, cfg)
        satisfied = peak_ok and loud_ok is not False
        next_gain, next_ceiling = gain, ceiling
        if not peak_ok:
            next_ceiling = round(ceiling - step, 3)
        if loud_ok is False and post.integrated_lufs is not None:
            next_gain = round(gain + (cfg.target_lufs - post.integrated_lufs), 3)
        clipped = backend.count_clipping(dst)
        last = MasterRun(k, gain, ceiling, reduction, stream, post, codec, dst, satisfied, clipped)
        state = PassState(k, gain, ceiling, next_gain, next_ceiling, satisfied)
        if after_pass is not None:
            after_pass(state)
        if satisfied:
            return last
        gain, ceiling = next_gain, next_ceiling
    assert last is not None  # noqa: S101 - first <= max_passes whenever the loop is entered
    return last


# --- the FFmpeg backend ---------------------------------------------------------------------

from agent_07_voice_production.ffmpeg import (  # noqa: E402 - after the Protocol they implement
    FfmpegAudioTools,
    ProcessRunner,
    decode_command,
    encode_command,
    ffprobe_command,
    parse_ffprobe,
    render_command,
)
from agent_07_voice_production.pcm import count_full_scale_pcm, wav_info  # noqa: E402
from amw_core.errors import RenderCrashError  # noqa: E402


def _measured_bitrate(facts: StreamFacts, encoded: Path) -> int:
    """ffprobe's reported stream ``bit_rate``; else file size over duration (still measured)."""
    if facts.bit_rate_bps is not None:
        return facts.bit_rate_bps
    seconds = facts.duration_samples / facts.sample_rate_hz
    if seconds <= 0:
        raise RenderCrashError("the verification encode has no duration")
    return round(encoded.stat().st_size * 8 / seconds)


class FfmpegMasteringBackend:
    """``MasteringBackend`` over FFmpeg: gain + ``alimiter`` render, ebur128 measurement, AAC-LC
    verification encode and decode (INF-09, INF-10). Filters are PROPOSALS until verified."""

    def __init__(self, runner: ProcessRunner, tools: FfmpegAudioTools) -> None:
        self._runner = runner
        self._tools = tools

    def _run(self, args: list[str]) -> None:
        done = self._runner.run(args)
        if done.returncode != 0:
            raise RenderCrashError(
                "FFmpeg exited abnormally", details={"returncode": done.returncode}
            )

    def render(
        self,
        src: Path,
        dst: Path,
        *,
        gain_db: float,
        ceiling_dbtp: float,
        input_channels: int,
        denoise: DenoiseMode,
    ) -> None:
        tmp = dst.with_name(dst.stem + ".part.wav")
        self._run(
            render_command(
                self._tools.ffmpeg,
                src,
                tmp,
                gain_db=gain_db,
                ceiling_dbtp=ceiling_dbtp,
                input_channels=input_channels,
                denoise=denoise,
            )
        )
        tmp.replace(dst)  # atomic within the scratch directory: no partial file at a final path

    def measure_mapped(self, stem: Path, *, input_channels: int) -> Loudness:
        return self._tools.loudness(stem, input_channels=input_channels)

    def count_clipping(self, path: Path) -> int:
        return count_full_scale_pcm(path)

    def analyse_master(self, path: Path) -> tuple[StreamFacts, Loudness]:
        info = wav_info(path)
        stream = StreamFacts(
            info.sample_rate_hz, info.channels, info.frames, f"pcm_s{8 * info.sample_width}le"
        )
        return stream, self._tools.loudness(path)

    def codec_verify(self, master: Path, workdir: Path, *, bitrate_bps: int) -> CodecFacts:
        encoded = workdir / (master.stem + ".m4a")
        decoded = workdir / (master.stem + ".decoded.wav")
        self._run(encode_command(self._tools.ffmpeg, master, encoded, bitrate_bps=bitrate_bps))
        probe = self._runner.run(ffprobe_command(self._tools.ffprobe, encoded))
        if probe.returncode != 0:
            raise RenderCrashError("ffprobe exited abnormally")
        facts = parse_ffprobe(probe.stdout)
        self._run(decode_command(self._tools.ffmpeg, encoded, decoded))
        return CodecFacts(
            facts.codec,
            facts.profile,
            facts.sample_rate_hz,
            facts.channels,
            bitrate_bps,
            self._tools.loudness(decoded),
            _measured_bitrate(facts, encoded),
        )

    def build(self) -> str:
        return self._tools.build()
