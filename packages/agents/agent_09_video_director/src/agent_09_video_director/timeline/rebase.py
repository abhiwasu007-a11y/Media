"""rebase_plan (F-24; FR-16): keep shot IDs, follow a new measured narration timeline."""

import itertools
from collections.abc import Mapping, Sequence

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import Shot
from agent_09_video_director.mathx import round_half_up
from agent_09_video_director.problems import input_invalid


def _anchors(
    old: Mapping[str, tuple[int, int]], new: Mapping[str, tuple[int, int]]
) -> list[tuple[int, int]]:
    pts: dict[int, int] = {0: 0}
    for seg_id, (os_, oe) in old.items():
        ns, ne = new[seg_id]
        pts[os_] = ns
        pts[oe] = ne
    return sorted(pts.items())


def _map(t: int, anchors: Sequence[tuple[int, int]]) -> int:
    """Piecewise-linear map of an old time to the new timeline (extrapolate by shift)."""
    if t <= anchors[0][0]:
        return anchors[0][1] + (t - anchors[0][0])
    for (a, a2), (b, b2) in itertools.pairwise(anchors):
        if a <= t <= b:
            return a2 + round_half_up((t - a) * (b2 - a2), b - a) if b > a else a2
    last_old, last_new = anchors[-1]
    return last_new + (t - last_old)


def rebase_shots(
    shots: Sequence[Shot],
    old_timeline: Mapping[str, tuple[int, int]],
    new_timeline: Mapping[str, tuple[int, int]],
    cfg: Agent09Config,
) -> tuple[Shot, ...]:
    """Recompute every start/end from the segment anchors; shot IDs, content keys, directions are
    kept. A J/L offset is kept on the new boundary. Fails ``REBASE_LIMIT`` when a hard limit
    cannot hold (the orchestrator then runs a new iteration of the full stage)."""
    anchors = _anchors(old_timeline, new_timeline)
    new_content_end = max(e for _, e in new_timeline.values())
    out: list[Shot] = []
    for i, shot in enumerate(shots):
        base_start = shot.start_ms - shot.cut_offset_ms if i else 0
        start = 0 if i == 0 else _map(base_start, anchors) + shot.cut_offset_ms
        if i + 1 < len(shots):
            nxt = shots[i + 1]
            end = _map(nxt.start_ms - nxt.cut_offset_ms, anchors) + nxt.cut_offset_ms
        else:
            end = new_content_end
        events = tuple(_map(e, anchors) for e in shot.change_events_ms)
        duration = end - start
        limit = shot.held.max_ms if shot.held is not None else cfg.g_max_ms
        if duration <= 0 or (shot.held is None and duration > limit):
            raise input_invalid("REBASE_LIMIT")
        out.append(
            shot.model_copy(
                update={
                    "start_ms": start,
                    "end_ms": end,
                    "duration_ms": duration,
                    "change_events_ms": events,
                }
            )
        )
    return tuple(out)
