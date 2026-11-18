"""Deterministic in-memory video-generation fake (no network)."""

from typing import Any

from amw_adapters.common import (
    FAKE_PRICE_REF,
    CallUsage,
    FailurePlan,
    FakeEngine,
    FixtureStore,
    fake_bytes,
)
from amw_adapters.video_gen.protocol import VideoGenRequest, VideoGenResult
from amw_core.enums import CostUnitKind

OPERATION = "video.generate"


class FakeVideoGenAdapter:
    def __init__(
        self,
        *,
        provider: str = "fake_video",
        currency: str = "USD",
        price_micros_per_video_ms: int = 1,
        failures: FailurePlan | None = None,
        fixtures: FixtureStore | None = None,
    ) -> None:
        self._provider = provider
        self._currency = currency
        self._price = price_micros_per_video_ms
        self.engine = FakeEngine("video_gen", failures=failures, fixtures=fixtures)

    @property
    def provider(self) -> str:
        return self._provider

    def generate(self, request: VideoGenRequest, *, idempotency_key: str) -> VideoGenResult:
        def build(digest: str, fixture: dict[str, Any] | None) -> VideoGenResult:
            fx = fixture or {}
            duration_ms = int(fx.get("duration_ms", request.duration_ms))
            usage = CallUsage(
                provider=self._provider,
                operation=OPERATION,
                model=request.model,
                units=duration_ms,
                unit_kind=CostUnitKind.VIDEO_MS,
                cost_micros=duration_ms * self._price,
                currency=self._currency,
                price_ref=FAKE_PRICE_REF,
                idempotency_key=idempotency_key,
            )
            return VideoGenResult(
                video=fake_bytes(digest, 64),
                media_type="video/mp4",
                duration_ms=duration_ms,
                aspect_ratio=request.aspect_ratio,
                is_realistic_synthetic=bool(fx.get("is_realistic_synthetic", True)),
                usage=usage,
            )

        return self.engine.run(OPERATION, idempotency_key, request, build, VideoGenResult)
