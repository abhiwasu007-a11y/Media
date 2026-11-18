"""``HookSelector`` (blueprint 6.2): code recomputes the totals and selects by the written rule."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_05_scriptwriter.errors import OutputSchemaInvalid


@dataclass(frozen=True, slots=True)
class HookScore:
    hook_id: str
    viewer_relevance: int
    curiosity: int
    qualified: bool


@dataclass(frozen=True, slots=True)
class Selection:
    status: str  # OK | REPAIR
    selected: str | None
    totals: dict[str, int] = field(default_factory=dict)
    mismatch: bool = False


def _number(hook_id: str) -> int:
    return int(hook_id[1:])


def select_hook(options: Sequence[HookScore], proposed: str | None, min_options: int) -> Selection:
    """Selected = highest total; tie: higher ``viewer_relevance``; tie: lower numeric ``hook_id``.

    Fewer than ``min_options`` qualified options is ``REPAIR`` (one quality repair, then fail).
    A rubric integer outside 0-2 is an ``OutputSchemaInvalid`` (the model broke its schema).
    """
    for option in options:
        if not (0 <= option.viewer_relevance <= 2 and 0 <= option.curiosity <= 2):
            raise OutputSchemaInvalid(
                "rubric score outside 0-2", details={"hook_id": option.hook_id}
            )
    totals = {o.hook_id: o.viewer_relevance + o.curiosity for o in options}
    qualified = [o for o in options if o.qualified]
    if len(qualified) < min_options:
        return Selection("REPAIR", None, totals, False)
    best = min(
        qualified,
        key=lambda o: (-totals[o.hook_id], -o.viewer_relevance, _number(o.hook_id)),
    )
    return Selection("OK", best.hook_id, totals, proposed != best.hook_id)
