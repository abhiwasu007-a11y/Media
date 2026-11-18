"""Music adapter: Protocol + deterministic fake."""

from amw_adapters.music.fake import FakeMusicAdapter
from amw_adapters.music.protocol import MusicAdapter

__all__ = ["FakeMusicAdapter", "MusicAdapter"]
