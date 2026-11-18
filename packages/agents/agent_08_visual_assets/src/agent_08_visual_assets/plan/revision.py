"""``ChangedShotSelector`` (FR-20): which shots a revision iteration re-sources.

A shot is re-sourced when it is new, or its ``content_key``, interval or aspect differs from the
previous manifest; the orchestrator hint can only add shots of the current plan (RV-01 to RV-06).
Result lists keep the current plan order.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShotKey:
    shot_id: str
    content_key: str
    start_ms: int
    end_ms: int
    aspect_ratio: str


@dataclass(frozen=True, slots=True)
class Selection:
    resource: tuple[str, ...]
    carry_over: tuple[str, ...]


class ChangedShotSelector:
    @staticmethod
    def select(
        previous: Sequence[ShotKey], current: Sequence[ShotKey], hint_ids: Sequence[str]
    ) -> Selection:
        before = {k.shot_id: k for k in previous}
        hinted = set(hint_ids)
        resource: list[str] = []
        carry: list[str] = []
        for key in current:
            if before.get(key.shot_id) != key or key.shot_id in hinted:
                resource.append(key.shot_id)
            else:
                carry.append(key.shot_id)
        return Selection(tuple(resource), tuple(carry))
