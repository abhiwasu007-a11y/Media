"""``PrivateChunkIndex``: the ``ChunkIndex`` port of ``LibraryChunkReader`` over the private index.

``load`` checks, before any chunk is served, that the manifest belongs to the pinned commit, the
tenant and the collection, that the chunker version is the one this code knows, and that every
shard exists, equals the SHA-256 the manifest records and names the blob id the manifest names.
Any gap is a typed refusal (fail closed): a missing manifest or shard is ``MissingDependencyError``,
an index of another commit / tenant / collection is ``InputInvalidError``, a damaged one is
``ConfigInvalidError``.

At use time ``LibraryChunkReader`` re-reads the text from the pinned checkout and checks each
chunk's SHA-256 (``ChunkLocation.text_sha256``). ``verify_against_library`` runs both checks for
every file of the index (operator ``verify`` command and tests)."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from agent_06_fact_checker.library.reader import KnowledgeLibraryReader
from amw_core.errors import (
    ConfigInvalidError,
    CorruptedOutputError,
    InputInvalidError,
)
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_orchestrator.db_adapters.chunk_reader import ChunkLocation, slice_text
from amw_orchestrator.library_index.chunking import git_blob_id
from amw_orchestrator.library_index.models import (
    CHUNKER_VERSION,
    FileShard,
    Manifest,
    chunk_id_for,
)
from amw_orchestrator.library_index.store import manifest_path, read_bytes, shard_path


@dataclass(frozen=True, slots=True)
class _Place:
    path: str
    blob_id: str
    locator: str
    start: int
    end: int
    text_sha256: str


class PrivateChunkIndex:
    """``chunk_id`` to ``ChunkLocation`` for one (org, collection, pinned commit)."""

    def __init__(self, manifest: Manifest, places: dict[str, _Place]) -> None:
        self._manifest = manifest
        self._places = places

    @property
    def commit_sha(self) -> str:
        return self._manifest.commit_sha

    def __len__(self) -> int:
        return len(self._places)

    @classmethod
    def load(
        cls, index_dir: Path, *, org_id: str, collection_id: str, commit_sha: str
    ) -> PrivateChunkIndex:
        try:
            manifest = Manifest.model_validate_json(
                read_bytes(manifest_path(index_dir, org_id, collection_id, commit_sha), "manifest")
            )
        except ValidationError:
            raise ConfigInvalidError("the library chunk index manifest is damaged") from None
        if (
            manifest.commit_sha != commit_sha
            or manifest.org_id != org_id
            or manifest.collection_id != collection_id
        ):
            raise InputInvalidError(
                "the library chunk index is not the one of this commit, tenant and collection"
            )
        if manifest.chunker != CHUNKER_VERSION:
            raise InputInvalidError("the library chunk index was cut by another chunker version")
        places: dict[str, _Place] = {}
        seen_paths: set[str] = set()
        for entry in manifest.files:
            if entry.path in seen_paths:
                raise ConfigInvalidError("the library chunk index names a file twice")
            seen_paths.add(entry.path)
            data = read_bytes(shard_path(index_dir, org_id, collection_id, entry.blob_id), "shard")
            if hashlib.sha256(data).hexdigest() != entry.shard_sha256:
                raise ConfigInvalidError("a library chunk index shard does not match its hash")
            try:
                shard = FileShard.model_validate_json(data)
            except ValidationError:
                raise ConfigInvalidError("a library chunk index shard is damaged") from None
            if shard.blob_id != entry.blob_id or shard.chunker != CHUNKER_VERSION:
                raise ConfigInvalidError("a library chunk index shard names another file version")
            for chunk in shard.entries:
                if chunk.end < chunk.start:
                    raise ConfigInvalidError("a library chunk index entry has bad offsets")
                cid = chunk_id_for(org_id, collection_id, entry.path, chunk.locator)
                if cid in places:
                    raise ConfigInvalidError("the library chunk index repeats a chunk")
                places[cid] = _Place(
                    entry.path, entry.blob_id, chunk.locator, chunk.start, chunk.end,
                    chunk.text_sha256,
                )  # fmt: skip
        return cls(manifest, places)

    def locate(self, tx: TenantTransaction, chunk_id: str) -> ChunkLocation | None:
        place = self._places.get(chunk_id)
        if place is None:
            return None
        return ChunkLocation(
            org_id=self._manifest.org_id,
            collection_id=self._manifest.collection_id,
            relative_path=place.path,
            locator=place.locator,
            start=place.start,
            end=place.end,
            text_sha256=place.text_sha256,
        )

    def verify_against_library(self, library: KnowledgeLibraryReader) -> int:
        """Re-read every indexed file at the pinned commit: the blob id and every chunk hash must
        match. Returns the number of chunks checked; never returns text."""
        if library.commit_sha != self._manifest.commit_sha:
            raise InputInvalidError("the library is not at the commit of the chunk index")
        by_file: dict[str, list[_Place]] = {}
        for place in self._places.values():
            by_file.setdefault(place.path, []).append(place)
        checked = 0
        for path, places in sorted(by_file.items()):
            raw = library.read_text(path)
            if git_blob_id(raw) != places[0].blob_id:
                raise CorruptedOutputError("a library file differs from the one that was indexed")
            for place in places:
                text = slice_text(raw, place.start, place.end)
                if hashlib.sha256(text.encode("utf-8")).hexdigest() != place.text_sha256:
                    raise CorruptedOutputError("a library chunk differs from its index hash")
                checked += 1
        return checked
