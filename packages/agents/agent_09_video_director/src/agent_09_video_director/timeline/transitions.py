"""TransitionPlanner (F-16; blueprint 6.4.6): never a dip to black, durations bounded."""

from typing import Literal

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import Transition, TransitionKind

BoundaryKind = Literal["SECTION", "SCENE", "SHOT"]
_ALLOWED = {k.value for k in TransitionKind}


def plan_transition(
    cfg: Agent09Config,
    *,
    boundary: BoundaryKind,
    hint: str | None,
    shorter_neighbour_ms: int,
    shifted_by_jl: bool = False,
) -> Transition:
    """Default CUT; CROSS_DISSOLVE at a section boundary without a J/L shift.

    A non-CUT kind needs ``transition.max_ms``; its duration is the smaller of that limit and
    20 percent of the shorter neighbour. A hint outside the allowed set (a fade to black) is
    ignored, never planned.
    """
    if cfg.transition_max_ms is None or shifted_by_jl:
        return Transition(kind=TransitionKind.CUT, duration_ms=0)
    kind = TransitionKind(hint) if hint in _ALLOWED else TransitionKind.CUT
    if kind is TransitionKind.CUT and boundary == "SECTION":
        kind = TransitionKind.CROSS_DISSOLVE
    if kind is TransitionKind.CUT:
        return Transition(kind=kind, duration_ms=0)
    duration = min(cfg.transition_max_ms, shorter_neighbour_ms * 20 // 100)
    if duration <= 0:
        return Transition(kind=TransitionKind.CUT, duration_ms=0)
    return Transition(kind=kind, duration_ms=duration)
