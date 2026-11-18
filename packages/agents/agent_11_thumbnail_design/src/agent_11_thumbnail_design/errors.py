"""Composer-local errors. Task-level failures use the typed 07 errors of ``amw_core.errors``."""


class TextDoesNotFitError(Exception):
    """The text does not fit; the caller repairs once, then drops the variant."""


class GlyphMissingError(Exception):
    """The font has no glyph for a character of the text."""


class ComposeFailedError(Exception):
    """Rasterising or encoding failed (mapped by the stage to AGENT.CRASH)."""
