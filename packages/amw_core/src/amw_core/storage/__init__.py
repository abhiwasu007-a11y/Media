"""Blob storage (ADR-005): the local-disk backend; the S3-compatible backend is 3C."""

from pathlib import Path

from amw_core.config import AmwSettings
from amw_core.errors import ConfigInvalidError
from amw_core.storage.local import PLATFORM, SCHEME, TENANT_AREAS, LocalDiskStorage, parse_uri


def storage_from_settings(settings: AmwSettings) -> LocalDiskStorage:
    """Backend and root come only from configuration (ADR-005 section 3.1)."""
    if settings.storage.backend != "local":
        raise ConfigInvalidError(f"storage backend {settings.storage.backend!r} is not available")
    root: Path | None = settings.storage.root
    if root is None:
        raise ConfigInvalidError("storage.root is not configured")
    return LocalDiskStorage(root, settings.storage.chunk_bytes)


__all__ = [
    "PLATFORM",
    "SCHEME",
    "TENANT_AREAS",
    "LocalDiskStorage",
    "parse_uri",
    "storage_from_settings",
]
