"""AI video generation adapter: Protocol + deterministic fake (not live in 3A)."""

from amw_adapters.video_gen.fake import FakeVideoGenAdapter
from amw_adapters.video_gen.protocol import VideoGenAdapter, VideoGenRequest, VideoGenResult

__all__ = ["FakeVideoGenAdapter", "VideoGenAdapter", "VideoGenRequest", "VideoGenResult"]
