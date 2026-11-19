"""TTS adapter: Protocol + deterministic fake."""

from amw_adapters.tts.fake import FakeTtsAdapter
from amw_adapters.tts.protocol import (
    ControlSupport,
    TtsAdapter,
    TtsCapabilities,
    TtsEmotion,
    TtsPace,
    TtsRequest,
    TtsResult,
    VoiceInfo,
    VoiceList,
    VoiceListRequest,
)

__all__ = [
    "ControlSupport",
    "FakeTtsAdapter",
    "TtsAdapter",
    "TtsCapabilities",
    "TtsEmotion",
    "TtsPace",
    "TtsRequest",
    "TtsResult",
    "VoiceInfo",
    "VoiceList",
    "VoiceListRequest",
]
