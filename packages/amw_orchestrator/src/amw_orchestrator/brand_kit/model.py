"""Brand-kit document of a channel (CCR-306, PROPOSED) as CONFIG DATA.

Code-made visuals only: a palette, two font KEYS of the repo's pinned font manifest (a brand
primary and a per-glyph fallback) and a caption style. There is deliberately no field for a logo,
a trademark, a wordmark image or a font file path: ``extra="forbid"`` refuses them. Colours are
named roles; the caption style names palette roles, never colours of its own."""

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

BRAND_KIT_SCHEMA: Final = "amw.brand_kit/1"

Colour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-f]{6}$")]
FontKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
PaletteRole = Literal["background", "foreground", "grid", "up", "down", "accent", "shade"]


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PaletteDoc(_Doc):
    background: Colour
    foreground: Colour
    grid: Colour
    up: Colour
    down: Colour
    accent: Colour
    shade: Colour


class FontsDoc(_Doc):
    primary: FontKey
    """Manifest key with purpose ``brand_primary`` (Mukta)."""
    fallback: FontKey
    """Manifest key with purpose ``brand_fallback`` (Noto Sans Devanagari): per-glyph fallback."""


class CaptionStyleDoc(_Doc):
    font_key: FontKey
    """A ``brand_primary`` manifest font (the caption weight, for example the bold cut)."""
    size_ratio: Annotated[float, Field(gt=0, le=0.2)]
    """Caption font size as a fraction of the frame height."""
    max_lines: Annotated[int, Field(ge=1, le=3)]
    alignment: Literal["left", "center"]
    text_colour: PaletteRole
    box_colour: PaletteRole


class BrandKitDocument(_Doc):
    schema_id: Literal["amw.brand_kit/1"] = Field(alias="schema")
    channel_key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    language: Annotated[str, StringConstraints(pattern=r"^[a-z]{2}-[A-Z]{2}$")]
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    palette: PaletteDoc
    fonts: FontsDoc
    caption_style: CaptionStyleDoc
    coverage_texts: Annotated[
        tuple[Annotated[str, StringConstraints(min_length=1, max_length=200)], ...],
        Field(min_length=1, max_length=20),
    ]
    """Strings every text the kit renders by itself must be drawn from (the display name and the
    caption sample); the reader checks that the font set has a glyph for each of them."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @property
    def font_keys(self) -> tuple[str, ...]:
        """Distinct manifest keys the kit needs, in order: primary, fallback, caption font."""
        return tuple(
            dict.fromkeys((self.fonts.primary, self.fonts.fallback, self.caption_style.font_key))
        )
