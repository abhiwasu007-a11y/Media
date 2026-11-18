"""VerticalPlanner (F-23; FR-14): the 9:16 plan is a re-edit, never a crop of the 16:9 plan."""

from collections.abc import Mapping, Sequence

from agent_09_video_director.contracts import Anchor, AspectRatio, Vertical


def plan_vertical(
    aspect: AspectRatio, anchors: Sequence[Anchor | None]
) -> tuple[Vertical | None, ...]:
    """9:16: an anchor on every shot (``CENTER`` for a code-made shot); 16:9: none."""
    if aspect is not AspectRatio.PORTRAIT:
        return tuple(None for _ in anchors)
    return tuple(Vertical(subject_anchor=a or Anchor.CENTER) for a in anchors)


def map_parent_shots(
    shot_segment_ids: Sequence[Sequence[str]],
    parent_segment_ids: Mapping[str, Sequence[str]],
    parent_shots: Mapping[str, Sequence[str]],
) -> tuple[str | None, ...]:
    """``parent_shot_id`` by the largest overlap of parent segments (nullable; ties earlier).

    ``parent_segment_ids``: child segment -> parent segments; ``parent_shots``: parent shot ->
    parent segments, in plan order.
    """
    out: list[str | None] = []
    for segs in shot_segment_ids:
        wanted = {p for s in segs for p in parent_segment_ids.get(s, ())}
        best: str | None = None
        best_n = 0
        for shot_id, psegs in parent_shots.items():
            n = len(wanted.intersection(psegs))
            if n > best_n:
                best, best_n = shot_id, n
        out.append(best)
    return tuple(out)
