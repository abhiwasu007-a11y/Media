"""DirectionBatcher (F-11): only slots with origin MODEL reach the model, in order."""

from collections.abc import Sequence
from dataclasses import dataclass

from agent_09_video_director.contracts import DirectionSlot


@dataclass(frozen=True, slots=True)
class Batch:
    batch_id: str
    slots: tuple[DirectionSlot, ...]


def make_batches(slots: Sequence[DirectionSlot], size: int) -> list[Batch]:
    """Order preserved; ``size`` from config. Chart, disclaimer and fallback slots are never in
    ``slots`` (the caller filters by origin)."""
    return [
        Batch(f"b{n:02d}", tuple(slots[i : i + size]))
        for n, i in enumerate(range(0, len(slots), size), start=1)
    ]
