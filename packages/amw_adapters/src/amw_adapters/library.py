"""Shared shapes and fake for licensed media libraries (stock footage, music; ADR-009 2.3-2.5).

Search is free metadata; ``license`` is the paid, idempotent side effect (scope ``stock.license``:
org, vendor item ID, licence ID) that returns the media plus a snapshot reference of the licence
terms (``terms_ref`` + ``terms_sha256``, ADR-009 section 2.4). No watermarked preview is ever a
deliverable (ADR-009 section 2.9).
"""

from typing import Annotated, Any

from pydantic import Field

from amw_adapters.common import (
    FAKE_PRICE_REF,
    AdapterModel,
    AdapterResult,
    CallUsage,
    FailurePlan,
    FakeEngine,
    FixtureStore,
    fake_bytes,
    fake_provider,
)
from amw_core.enums import AspectRatio, CostUnitKind


class LibrarySearchRequest(AdapterModel):
    query: Annotated[str, Field(min_length=1)]
    aspect_ratio: AspectRatio | None = None
    min_duration_ms: Annotated[int, Field(ge=0)] | None = None
    max_results: Annotated[int, Field(ge=1, le=50)] = 10


class LibraryItem(AdapterModel):
    vendor_item_id: str
    title: str
    duration_ms: int | None
    width_px: int | None = None
    height_px: int | None = None


class LibrarySearchResult(AdapterResult):
    items: tuple[LibraryItem, ...]


class LibraryLicenseRequest(AdapterModel):
    vendor_item_id: Annotated[str, Field(min_length=1)]
    licence_ref: Annotated[str, Field(min_length=1)]
    """The ``licences`` row (``lic_...``) the use is registered under."""


class LibraryLicenseResult(AdapterResult):
    vendor_item_id: str
    media: bytes
    media_type: str
    terms_ref: str
    terms_sha256: str


class FakeLibrary:
    """Deterministic fake for one library kind (``stock`` or ``music`` operations)."""

    def __init__(
        self,
        *,
        adapter: str,
        operation_prefix: str,
        provider: str,
        media_type: str,
        currency: str,
        price_micros_per_item: int,
        failures: FailurePlan | None,
        fixtures: FixtureStore | None,
    ) -> None:
        self._provider = fake_provider(provider)
        self._media_type = media_type
        self._currency = currency
        self._price = price_micros_per_item
        self._search_op = f"{operation_prefix}.search"
        self._license_op = f"{operation_prefix}.license"
        self.engine = FakeEngine(adapter, failures=failures, fixtures=fixtures)

    @property
    def provider(self) -> str:
        return self._provider

    def search(self, request: LibrarySearchRequest, *, idempotency_key: str) -> LibrarySearchResult:
        def build(digest: str, fixture: dict[str, Any] | None) -> LibrarySearchResult:
            if fixture is not None:
                items = tuple(LibraryItem.model_validate(i) for i in fixture["items"])
            else:
                count = min(request.max_results, 3)
                items = tuple(
                    LibraryItem(
                        vendor_item_id=f"fake-{digest[:8]}-{n}",
                        title=f"{request.query} {n}",
                        duration_ms=max(request.min_duration_ms or 0, 10_000),
                    )
                    for n in range(count)
                )
            usage = CallUsage(
                provider=self._provider,
                operation=self._search_op,
                units=len(items),
                unit_kind=CostUnitKind.ITEMS,
                amount_micros=0,
                currency=self._currency,
                idempotency_key=idempotency_key,
            )
            return LibrarySearchResult(items=items, usage=usage)

        return self.engine.run(
            self._search_op, idempotency_key, request, build, LibrarySearchResult
        )

    def license(
        self, request: LibraryLicenseRequest, *, idempotency_key: str
    ) -> LibraryLicenseResult:
        def build(digest: str, fixture: dict[str, Any] | None) -> LibraryLicenseResult:
            fx = fixture or {}
            usage = CallUsage(
                provider=self._provider,
                operation=self._license_op,
                units=1,
                unit_kind=CostUnitKind.ITEMS,
                amount_micros=int(fx.get("amount_micros", self._price)),
                currency=self._currency,
                price_ref=FAKE_PRICE_REF,
                idempotency_key=idempotency_key,
            )
            return LibraryLicenseResult(
                vendor_item_id=request.vendor_item_id,
                media=fake_bytes(digest, 64),
                media_type=self._media_type,
                terms_ref=str(fx.get("terms_ref", f"fake-terms/{request.vendor_item_id}")),
                terms_sha256=str(fx.get("terms_sha256", digest)),
                usage=usage,
            )

        return self.engine.run(
            self._license_op, idempotency_key, request, build, LibraryLicenseResult
        )
