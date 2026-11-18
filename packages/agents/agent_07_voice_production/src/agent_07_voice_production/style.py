"""Style mapping (F-26): pace and emotion tags to the adapter's declared controls.

A closed 3x6 enum mapped through the adapter's capabilities; a control the adapter does not
declare is reported as ``applied = NONE``, never faked (FR-8, ADR-008 open item).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from agent_07_voice_production.contracts import (
    AppliedEmotion,
    AppliedPace,
    ControlLevel,
    Emotion,
    Pace,
    ScriptSegment,
)
from agent_07_voice_production.ports import TtsCapabilities


@dataclass(frozen=True, slots=True)
class StyleDecision:
    pace_applied: AppliedPace
    emotion_applied: AppliedEmotion


def map_style(pace: Pace, emotion: Emotion, caps: TtsCapabilities) -> StyleDecision:
    return StyleDecision(
        pace_applied=AppliedPace(pace.value)
        if caps.pace_control is ControlLevel.NATIVE
        else AppliedPace.NONE,
        emotion_applied=AppliedEmotion(emotion.value)
        if caps.emotion_control is ControlLevel.NATIVE
        else AppliedEmotion.NONE,
    )


def is_non_default(segment: ScriptSegment) -> bool:
    return segment.pace is not Pace.NORMAL or segment.emotion is not Emotion.NEUTRAL


def applied_ratio(
    segments: Sequence[ScriptSegment], decisions: Sequence[StyleDecision]
) -> tuple[int, int]:
    """(sentences whose requested non-default style was fully applied, sentences that asked)."""
    asked = 0
    applied = 0
    for seg, dec in zip(segments, decisions, strict=True):
        if not is_non_default(seg):
            continue
        asked += 1
        pace_ok = seg.pace is Pace.NORMAL or dec.pace_applied.value == seg.pace.value
        emotion_ok = seg.emotion is Emotion.NEUTRAL or dec.emotion_applied.value == seg.emotion.value
        if pace_ok and emotion_ok:
            applied += 1
    return applied, asked


def distinct_variation(segments: Sequence[ScriptSegment]) -> bool:
    """18 section 4 ``qc.voice.variation``: at least two distinct pace or emotion values."""
    return len({s.pace for s in segments}) >= 2 or len({s.emotion for s in segments}) >= 2
