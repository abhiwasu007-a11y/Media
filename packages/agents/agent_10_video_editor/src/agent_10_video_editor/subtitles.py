"""Subtitles: cue builder, SRT writer, parser and validator (blueprint 10 section 10.1; F-29..F-33).

Cue text is the script string itself (by ``segment_id``); timing comes from the aligned narration
timeline. Nothing here rewrites, translates or drops text: a cue that would have zero duration is
``PERMANENT.INPUT_INVALID`` (``CUE_TOO_SHORT``).
"""

import itertools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_10_video_editor.errors import input_invalid
from agent_10_video_editor.inputs import NarrationTimeline


@dataclass(frozen=True, slots=True)
class Cue:
    index: int
    start_ms: int
    end_ms: int
    text: str
    segment_id: str | None = None


@dataclass(frozen=True, slots=True)
class CueBuild:
    cues: tuple[Cue, ...]
    warnings: tuple[str, ...]


def _round_half_up_div(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


class CueBuilder:
    @staticmethod
    def build(
        segment_id: str, start_ms: int, end_ms: int, text: str, max_chars_per_cue: int
    ) -> CueBuild:
        if max_chars_per_cue < 1:
            raise input_invalid("MAX_CHARS_NOT_POSITIVE")
        lines: list[str] = []
        warnings: list[str] = []
        current = ""
        for token in text.split():
            if current and len(current) + 1 + len(token) <= max_chars_per_cue:
                current = f"{current} {token}"
                continue
            if current:
                lines.append(current)
            current = token
            if len(token) > max_chars_per_cue:
                warnings.append(f"OVERLONG_TOKEN:{segment_id}")
                lines.append(current)
                current = ""
        if current:
            lines.append(current)
        if not lines:
            raise input_invalid(f"EMPTY_TEXT:{segment_id}")
        total = sum(len(line) for line in lines)
        duration = end_ms - start_ms
        boundaries = [start_ms]
        cumulative = 0
        for line in lines:
            cumulative += len(line)
            boundaries.append(start_ms + _round_half_up_div(duration * cumulative, total))
        boundaries[-1] = end_ms
        if any(b <= a for a, b in itertools.pairwise(boundaries)):
            raise input_invalid(f"CUE_TOO_SHORT:{segment_id}")
        cues = tuple(
            Cue(0, boundaries[i], boundaries[i + 1], line, segment_id)
            for i, line in enumerate(lines)
        )
        return CueBuild(cues, tuple(dict.fromkeys(warnings)))


class SrtWriter:
    @staticmethod
    def format_time(ms: int) -> str:
        hours, rest = divmod(ms, 3_600_000)
        minutes, rest = divmod(rest, 60_000)
        seconds, millis = divmod(rest, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    @staticmethod
    def write(cues: Sequence[Cue]) -> bytes:
        """UTF-8 without BOM, LF, numbered cues, a blank line after every cue."""
        fmt = SrtWriter.format_time
        parts = [
            f"{n}\n{fmt(c.start_ms)} --> {fmt(c.end_ms)}\n{c.text}\n"
            for n, c in enumerate(cues, start=1)
        ]
        return "\n".join(parts).encode("utf-8")


_TIME = re.compile(r"^(\d{2,}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2,}):(\d{2}):(\d{2}),(\d{3})$")


def _ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


class SrtParser:
    """F-31: strict parse (used by the validator and the round-trip test)."""

    @staticmethod
    def parse(data: bytes) -> list[Cue]:
        if data.startswith(b"\xef\xbb\xbf"):
            raise input_invalid("SRT_BOM")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise input_invalid("SRT_NOT_UTF8") from exc
        if "\r" in text:
            raise input_invalid("SRT_NOT_LF")
        cues: list[Cue] = []
        for block in text.strip("\n").split("\n\n"):
            lines = block.split("\n")
            if len(lines) < 3 or not lines[0].isdigit():
                raise input_invalid("SRT_BLOCK")
            match = _TIME.match(lines[1])
            if match is None:
                raise input_invalid("SRT_TIME")
            g = match.groups()
            cues.append(Cue(int(lines[0]), _ms(*g[:4]), _ms(*g[4:]), "\n".join(lines[2:])))
        return cues


class SrtValidator:
    """F-32: report ALL errors in cue order (no first-error stop)."""

    @staticmethod
    def validate(cues: Sequence[Cue], video_duration_ms: int) -> list[str]:
        errors: list[str] = []
        previous_end: int | None = None
        for position, cue in enumerate(cues, start=1):
            if cue.index != position:
                errors.append(f"NUMBERING:{cue.index}")
            if not cue.text.strip():
                errors.append(f"EMPTY_TEXT:{cue.index}")
            if cue.end_ms <= cue.start_ms:
                errors.append(f"NON_POSITIVE_DURATION:{cue.index}")
            if previous_end is not None and cue.start_ms < previous_end:
                errors.append(f"OVERLAP:{cue.index}")
            previous_end = cue.end_ms
        if cues and cues[-1].end_ms > video_duration_ms:
            errors.append("LAST_CUE_AFTER_VIDEO_END")
        if not cues:
            errors.append("NO_CUES")
        return errors


@dataclass(frozen=True, slots=True)
class SubtitleBuild:
    cues: tuple[Cue, ...]
    srt: bytes
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


class SubtitleStageCore:
    """The pure part of ``agent_10.subtitles`` (the stage adds storage and rows)."""

    @staticmethod
    def check_timeline_source(timeline_source: str) -> None:
        """F-33: an ``UNALIGNED`` timeline is a contract violation (cannot occur in 3A, CCR-051)."""
        if timeline_source == "UNALIGNED":
            raise input_invalid("TIMELINE_UNALIGNED")

    @staticmethod
    def build(
        timeline: NarrationTimeline,
        script_segments: Mapping[str, str],
        max_chars_per_cue: int,
        video_duration_ms: int,
    ) -> SubtitleBuild:
        SubtitleStageCore.check_timeline_source(timeline.source)
        cues: list[Cue] = []
        warnings: list[str] = []
        for segment in timeline.segments:
            text = script_segments.get(segment.segment_id)
            if text is None:
                raise input_invalid(f"SEGMENT_TEXT_MISSING:{segment.segment_id}")
            built = CueBuilder.build(
                segment.segment_id, segment.start_ms, segment.end_ms, text, max_chars_per_cue
            )
            cues.extend(built.cues)
            warnings.extend(built.warnings)
        numbered = tuple(
            Cue(n, c.start_ms, c.end_ms, c.text, c.segment_id) for n, c in enumerate(cues, start=1)
        )
        errors = tuple(SrtValidator.validate(numbered, video_duration_ms))
        return SubtitleBuild(
            numbered, SrtWriter.write(numbered), tuple(dict.fromkeys(warnings)), errors
        )
