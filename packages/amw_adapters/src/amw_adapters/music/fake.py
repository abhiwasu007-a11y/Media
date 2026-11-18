"""Deterministic in-memory music fake (no network)."""

from amw_adapters.common import FailurePlan, FakeProvider, FixtureStore
from amw_adapters.library import FakeLibrary


class FakeMusicAdapter(FakeLibrary):
    def __init__(
        self,
        *,
        provider: str = FakeProvider.MUSIC,
        currency: str = "USD",
        price_micros_per_item: int = 1000,
        failures: FailurePlan | None = None,
        fixtures: FixtureStore | None = None,
    ) -> None:
        super().__init__(
            adapter="music",
            operation_prefix="music",
            provider=provider,
            media_type="audio/wav",
            currency=currency,
            price_micros_per_item=price_micros_per_item,
            failures=failures,
            fixtures=fixtures,
        )
