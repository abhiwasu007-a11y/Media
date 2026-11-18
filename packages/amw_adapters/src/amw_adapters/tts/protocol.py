"""TTS adapter Protocol (ADR-008 section 2.1, 2.7, 2.9).

Voice and model references are config (``voices.provider_voice_ref``). Cost is recorded per call
as ``units`` of ``characters`` (or ``audio_ms`` where the provider bills by audio). A retake is a
new call with its own idempotency key (scope ``tts.synthesize``: task, segment, text SHA-256,
voice). Human narration intake is not a provider call and is not part of this Protocol.
"""

from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field

from amw_adapters.common import AdapterModel, AdapterResult

OPERATION_SYNTHESIZE = "tts.synthesize"
OPERATION_LIST_VOICES = "tts.list_voices"


class TtsRequest(AdapterModel):
    text: Annotated[str, Field(min_length=1)]
    voice_ref: Annotated[str, Field(min_length=1)]
    model: Annotated[str, Field(min_length=1)]
    language: Annotated[str, Field(min_length=2)]
    """BCP 47 tag, e.g. ``mr``."""
    sample_rate_hz: Annotated[int, Field(ge=8000)] = 48_000
    pronunciation_dictionary_ref: str | None = None


class TtsResult(AdapterResult):
    audio: bytes
    media_type: str
    duration_ms: int
    sample_rate_hz: int


class VoiceInfo(AdapterModel):
    voice_ref: str
    name: str
    languages: tuple[str, ...]


class VoiceListRequest(AdapterModel):
    language: str | None = None


class VoiceList(AdapterResult):
    voices: tuple[VoiceInfo, ...]


@runtime_checkable
class TtsAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult: ...

    def list_voices(self, request: VoiceListRequest, *, idempotency_key: str) -> VoiceList: ...
