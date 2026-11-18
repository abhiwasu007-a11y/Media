"""Blob storage interface (ADR-005 section 3.1; 03 section 8).

URIs are ``amw-blob://<org wire id|platform>/<area>/<path>``. Every call checks that the URI's
owner is the context's org (``platform`` is read-only), else ``CrossTenantRefError`` (security
event, L3). Blobs are write-once (03 section 8.2); a write is temp file -> flush -> atomic publish
(07 section 8.1). Implementation (local disk first): lane L1.
"""

from dataclasses import dataclass
from typing import NewType, Protocol, runtime_checkable

from amw_core.interfaces.tenancy_context import TenantContext

BlobUri = NewType("BlobUri", str)


@dataclass(frozen=True, slots=True)
class BlobInfo:
    uri: BlobUri
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BlobHead:
    exists: bool
    sha256: str | None
    size_bytes: int | None


@runtime_checkable
class BlobStorage(Protocol):
    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        """Build a tenant-scoped URI for ``<area>/<path>`` (areas: 03 section 8)."""
        ...

    def put(self, context: TenantContext, uri: BlobUri, data: bytes, media_type: str) -> BlobInfo:
        """Write once. Existing path -> ``InputInvalidError`` unless identical content (idempotent
        replay returns the stored info). No space -> ``DiskFullError``; backend down ->
        ``StorageUnavailableError``."""
        ...

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> bytes:
        """Read and verify; hash/size mismatch -> ``CorruptedOutputError``; absent ->
        ``MissingDependencyError``."""
        ...

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        """Existence, SHA-256 and size; used by the 03 section 5.3 success rule."""
        ...
