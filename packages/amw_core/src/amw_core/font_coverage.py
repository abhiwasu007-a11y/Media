"""One glyph-coverage rule for every renderer (agent 10 text check, agent 11 composer).

A character is *covered* when any font of the font set (brand font first, then the fallback fonts)
maps its code point in the cmap. Spaces and joiners are layout, not glyphs, and are never required.
Both agents call these functions, so they cannot disagree on what a font set covers.
"""

import io
from collections.abc import Iterable, Sequence

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

#: Zero-width joiner / non-joiner / space, no-break space: never need a glyph of their own.
IGNORED_CODE_POINTS = frozenset({0x200C, 0x200D, 0x200B, 0x20, 0xA0})


def read_cmap(font_bytes: bytes) -> frozenset[int]:
    """The Unicode code points the font maps to a glyph (bytes only: no name or path lookup)."""
    cmap = TTFont(io.BytesIO(font_bytes), lazy=True).getBestCmap() or {}
    return frozenset(cmap)


def needs_glyph(ch: str) -> bool:
    return not ch.isspace() and ord(ch) not in IGNORED_CODE_POINTS


def uncovered_code_points(texts: Iterable[str], cmaps: Sequence[frozenset[int]]) -> frozenset[int]:
    """Code points of ``texts`` that no cmap of the set covers."""
    covered: frozenset[int] = frozenset().union(*cmaps) if cmaps else frozenset()
    return frozenset(ord(ch) for text in texts for ch in text if needs_glyph(ch)) - covered


def fallback_code_points(
    texts: Iterable[str], primary: frozenset[int], fallback: frozenset[int]
) -> frozenset[int]:
    """Code points the primary lacks and the fallback supplies (the ones the fallback draws)."""
    return frozenset(
        ord(ch)
        for text in texts
        for ch in text
        if needs_glyph(ch) and ord(ch) not in primary and ord(ch) in fallback
    )


__all__ = [
    "IGNORED_CODE_POINTS",
    "fallback_code_points",
    "needs_glyph",
    "read_cmap",
    "uncovered_code_points",
]
