"""Pinned fonts and the rendering-environment record (determinism must not depend on the host).

* ``data/fonts/manifest.json``: the fonts shipped in the repo, with SHA-256, licence and source.
* A font is rasterised only if its bytes hash to the hash that was claimed for it (the registered
  asset's recorded ``sha256``, or a manifest entry): a mismatch is ``FontIntegrityError``. Tenant
  brand-kit fonts (blueprint FR-09) are therefore allowed; the stage still requires the font to be
  a registered asset with a licence row. Fonts are loaded from memory only, so a system font can
  never be substituted.
* ``data/environments.json``: the canary raster hashes (box test font and the real Noto font)
  recorded per FreeType version. The renderer NEVER refuses to render because the environment is
  not listed: the environment is recorded as provenance in the thumbnail manifest, and the canary
  test compares against the table (a listed FreeType must match exactly; an unlisted one is
  reported, and fails only in the strict clean-image CI job, ``A11_REQUIRE_RECORDED_ENV=1``).

The key is only what was measured to change pixels (see ``environments.json`` ``evidence``). The PNG
file bytes are not the cross-host identity: the cross-host identity is ``pixel_sha256`` of the
decoded RGB raster.
"""

import hashlib
import json
import platform
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

import PIL
from PIL import features

from agent_11_thumbnail_design.errors import FontIntegrityError

_PKG = "agent_11_thumbnail_design"
#: Per-glyph fallback of the brand font (owner decision 2026-11-19, WS-06): Mukta is the primary.
FALLBACK_FONT_KEY = "noto_sans_devanagari_vf"


def _data(name: str) -> bytes:
    return resources.files(_PKG).joinpath("data").joinpath(name).read_bytes()


@dataclass(frozen=True, slots=True)
class PinnedFont:
    key: str
    file: str
    sha256: str
    purpose: str
    licence: str
    weight: int | None = None


@cache
def font_manifest() -> dict[str, PinnedFont]:
    """Pinned fonts by SHA-256. The manifest file itself is checked against the font files."""
    raw: dict[str, Any] = json.loads(_data("fonts/manifest.json"))
    out: dict[str, PinnedFont] = {}
    for f in raw["fonts"]:
        pinned = PinnedFont(
            f["key"], f["file"], f["sha256"], f["purpose"], f["licence"], f.get("weight")
        )
        out[pinned.sha256] = pinned
    return out


def pinned_font_bytes(key: str) -> bytes:
    """Read a pinned font from the package and verify it against the manifest."""
    for sha, pinned in font_manifest().items():
        if pinned.key == key:
            data = _data(f"fonts/{pinned.file}")
            verify_font(data, sha)
            return data
    raise FontIntegrityError(f"font key {key!r} is not in the pinned font manifest")


def verify_font(font_bytes: bytes, claimed_sha256: str) -> str:
    """Check the bytes against the claimed (recorded) hash; return the font source label."""
    actual = hashlib.sha256(font_bytes).hexdigest()
    if actual != claimed_sha256:
        raise FontIntegrityError("font bytes do not match their recorded hash")
    pinned = font_manifest().get(actual)
    return f"repo_manifest:{pinned.key}" if pinned else "tenant_asset"


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Everything recorded as provenance; only ``freetype2`` is the canary key (measured)."""

    pillow: str
    freetype2: str
    raqm: str
    harfbuzz: str
    fribidi: str
    machine: str


def current_fingerprint() -> Fingerprint:
    def ver(name: str) -> str:
        return str(features.version(name) or "absent") if features.check(name) else "absent"

    return Fingerprint(
        pillow=str(PIL.__version__),
        freetype2=ver("freetype2"),
        raqm=ver("raqm"),
        harfbuzz=ver("harfbuzz"),
        fribidi=ver("fribidi"),
        machine=platform.machine().lower(),
    )


@cache
def _environments() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(_data("environments.json"))
    return raw


def recorded_canary(freetype2: str, font_key: str) -> str | None:
    """Canary pixel SHA-256 recorded for this FreeType version and canary font, or None."""
    for e in _environments()["environments"]:
        if e["freetype2"] == freetype2:
            value = e["canary_pixel_sha256"].get(font_key)
            return None if value is None else str(value)
    return None


def render_environment() -> dict[str, Any]:
    """Provenance record for the thumbnail manifest: versions and the font manifest hash."""
    fp = current_fingerprint()
    return {
        "pillow": fp.pillow,
        "freetype2": fp.freetype2,
        "harfbuzz": fp.harfbuzz,
        "raqm": fp.raqm,
        "fribidi": fp.fribidi,
        "machine": fp.machine,
        "font_manifest_sha256": hashlib.sha256(_data("fonts/manifest.json")).hexdigest(),
        "canary_recorded": recorded_canary(fp.freetype2, "a11_test_box") is not None,
    }


def pixel_sha256(mode: str, size: tuple[int, int], raw: bytes) -> str:
    """Host-independent identity of a raster: mode, size and the raw pixel bytes."""
    head = f"{mode}:{size[0]}x{size[1]}:".encode()
    return hashlib.sha256(head + raw).hexdigest()
