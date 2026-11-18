"""Write-once blob helpers over ``amw_core`` storage (03 section 8.2: no overwrite, ever)."""

import hashlib
import io
from collections.abc import Sequence

from amw_core.errors import CorruptedOutputError, MissingDependencyError
from amw_core.interfaces.storage import BlobInfo, BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext


def put_once(storage: BlobStorage, ctx: TenantContext, uri: BlobUri, data: bytes) -> BlobInfo:
    """Idempotent write: an existing blob with the same hash is the replay of this write; a
    different hash at the same path is corruption (never overwritten)."""
    sha = hashlib.sha256(data).hexdigest()
    head = storage.head(ctx, uri)
    if head.exists:
        if head.sha256 != sha:
            raise CorruptedOutputError("a different blob already exists at a write-once path")
        return BlobInfo(uri, sha, len(data))
    return storage.put(ctx, uri, io.BytesIO(data))


def read_verified(storage: BlobStorage, ctx: TenantContext, uri: BlobUri, sha256: str) -> bytes:
    """Bytes of a blob whose SHA-256 is verified while streaming (``CorruptedOutputError``)."""
    return b"".join(storage.get(ctx, uri, sha256))


def read_actual(storage: BlobStorage, ctx: TenantContext, uri: BlobUri) -> tuple[bytes, str]:
    """Bytes and their real hash, for callers that compare the hash themselves and want a
    business error (``INPUT_INVALID``) rather than a storage one."""
    head = storage.head(ctx, uri)
    if not head.exists or head.sha256 is None:
        raise MissingDependencyError("blob not found")
    return read_verified(storage, ctx, uri, head.sha256), head.sha256


def total_size(sizes: Sequence[int]) -> int:
    return sum(sizes)
