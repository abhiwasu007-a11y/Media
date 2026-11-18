"""Image generation adapter Protocol (capability ``image_gen``; ADR-009 section 2.7).

No live adapter in 3A (3A slice spec section 2.3: visuals are code-made or owner material).
Idempotency scope ``media.generate`` (task, shot, prompt SHA-256). Cost unit ``images``.
"""

from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field

from amw_adapters.common import AdapterModel, AdapterResult


class ImageRequest(AdapterModel):
    prompt: Annotated[str, Field(min_length=1)]
    model: Annotated[str, Field(min_length=1)]
    width_px: Annotated[int, Field(ge=1)]
    height_px: Annotated[int, Field(ge=1)]
    seed: int | None = None


class ImageResult(AdapterResult):
    image: bytes
    media_type: str
    width_px: int
    height_px: int


@runtime_checkable
class ImageAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    def generate(self, request: ImageRequest, *, idempotency_key: str) -> ImageResult: ...
