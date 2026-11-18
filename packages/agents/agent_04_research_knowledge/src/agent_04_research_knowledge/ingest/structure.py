"""ChapterMapper (deterministic headings) and QaSampler (blueprint 10.9, ADR-013 section 2.8)."""

import random
import re
from dataclasses import dataclass

_CHAPTER = re.compile(
    r"^\s*(?:#{1,3}\s+(?P<md>.+)|(?:chapter|part|section)\s+(?P<n>[0-9ivxlc]+)\b[\s:.\-]*(?P<t>.*))$",
    re.IGNORECASE,
)
_LOOKS_LIKE_HEADING = re.compile(r"^[A-Z0-9][A-Z0-9 ,:'\-]{3,58}$")


@dataclass(frozen=True, slots=True)
class Section:
    chapter: str | None
    page: int
    text: str

    def __repr__(self) -> str:
        return f"Section({self.chapter!r}, page={self.page})"


def map_structure(pages: list[tuple[int, str]]) -> tuple[list[Section], int]:
    """Split pages into (chapter, page, text) sections; a chapter heading is a Markdown heading or a
    line starting ``Chapter``/``Part``/``Section`` plus a number. An all-capitals line that is
    not a recognised heading is counted as an unresolved heading for human QA."""
    sections: list[Section] = []
    chapter: str | None = None
    unresolved = 0
    for number, text in pages:
        buffer: list[str] = []
        for line in text.splitlines():
            match = _CHAPTER.match(line)
            if match:
                if buffer:
                    sections.append(Section(chapter, number, "\n".join(buffer)))
                    buffer = []
                chapter = line.strip().lstrip("#").strip()
                continue
            if _LOOKS_LIKE_HEADING.match(line.strip()):
                unresolved += 1
            buffer.append(line)
        if buffer:
            sections.append(Section(chapter, number, "\n".join(buffer)))
    return [s for s in sections if s.text.strip()], unresolved


def qa_sample(chunk_nos: list[int], size: int, seed: int) -> list[int]:
    """Deterministic sample for the human spot check (failures are re-queued, never dropped)."""
    rng = random.Random(seed)  # noqa: S311 - sampling, not security
    return sorted(rng.sample(chunk_nos, min(size, len(chunk_nos))))
