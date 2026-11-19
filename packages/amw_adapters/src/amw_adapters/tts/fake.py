"""Deterministic in-memory TTS fake (no network)."""

from typing import Any

from amw_adapters.common import (
    FAKE_PRICE_REF,
    CallUsage,
    FailurePlan,
    FakeEngine,
    FakeProvider,
    FixtureStore,
    fake_bytes,
    fake_provider,
)
from amw_adapters.tts.protocol import (
    OPERATION_LIST_VOICES,
    OPERATION_SYNTHESIZE,
    ControlSupport,
    TtsCapabilities,
    TtsRequest,
    TtsResult,
    VoiceInfo,
    VoiceList,
    VoiceListRequest,
)
from amw_core.enums import CostUnitKind
from amw_core.errors import InputInvalidError

MS_PER_CHARACTER = 60
"""Synthetic narration pace of the fake (not a measured figure)."""


class FakeTtsAdapter:
    def __init__(
        self,
        *,
        provider: str = FakeProvider.TTS,
        currency: str = "USD",
        price_micros_per_character: int = 1,
        voices: tuple[VoiceInfo, ...] = (
            VoiceInfo(voice_ref="fake-neutral-1", name="Neutral 1", languages=("mr", "hi", "en")),
        ),
        failures: FailurePlan | None = None,
        fixtures: FixtureStore | None = None,
        pace_control: ControlSupport = ControlSupport.NONE,
        emotion_control: ControlSupport = ControlSupport.NONE,
        max_chars_per_request: int | None = None,
        phoneme_support: bool = False,
        markup_delimiters: tuple[str, ...] = (),
    ) -> None:
        self._pace_control = pace_control
        self._emotion_control = emotion_control
        self._max_chars = max_chars_per_request
        self._phoneme_support = phoneme_support
        self._markup_delimiters = markup_delimiters
        self._provider = fake_provider(provider)
        self._currency = currency
        self._price = price_micros_per_character
        self._voices = voices
        self.engine = FakeEngine("tts", failures=failures, fixtures=fixtures)

    @property
    def provider(self) -> str:
        return self._provider

    def capabilities(self) -> TtsCapabilities:
        languages = sorted({lang for v in self._voices for lang in v.languages})
        return TtsCapabilities(
            pace_control=self._pace_control,
            emotion_control=self._emotion_control,
            phoneme_support=self._phoneme_support,
            languages=tuple(languages),
            max_chars_per_request=self._max_chars,
            markup_delimiters=self._markup_delimiters,
        )

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult:
        if request.pace is not None and self._pace_control is ControlSupport.NONE:
            raise InputInvalidError("this adapter has no pace control")
        if request.emotion is not None and self._emotion_control is ControlSupport.NONE:
            raise InputInvalidError("this adapter has no emotion control")
        if self._max_chars is not None and len(request.text) > self._max_chars:
            raise InputInvalidError("text exceeds max_chars_per_request")

        def build(digest: str, fixture: dict[str, Any] | None) -> TtsResult:
            fx = fixture or {}
            characters = len(request.text)
            duration_ms = int(fx.get("duration_ms", characters * MS_PER_CHARACTER))
            usage = CallUsage(
                provider=self._provider,
                operation=OPERATION_SYNTHESIZE,
                model=request.model,
                units=characters,
                unit_kind=CostUnitKind.CHARACTERS,
                chars_in=characters,
                language=request.language,
                amount_micros=characters * self._price,
                currency=self._currency,
                price_ref=FAKE_PRICE_REF,
                idempotency_key=idempotency_key,
            )
            return TtsResult(
                audio=fake_bytes(digest, 64),
                media_type=str(fx.get("media_type", "audio/wav")),
                duration_ms=duration_ms,
                sample_rate_hz=request.sample_rate_hz,
                usage=usage,
            )

        return self.engine.run(OPERATION_SYNTHESIZE, idempotency_key, request, build, TtsResult)

    def list_voices(self, request: VoiceListRequest, *, idempotency_key: str) -> VoiceList:
        def build(_digest: str, _fixture: dict[str, Any] | None) -> VoiceList:
            voices = tuple(
                v
                for v in self._voices
                if request.language is None or request.language in v.languages
            )
            usage = CallUsage(
                provider=self._provider,
                operation=OPERATION_LIST_VOICES,
                amount_micros=0,
                currency=self._currency,
                idempotency_key=idempotency_key,
            )
            return VoiceList(voices=voices, usage=usage)

        return self.engine.run(OPERATION_LIST_VOICES, idempotency_key, request, build, VoiceList)
