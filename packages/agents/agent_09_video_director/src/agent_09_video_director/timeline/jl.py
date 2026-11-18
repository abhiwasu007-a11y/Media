"""JlPlanner (F-17; blueprint 6.4.5): J-cuts and L-cuts on sentence-aligned boundaries."""

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from agent_09_video_director.config import Agent09Config


@dataclass(frozen=True, slots=True)
class JlShot:
    shot_id: str
    start_ms: int
    end_ms: int
    is_chart: bool = False
    change_events_ms: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundaryInfo:
    """Facts about the boundary at the start of the next shot."""

    next_shot_is_chart: bool = False
    next_first_segment_starts_here: bool = False
    next_segment_is_disclaimer: bool = False
    previous_segment_is_disclaimer: bool = False


@dataclass(frozen=True, slots=True)
class AppliedCut:
    boundary_ms: int
    kind: Literal["J", "L"]
    cut_ms: int
    cut_offset_ms: int
    from_shot_id: str
    to_shot_id: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SkippedBoundary:
    boundary_ms: int
    reason: str


@dataclass(frozen=True, slots=True)
class JlResult:
    applied: tuple[AppliedCut, ...]
    skipped: tuple[SkippedBoundary, ...]
    eligible_count: int


def plan_jl(
    shots: Sequence[JlShot],
    cfg: Agent09Config,
    hook_end_ms: int,
    *,
    eligible_boundaries_ms: set[int] | None = None,
    info: Mapping[int, BoundaryInfo] | None = None,
) -> JlResult:
    """``eligible_boundaries_ms=None`` means every shot boundary is sentence-aligned."""
    if cfg.jl_offset_ms is None or cfg.jl_every_nth is None:
        return JlResult((), (), 0)  # feature off until the rate is set (WARN in the check)
    offset, nth = cfg.jl_offset_ms, cfg.jl_every_nth
    lo, hi = cfg.snap_min_slot_ms, cfg.g_max_ms
    applied: list[AppliedCut] = []
    skipped: list[SkippedBoundary] = []
    k = 0
    next_kind: Literal["J", "L"] = "J"
    for prev, nxt in itertools.pairwise(shots):
        b = nxt.start_ms
        if eligible_boundaries_ms is not None and b not in eligible_boundaries_ms:
            continue
        facts = (info or {}).get(b, BoundaryInfo())
        if b == hook_end_ms:
            skipped.append(SkippedBoundary(b, "HOOK_END"))
            continue
        if facts.next_segment_is_disclaimer or facts.previous_segment_is_disclaimer:
            skipped.append(SkippedBoundary(b, "DISCLAIMER"))
            continue
        k += 1
        if k % nth != 0:
            continue
        kind: Literal["J", "L"] = next_kind
        note: str | None = None
        if (
            kind == "J"
            and (facts.next_shot_is_chart or nxt.is_chart)
            and (facts.next_first_segment_starts_here)
        ):
            kind, note = "L", "CHART_NEEDS_VISIBLE"
        cut = b + offset if kind == "J" else b - offset
        prev_len, next_len = cut - prev.start_ms, nxt.end_ms - cut
        events_ok = all(prev.start_ms < e < cut for e in prev.change_events_ms) and all(
            cut < e < nxt.end_ms for e in nxt.change_events_ms
        )
        if not (lo <= prev_len <= hi and lo <= next_len <= hi) or not events_ok:
            skipped.append(SkippedBoundary(b, "GAP_LIMIT"))
            continue
        applied.append(AppliedCut(b, kind, cut, cut - b, prev.shot_id, nxt.shot_id, note))
        next_kind = "L" if next_kind == "J" else "J"
    return JlResult(tuple(applied), tuple(skipped), k)
