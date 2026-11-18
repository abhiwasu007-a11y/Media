"""NarrationTimeline / TimeMap (F-04, FR-03): the measured narration timeline, verified."""

from collections.abc import Sequence
from dataclasses import dataclass

from agent_09_video_director.contracts import NarrationTimeline
from agent_09_video_director.problems import input_invalid


@dataclass(frozen=True, slots=True)
class TimeMap:
    """Segment -> (start_ms, end_ms), in script order."""

    order: tuple[str, ...]
    spans: dict[str, tuple[int, int]]

    @property
    def content_end_ms(self) -> int:
        return max(end for _, end in self.spans.values())

    def start(self, segment_id: str) -> int:
        return self.spans[segment_id][0]

    def end(self, segment_id: str) -> int:
        return self.spans[segment_id][1]

    def segment_starts(self) -> tuple[int, ...]:
        """Sentence boundaries (segment starts and the content end), sorted and unique."""
        return tuple(sorted({s for s, _ in self.spans.values()} | {self.content_end_ms}))


def build_time_map(script_segment_ids: Sequence[str], timeline: NarrationTimeline) -> TimeMap:
    """Verify coverage (every script segment exactly once, in order, aligned) and build the map.

    ``UNALIGNED`` or any null time -> ``TIMELINE_UNALIGNED``; a missing, extra, repeated or
    reordered segment, an overlap or a non-positive span -> ``TIMELINE_INCOMPLETE``.
    """
    if timeline.source == "UNALIGNED" or any(
        s.start_ms is None or s.end_ms is None for s in timeline.segments
    ):
        raise input_invalid("TIMELINE_UNALIGNED")
    ids = [s.segment_id for s in timeline.segments]
    if ids != list(script_segment_ids):
        raise input_invalid("TIMELINE_INCOMPLETE")
    spans: dict[str, tuple[int, int]] = {}
    previous_end = 0
    for seg in timeline.segments:
        if seg.start_ms is None or seg.end_ms is None:  # narrowed above, never reached
            raise input_invalid("TIMELINE_UNALIGNED")
        if seg.start_ms >= seg.end_ms or seg.start_ms < previous_end or seg.start_ms < 0:
            raise input_invalid("TIMELINE_INCOMPLETE")
        spans[seg.segment_id] = (seg.start_ms, seg.end_ms)
        previous_end = seg.end_ms
    return TimeMap(order=tuple(ids), spans=spans)
