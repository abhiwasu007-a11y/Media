"""Document models of the private library chunk index (CCR-307, PROPOSED).

DESIGN DECISION (owner brief): the index holds ONLY locators, offsets and hashes, never book text.
Chunk text is re-read from the pinned library checkout at use time (through the read-only library
reader), so no second store of book text exists. A chunk is the body of one ``§ <locator>``
section (CCR-291); its offsets are character offsets into the decoded file and its hash is the
SHA-256 of the chunk text exactly as ``slice_text`` returns it.

Layout under the private index directory (OUTSIDE every git working tree)::

    <index_dir>/<org_id>/<collection_id>/<commit_sha>/manifest.json
    <index_dir>/<org_id>/<collection_id>/shards/<blob_id>.json

A shard is content addressed by the git blob id of one library file and holds only that file's
chunk entries; the manifest names, per path, the blob id and the SHA-256 of the shard file.
"""

import hashlib
import re
import uuid
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from amw_core.ids import Prefix, format_id

MANIFEST_SCHEMA: Final = "amw.library_chunk_index.manifest/1"
SHARD_SCHEMA: Final = "amw.library_chunk_index.shard/1"
CHUNKER_VERSION: Final = "section-marker/1"
"""Bumped when the way a file is cut into chunks changes; a loader refuses a different value."""

SAFE_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_SHA40 = r"^[0-9a-f]{40}$"
_SHA64 = r"^[0-9a-f]{64}$"

Sha40 = Annotated[str, StringConstraints(pattern=_SHA40)]
Sha64 = Annotated[str, StringConstraints(pattern=_SHA64)]
LibraryPath = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChunkEntry(_Doc):
    locator: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    """The text after ``§`` on the marker line (unique inside its file, otherwise not indexed)."""
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]
    text_sha256: Sha64


class FileShard(_Doc):
    schema_id: str = Field(default=SHARD_SCHEMA, alias="schema")
    blob_id: Sha40
    chunker: str
    entries: tuple[ChunkEntry, ...]

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ManifestFile(_Doc):
    path: LibraryPath
    blob_id: Sha40
    shard_sha256: Sha64


class Manifest(_Doc):
    schema_id: str = Field(default=MANIFEST_SCHEMA, alias="schema")
    org_id: str
    collection_id: str
    commit_sha: Sha40
    chunker: str
    files: tuple[ManifestFile, ...]

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def chunk_id_for(org_id: str, collection_id: str, path: str, locator: str) -> str:
    """Deterministic ``kch_`` wire id of a chunk: the same library place always gets the same id
    (a rebuild never renumbers chunks that a research pack already cites).

    The 128 bits come from SHA-256 of the place; the version and variant bits are those of a
    UUIDv7 so the id passes the wire format (``amw_core.ids``). The embedded timestamp is
    meaningless (CCR-307)."""
    key = "\x1f".join(("kch/1", org_id, collection_id, path, locator)).encode("utf-8")
    raw = bytearray(hashlib.sha256(key).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(format_id(Prefix.KNOWLEDGE_CHUNK, uuid.UUID(bytes=bytes(raw))))
