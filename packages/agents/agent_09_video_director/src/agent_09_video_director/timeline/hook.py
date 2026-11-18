"""HookAnalyzer (F-06, FR-04): hook end and first payoff on the measured timeline."""

from collections.abc import Sequence
from dataclasses import dataclass

from agent_09_video_director.contracts import AspectRatio, SegmentKind
from agent_09_video_director.problems import input_invalid

_LONG_HOOK = frozenset({SegmentKind.HOOK_PROOF, SegmentKind.HOOK_WHY, SegmentKind.HOOK_COVERS})


@dataclass(frozen=True, slots=True)
class TimedSegment:
    segment_id: str
    kind: SegmentKind
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class HookInfo:
    end_ms: int
    first_payoff_ms: int
    segment_ids: tuple[str, ...]


def analyze_hook(segments: Sequence[TimedSegment], aspect: AspectRatio, window_ms: int) -> HookInfo:
    """Hook = contiguous hook-kind segments from the first segment.

    Long form: ``HOOK_PROOF``/``HOOK_WHY``/``HOOK_COVERS``, first payoff = end of the last
    ``HOOK_PROOF``. 9:16: ``SHORT_HOOK`` beats, first payoff = hook end (CCR-003).
    """
    kinds = {SegmentKind.SHORT_HOOK} if aspect is AspectRatio.PORTRAIT else _LONG_HOOK
    hook: list[TimedSegment] = []
    for seg in segments:
        if seg.kind not in kinds:
            break
        hook.append(seg)
    needed = SegmentKind.SHORT_HOOK if aspect is AspectRatio.PORTRAIT else SegmentKind.HOOK_PROOF
    if not any(s.kind is needed for s in hook):
        raise input_invalid("HOOK_BEATS_MISSING")
    hook_end = hook[-1].end_ms
    if aspect is AspectRatio.PORTRAIT:
        payoff = hook_end
    else:
        payoff = max(s.end_ms for s in hook if s.kind is SegmentKind.HOOK_PROOF)
    if hook_end > window_ms or payoff > window_ms:
        raise input_invalid("HOOK_WINDOW_EXCEEDED")
    return HookInfo(
        end_ms=hook_end, first_payoff_ms=payoff, segment_ids=tuple(s.segment_id for s in hook)
    )
