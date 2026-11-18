"""SlotGrid and ChartPlanner (F-08, F-09; blueprint 6.2): shot slots from the measured spans."""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import Held, HeldReason
from agent_09_video_director.mathx import ceil_div, round_half_up


@dataclass(frozen=True, slots=True)
class GridSlot:
    start_ms: int
    end_ms: int
    held: Held | None = None
    change_events_ms: tuple[int, ...] = ()


def _snap(
    ideal: Sequence[int],
    boundaries: Sequence[int],
    t0: int,
    t1: int,
    cfg: Agent09Config,
) -> list[int]:
    """Step 5: nearest sentence boundary within tolerance (ties earlier), if slots stay legal."""
    g_max = cfg.g_max_ms
    inner = sorted(b for b in set(boundaries) if t0 < b < t1)
    result = list(ideal)
    for k, b in enumerate(ideal):
        near = [c for c in inner if abs(c - b) <= cfg.snap_tolerance_ms]
        if not near:
            continue
        cand = min(near, key=lambda c: (abs(c - b), c))
        prev_edge = result[k - 1] if k > 0 else t0
        next_edge = ideal[k + 1] if k + 1 < len(ideal) else t1
        lo, hi = cfg.snap_min_slot_ms, g_max
        if cand <= prev_edge or cand >= next_edge:
            continue
        if lo <= cand - prev_edge <= hi and lo <= next_edge - cand <= hi:
            result[k] = cand
    return result


def build_slots(
    *,
    beat: str,
    explanatory: bool,
    change_beats: int,
    t0: int,
    t1: int,
    target_gap_ms: int,
    sentence_boundaries_ms: Sequence[int],
    cfg: Agent09Config,
    deliberate_pause: bool = False,
) -> list[GridSlot]:
    """The algorithm of 6.2 steps 1-7 for one span; pure and deterministic."""
    span = t1 - t0
    g_min, g_max = cfg.cadence_min_gap_ms, cfg.g_max_ms
    if not explanatory and cfg.held_max_ms is not None and span <= cfg.held_max_ms:
        reason = (
            HeldReason.DELIBERATE_PAUSE
            if deliberate_pause or beat == "PAUSE"
            else HeldReason.SCRIPT_NON_EXPLANATORY
        )
        return [GridSlot(t0, t1, Held(reason=reason, max_ms=cfg.held_max_ms))]
    n_min = ceil_div(span, g_max)
    n_tgt = round_half_up(span, target_gap_ms)
    n_cap = max(1, span // g_min)
    n = max(n_min, min(n_tgt, n_cap))
    if change_beats > n and span >= change_beats * g_min:
        n = change_beats  # step 6: the script's intent is a minimum when feasible
    ideal = [t0 + round_half_up(k * span, n) for k in range(1, n)]
    edges = [t0, *_snap(ideal, sentence_boundaries_ms, t0, t1, cfg), t1]
    return [GridSlot(a, b) for a, b in itertools.pairwise(edges)]


def plan_chart(*, change_beats: int, t0: int, t1: int, cfg: Agent09Config) -> GridSlot:
    """6.2 step 7: one CHART shot, ``m`` reveal steps as change events inside it."""
    span = t1 - t0
    m = max(change_beats, ceil_div(span, cfg.g_max_ms))
    events = tuple(t0 + round_half_up(j * span, m) for j in range(1, m))
    return GridSlot(t0, t1, Held(reason=HeldReason.CHART_REVEAL, max_ms=span), events)
