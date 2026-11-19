"""Local-disk ``BlobStorage`` backend (ADR-005 sections 3.1-3.3; 03 section 8; 07 section 8.1).

* URI ``amw-blob://<org wire id|platform>/<area>/<path>`` -> ``<root>/<org uuid>/<area>/<path>``
  (``<root>/platform/<area>/<path>`` for platform URIs). The org segment is always first.
* Tenant check before any file-system access: the URI owner must be the context's org
  (``CrossTenantRefError``, logged as a security event). ``platform`` URIs are read-only.
* Write-once and atomic: the stream goes to a temporary file in the same directory, is flushed
  and ``fsync``-ed, then hard-linked to the final name. ``link`` fails if the name exists, so two
  racing writers can never overwrite each other, and a killed process leaves no final file.
* SHA-256 and size are computed while writing; ``get`` verifies them while streaming and raises
  ``CorruptedOutputError`` before the last chunk is handed out.
"""

import errno
import hashlib
import os
import re
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from amw_core.errors import (
    CorruptedOutputError,
    CrossTenantRefError,
    DiskFullError,
    InputInvalidError,
    MissingDependencyError,
    StorageUnavailableError,
)
from amw_core.ids import ORG, OrgId, Prefix, is_valid_id
from amw_core.interfaces.storage import BlobHead, BlobInfo, BlobUri, ReadableStream
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.observability import get_logger, log_context
from amw_core.tenancy.storage_paths import check_jobs_subpath

SCHEME = "amw-blob://"
PLATFORM = "platform"
TENANT_AREAS: frozenset[str] = frozenset(
    {"jobs", "assets", "knowledge", "licences", "consents", "exports", "evidence"}
)
"""03 section 8 areas (first path segment)."""
TEMP_PREFIX = ".amw-tmp-"
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.=-]{0,199}$")
_log = get_logger("storage")


@dataclass(frozen=True, slots=True)
class ParsedUri:
    owner: str
    """Org wire ID or ``platform``."""
    area: str
    path: str

    @property
    def is_platform(self) -> bool:
        return self.owner == PLATFORM


def parse_uri(uri: str) -> ParsedUri:
    """Validate a blob URI; malformed or unsafe paths are ``PERMANENT.INPUT_INVALID``."""
    if not uri.startswith(SCHEME):
        raise InputInvalidError("not an amw-blob URI")
    parts = uri[len(SCHEME) :].split("/")
    if len(parts) < 3:
        raise InputInvalidError("blob URI needs <owner>/<area>/<path>")
    owner, area, rest = parts[0], parts[1], parts[2:]
    if owner != PLATFORM and not is_valid_id(owner, Prefix.ORGANISATION):
        raise InputInvalidError("blob URI owner is neither an org wire ID nor platform")
    if owner != PLATFORM and area not in TENANT_AREAS:
        raise InputInvalidError(f"unknown storage area {area!r} (03 section 8)")
    if owner != PLATFORM and area == "jobs":
        check_jobs_subpath("/".join(rest))
    for segment in (area, *rest):
        if not _SEGMENT_RE.fullmatch(segment) or segment in {".", ".."}:
            raise InputInvalidError("unsafe or empty blob path segment")
    return ParsedUri(owner=owner, area=area, path="/".join(rest))


class LocalDiskStorage:
    """``amw_core.interfaces.BlobStorage`` on a local directory (root from ``storage.root``)."""

    def __init__(self, root: Path, chunk_bytes: int = 1024 * 1024) -> None:
        if not root.is_absolute():
            raise InputInvalidError("storage root must be an absolute path")
        self._root = root
        self._chunk = chunk_bytes

    # --- mapping and checks -------------------------------------------------------------------
    def _owner_dir(self, owner: str) -> Path:
        if owner == PLATFORM:
            return self._root / PLATFORM
        return self._root / str(ORG.to_uuid(owner))

    def _path(self, parsed: ParsedUri) -> Path:
        return self._owner_dir(parsed.owner) / parsed.area / parsed.path

    def _check(self, context: TenantContext, uri: str, *, write: bool) -> ParsedUri:
        parsed = parse_uri(uri)
        if parsed.is_platform:
            if write:
                self._security_event(context, "platform blobs are read-only for tenants", uri)
                raise CrossTenantRefError("platform blobs are read-only for tenant contexts")
            return parsed
        if parsed.owner != context.org_id:
            self._security_event(context, "cross-tenant blob reference", uri)
            raise CrossTenantRefError("blob URI belongs to another tenant")
        return parsed

    @staticmethod
    def _security_event(context: TenantContext, message: str, uri: str) -> None:
        owner = uri[len(SCHEME) :].split("/", 1)[0] if uri.startswith(SCHEME) else "?"
        with log_context(
            org_id=context.org_id, actor=context.actor, error_code=CrossTenantRefError.code
        ):
            _log.warning(
                "security event: %s", message, extra={"security_event": True, "uri_owner": owner}
            )

    # --- BlobStorage -------------------------------------------------------------------------
    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        uri = f"{SCHEME}{context.org_id}/{area}/{path}"
        parse_uri(uri)
        return BlobUri(uri)

    def put(self, context: TenantContext, uri: BlobUri, stream: ReadableStream) -> BlobInfo:
        parsed = self._check(context, uri, write=True)
        final = self._path(parsed)
        if final.exists():
            raise InputInvalidError("blob already exists (write-once, 03 section 8.2)")
        digest = hashlib.sha256()
        size = 0
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
            tmp = final.parent / f"{TEMP_PREFIX}{uuid.uuid4().hex}"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            raise _os_error(exc) from exc
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := stream.read(self._chunk):
                    digest.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(tmp, 0o444)
            try:
                os.link(tmp, final)
            except FileExistsError:
                raise InputInvalidError(
                    "blob already exists (write-once, 03 section 8.2)"
                ) from None
            _fsync_dir(final.parent)
        except OSError as exc:
            raise _os_error(exc) from exc
        finally:
            tmp.unlink(missing_ok=True)
        return BlobInfo(uri=uri, sha256=digest.hexdigest(), size_bytes=size)

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        parsed = self._check(context, uri, write=False)
        path = self._path(parsed)
        if not path.is_file():
            raise MissingDependencyError("blob not found")
        return self._verified_chunks(path, expected_sha256.lower())

    def _verified_chunks(self, path: Path, expected: str) -> Iterator[bytes]:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as src:
                pending = src.read(self._chunk)
                while pending:
                    digest.update(pending)
                    following = src.read(self._chunk)
                    if not following:
                        break
                    yield pending
                    pending = following
                if digest.hexdigest() != expected:
                    raise CorruptedOutputError("blob SHA-256 does not match the expected value")
                if pending:
                    yield pending
        except OSError as exc:
            raise _os_error(exc) from exc

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        parsed = self._check(context, uri, write=False)
        path = self._path(parsed)
        if not path.is_file():
            return BlobHead(exists=False, sha256=None, size_bytes=None)
        sha, size = self._hash_file(path)
        return BlobHead(exists=True, sha256=sha, size_bytes=size)

    def list_prefix(self, context: TenantContext, org_id: OrgId, area: str) -> Iterable[BlobInfo]:
        if org_id != context.org_id:
            self._security_event(context, "cross-tenant list_prefix", f"{SCHEME}{org_id}/")
            raise CrossTenantRefError("list_prefix for another tenant")
        if area not in TENANT_AREAS:
            raise InputInvalidError(f"unknown storage area {area!r}")
        base = self._owner_dir(org_id) / area
        if not base.is_dir():
            return []
        out: list[BlobInfo] = []
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.name.startswith(TEMP_PREFIX):
                continue
            rel = path.relative_to(base).as_posix()
            sha, size = self._hash_file(path)
            out.append(
                BlobInfo(uri=BlobUri(f"{SCHEME}{org_id}/{area}/{rel}"), sha256=sha, size_bytes=size)
            )
        return out

    # --- maintenance -------------------------------------------------------------------------
    def remove_orphan_temp_files(self, older_than_s: float, now_s: float) -> int:
        """ADR-005 section 3.3: temporary files never published are removed by a cleanup task."""
        removed = 0
        for path in self._root.rglob(f"{TEMP_PREFIX}*"):
            try:
                if now_s - path.stat().st_mtime >= older_than_s:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
        return removed

    def _hash_file(self, path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as src:
                while chunk := src.read(self._chunk):
                    digest.update(chunk)
                    size += len(chunk)
        except OSError as exc:
            raise _os_error(exc) from exc
        return digest.hexdigest(), size


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _os_error(exc: OSError) -> Exception:
    if exc.errno in (errno.ENOSPC, errno.EDQUOT):
        return DiskFullError("no space left in blob storage")
    return StorageUnavailableError("blob storage unavailable", details={"errno": exc.errno})
