"""9:16 cut (3A-15): a real FFmpeg re-frame of a finished 16:9 master.

Re-frame modes: ``blur_pad`` (the whole 16:9 picture fitted inside the safe width, centred on a
blurred, enlarged copy of itself) or ``crop`` (centre or ``focus_x`` crop, no padding). Burned-in
subtitles are re-laid inside the 9:16 safe area (margins are PARAMETERS: the official Shorts UI
zones are still REQUIRES REVIEW (Phase 1), so nothing is hard-coded here). The audio stream is
copied bit for bit (same loudness) and the output is probed: size, fps, codec profile, pixel
format, duration within tolerance, audio present, and optionally loudness within tolerance.

Nothing from Agent 10 was reused: its render module covers only the 16:9 / preset path and holds no
re-frame code (it only names the ``shorts_9x16`` preset), and its runner is bound to its segment
plan. This module is a small, self-contained argument-list builder with no shell.
"""

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from amw_core.errors import (
    AgentHangError,
    CorruptedOutputError,
    InputInvalidError,
    MissingDependencyError,
    RenderCrashError,
)


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SafeArea(_M):
    """Pixels kept clear of platform UI, measured from each edge of the 9:16 frame."""

    top_px: Annotated[int, Field(ge=0)]
    bottom_px: Annotated[int, Field(ge=0)]
    left_px: Annotated[int, Field(ge=0)]
    right_px: Annotated[int, Field(ge=0)]


class VerticalSpec(_M):
    """Everything configurable about the cut; the caller passes it (config, not literals)."""

    width_px: Annotated[int, Field(ge=2)]
    height_px: Annotated[int, Field(ge=2)]
    fps: Annotated[int, Field(ge=1)]
    safe_area: SafeArea
    mode: Literal["blur_pad", "crop"]
    focus_x: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    blur_radius: Annotated[int, Field(ge=1)]
    video_crf: Annotated[int, Field(ge=0, le=51)]
    x264_preset: str
    h264_profile: Literal["baseline", "main", "high"]
    subtitle_font_size: Annotated[int, Field(ge=1)]
    duration_tolerance_ms: Annotated[int, Field(ge=0)]
    loudness_tolerance_lu: Annotated[float, Field(ge=0)] | None = None
    """When set, integrated loudness of input and output must agree within this tolerance."""
    threads: Annotated[int, Field(ge=1)] = 1
    timeout_s: Annotated[int, Field(ge=1)]
    nice: int | None = 10
    """Run FFmpeg under ``nice -n <value>`` when the tool exists (shared CPU); ``None`` = off."""


@dataclass(frozen=True, slots=True)
class MediaProbe:
    width: int
    height: int
    fps_num: int
    fps_den: int
    video_codec: str
    video_profile: str | None
    pix_fmt: str | None
    duration_ms: int
    audio_codec: str | None
    audio_sample_rate: int | None
    audio_channels: int | None

    @property
    def fps(self) -> float:
        return self.fps_num / self.fps_den


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise MissingDependencyError(f"{name} is not installed")
    return path


def _run(
    argv: list[str], *, cwd: Path, timeout_s: int, nice: int | None
) -> subprocess.CompletedProcess[str]:
    cmd = list(argv)
    nice_bin = shutil.which("nice")
    if nice is not None and nice_bin is not None:
        cmd = [nice_bin, "-n", str(nice), *cmd]
    try:
        return subprocess.run(  # noqa: S603 (argument list, no shell, fixed templates)
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentHangError("ffmpeg timed out", details={"timeout_s": timeout_s}) from exc


def probe_media(path: Path) -> MediaProbe:
    """ffprobe JSON of one file; a missing stream is reported, never defaulted to a pass."""
    if not path.is_file():
        raise MissingDependencyError("media file not found")
    res = _run(
        [_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams",
         "-show_format", str(path)],
        cwd=path.parent, timeout_s=60, nice=None,
    )  # fmt: skip
    if res.returncode != 0:
        raise InputInvalidError(
            "ffprobe could not read the file", details={"stderr": res.stderr[-300:]}
        )
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise InputInvalidError("no video stream")
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    num, _, den = str(v.get("avg_frame_rate", "0/1")).partition("/")
    duration = data.get("format", {}).get("duration") or v.get("duration")
    if duration is None:
        raise InputInvalidError("duration unavailable")
    return MediaProbe(
        width=int(v["width"]),
        height=int(v["height"]),
        fps_num=int(num),
        fps_den=int(den or 1) or 1,
        video_codec=str(v["codec_name"]),
        video_profile=v.get("profile"),
        pix_fmt=v.get("pix_fmt"),
        duration_ms=round(float(duration) * 1000),
        audio_codec=a.get("codec_name") if a else None,
        audio_sample_rate=int(a["sample_rate"]) if a and a.get("sample_rate") else None,
        audio_channels=int(a["channels"]) if a and a.get("channels") else None,
    )


_LUFS = re.compile(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS")


def integrated_lufs(path: Path, *, timeout_s: int, nice: int | None) -> float:
    res = _run(
        [_tool("ffmpeg"), "-hide_banner", "-nostats", "-i", path.name, "-vn",
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        cwd=path.parent, timeout_s=timeout_s, nice=nice,
    )  # fmt: skip
    found = _LUFS.findall(res.stderr)
    if res.returncode != 0 or not found:
        raise CorruptedOutputError("loudness could not be measured")
    return float(found[-1])


def build_filter(spec: VerticalSpec, *, subtitles_name: str | None) -> str:
    """The ``-filter_complex`` string (pure, testable)."""
    w, h = spec.width_px, spec.height_px
    sa = spec.safe_area
    inner_w = w - sa.left_px - sa.right_px
    if inner_w < 2 or h - sa.top_px - sa.bottom_px < 2:
        raise InputInvalidError("safe area leaves no room")
    if spec.mode == "crop":
        # Scale to cover the frame, then crop around focus_x (percentage of the spare width).
        base = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:x='(iw-{w})*{spec.focus_x}':y='(ih-{h})/2',setsar=1[base]"
        )
    else:
        base = (
            f"[0:v]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"boxblur={spec.blur_radius}:1[bg];"
            f"[fgsrc]scale={inner_w}:-2[fg];"
            f"[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2,setsar=1[base]"
        )
    tail = f"[base]fps={spec.fps},format=yuv420p"
    if subtitles_name is not None:
        style = (
            f"Alignment=2,MarginV={sa.bottom_px},MarginL={sa.left_px},MarginR={sa.right_px},"
            f"FontSize={spec.subtitle_font_size},WrapStyle=0"
        )
        tail += f",subtitles=f={subtitles_name}:original_size={w}x{h}:force_style='{style}'"
    return f"{base};{tail}[v]"


def make_9x16(
    input_mp4: Path,
    out_mp4: Path,
    spec: VerticalSpec,
    *,
    subtitles_srt: Path | None = None,
) -> MediaProbe:
    """Re-frame ``input_mp4`` to 9:16 at ``out_mp4`` and verify the result by probing it.

    Returns the output probe. Raises ``MissingDependencyError`` (input, tools),
    ``InputInvalidError`` (no audio), ``RenderCrashError`` (FFmpeg failed),
    ``AgentHangError`` (timeout) or ``CorruptedOutputError`` (output fails the probe:
    size, fps, profile, duration, audio, loudness); a failing output file is removed.
    """
    src = probe_media(input_mp4)
    if src.audio_codec is None:
        raise InputInvalidError("the 16:9 master has no audio stream")
    if subtitles_srt is not None and not subtitles_srt.is_file():
        raise MissingDependencyError("subtitle file not found")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out_mp4.with_name(out_mp4.name + ".partial.mp4")
    with tempfile.TemporaryDirectory(prefix="amw-vertical-") as scratch_name:
        scratch = Path(scratch_name)
        shutil.copyfile(input_mp4, scratch / "in.mp4")  # fixed scratch names: no path in argv
        sub_name: str | None = None
        if subtitles_srt is not None:
            shutil.copyfile(subtitles_srt, scratch / "sub.srt")
            sub_name = "sub.srt"
        argv = [
            _tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file",
            "-i", "in.mp4", "-filter_complex", build_filter(spec, subtitles_name=sub_name),
            "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-profile:v", spec.h264_profile,
            "-preset", spec.x264_preset, "-crf", str(spec.video_crf), "-r", str(spec.fps),
            "-threads", str(spec.threads), "-c:a", "copy", "-movflags", "+faststart", "out.mp4",
        ]  # fmt: skip
        res = _run(argv, cwd=scratch, timeout_s=spec.timeout_s, nice=spec.nice)
        if res.returncode != 0 or not (scratch / "out.mp4").is_file():
            raise RenderCrashError(
                "ffmpeg failed to build the 9:16 cut", details={"stderr": res.stderr[-400:]}
            )
        shutil.move(scratch / "out.mp4", tmp_out)
    try:
        out = _verify(src, input_mp4, tmp_out, spec)
        tmp_out.replace(out_mp4)
    except BaseException:
        tmp_out.unlink(missing_ok=True)
        raise
    return out


def _verify(src: MediaProbe, src_path: Path, path: Path, spec: VerticalSpec) -> MediaProbe:
    out = probe_media(path)
    problems: list[str] = []
    if (out.width, out.height) != (spec.width_px, spec.height_px):
        problems.append(f"size {out.width}x{out.height}")
    if out.fps_num != spec.fps * out.fps_den:
        problems.append(f"fps {out.fps_num}/{out.fps_den}")
    if out.video_codec != "h264":
        problems.append(f"codec {out.video_codec}")
    if not (out.video_profile or "").lower().endswith(spec.h264_profile):
        problems.append(f"profile {out.video_profile}")
    if out.pix_fmt != "yuv420p":
        problems.append(f"pix_fmt {out.pix_fmt}")
    if abs(out.duration_ms - src.duration_ms) > spec.duration_tolerance_ms:
        problems.append(f"duration {out.duration_ms} vs {src.duration_ms} ms")
    if out.audio_codec is None:
        problems.append("audio missing")
    elif (out.audio_codec, out.audio_sample_rate, out.audio_channels) != (
        src.audio_codec,
        src.audio_sample_rate,
        src.audio_channels,
    ):
        problems.append("audio changed")
    if problems:
        raise CorruptedOutputError(
            "9:16 output failed verification", details={"problems": problems}
        )
    if spec.loudness_tolerance_lu is not None:
        before = integrated_lufs(src_path, timeout_s=spec.timeout_s, nice=spec.nice)
        after = integrated_lufs(path, timeout_s=spec.timeout_s, nice=spec.nice)
        if abs(before - after) > spec.loudness_tolerance_lu:
            raise CorruptedOutputError(
                "9:16 loudness differs from the master",
                details={"before_lufs": before, "after_lufs": after},
            )
    return out
