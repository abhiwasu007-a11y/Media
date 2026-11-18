"""AI video generation adapter Protocol (capability ``video_gen``; ADR-009 section 2.6).

Not live in 3A (3A slice spec section 2.3: AI B-roll is 3B at the earliest, only where no real or
licensed option exists). Cost unit ``video_ms``; idempotency scope ``media.generate``.
"""

from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field

from amw_adapters.common import AdapterModel, AdapterResult
from amw_core.enums import AspectRatio


class VideoGenRequest(AdapterModel):
    prompt: Annotated[str, Field(min_length=1)]
    model: Annotated[str, Field(min_length=1)]
    duration_ms: Annotated[int, Field(ge=1)]
    aspect_ratio: AspectRatio


class VideoGenResult(AdapterResult):
    video: bytes
    media_type: str
    duration_ms: int
    aspect_ratio: AspectRatio
    is_realistic_synthetic: bool
    """Feeds the disclosure decision (ADR-009 section 2.6)."""


@runtime_checkable
class VideoGenAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    def generate(self, request: VideoGenRequest, *, idempotency_key: str) -> VideoGenResult: ...
