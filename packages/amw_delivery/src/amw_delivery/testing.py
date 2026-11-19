"""In-memory fakes and builders for tests and the integrator's dry run (no network, no paid call).

``MemoryBlobStorage`` implements ``BlobStorage`` (tenant check, write-once, hash verified on get).
``PLUMBING_VERTICAL_SPEC`` carries PLACEHOLDER values (the official Shorts safe zones are
REQUIRES REVIEW (Phase 1)); it exists only so plumbing tests and the dry run can run.
"""

import hashlib
import io
from collections.abc import Iterable, Iterator

from amw_core.errors import (
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
)
from amw_core.ids import OrgId
from amw_core.interfaces.storage import BlobHead, BlobInfo, BlobUri, ReadableStream
from amw_core.interfaces.tenancy_context import TenantContext
from amw_delivery.vertical import SafeArea, VerticalSpec

PLUMBING_VERTICAL_SPEC = VerticalSpec(
    width_px=1080,
    height_px=1920,
    fps=25,
    safe_area=SafeArea(top_px=150, bottom_px=300, left_px=60, right_px=120),
    mode="blur_pad",
    blur_radius=20,
    video_crf=28,
    x264_preset="veryfast",
    h264_profile="high",
    subtitle_font_size=14,
    duration_tolerance_ms=200,
    timeout_s=300,
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class MemoryBlobStorage:
    """``BlobStorage`` in memory; ``chunk`` makes ``get`` yield several chunks."""

    def __init__(self, chunk: int = 64 * 1024) -> None:
        self.blobs: dict[str, bytes] = {}
        self._recorded: dict[str, str] = {}
        self._chunk = chunk

    @staticmethod
    def _owner(uri: str) -> str:
        return uri.split("://", 1)[1].split("/", 1)[0]

    def _check(self, context: TenantContext, uri: str, *, write: bool) -> None:
        owner = self._owner(uri)
        if owner != context.org_id and not (owner == "platform" and not write):
            raise CrossTenantRefError("blob belongs to another tenant")

    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        return BlobUri(f"amw-blob://{context.org_id}/{area}/{path}")

    def put(self, context: TenantContext, uri: BlobUri, stream: ReadableStream) -> BlobInfo:
        self._check(context, uri, write=True)
        data = stream.read()
        if uri in self.blobs:
            raise InputInvalidError("write-once: blob exists")
        self.blobs[uri] = data
        self._recorded[uri] = sha256_hex(data)
        return BlobInfo(uri, self._recorded[uri], len(data))

    def put_bytes(self, context: TenantContext, uri: str, data: bytes) -> BlobInfo:
        return self.put(context, BlobUri(uri), io.BytesIO(data))

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        self._check(context, uri, write=False)
        if uri not in self.blobs:
            raise MissingDependencyError("blob absent")
        data = self.blobs[uri]
        if sha256_hex(data) != expected_sha256:
            raise CorruptedOutputError("blob hash mismatch")
        for i in range(0, len(data), self._chunk):
            yield data[i : i + self._chunk]

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        self._check(context, uri, write=False)
        data = self.blobs.get(uri)
        if data is None:
            return BlobHead(False, None, None)
        return BlobHead(True, self._recorded[uri], len(data))

    def list_prefix(self, context: TenantContext, org_id: OrgId, area: str) -> Iterable[BlobInfo]:
        if org_id != context.org_id:
            raise CrossTenantRefError("other tenant")
        prefix = f"amw-blob://{org_id}/{area}/"
        return [
            BlobInfo(BlobUri(u), self._recorded[u], len(d))
            for u, d in sorted(self.blobs.items())
            if u.startswith(prefix)
        ]
