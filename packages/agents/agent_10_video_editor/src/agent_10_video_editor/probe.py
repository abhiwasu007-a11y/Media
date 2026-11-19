"""Tool-output parsers (blueprint 10 section 10; F-18..F-24; 18 section 7).

Pure functions on tool text. Seconds in tool text become integer milliseconds by DECIMAL TEXT
(round half up), never through floating-point arithmetic. A missing or unparseable value raises
``MeasurementUnavailable``; nothing here ever defaults to a passing value (18 section 7.0.3).
"""

import itertools
import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

from agent_10_video_editor.errors import MeasurementUnavailable

Interval = tuple[int, int]


def seconds_to_ms(text: str) -> int:
    """Decimal seconds text to integer ms, round half up (no float arithmetic)."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation as exc:
        raise MeasurementUnavailable([f"seconds:{text.strip()[:16]}"]) from exc
    return int((value * 1000).to_integral_value(rounding=ROUND_HALF_UP))


def _rational(text: str) -> Fraction:
    try:
        if "/" in text:
            num, den = text.split("/")
            if int(den) == 0:
                raise MeasurementUnavailable(["rational"])
            return Fraction(int(num), int(den))
        return Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise MeasurementUnavailable(["rational"]) from exc


# ----------------------------------------------------------------------------- ffprobe json


@dataclass(frozen=True, slots=True)
class VideoStream:
    codec_name: str
    profile: str | None
    pix_fmt: str | None
    width: int
    height: int
    field_order: str | None
    r_frame_rate: Fraction
    avg_frame_rate: Fraction
    bit_rate: int | None
    start_time: str | None
    duration: str | None
    colour: dict[str, str | None]
    level: int | None = None
    has_b_frames: int | None = None


@dataclass(frozen=True, slots=True)
class AudioStream:
    codec_name: str
    profile: str | None
    sample_rate: int
    channels: int
    bit_rate: int | None
    start_time: str | None
    duration: str | None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    video: VideoStream
    audio: AudioStream | None
    format_name: str
    duration_ms: int
    size_bytes: int | None
    format_bit_rate: int | None

    @property
    def video_bitrate_bps(self) -> int:
        """Stream ``bit_rate``; absent -> ``size * 8 / duration`` (blueprint F-18)."""
        if self.video.bit_rate is not None:
            return self.video.bit_rate
        if self.size_bytes is None or self.duration_ms <= 0:
            raise MeasurementUnavailable(["video_bitrate_bps"])
        audio_bits = (self.audio.bit_rate or 0) if self.audio else 0
        total = self.size_bytes * 8 * 1000 // self.duration_ms
        return max(total - audio_bits, 0)


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except TypeError, ValueError:
        return None


class ProbeParser:
    @staticmethod
    def parse(json_text: str) -> ProbeResult:
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise MeasurementUnavailable(["probe_json"]) from exc
        streams = data.get("streams")
        fmt = data.get("format")
        if not isinstance(streams, list) or not isinstance(fmt, dict):
            raise MeasurementUnavailable(["streams", "format"])
        video_raw = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_raw = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video_raw is None:
            raise MeasurementUnavailable(["video_stream"])
        required = ("codec_name", "width", "height", "r_frame_rate", "avg_frame_rate")
        missing = [k for k in required if k not in video_raw]
        if missing or "duration" not in fmt:
            raise MeasurementUnavailable([*missing, *([] if "duration" in fmt else ["duration"])])
        video = VideoStream(
            codec_name=video_raw["codec_name"],
            profile=video_raw.get("profile"),
            pix_fmt=video_raw.get("pix_fmt"),
            width=int(video_raw["width"]),
            height=int(video_raw["height"]),
            field_order=video_raw.get("field_order"),
            r_frame_rate=_rational(str(video_raw["r_frame_rate"])),
            avg_frame_rate=_rational(str(video_raw["avg_frame_rate"])),
            bit_rate=_int(video_raw.get("bit_rate")),
            start_time=video_raw.get("start_time"),
            duration=video_raw.get("duration"),
            colour={
                "primaries": video_raw.get("color_primaries"),
                "transfer": video_raw.get("color_transfer"),
                "matrix": video_raw.get("color_space"),
                "range": video_raw.get("color_range"),
            },
            level=_int(video_raw.get("level")),
            has_b_frames=_int(video_raw.get("has_b_frames")),
        )
        audio = None
        if audio_raw is not None:
            if (
                "codec_name" not in audio_raw
                or "sample_rate" not in audio_raw
                or "channels" not in audio_raw
            ):
                raise MeasurementUnavailable(["audio_stream_fields"])
            audio = AudioStream(
                codec_name=audio_raw["codec_name"],
                profile=audio_raw.get("profile"),
                sample_rate=int(audio_raw["sample_rate"]),
                channels=int(audio_raw["channels"]),
                bit_rate=_int(audio_raw.get("bit_rate")),
                start_time=audio_raw.get("start_time"),
                duration=audio_raw.get("duration"),
            )
        return ProbeResult(
            video=video,
            audio=audio,
            format_name=str(fmt.get("format_name", "")),
            duration_ms=seconds_to_ms(str(fmt["duration"])),
            size_bytes=_int(fmt.get("size")),
            format_bit_rate=_int(fmt.get("bit_rate")),
        )

    @staticmethod
    def parse_frame_count(json_text: str) -> int:
        try:
            streams = json.loads(json_text)["streams"]
            return int(streams[0]["nb_read_frames"])
        except (json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError) as exc:
            raise MeasurementUnavailable(["nb_read_frames"]) from exc

    @staticmethod
    def parse_first_frame_idr(json_text: str) -> bool:
        try:
            frame = json.loads(json_text)["frames"][0]
            return int(frame["key_frame"]) == 1 and frame.get("pict_type") == "I"
        except (json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError) as exc:
            raise MeasurementUnavailable(["first_frame"]) from exc


# ----------------------------------------------------------------------------- ebur128


_I = re.compile(r"^\s+I:\s+(-?\d+(?:\.\d+)?)\s+LUFS\s*$", re.MULTILINE)
_LRA = re.compile(r"^\s+LRA:\s+(-?\d+(?:\.\d+)?)\s+LU\s*$", re.MULTILINE)
_PEAK = re.compile(r"^\s+Peak:\s+(-?\d+(?:\.\d+)?|-inf)\s+dBFS\s*$", re.MULTILINE)
SILENCE_FLOOR_DBTP = -144.0
"""Stored in place of ``-inf``: digital silence has no finite true peak (``silent`` flag is set)."""


class Ebur128Parser:
    """Summary block only; frame log lines are ignored (a running line is not a result)."""

    @staticmethod
    def parse(stderr: str) -> dict[str, float]:
        marker = stderr.rfind("Summary:")
        summary = stderr[marker:] if marker >= 0 else ""
        found: dict[str, float] = {}
        for key, pattern, block in (
            ("integrated_lufs", _I, "Integrated loudness:"),
            ("lra_lu", _LRA, "Loudness range:"),
            ("true_peak_dbtp", _PEAK, "True peak:"),
        ):
            position = summary.find(block)
            if position < 0:
                continue
            match = pattern.search(summary, position)
            if match:
                text = match.group(1)
                if text == "-inf":
                    found["silent"] = 1.0
                found[key] = SILENCE_FLOOR_DBTP if text == "-inf" else float(text)
        missing = [k for k in ("integrated_lufs", "lra_lu", "true_peak_dbtp") if k not in found]
        if missing:
            raise MeasurementUnavailable(missing)
        return found

    @staticmethod
    def parse_series(stderr: str) -> list[tuple[int, float]]:
        """Frame log lines ``t: <s> ... I: <x> LUFS`` downsampled to 1 Hz: ``(second, I)``."""
        series: dict[int, float] = {}
        for match in re.finditer(
            r"t:\s+(\d+(?:\.\d+)?)\s+M:.*?I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", stderr
        ):
            second = int(Decimal(match.group(1)))
            series.setdefault(second, float(match.group(2)))
        return sorted(series.items())


# ----------------------------------------------------------------------------- detectors


_BLACK = re.compile(r"black_start:(\S+)\s+black_end:(\S+)\s+black_duration:(\S+)")


class BlackdetectParser:
    @staticmethod
    def parse(stderr: str) -> list[Interval]:
        out: list[Interval] = []
        for line in stderr.splitlines():
            if "[blackdetect" not in line:
                continue
            match = _BLACK.search(line)
            if match is None:
                raise MeasurementUnavailable(["blackdetect_line"])
            out.append((seconds_to_ms(match.group(1)), seconds_to_ms(match.group(2))))
        return out


class SilencedetectParser:
    @staticmethod
    def parse(stderr: str, stream_end_ms: int) -> list[Interval]:
        runs: list[Interval] = []
        open_start: int | None = None
        for line in stderr.splitlines():
            if "[silencedetect" not in line:
                continue
            start = re.search(r"silence_start:\s*(\S+)", line)
            end = re.search(r"silence_end:\s*(\S+)", line)
            if start:
                open_start = seconds_to_ms(start.group(1))
            elif end:
                if open_start is None:
                    raise MeasurementUnavailable(["silence_start"])
                runs.append((open_start, seconds_to_ms(end.group(1))))
                open_start = None
            else:
                raise MeasurementUnavailable(["silencedetect_line"])
        if open_start is not None:
            runs.append((open_start, stream_end_ms))
        return runs


class FreezedetectParser:
    @staticmethod
    def parse(stderr: str, stream_end_ms: int | None = None) -> list[Interval]:
        runs: list[Interval] = []
        open_start: int | None = None
        for line in stderr.splitlines():
            if "freezedetect.freeze_start" in line:
                open_start = seconds_to_ms(line.rsplit(":", 1)[1])
            elif "freezedetect.freeze_end" in line:
                if open_start is None:
                    raise MeasurementUnavailable(["freeze_start"])
                runs.append((open_start, seconds_to_ms(line.rsplit(":", 1)[1])))
                open_start = None
        if open_start is not None:
            if stream_end_ms is None:
                raise MeasurementUnavailable(["stream_end_ms"])
            runs.append((open_start, stream_end_ms))
        return runs


class SceneParser:
    @staticmethod
    def parse(stderr: str) -> list[int]:
        return [
            seconds_to_ms(m.group(1))
            for m in re.finditer(r"\[Parsed_showinfo[^\]]*\].*?pts_time:(\d+(?:\.\d+)?)", stderr)
        ]


# ----------------------------------------------------------------------------- packets, atoms


class PacketParser:
    @staticmethod
    def histogram(csv_text: str) -> dict[str, int]:
        """Sorted ``pts_time`` values to a histogram of frame intervals keyed ``%.6f`` (text)."""
        values: list[Decimal] = []
        for line in csv_text.splitlines():
            token = line.strip().rstrip(",")
            if not token or token == "N/A":  # noqa: S105 - ffprobe text, not a credential
                continue
            try:
                values.append(Decimal(token))
            except InvalidOperation as exc:
                raise MeasurementUnavailable(["packet_pts"]) from exc
        if len(values) < 2:
            raise MeasurementUnavailable(["packet_pts"])
        values.sort()
        histogram: dict[str, int] = {}
        for earlier, later in itertools.pairwise(values):
            key = format(
                (later - earlier).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f"
            )
            histogram[key] = histogram.get(key, 0) + 1
        return histogram

    @staticmethod
    def count(csv_text: str) -> int:
        return sum(1 for line in csv_text.splitlines() if line.strip() and line.strip() != "N/A")


class AtomOrderChecker:
    """F-24 faststart: ``moov`` precedes ``mdat`` among the top-level boxes of the file head."""

    @staticmethod
    def order(head: bytes) -> list[str]:
        boxes: list[str] = []
        pos = 0
        while pos + 8 <= len(head):
            size = int.from_bytes(head[pos : pos + 4], "big")
            kind = head[pos + 4 : pos + 8].decode("latin-1")
            boxes.append(kind)
            if kind == "mdat" or size < 8:
                break
            pos += size
        return boxes

    @staticmethod
    def moov_first(head: bytes) -> bool:
        boxes = AtomOrderChecker.order(head)
        if "moov" not in boxes and "mdat" not in boxes:
            raise MeasurementUnavailable(["mp4_boxes"])
        if "mdat" not in boxes:
            return "moov" in boxes
        return "moov" in boxes and boxes.index("moov") < boxes.index("mdat")


def parse_stream_times(csv_text: str) -> dict[str, tuple[str, str]]:
    """``video,<start>,<duration>`` / ``audio,<start>,<duration>`` lines."""
    out: dict[str, tuple[str, str]] = {}
    for line in csv_text.splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 3 and parts[0] in ("video", "audio"):
            out[parts[0]] = (parts[1], parts[2])
    if "video" not in out or "audio" not in out:
        raise MeasurementUnavailable(["stream_times"])
    return out


# ----------------------------------------------------------------------------- encoder settings

_SSIM_ALL = re.compile(r"SSIM Y:[0-9.]+ .*?All:([0-9]+\.[0-9]+)")
_X264_SEI = b"x264 - core "
_X264_OPTIONS = re.compile(r"([a-z0-9_]+)=([^ ]+)")


class SsimParser:
    """The ``ssim`` filter summary ``SSIM Y:… U:… V:… All:<mean> (<dB>)`` (last line wins)."""

    @staticmethod
    def parse(stderr: str) -> str:
        found = _SSIM_ALL.findall(stderr)
        if not found:
            raise MeasurementUnavailable(["ssim_all"])
        return str(found[-1])


class X264SeiParser:
    """The x264 user-data SEI (``x264 - core … - options: k=v …``) that libx264 writes into the
    first access unit of every encode; ``-map_metadata -1`` and ``+bitexact`` do not remove it
    (measured on FFmpeg 6.1.1). Returns the option map, or ``None`` when no SEI is present."""

    @staticmethod
    def find(data: bytes) -> dict[str, str] | None:
        at = data.find(_X264_SEI)
        if at < 0:
            return None
        end = data.find(b"\x00", at)
        text = data[at : end if end >= 0 else at + 4096].decode("ascii", errors="replace")
        if " options: " not in text:
            return None
        options = text.split(" options: ", 1)[1]
        parsed = dict(_X264_OPTIONS.findall(options))
        core = text[len("x264 - core ") :].split(" - ", 1)[0]
        parsed["_core"] = core
        return parsed

    @staticmethod
    def scan_file(path: Any, chunk: int = 1 << 20) -> dict[str, str] | None:
        """Scan a file in chunks (with overlap) for the first SEI; bounded by the file size."""
        tail = b""
        with open(path, "rb") as handle:
            while True:
                block = handle.read(chunk)
                if not block:
                    return None
                data = tail + block
                at = data.find(_X264_SEI)
                if at >= 0:
                    rest = data[at:] + handle.read(8192)
                    return X264SeiParser.find(rest)
                tail = data[-len(_X264_SEI) :]
