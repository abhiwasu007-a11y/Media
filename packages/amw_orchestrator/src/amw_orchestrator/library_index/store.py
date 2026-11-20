"""Private index directory: where it may live and how it is written (atomic, write-once shards).

The index directory must be OUTSIDE git: not inside the library checkout and not inside any
directory tree that has a ``.git`` (this repository included). Nothing here ever writes into the
library or the repository."""

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError
from amw_orchestrator.library_index.models import (
    SAFE_ID,
    FileShard,
    Manifest,
)


def canonical_bytes(doc: Mapping[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def shard_bytes(shard: FileShard) -> bytes:
    return canonical_bytes(shard.model_dump(by_alias=True))


def manifest_bytes(manifest: Manifest) -> bytes:
    return canonical_bytes(manifest.model_dump(by_alias=True))


def check_private_dir(index_dir: Path, library_root: Path | None = None) -> Path:
    """The resolved index directory, refused when it is inside the library checkout or inside any
    git working tree (a ``.git`` in the directory itself or in any parent)."""
    resolved = index_dir.expanduser().resolve()
    if library_root is not None and (
        resolved == library_root.resolve() or resolved.is_relative_to(library_root.resolve())
    ):
        raise ConfigInvalidError("the index directory must not be inside the library checkout")
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists():
            raise ConfigInvalidError("the index directory must be outside every git working tree")
    return resolved


def _safe(name: str, what: str) -> str:
    if SAFE_ID.fullmatch(name) is None:
        raise InputInvalidError(f"{what} is not a safe directory name")
    return name


def collection_dir(index_dir: Path, org_id: str, collection_id: str) -> Path:
    return index_dir / _safe(org_id, "org id") / _safe(collection_id, "collection id")


def manifest_path(index_dir: Path, org_id: str, collection_id: str, commit_sha: str) -> Path:
    return (
        collection_dir(index_dir, org_id, collection_id)
        / _safe(commit_sha, "commit")
        / ("manifest.json")
    )


def shard_path(index_dir: Path, org_id: str, collection_id: str, blob_id: str) -> Path:
    return (
        collection_dir(index_dir, org_id, collection_id)
        / "shards"
        / f"{_safe(blob_id, 'blob')}.json"
    )


def _write_atomic(path: Path, data: bytes, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if path.read_bytes() == data:
            return
        if not overwrite:
            raise InputInvalidError("an index file with other content already exists")
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


def write_shard(index_dir: Path, org_id: str, collection_id: str, shard: FileShard) -> str:
    """Write a shard (write-once: the blob id fixes its content) and return its SHA-256."""
    data = shard_bytes(shard)
    _write_atomic(
        shard_path(index_dir, org_id, collection_id, shard.blob_id), data, overwrite=False
    )
    return hashlib.sha256(data).hexdigest()


def write_manifest(index_dir: Path, manifest: Manifest) -> None:
    """A manifest of the same commit may be rebuilt (the shards it names are write-once)."""
    path = manifest_path(index_dir, manifest.org_id, manifest.collection_id, manifest.commit_sha)
    _write_atomic(path, manifest_bytes(manifest), overwrite=True)


def read_bytes(path: Path, what: str) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raise MissingDependencyError(
            f"the library chunk index has no {what}", details={"class": "chunk_index"}
        ) from None
    except OSError:
        raise MissingDependencyError(
            f"the library chunk index {what} cannot be read", details={"class": "chunk_index"}
        ) from None
