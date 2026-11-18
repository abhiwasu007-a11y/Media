"""Blob storage interface (ADR-005 section 3.1; 03 section 8).

URIs are ``amw-blob://<org wire id|platform>/<area>/<path>``; the backend maps them to
``<root>/<org uuid>/<area>/<path>`` (03 section 8 rule 1). Every operation runs in a tenant
context and first checks that the URI's owner is the context's org; a mismatch is
``CrossTenantRefError`` (security event, L3; 03 section 8.3, 04 section 3.7.8). ``platform`` URIs
are read-only for tenant contexts. Implementation (local disk first, ADR-005 section 3.2): lane L1.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import NewType, Protocol, runtime_checkable

from amw_core.ids import OrgId
from amw_core.interfaces.tenancy_context import TenantContext

BlobUri = NewType("BlobUri", str)

CHUNK_BYTES = 1024 * 1024
"""Suggested chunk size for streams (implementation detail, not a contract value)."""


@runtime_checkable
class ReadableStream(Protocol):
    """A binary source read in chunks (a file object, an HTTP body, ``io.BytesIO``)."""

    def read(self, size: int = -1, /) -> bytes: ...


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
        """Build a URI for ``<area>/<path>`` of the context's org (areas: 03 section 8)."""
        ...

    def put(self, context: TenantContext, uri: BlobUri, stream: ReadableStream) -> BlobInfo:
        """ADR-005 ``put(uri, stream) -> (sha256, size_bytes)``.

        * Tenant check first (``CrossTenantRefError``); ``platform`` URIs are refused for tenants.
        * Write-once (03 section 8.2): if the path already exists the put is **refused**, even
          with identical content (ADR-005 states no exception). The refusal raises
          ``InputInvalidError`` (no dedicated 07 code exists; flagged to the contract integrator).
          Callers that may repeat a write check ``head`` first or rely on idempotency keys.
        * Writes temp -> flush -> atomic publish to the final path (07 section 8.1); a killed
          process leaves no file at the final path. SHA-256 and size are computed while writing.
        * No space -> ``DiskFullError``; backend unreachable -> ``StorageUnavailableError``.
        """
        ...

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        """ADR-005 ``get(uri, expected_sha256) -> stream``, as an iterator of chunks.

        Tenant check (``CrossTenantRefError``; ``platform`` readable). Absent ->
        ``MissingDependencyError``. The SHA-256 and size are verified while streaming; a mismatch
        raises ``CorruptedOutputError`` before the final chunk is yielded, so a consumer that reads
        to the end never accepts unverified content.
        """
        ...

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        """ADR-005 ``head(uri) -> (exists, sha256, size_bytes)``; used by the 03 section 5.3
        success rule. Tenant check as above."""
        ...

    def list_prefix(self, context: TenantContext, org_id: OrgId, area: str) -> Iterable[BlobInfo]:
        """ADR-005 ``list_prefix(org, area)``: every blob under ``<org>/<area>/`` (tenant / job
        export, 1C.10). ``org_id`` must equal the context's org (``CrossTenantRefError``)."""
        ...
