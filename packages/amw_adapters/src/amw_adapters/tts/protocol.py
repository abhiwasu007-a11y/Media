"""TTS adapter Protocol (ADR-008 section 2.1, 2.7, 2.9).

Voice and model references are config (``voices.provider_voice_ref``). Cost is recorded per call
as ``units`` of ``characters`` (or ``audio_ms`` where the provider bills by audio). A retake is a
new call with its own idempotency key (scope ``tts.synthesize``: task, segment, text SHA-256,
voice). Human narration intake is not a provider call and is not part of this Protocol.
"""

from enum import StrEnum
from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field

from amw_adapters.common import AdapterModel, AdapterResult

OPERATION_SYNTHESIZE = "tts.synthesize"
OPERATION_LIST_VOICES = "tts.list_voices"


class TtsPace(StrEnum):
    """Closed sentence pace set (agent_07 section 7); adapter-owned (CCR-057, CCR-130)."""

    SLOW = "SLOW"
    NORMAL = "NORMAL"
    FAST = "FAST"


class TtsEmotion(StrEnum):
    """Closed sentence emotion set (agent_07 section 7); adapter-owned (CCR-057, CCR-130)."""

    NEUTRAL = "NEUTRAL"
    CURIOUS = "CURIOUS"
    SERIOUS = "SERIOUS"
    WARM = "WARM"
    ENERGETIC = "ENERGETIC"
    EMPHASIS = "EMPHASIS"


class ControlSupport(StrEnum):
    """Whether the provider offers a style control natively; never emulated by post-processing."""

    NONE = "NONE"
    NATIVE = "NATIVE"


class TtsCapabilities(AdapterModel):
    """What this adapter can really do (ADR-008 2.1; agent_07 FR-8 and ``provenance``). A caller
    never sends a control the adapter does not declare."""

    pace_control: ControlSupport
    emotion_control: ControlSupport
    phoneme_support: bool
    languages: tuple[str, ...]
    max_chars_per_request: Annotated[int, Field(ge=1)] | None
    markup_delimiters: tuple[str, ...] = ()
    """Provider markup delimiters beyond ``< > &`` that the caller must escape in script text
    (agent 07 blueprint 6.3 step 4); empty = none beyond the XML-significant three."""


class TtsRequest(AdapterModel):
    text: Annotated[str, Field(min_length=1)]
    voice_ref: Annotated[str, Field(min_length=1)]
    model: Annotated[str, Field(min_length=1)]
    language: Annotated[str, Field(min_length=2)]
    """BCP 47 tag, e.g. ``mr``."""
    sample_rate_hz: Annotated[int, Field(ge=8000)] = 48_000
    pronunciation_dictionary_ref: str | None = None
    pace: TtsPace | None = None
    """Style request; ``None`` = adapter default. An adapter whose ``pace_control`` is ``NONE``
    refuses a value (``InputInvalidError``) rather than ignoring it silently."""
    emotion: TtsEmotion | None = None


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

    def capabilities(self) -> TtsCapabilities: ...

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult: ...

    def list_voices(self, request: VoiceListRequest, *, idempotency_key: str) -> VoiceList: ...
