"""TemplateCatalogue (F-08) and the glyph catalogue: versioned package data with recorded hashes."""

import hashlib
import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_11_thumbnail_design.models import PictureKind, TemplateOffer
from agent_11_thumbnail_design.revision import canonical_json
from agent_11_thumbnail_design.subject_options import GlyphFacts
from amw_core.errors import ConfigInvalidError

Box = tuple[int, int, int, int]


class TemplateSpec(BaseModel):
    """A template with its geometry (permille of the canvas)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    template_key: str
    version: int
    is_default: bool
    text_lines_max: int
    supports_subject_kinds: tuple[PictureKind, ...]
    direction_neutral: bool
    text_box: Box
    subject_box: Box
    band: Box | None
    align: str = "left"

    def offer(self) -> TemplateOffer:
        return TemplateOffer(
            template_key=self.template_key,
            is_default=self.is_default,
            text_lines_max=self.text_lines_max,
            supports_subject_kinds=self.supports_subject_kinds,
            direction_neutral=self.direction_neutral,
        )


@dataclass(frozen=True, slots=True)
class GlyphSpec:
    key: str
    label: str
    neutral: bool
    ops: tuple[dict[str, Any], ...]

    def facts(self) -> GlyphFacts:
        return GlyphFacts(key=self.key, label=self.label, direction_neutral=self.neutral)


def _data(name: str) -> dict[str, Any]:
    raw = resources.files("agent_11_thumbnail_design").joinpath("data", name).read_text("utf-8")
    loaded: dict[str, Any] = json.loads(raw)
    return loaded


@cache
def palette() -> dict[str, str]:
    roles: dict[str, str] = _data("palette.json")["roles"]
    return roles


@cache
def glyph_catalogue() -> tuple[GlyphSpec, ...]:
    doc = _data("glyphs.json")
    allow = set(doc["neutral_allow_list"])
    return tuple(
        GlyphSpec(g["key"], g["label"], g["key"] in allow, tuple(g["ops"])) for g in doc["glyphs"]
    )


def neutral_allow_list_sha256() -> str:
    return hashlib.sha256(canonical_json({"allow": _data("glyphs.json")["neutral_allow_list"]})).hexdigest()


def template_set_sha256() -> str:
    """Hash of the template geometry and the glyph set (recorded in the manifest provenance)."""
    return hashlib.sha256(
        canonical_json({"t": _data("templates.json"), "g": _data("glyphs.json")})
    ).hexdigest()


def load_templates(doc: dict[str, Any] | None = None) -> tuple[TemplateSpec, ...]:
    raw = (doc or _data("templates.json"))["templates"]
    specs = tuple(TemplateSpec.model_validate(t) for t in raw)
    keys = [s.template_key for s in specs]
    if len(set(keys)) != len(keys) or sum(1 for s in specs if s.is_default) != 1:
        raise ConfigInvalidError("template catalogue needs unique keys and exactly one default")
    return specs


def offer_templates(
    specs: tuple[TemplateSpec, ...], *, finance: bool, language_ok: bool = True
) -> tuple[TemplateOffer, ...]:
    """Offer templates, filtered by font coverage for the language and by finance neutrality."""
    if not language_ok:
        return ()
    return tuple(s.offer() for s in specs if s.direction_neutral or not finance)


def reserved_corner_rect(corner: str, width: int, height: int) -> tuple[int, int, int, int]:
    """The corner kept free of text (the video-length badge), in pixels."""
    cw, ch = (width * _data("templates.json")["reserved_corner_permille"][0] // 1000,
              height * _data("templates.json")["reserved_corner_permille"][1] // 1000)
    right = corner.endswith("right")
    bottom = corner.startswith("bottom")
    x0 = width - cw if right else 0
    y0 = height - ch if bottom else 0
    return (x0, y0, x0 + cw, y0 + ch)
