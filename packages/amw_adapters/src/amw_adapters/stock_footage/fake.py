"""Deterministic in-memory stock_footage fake (no network)."""

from amw_adapters.common import FailurePlan, FixtureStore
from amw_adapters.library import FakeLibrary


class FakeStockFootageAdapter(FakeLibrary):
    def __init__(
        self,
        *,
        provider: str = "fake_stock",
        currency: str = "USD",
        price_micros_per_item: int = 1000,
        failures: FailurePlan | None = None,
        fixtures: FixtureStore | None = None,
    ) -> None:
        super().__init__(
            adapter="stock_footage",
            operation_prefix="stock",
            provider=provider,
            media_type="video/mp4",
            currency=currency,
            price_micros_per_item=price_micros_per_item,
            failures=failures,
            fixtures=fixtures,
        )
