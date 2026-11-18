"""Stem assembly and the measured narration timeline (F-14, F-15, FR-11, FR-12).

All positions are exact sample arithmetic at 48 000 Hz and reported in whole milliseconds. The
timeline is MEASURED from the clips (or, for an owner recording, from the owner's per-sentence
marks); it is never estimated. There is no ``UNALIGNED`` result in 3A: a recording without
complete marks is refused (CCR-051).
"""

from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from agent_07_voice_production.contracts import (
    AppliedEmotion,
    AppliedPace,
    NarrationTimeline,
    PauseKind,
    ScriptDocument,
    SegmentMark,
    TimelinePause,
    TimelineSegment,
    TimelineSource,
)
from agent_07_voice_production.pcm import silence_samples
from agent_07_voice_production.style import StyleDecision
from amw_core.errors import InputInvalidError


@dataclass(frozen=True, slots=True)
class PlacedClip:
    segment_id: str
    samples: array[int]
    spoken_text_sha256: str
    idempotency_key: str | None
    reused: bool


@dataclass(frozen=True, slots=True)
class Assembly:
    samples: array[int]
    segments: tuple[TimelineSegment, ...]
    pauses: tuple[TimelinePause, ...]


def _ms(samples: int, rate: int) -> int:
    return samples * 1000 // rate


def assemble(
    clips: Sequence[PlacedClip],
    script: ScriptDocument,
    styles: Mapping[str, StyleDecision],
    *,
    gap_ms: int,
    sample_rate_hz: int,
) -> Assembly:
    """Concatenate at sample precision: a gap after every sentence except the last, and the
    scene's ``deliberate_pause_ms`` after the gap that follows its last sentence (FR-11)."""
    by_id = {s.segment_id: s for s in script.segments}
    pause_of = {s.scene_id: s.deliberate_pause_ms for s in script.scenes}
    stem: array[int] = array("h")
    segments: list[TimelineSegment] = []
    pauses: list[TimelinePause] = []
    gap = gap_ms * sample_rate_hz // 1000
    for index, clip in enumerate(clips):
        seg = by_id[clip.segment_id]
        start = len(stem)
        stem.extend(clip.samples)
        end = len(stem)
        style = styles[clip.segment_id]
        segments.append(
            TimelineSegment(
                segment_id=clip.segment_id,
                start_ms=_ms(start, sample_rate_hz),
                end_ms=_ms(end, sample_rate_hz),
                duration_ms=_ms(end - start, sample_rate_hz),
                pace_requested=seg.pace,
                emotion_requested=seg.emotion,
                pace_applied=style.pace_applied,
                emotion_applied=style.emotion_applied,
                spoken_text_sha256=clip.spoken_text_sha256,
                reused_clip=clip.reused,
                idempotency_key=clip.idempotency_key,
            )
        )
        if index == len(clips) - 1:
            continue
        if gap > 0:
            stem.extend(silence_samples(gap_ms, sample_rate_hz))
            pauses.append(
                TimelinePause(
                    after_segment_id=clip.segment_id,
                    start_ms=_ms(end, sample_rate_hz),
                    end_ms=_ms(len(stem), sample_rate_hz),
                    kind=PauseKind.GAP,
                )
            )
        scene_pause_ms = pause_of.get(seg.scene_id, 0)
        next_seg = by_id[clips[index + 1].segment_id]
        if scene_pause_ms > 0 and next_seg.scene_id != seg.scene_id:
            before = len(stem)
            stem.extend(silence_samples(scene_pause_ms, sample_rate_hz))
            pauses.append(
                TimelinePause(
                    after_segment_id=clip.segment_id,
                    start_ms=_ms(before, sample_rate_hz),
                    end_ms=_ms(len(stem), sample_rate_hz),
                    kind=PauseKind.SCENE_PAUSE,
                )
            )
    return Assembly(stem, tuple(segments), tuple(pauses))


# --- owner recording (F-13) -----------------------------------------------------------------


def validate_marks(
    marks: Sequence[SegmentMark],
    script: ScriptDocument,
    *,
    duration_ms: int,
    max_gap_ms: int | None,
) -> None:
    """Marks are required, one per script segment, strictly increasing and inside the recording.
    The violation list names segment IDs so the owner can fix the marks (CCR-051)."""
    problems: list[str] = []
    wanted = [s.segment_id for s in script.segments]
    got = [m.segment_id for m in marks]
    missing = [s for s in wanted if s not in got]
    extra = [s for s in got if s not in wanted]
    if missing:
        problems.append(f"no mark for segments {', '.join(missing)}")
    if extra:
        problems.append(f"marks for unknown segments {', '.join(extra)}")
    if len(set(got)) != len(got):
        problems.append("duplicate segment marks")
    if not (missing or extra) and got != wanted:
        problems.append("marks are not in script order")
    previous_end = 0
    for mark in marks:
        if mark.end_ms <= mark.start_ms:
            problems.append(f"{mark.segment_id}: end is not after start")
        if mark.start_ms < previous_end:
            problems.append(f"{mark.segment_id}: starts before the previous segment ends")
        elif max_gap_ms is not None and mark.start_ms - previous_end > max_gap_ms:
            problems.append(f"{mark.segment_id}: gap before it exceeds the configured maximum")
        if mark.end_ms > duration_ms:
            problems.append(f"{mark.segment_id}: ends after the recording")
        previous_end = max(previous_end, mark.end_ms)
    if problems:
        raise InputInvalidError(
            "the segment marks are not usable (a recording without complete marks is refused)",
            details={
                "violations": [{"path": "", "keyword": "marks", "message": m} for m in problems]
            },
        )


def timeline_from_marks(
    marks: Sequence[SegmentMark], script: ScriptDocument
) -> tuple[tuple[TimelineSegment, ...], tuple[TimelinePause, ...]]:
    by_id = {s.segment_id: s for s in script.segments}
    segments = tuple(
        TimelineSegment(
            segment_id=m.segment_id,
            start_ms=m.start_ms,
            end_ms=m.end_ms,
            duration_ms=m.end_ms - m.start_ms,
            pace_requested=by_id[m.segment_id].pace,
            emotion_requested=by_id[m.segment_id].emotion,
            pace_applied=AppliedPace.NONE,
            emotion_applied=AppliedEmotion.NONE,
            spoken_text_sha256=None,
            reused_clip=False,
            idempotency_key=None,
        )
        for m in marks
    )
    pauses = tuple(
        TimelinePause(
            after_segment_id=a.segment_id, start_ms=a.end_ms, end_ms=b.start_ms, kind=PauseKind.GAP
        )
        for a, b in pairwise(marks)
        if b.start_ms > a.end_ms
    )
    return segments, pauses


# --- a07.timeline.complete ----------------------------------------------------------------


def timeline_problems(
    timeline: NarrationTimeline, script: ScriptDocument, stem_duration_ms: int
) -> list[str]:
    """Empty list = ``a07.timeline.complete`` PASS: an entry per sentence, monotonic, and (for
    provider clips) a total equal to the stem duration."""
    problems: list[str] = []
    if [s.segment_id for s in timeline.segments] != [s.segment_id for s in script.segments]:
        problems.append("timeline segments differ from the script segments")
    previous_end = 0
    for seg in timeline.segments:
        if seg.start_ms < previous_end or seg.end_ms <= seg.start_ms:
            problems.append(f"{seg.segment_id} is not monotonic")
        previous_end = seg.end_ms
    last_end = timeline.segments[-1].end_ms if timeline.segments else 0
    if last_end > stem_duration_ms:
        problems.append("the last segment ends after the stem")
    if timeline.source is TimelineSource.PROVIDER_CLIPS and last_end != stem_duration_ms:
        problems.append("the total timeline differs from the stem duration")
    if timeline.total_duration_ms != stem_duration_ms:
        problems.append("timeline total_duration_ms differs from the stem duration")
    return problems
