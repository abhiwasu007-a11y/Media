"""Music library adapter Protocol (ADR-009 section 2.5: licensed only; no live adapter in 3A)."""

from typing import Protocol, runtime_checkable

from amw_adapters.library import (
    LibraryLicenseRequest,
    LibraryLicenseResult,
    LibrarySearchRequest,
    LibrarySearchResult,
)


@runtime_checkable
class MusicAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    def search(self, request: LibrarySearchRequest, *, idempotency_key: str) -> LibrarySearchResult:
        """Free metadata search (operation ``music.search``)."""
        ...

    def license(
        self, request: LibraryLicenseRequest, *, idempotency_key: str
    ) -> LibraryLicenseResult:
        """Paid licence + download (operation ``music.license``)."""
        ...
