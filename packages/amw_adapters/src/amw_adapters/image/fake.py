"""Deterministic in-memory image-generation fake (no network)."""

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
from amw_adapters.image.protocol import ImageRequest, ImageResult
from amw_core.enums import CostUnitKind

OPERATION = "image.generate"


class FakeImageAdapter:
    def __init__(
        self,
        *,
        provider: str = FakeProvider.IMAGE,
        currency: str = "USD",
        price_micros_per_image: int = 1000,
        failures: FailurePlan | None = None,
        fixtures: FixtureStore | None = None,
    ) -> None:
        self._provider = fake_provider(provider)
        self._currency = currency
        self._price = price_micros_per_image
        self.engine = FakeEngine("image", failures=failures, fixtures=fixtures)

    @property
    def provider(self) -> str:
        return self._provider

    def generate(self, request: ImageRequest, *, idempotency_key: str) -> ImageResult:
        def build(digest: str, fixture: dict[str, Any] | None) -> ImageResult:
            fx = fixture or {}
            usage = CallUsage(
                provider=self._provider,
                operation=OPERATION,
                model=request.model,
                units=1,
                unit_kind=CostUnitKind.IMAGES,
                amount_micros=int(fx.get("amount_micros", self._price)),
                currency=self._currency,
                price_ref=FAKE_PRICE_REF,
                idempotency_key=idempotency_key,
            )
            return ImageResult(
                image=fake_bytes(digest, 64),
                media_type=str(fx.get("media_type", "image/png")),
                width_px=request.width_px,
                height_px=request.height_px,
                usage=usage,
            )

        return self.engine.run(OPERATION, idempotency_key, request, build, ImageResult)
