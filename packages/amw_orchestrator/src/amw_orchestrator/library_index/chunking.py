"""Cut a library text file into ``§ <locator>`` sections (CCR-291 marker format).

Pure functions over the decoded text; they never log or store it."""

import hashlib
import re
from dataclasses import dataclass
from typing import Final

from amw_orchestrator.db_adapters.chunk_reader import slice_text
from amw_orchestrator.library_index.models import ChunkEntry

_MARKER: Final = re.compile(r"^§[ \t]*(?P<loc>\S.*?)[ \t]*$")
"""The same marker as ``chunk_reader.section_text`` (kept equal by a test)."""


@dataclass(frozen=True, slots=True)
class Chunking:
    entries: tuple[ChunkEntry, ...]
    ambiguous: int
    """Locators that occur more than once in the file: none of their sections is indexed (a
    repeated locator never resolves, CCR-291)."""


def _text_hash(raw: str, start: int, end: int) -> str:
    return hashlib.sha256(slice_text(raw, start, end).encode("utf-8")).hexdigest()


def chunk_sections(raw: str) -> Chunking:
    """Every unambiguous section of ``raw``; text before the first marker is not a chunk."""
    sections: list[tuple[str, int, int]] = []
    position = 0
    open_locator: str | None = None
    body_start = 0
    for line in raw.splitlines(keepends=True):
        marker = _MARKER.match((line.splitlines() or [""])[0])
        if marker is not None:
            if open_locator is not None:
                sections.append((open_locator, body_start, position))
            open_locator = marker.group("loc")
            body_start = position + len(line)
        position += len(line)
    if open_locator is not None:
        sections.append((open_locator, body_start, position))
    counts: dict[str, int] = {}
    for locator, _, _ in sections:
        counts[locator] = counts.get(locator, 0) + 1
    entries = tuple(
        ChunkEntry(locator=loc, start=s, end=e, text_sha256=_text_hash(raw, s, e))
        for loc, s, e in sections
        if counts[loc] == 1
    )
    return Chunking(entries, ambiguous=sum(1 for n in counts.values() if n > 1))


def git_blob_id(raw: str) -> str:
    """Git blob id of the file the text was decoded from (UTF-8 round trip is exact)."""
    data = raw.encode("utf-8")
    head = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(head + data, usedforsecurity=False).hexdigest()
