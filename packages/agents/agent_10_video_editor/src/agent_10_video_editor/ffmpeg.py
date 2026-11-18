"""FFmpeg command construction and the process boundary (blueprint 10 sections 9, 10, 12, 19).

``ArgvBuilder`` builds argument LISTS from fixed templates (never a shell string); no text from a
payload, script, asset title or metadata reaches an argument: inputs are staged under scratch
names ``in_<n>.<ext>`` and referenced by those names only, ``-protocol_whitelist file`` is set on
every input, and the only process spawn is ``ProcessFfmpegRunner`` (no shell). The runner is a
Protocol so the worker injects the concrete one and tests inject an in-memory fake.
"""

import os
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from agent_10_video_editor.canonical import canonical_sha256
from agent_10_video_editor.config import RenderConfig
from agent_10_video_editor.errors import input_invalid
from agent_10_video_editor.frames import ms_to_seconds_text
from agent_10_video_editor.inputs import CodecProfile
from agent_10_video_editor.segments import SegmentSlice
from agent_10_video_editor.timeline import TimelineShot
from amw_core.errors import (
    AgentHangError,
    AmwError,
    DiskFullError,
    OomError,
    RenderCrashError,
)

KilledBy = Literal["SIGTERM", "SIGKILL", "TIMEOUT"]
_EXTENSIONS = frozenset(
    {"png", "jpg", "jpeg", "webp", "mp4", "mov", "mkv", "wav", "ttf", "otf", "flac"}
)
_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp"})


@dataclass(frozen=True, slots=True)
class RunLimits:
    timeout_ms: int | None = None
    threads: int = 1


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    wall_ms: int = 0
    killed_by: KilledBy | None = None


@runtime_checkable
class FfmpegRunner(Protocol):
    """Runs one local executable with an argument list inside ``cwd`` (the task scratch dir)."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        limits: RunLimits,
        stop: Callable[[], bool] | None = None,
    ) -> ProcessResult:
        """``stop()`` true while the process runs: terminate it (SIGTERM) and report it."""
        ...


class ProcessFfmpegRunner:
    """The only process spawn of the package (argument list, never a shell; F-17)."""

    def __init__(self, poll_ms: int = 50) -> None:
        self._poll_s = poll_ms / 1000

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        limits: RunLimits,
        stop: Callable[[], bool] | None = None,
    ) -> ProcessResult:
        out_path, err_path = cwd / ".stdout.txt", cwd / ".stderr.txt"
        started = time.monotonic()
        killed: KilledBy | None = None
        with out_path.open("wb") as out, err_path.open("wb") as err:
            proc = subprocess.Popen(  # noqa: S603 - argument list, no shell, fixed templates
                list(argv),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=env_for_child(),
            )
            while proc.poll() is None:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                if limits.timeout_ms is not None and elapsed_ms > limits.timeout_ms:
                    killed = "TIMEOUT"
                elif stop is not None and stop():
                    killed = "SIGTERM"
                if killed is not None:
                    proc.send_signal(signal.SIGTERM)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    break
                time.sleep(self._poll_s)
        code = proc.returncode
        if killed is None and code is not None and code < 0 and -code == signal.SIGKILL:
            killed = "SIGKILL"
        stdout = out_path.read_text(encoding="utf-8", errors="replace")
        stderr = err_path.read_text(encoding="utf-8", errors="replace")
        for path in (out_path, err_path):
            path.unlink(missing_ok=True)
        return ProcessResult(
            exit_code=code if code is not None else -1,
            stdout=stdout,
            stderr=stderr,
            wall_ms=int((time.monotonic() - started) * 1000),
            killed_by=killed,
        )


def error_for_result(result: ProcessResult) -> AmwError | None:
    """F-42 / section 18 mapping of an abnormal process end; ``None`` for a clean exit."""
    if result.killed_by == "SIGTERM":
        return None  # a requested stop is not an error (the caller checkpoints)
    if result.killed_by == "SIGKILL" or result.exit_code == -signal.SIGKILL:
        return OomError("process killed (memory)")
    if result.killed_by == "TIMEOUT":
        return AgentHangError("process exceeded its wall budget")
    if result.exit_code == 0:
        return None
    if "No space left on device" in result.stderr:
        return DiskFullError("no space left")
    return RenderCrashError("ffmpeg exited abnormally", details={"exit_code": result.exit_code})


# ----------------------------------------------------------------------------- command objects


@dataclass(frozen=True, slots=True)
class StagedInput:
    name: str
    uri: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SegmentCommand:
    argv: tuple[str, ...]
    inputs: tuple[StagedInput, ...]
    output_name: str
    args_sha256: str
    warnings: tuple[str, ...] = ()
    gop: dict[str, object] = field(default_factory=dict)


def _ext_of(uri: str) -> str:
    ext = uri.rsplit(".", 1)[-1].lower() if "." in uri.rsplit("/", 1)[-1] else ""
    if ext not in _EXTENSIONS:
        raise input_invalid("ASSET_EXTENSION_UNSUPPORTED")
    return ext


def _fps(num: int, den: int) -> str:
    return f"{num}/{den}"


_ANCHOR_XY: dict[str, tuple[str, str]] = {
    "CENTER": ("(iw-ow)/2", "(ih-oh)/2"),
    "UPPER_THIRD": ("(iw-ow)/2", "(ih-oh)/3"),
    "LOWER_THIRD": ("(iw-ow)/2", "(ih-oh)*2/3"),
    "LEFT": ("0", "(ih-oh)/2"),
    "RIGHT": ("iw-ow", "(ih-oh)/2"),
}


class ArgvBuilder:
    """F-15, F-16: argument lists from closed templates."""

    def __init__(
        self, cfg: RenderConfig, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"
    ) -> None:
        self._cfg = cfg
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    # -- segment ---------------------------------------------------------------------------

    def segment_command(self, slice_: SegmentSlice) -> SegmentCommand:
        cfg = self._cfg
        width, height = cfg.geometry
        colour = cfg.colour
        fps = _fps(cfg.fps_num, cfg.fps_den)
        inputs: list[StagedInput] = []
        input_args: list[str] = []
        graph: list[str] = []
        warnings: list[str] = []
        labels: list[str] = []

        def add_input(uri: str, sha: str, *, still: bool, seek_ms: int = 0) -> int:
            index = len(inputs)
            ext = _ext_of(uri)
            name = f"in_{index}.{ext}"
            inputs.append(StagedInput(name, uri, sha))
            input_args.extend(["-protocol_whitelist", "file"])
            if still or ext in _IMAGE_EXTENSIONS:
                input_args.extend(["-loop", "1", "-framerate", fps])
            elif seek_ms > 0:
                input_args.extend(["-ss", ms_to_seconds_text(seek_ms)])
            input_args.extend(["-i", name])
            return index

        def scale_chain(index: int, label: str, frames: int, crop: dict[str, object]) -> None:
            pre = ""
            keep = int(crop.get("keep_permille", 1000))  # type: ignore[call-overload]
            if crop.get("mode") != "NONE" and keep < 1000:
                x, y = _ANCHOR_XY[str(crop.get("anchor") or "CENTER")]
                pre = f"crop=w=trunc(iw*{keep}/2000)*2:h=trunc(ih*{keep}/2000)*2:x={x}:y={y},"
            graph.append(
                f"[{index}:v]{pre}scale={width}:{height}:force_original_aspect_ratio=increase"
                f":out_color_matrix={colour.matrix}:out_range={colour.range},"
                f"crop={width}:{height},setsar=1,fps={fps},"
                f"tpad=stop_mode=clone:stop={frames},trim=end_frame={frames},"
                f"setpts=PTS-STARTPTS,format=yuv420p[{label}]"
            )

        for part in slice_.parts:
            _warn_part(part, warnings)
            if part.reveal_steps:
                bounds = [s.start_frame for s in part.reveal_steps] + [part.end_frame]
                for k, step in enumerate(part.reveal_steps):
                    index = add_input(step.asset_uri, step.asset_sha256, still=True)
                    label = f"v{len(labels)}"
                    scale_chain(index, label, bounds[k + 1] - bounds[k], part.crop)
                    labels.append(label)
            else:
                index = add_input(
                    part.asset_uri, part.asset_sha256, still=False, seek_ms=part.source_in_ms
                )
                label = f"v{len(labels)}"
                scale_chain(index, label, part.frames, part.crop)
                labels.append(label)
        joined = "".join(f"[{label}]" for label in labels)
        graph.append(
            f"{joined}concat=n={len(labels)}:v=1:a=0[vc0]"
            if len(labels) > 1
            else f"{joined}null[vc0]"
        )
        current = "vc0"
        seg_start = slice_.segment.start_frame
        for n, overlay in enumerate(slice_.overlays):
            index = add_input(overlay.template_uri, overlay.template_sha256, still=True)
            if overlay.text_sha256s:
                warnings.append(f"OVERLAY_TEXT_NOT_DRAWN:{overlay.overlay_id}")
            start = max(overlay.start_frame, seg_start) - seg_start
            end = min(overlay.end_frame, slice_.segment.end_frame) - seg_start - 1
            graph.append(
                f"[{index}:v]scale={width}:{height},format=rgba,setpts=PTS-STARTPTS[ov{n}]"
            )
            graph.append(
                f"[{current}][ov{n}]overlay=0:0:format=auto:eof_action=pass"
                f":enable='between(n,{start},{end})'[vc{n + 1}]"
            )
            current = f"vc{n + 1}"
        x264 = (
            f"keyint={cfg.gop_frames}:min-keyint={cfg.gop_frames}:scenecut=0:open-gop=0"
            f":threads={cfg.threads}"
        )
        argv = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            *input_args,
            "-filter_complex",
            ";".join(graph),
            "-map",
            f"[{current}]",
            "-frames:v",
            str(slice_.segment.frames),
            "-fps_mode",
            "cfr",
            "-r",
            fps,
            "-c:v",
            cfg.video_encoder,
            "-preset",
            cfg.x264_preset,
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            str(cfg.video_bitrate_bps),
            "-maxrate",
            str(cfg.video_maxrate_bps),
            "-bufsize",
            str(cfg.video_maxrate_bps * 2),
            "-g",
            str(cfg.gop_frames),
            "-keyint_min",
            str(cfg.gop_frames),
            "-sc_threshold",
            "0",
            "-x264-params",
            x264,
            "-color_primaries",
            colour.primaries,
            "-color_trc",
            colour.transfer,
            "-colorspace",
            colour.matrix,
            "-color_range",
            colour.range,
            "-an",
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-f",
            "mp4",
            "segment.part",
        ]
        return SegmentCommand(
            argv=tuple(argv),
            inputs=tuple(inputs),
            output_name="segment.part",
            args_sha256=canonical_sha256(argv),
            warnings=tuple(dict.fromkeys(warnings)),
            gop={
                "gop_frames": cfg.gop_frames,
                "closed_gop": True,
                "idr_at_segment_start": True,
            },
        )

    # -- mux -------------------------------------------------------------------------------

    def mux_argv(
        self,
        segment_names: Sequence[str],
        master_name: str,
        codec_profile: CodecProfile,
        duration_ms: int,
        list_name: str = "concat.txt",
    ) -> tuple[list[str], str]:
        """Return ``(argv, concat_list_text)``: video ``-c copy``, audio re-encoded per the
        typed ``codec_profile`` of Agent 07, padded to the video length, faststart, ``-t`` cap."""
        if codec_profile.codec != "aac":
            raise input_invalid("CODEC_PROFILE_UNSUPPORTED")
        profile = {"LC": "aac_low"}.get(codec_profile.profile)
        if profile is None:
            raise input_invalid("CODEC_PROFILE_UNSUPPORTED")
        colour = self._cfg.colour
        listing = "".join(f"file '{name}'\n" for name in segment_names)
        argv = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_name,
            "-protocol_whitelist",
            "file",
            "-i",
            master_name,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-profile:a",
            profile,
            "-b:a",
            str(codec_profile.bitrate_bps),
            "-ar",
            str(codec_profile.sample_rate_hz),
            "-ac",
            str(codec_profile.channels),
            "-af",
            "apad",
            "-t",
            ms_to_seconds_text(duration_ms),
            "-color_primaries",
            colour.primaries,
            "-color_trc",
            colour.transfer,
            "-colorspace",
            colour.matrix,
            "-color_range",
            colour.range,
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags:a",
            "+bitexact",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            "final.part",
        ]
        return argv, listing

    # -- probes and detectors --------------------------------------------------------------

    def probe_full(self, name: str) -> list[str]:
        entries = (
            "stream=index,codec_type,codec_name,profile,pix_fmt,width,height,field_order,"
            "r_frame_rate,avg_frame_rate,bit_rate,sample_rate,channels,start_time,duration,"
            "color_range,color_space,color_transfer,color_primaries"
            ":format=duration,bit_rate,format_name,size"
        )
        return [
            self.ffprobe_bin,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-show_entries",
            entries,
            "-of",
            "json",
            name,
        ]

    def probe_frame_count(self, name: str) -> list[str]:
        return [
            self.ffprobe_bin,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames,r_frame_rate,avg_frame_rate",
            "-of",
            "json",
            name,
        ]

    def probe_first_frame(self, name: str) -> list[str]:
        return [
            self.ffprobe_bin,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-select_streams",
            "v:0",
            "-read_intervals",
            "%+#1",
            "-show_frames",
            "-show_entries",
            "frame=key_frame,pict_type",
            "-of",
            "json",
            name,
        ]

    def probe_packets(self, name: str) -> list[str]:
        return [
            self.ffprobe_bin,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=pts_time",
            "-of",
            "csv=p=0",
            name,
        ]

    def probe_stream_times(self, name: str) -> list[str]:
        return [
            self.ffprobe_bin,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-show_entries",
            "stream=codec_type,start_time,duration",
            "-of",
            "csv=p=0",
            name,
        ]

    def _detector(self, name: str, stream: str, filter_: str) -> list[str]:
        flag = "-af" if stream == "a" else "-vf"
        return [
            self.ffmpeg_bin,
            "-nostdin",
            "-nostats",
            "-hide_banner",
            "-protocol_whitelist",
            "file",
            "-i",
            name,
            "-map",
            f"0:{stream}:0",
            flag,
            filter_,
            *(["-an"] if stream == "v" else ["-vn"]),
            "-f",
            "null",
            "-",
        ]

    def ebur128(self, name: str, *, framelog: str = "quiet") -> list[str]:
        return self._detector(name, "a", f"ebur128=peak=true:framelog={framelog}")

    def silencedetect(self, name: str, n_db: int, d_s: str) -> list[str]:
        return self._detector(name, "a", f"silencedetect=n={n_db}dB:d={d_s}")

    def blackdetect(self, name: str, d_s: str, pic_th: str, pix_th: str) -> list[str]:
        return self._detector(name, "v", f"blackdetect=d={d_s}:pic_th={pic_th}:pix_th={pix_th}")

    def freezedetect(self, name: str, n_db: int, d_s: str) -> list[str]:
        return self._detector(name, "v", f"freezedetect=n={n_db}dB:d={d_s}")

    def scene(self, name: str, threshold: str) -> list[str]:
        return self._detector(name, "v", f"select='gt(scene,{threshold})',showinfo")

    def srt_check(self, name: str) -> list[str]:
        return [self.ffmpeg_bin, "-nostdin", "-v", "error", "-i", name, "-f", "null", "-"]

    def sample_frame(self, name: str, seek_ms: int, out_name: str) -> list[str]:
        return [
            self.ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file",
            "-ss",
            ms_to_seconds_text(seek_ms),
            "-i",
            name,
            "-frames:v",
            "1",
            "-f",
            "image2",
            "-update",
            "1",
            out_name,
        ]

    def contact_sheet(
        self, pattern: str, columns: int, rows: int, tile_width: int, out_name: str
    ) -> list[str]:
        return [
            self.ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file",
            "-framerate",
            "1",
            "-start_number",
            "1",
            "-i",
            pattern,
            "-vf",
            f"scale={tile_width}:-1,tile={columns}x{rows}",
            "-frames:v",
            "1",
            "-f",
            "image2",
            "-update",
            "1",
            out_name,
        ]

    def version(self) -> list[str]:
        return [self.ffmpeg_bin, "-hide_banner", "-version"]


def _warn_part(part: TimelineShot, warnings: list[str]) -> None:
    if part.motion != "STATIC":
        warnings.append(f"MOTION_NOT_RENDERED:{part.shot_id}")
    if part.transition_in.get("duration_ms", 0):
        warnings.append(f"TRANSITION_RENDERED_AS_CUT:{part.shot_id}")


def ffmpeg_build_id(version_stdout: str) -> str:
    """Build ID recorded with every render and QC run: the first line of ``ffmpeg -version``."""
    first = version_stdout.strip().splitlines()[0] if version_stdout.strip() else ""
    return first[:128]


def env_for_child() -> dict[str, str]:
    """Minimal environment for a child process (no inherited secrets)."""
    return {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"}
