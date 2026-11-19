"""Font cmap reader for the F-10 coverage check (the ``font_reader`` port of ``Deps``).

It is the shared reader of ``amw_core.font_coverage`` (the same rule agent 11 applies), and parses
only the bytes it is given (verified by the caller against the asset's recorded SHA-256).
"""

from amw_core.font_coverage import read_cmap as cmap_font_reader

__all__ = ["cmap_font_reader"]
