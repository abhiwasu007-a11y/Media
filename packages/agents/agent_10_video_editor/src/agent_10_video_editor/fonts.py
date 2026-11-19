"""Font cmap reader for the F-10 coverage check (the ``font_reader`` port of ``Deps``).

The reader only parses the bytes it is given (verified by the caller against the asset's recorded
SHA-256); it never looks up a font by name, so no system font can be consulted.
"""

import io

from fontTools.ttLib import TTFont  # type: ignore[import-untyped]


def cmap_font_reader(font_bytes: bytes) -> frozenset[int]:
    """The set of Unicode code points the font maps to a glyph."""
    cmap = TTFont(io.BytesIO(font_bytes), lazy=True).getBestCmap() or {}
    return frozenset(cmap)


__all__ = ["cmap_font_reader"]
