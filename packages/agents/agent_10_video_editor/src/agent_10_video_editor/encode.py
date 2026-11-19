"""Encoder targets and settings of the delivery encode (ADR-014, owner decision D10).

The video bitrate is an ENCODER TARGET, never a measured floor: x264 runs average-bitrate rate
control (``rc=abr``, variable bitrate) at the YouTube recommendation for the size and frame rate
(RESEARCH_LOG INF-12). The values are DATA (``data/encode_targets.json``, each row names its
research-log source), not code constants; a size or frame rate without a row needs an operator
value (``agent_10.render.video_bitrate_bps``; REQUIRES REVIEW). No filler data is ever written:
the argument templates never set ``nal-hrd=cbr`` or ``filler`` and QC refuses a stream that has it.
"""

import json
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from importlib import resources
from typing import Any

X264_PRESETS_ALLOWED = frozenset({"faster", "fast", "medium", "slow", "slower", "veryslow"})
"""``ultrafast`` produces Constrained Baseline (no CABAC, no B-frames; measured, README); the
other fast presets are not offered either: the owner asked for ``faster`` or slower (ADR-014)."""


@dataclass(frozen=True, slots=True)
class EncodeTarget:
    width_px: int
    height_px: int
    fps: tuple[Fraction, ...]
    target_bps: int
    source: str


@dataclass(frozen=True, slots=True)
class EncodeTable:
    profile: str
    pix_fmt: str
    bframes: int
    cabac: bool
    closed_gop: bool
    gop_rule: str
    rate_control: str
    codec_source: str
    targets: tuple[EncodeTarget, ...]

    def target_for(self, width_px: int, height_px: int, fps: Fraction) -> EncodeTarget | None:
        for row in self.targets:
            if row.width_px == width_px and row.height_px == height_px and fps in row.fps:
                return row
        return None

    def gop_for(self, fps: Fraction) -> int | None:
        """``HALF_FRAME_RATE`` (INF-13): only when half the rate is a whole number of frames."""
        if self.gop_rule != "HALF_FRAME_RATE":
            return None
        half = fps / 2
        return int(half) if half.denominator == 1 and half >= 1 else None


def _fraction(text: str) -> Fraction:
    num, den = text.split("/")
    return Fraction(int(num), int(den))


def parse_table(raw: dict[str, Any]) -> EncodeTable:
    codec = raw["codec"]
    return EncodeTable(
        profile=str(codec["profile"]),
        pix_fmt=str(codec["pix_fmt"]),
        bframes=int(codec["bframes"]),
        cabac=bool(codec["cabac"]),
        closed_gop=bool(codec["closed_gop"]),
        gop_rule=str(codec["gop_rule"]),
        rate_control=str(codec["rate_control"]),
        codec_source=str(codec["source"]),
        targets=tuple(
            EncodeTarget(
                width_px=int(row["width_px"]),
                height_px=int(row["height_px"]),
                fps=tuple(_fraction(f) for f in row["fps"]),
                target_bps=int(row["target_bps"]),
                source=str(row["source"]),
            )
            for row in raw["targets"]
        ),
    )


@cache
def encode_table() -> EncodeTable:
    text = (
        resources.files("agent_10_video_editor")
        .joinpath("data", "encode_targets.json")
        .read_text("utf-8")
    )
    return parse_table(json.loads(text))


@dataclass(frozen=True, slots=True)
class EncodeSettings:
    """The resolved settings of one render configuration (recorded in the render output)."""

    target_bps: int
    target_source: str
    maxrate_bps: int | None
    bufsize_bps: int | None
    gop_frames: int
    gop_source: str
    bframes: int
    cabac: bool
    x264_preset: str
    rate_control: str

    def recorded(self) -> dict[str, Any]:
        return {
            "mode": self.rate_control,
            "target_bps": self.target_bps,
            "target_source": self.target_source,
            "maxrate_bps": self.maxrate_bps,
            "bufsize_bps": self.bufsize_bps,
            "bframes": self.bframes,
            "cabac": self.cabac,
            "x264_preset": self.x264_preset,
            "filler": False,
        }


def resolve(
    *,
    width_px: int,
    height_px: int,
    fps: Fraction,
    video_bitrate_bps: int | None,
    video_maxrate_bps: int | None,
    video_bufsize_bps: int | None,
    gop_frames: int | None,
    x264_preset: str,
    table: EncodeTable | None = None,
) -> EncodeSettings:
    """Resolve the settings; a problem raises ``ValueError`` with a stable reason code."""
    t = table or encode_table()
    if x264_preset not in X264_PRESETS_ALLOWED:
        raise ValueError("X264_PRESET_NOT_ALLOWED")
    row = t.target_for(width_px, height_px, fps)
    if row is not None:
        if video_bitrate_bps is not None and video_bitrate_bps != row.target_bps:
            raise ValueError("ENCODE_TARGET_CONFLICT")
        target, source = row.target_bps, row.source
    elif video_bitrate_bps is not None:
        target, source = video_bitrate_bps, "OPERATOR_CONFIG (REQUIRES REVIEW: no INF-12 row)"
    else:
        raise ValueError("ENCODE_TARGET_REQUIRES_REVIEW")
    if video_bufsize_bps is not None and video_maxrate_bps is None:
        raise ValueError("VBV_BUFSIZE_WITHOUT_MAXRATE")
    if video_maxrate_bps is not None:
        if video_maxrate_bps <= target:
            raise ValueError("VBR_MAXRATE_NOT_ABOVE_TARGET")  # x264 would switch to rc=cbr
        if video_bufsize_bps is None:
            raise ValueError("VBV_MAXRATE_WITHOUT_BUFSIZE")
    derived = t.gop_for(fps)
    if derived is not None:
        if gop_frames is not None and gop_frames != derived:
            raise ValueError("GOP_CONFLICT")
        gop, gop_source = derived, t.codec_source
    elif gop_frames is not None:
        gop = gop_frames
        gop_source = "OPERATOR_CONFIG (REQUIRES REVIEW: half the rate is fractional)"
    else:
        raise ValueError("GOP_REQUIRES_REVIEW")
    return EncodeSettings(
        target_bps=target,
        target_source=source,
        maxrate_bps=video_maxrate_bps,
        bufsize_bps=video_bufsize_bps,
        gop_frames=gop,
        gop_source=gop_source,
        bframes=t.bframes,
        cabac=t.cabac,
        x264_preset=x264_preset,
        rate_control=t.rate_control,
    )


__all__ = [
    "X264_PRESETS_ALLOWED",
    "EncodeSettings",
    "EncodeTable",
    "EncodeTarget",
    "encode_table",
    "parse_table",
    "resolve",
]
