"""Image generation adapter: Protocol + deterministic fake."""

from amw_adapters.image.fake import FakeImageAdapter
from amw_adapters.image.protocol import ImageAdapter, ImageRequest, ImageResult

__all__ = ["FakeImageAdapter", "ImageAdapter", "ImageRequest", "ImageResult"]
