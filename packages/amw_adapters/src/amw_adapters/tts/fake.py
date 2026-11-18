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
    TtsRequest,
    TtsResult,
    VoiceInfo,
    VoiceList,
    VoiceListRequest,
)
from amw_core.enums import CostUnitKind

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
    ) -> None:
        self._provider = fake_provider(provider)
        self._currency = currency
        self._price = price_micros_per_character
        self._voices = voices
        self.engine = FakeEngine("tts", failures=failures, fixtures=fixtures)

    @property
    def provider(self) -> str:
        return self._provider

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult:
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
