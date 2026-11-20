"""Manifest-only fonts and glyph coverage for a brand kit.

The repo's pinned font manifest (agent_11 ``data/fonts/manifest.json``) is the only source of
fonts (MANIFEST_ONLY, the owner channel): a kit font must be listed, have a brand purpose (never
the test fixture) and its file must hash to the manifest value. Glyph coverage uses the one shared
rule of ``amw_core.font_coverage`` (the same code agent 10 and agent 11 call)."""

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final

from amw_core.errors import ConfigInvalidError, MissingDependencyError
from amw_core.font_coverage import read_cmap, uncovered_code_points
from amw_orchestrator.brand_kit.model import BrandKitDocument

BRAND_PURPOSES: Final = frozenset({"brand_primary", "brand_fallback"})


def packaged_manifest_path() -> Path:
    """The manifest committed with agent_11 (the repo's pinned fonts)."""
    return Path(
        str(resources.files("agent_11_thumbnail_design").joinpath("data/fonts/manifest.json"))
    )


@dataclass(frozen=True, slots=True)
class ManifestFont:
    key: str
    path: Path
    sha256: str
    purpose: str


class FontManifest:
    """The pinned manifest, read and hash-checked file by file on demand."""

    def __init__(self, path: Path) -> None:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            raw: Mapping[str, Mapping[str, Any]] = {f["key"]: f for f in doc["fonts"]}
        except OSError, ValueError, KeyError, TypeError:
            raise ConfigInvalidError("font manifest cannot be read") from None
        self._dir = path.parent
        self._raw = raw

    def font(self, key: str) -> ManifestFont:
        entry = self._raw.get(key)
        if entry is None:
            raise MissingDependencyError(
                "a brand-kit font is not in the font manifest", details={"class": "brand_font"}
            )
        purpose = str(entry.get("purpose"))
        if purpose not in BRAND_PURPOSES:
            raise ConfigInvalidError("a brand-kit font has no brand purpose in the manifest")
        return ManifestFont(key, self._dir / str(entry["file"]), str(entry.get("sha256")), purpose)

    def read(self, font: ManifestFont) -> bytes:
        try:
            data = font.path.read_bytes()
        except OSError:
            raise ConfigInvalidError("a pinned font file is missing") from None
        if hashlib.sha256(data).hexdigest() != font.sha256:
            raise ConfigInvalidError("a pinned font file does not match its manifest hash")
        return data


@dataclass(frozen=True, slots=True)
class KitFonts:
    """Verified fonts of a kit: manifest entries in key order and their code point sets."""

    fonts: Mapping[str, ManifestFont]
    cmaps: Mapping[str, frozenset[int]]

    def uncovered(self, texts: Iterable[str], keys: Iterable[str]) -> frozenset[int]:
        return uncovered_code_points(texts, [self.cmaps[k] for k in keys])


def check_kit_fonts(doc: BrandKitDocument, manifest: FontManifest) -> KitFonts:
    """Every font of the kit is a hash-verified manifest font of the right purpose, and the
    primary + fallback pair covers every coverage text of the kit (fail closed)."""
    fonts: dict[str, ManifestFont] = {}
    cmaps: dict[str, frozenset[int]] = {}
    for key in doc.font_keys:
        font = manifest.font(key)
        fonts[key] = font
        cmaps[key] = read_cmap(manifest.read(font))
    if fonts[doc.fonts.primary].purpose != "brand_primary":
        raise ConfigInvalidError("the kit's primary font is not a brand_primary manifest font")
    if fonts[doc.fonts.fallback].purpose != "brand_fallback":
        raise ConfigInvalidError("the kit's fallback font is not a brand_fallback manifest font")
    if fonts[doc.caption_style.font_key].purpose != "brand_primary":
        raise ConfigInvalidError("the kit's caption font is not a brand_primary manifest font")
    kit = KitFonts(fonts, cmaps)
    gaps = kit.uncovered(
        (*doc.coverage_texts, doc.display_name), (doc.fonts.primary, doc.fonts.fallback)
    )
    if gaps:
        raise ConfigInvalidError(
            "the kit's fonts have no glyph for a coverage text",
            details={"code_points": [f"U+{cp:04X}" for cp in sorted(gaps)[:20]]},
        )
    return kit
