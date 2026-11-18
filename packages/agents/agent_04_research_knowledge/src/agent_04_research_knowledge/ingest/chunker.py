"""SectionChunker (blueprint 10.9, ADR-013 plan step 6): split by section with small overlap.

Chunk sizes are configuration (ESTIMATE, tuned in 3B). A chunk never crosses a chapter or a
section boundary; within a section, text is cut at paragraph or sentence boundaries first.
"""

import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


@dataclass(frozen=True, slots=True)
class TextPiece:
    text: str
    page_from: int | None
    page_to: int | None


def split_text(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    """Pieces of at most ``target_chars`` (a single over-long sentence is cut hard), with the last
    ``overlap_chars`` of the previous piece repeated at the start of the next."""
    if target_chars < 1 or overlap_chars < 0 or overlap_chars >= target_chars:
        raise ValueError("overlap must be smaller than the target size")
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            while len(sentence) > target_chars:
                units.append(sentence[:target_chars])
                sentence = sentence[target_chars:]
            if sentence:
                units.append(sentence)
    pieces: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current} {unit}".strip()
        if current and len(candidate) > target_chars:
            pieces.append(current)
            tail = current[-overlap_chars:] if overlap_chars else ""
            current = f"{tail} {unit}".strip() if tail else unit
            if len(current) > target_chars:
                current = unit
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces
