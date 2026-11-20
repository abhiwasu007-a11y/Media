"""``PrivateChunkReader`` of agent_16 over the PRIVATE knowledge library (read only).

The text comes only from the merged read-only library reader of agent_06
(``KnowledgeLibraryReader``: a checkout path plus the full commit SHA the job names; HEAD must
equal the SHA and the file must equal the pinned commit's blob, otherwise it refuses). The text is
returned to the caller in memory for the near-copy measure; this module never logs it, never
stores it, never copies it and never offers a way to list or write the library.

What is NOT defined anywhere (CCR-299, PROPOSED, fail closed): how a ``chunk_id`` maps to a file and
a section of the library. 04 5.10 has ``knowledge_chunks`` but no migration creates it, and the
library file layout has no chunk index. The mapping is therefore an injected port,
``ChunkIndex``; without a location for a chunk the reader refuses with ``MissingDependencyError``
and a location of another tenant is ``CrossTenantRefError``. Sections use the marker of CCR-291
(a line ``§ <locator>``); a missing or repeated locator never resolves.
"""

import re
from dataclasses import dataclass
from typing import Final, Protocol

from agent_06_fact_checker.library.reader import KnowledgeLibraryReader
from agent_16_compliance_qa.nearcopy import ChunkText
from amw_core.errors import CrossTenantRefError, InputInvalidError, MissingDependencyError
from amw_core.interfaces.tenancy_context import TenantTransaction

_MARKER: Final = re.compile(r"^§[ \t]*(?P<loc>\S.*?)[ \t]*$")


@dataclass(frozen=True, slots=True)
class ChunkLocation:
    """Where one chunk lives: the tenant it belongs to, its collection, the library file and the
    section locator (``None`` = the whole file)."""

    org_id: str
    collection_id: str
    relative_path: str
    locator: str | None = None


class ChunkIndex(Protocol):
    """``chunk_id`` to location, read inside the tenant transaction (explicit org filter)."""

    def locate(self, tx: TenantTransaction, chunk_id: str) -> ChunkLocation | None: ...


def section_text(raw: str, locator: str) -> str:
    """Raw text of the one section whose marker line names ``locator`` (marker line excluded)."""
    found: list[list[str]] = []
    current: list[str] | None = None
    for line in raw.splitlines():
        marker = _MARKER.match(line)
        if marker:
            current = []
            if marker.group("loc") == locator:
                found.append(current)
        elif current is not None:
            current.append(line)
    if len(found) != 1:
        raise MissingDependencyError("library section not found or not unique")
    return "\n".join(found[0])


class LibraryChunkReader:
    def __init__(self, library: KnowledgeLibraryReader, index: ChunkIndex) -> None:
        self._library = library
        self._index = index

    def read(self, tx: TenantTransaction, chunk_id: str) -> ChunkText:
        if not chunk_id:
            raise InputInvalidError("chunk id is required")
        location = self._index.locate(tx, chunk_id)
        if location is None:
            raise MissingDependencyError("chunk not found", details={"class": "chunk"})
        org = str(tx.context.org_id)
        if location.org_id != org:
            raise CrossTenantRefError("the chunk belongs to another tenant")
        raw = self._library.read_text(location.relative_path)
        text = raw if location.locator is None else section_text(raw, location.locator)
        return ChunkText(
            chunk_id=chunk_id, org_id=org, collection_id=location.collection_id, text=text
        )
