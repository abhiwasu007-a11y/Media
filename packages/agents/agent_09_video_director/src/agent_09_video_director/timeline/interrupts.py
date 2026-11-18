"""InterruptPlacer (F-10; blueprint 6.4.1-2): code guarantees an interrupt in each window."""

from collections.abc import Sequence
from dataclasses import dataclass

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import InterruptWindow


@dataclass(frozen=True, slots=True)
class SlotSpan:
    slot_id: str
    start_ms: int
    end_ms: int

    @property
    def centre2(self) -> int:
        """Twice the centre (integer arithmetic)."""
        return self.start_ms + self.end_ms


@dataclass(frozen=True, slots=True)
class Forced:
    slot_id: str
    window: InterruptWindow


@dataclass(frozen=True, slots=True)
class InterruptPlacement:
    forced: tuple[Forced, ...]
    satisfied_by: dict[InterruptWindow, str]
    """Windows already satisfied by a script-planned interrupt: window -> ``SCRIPT_PLANNED``."""
    unset_windows: tuple[InterruptWindow, ...]


def windows(content_end_ms: int, cfg: Agent09Config) -> dict[InterruptWindow, tuple[int, int]]:
    """W1 and W2 of 6.4.1; a window whose config is unset does not exist."""
    out: dict[InterruptWindow, tuple[int, int]] = {}
    if cfg.first_dropoff_start_ms is not None and cfg.first_dropoff_end_ms is not None:
        out[InterruptWindow.FIRST_DROPOFF] = (cfg.first_dropoff_start_ms, cfg.first_dropoff_end_ms)
    if cfg.midpoint_half_width_ms is not None:
        mid2 = content_end_ms  # twice the midpoint
        h = cfg.midpoint_half_width_ms
        out[InterruptWindow.MIDPOINT] = ((mid2 - 2 * h) // 2, (mid2 + 2 * h) // 2)
    return out


def place_interrupts(
    slots: Sequence[SlotSpan],
    content_end_ms: int,
    cfg: Agent09Config,
    script_interrupt_slot_ids: Sequence[str],
) -> InterruptPlacement:
    """For each existing window without an interrupt slot force the slot nearest its centre."""
    wins = windows(content_end_ms, cfg)
    by_id = {s.slot_id: s for s in slots}
    scripted = [by_id[i] for i in script_interrupt_slot_ids if i in by_id]
    forced: list[Forced] = []
    satisfied: dict[InterruptWindow, str] = {}
    taken = {s.slot_id for s in scripted}
    for window, (w0, w1) in wins.items():
        if any(w0 * 2 <= s.centre2 <= w1 * 2 for s in scripted):
            satisfied[window] = "SCRIPT_PLANNED"
            continue
        centre2 = w0 + w1
        candidates = [s for s in slots if s.slot_id not in taken]
        if not candidates:
            continue
        pick = min(candidates, key=lambda s: (abs(s.centre2 - centre2), s.start_ms))
        forced.append(Forced(pick.slot_id, window))
        taken.add(pick.slot_id)
    unset = tuple(
        w for w in (InterruptWindow.FIRST_DROPOFF, InterruptWindow.MIDPOINT) if w not in wins
    )
    return InterruptPlacement(tuple(forced), satisfied, unset)
