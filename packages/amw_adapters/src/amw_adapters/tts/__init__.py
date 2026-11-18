"""TTS adapter: Protocol + deterministic fake."""

from amw_adapters.tts.fake import FakeTtsAdapter
from amw_adapters.tts.protocol import (
    TtsAdapter,
    TtsRequest,
    TtsResult,
    VoiceInfo,
    VoiceList,
    VoiceListRequest,
)

__all__ = [
    "FakeTtsAdapter",
    "TtsAdapter",
    "TtsRequest",
    "TtsResult",
    "VoiceInfo",
    "VoiceList",
    "VoiceListRequest",
]
