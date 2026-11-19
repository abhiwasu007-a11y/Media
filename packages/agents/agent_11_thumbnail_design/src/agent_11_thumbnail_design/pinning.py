"""Pinned fonts and pinned rendering environments (determinism must not depend on the host).

Two lists live in package data and are the only authority:

* ``data/fonts/manifest.json``: every font the composer may rasterise, with its SHA-256, licence and
  source. A font whose bytes hash differently from the claimed hash, or whose hash is not listed, is
  refused (``FontIntegrityError``). Fonts are always loaded from memory, never by name or path, so a
  system font can never be substituted.
* ``data/environments.json``: the rendering environments the canary was recorded for. The key is the
  fingerprint of Pillow, FreeType, Raqm, HarfBuzz, FriBiDi and the CPU architecture. An environment
  that is not listed is refused (``RenderEnvironmentError``) instead of rendering something different.

The PNG file bytes are NOT part of the cross-host identity: Pillow's wheel links the host's zlib, and
different zlib builds write different (equally valid) deflate streams for the same pixels. The
cross-host identity is ``pixel_sha256`` of the decoded RGB raster.
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

from agent_11_thumbnail_design.errors import FontIntegrityError, RenderEnvironmentError

_PKG = "agent_11_thumbnail_design"


def _data(name: str) -> bytes:
    return resources.files(_PKG).joinpath("data").joinpath(name).read_bytes()


@dataclass(frozen=True, slots=True)
class PinnedFont:
    key: str
    file: str
    sha256: str
    purpose: str
    licence: str


@cache
def font_manifest() -> dict[str, PinnedFont]:
    """Pinned fonts by SHA-256. The manifest file itself is checked against the font files."""
    raw: dict[str, Any] = json.loads(_data("fonts/manifest.json"))
    out: dict[str, PinnedFont] = {}
    for f in raw["fonts"]:
        pinned = PinnedFont(f["key"], f["file"], f["sha256"], f["purpose"], f["licence"])
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


def verify_font(font_bytes: bytes, claimed_sha256: str) -> PinnedFont:
    actual = hashlib.sha256(font_bytes).hexdigest()
    if actual != claimed_sha256:
        raise FontIntegrityError("font bytes do not match their recorded hash")
    pinned = font_manifest().get(actual)
    if pinned is None:
        raise FontIntegrityError("font is not in the pinned font manifest")
    return pinned


@dataclass(frozen=True, slots=True)
class Fingerprint:
    pillow: str
    freetype2: str
    raqm: str
    harfbuzz: str
    fribidi: str
    machine: str

    @property
    def key(self) -> str:
        return (
            f"pillow-{self.pillow}-freetype-{self.freetype2}-raqm-{self.raqm}"
            f"-harfbuzz-{self.harfbuzz}-fribidi-{self.fribidi}-{self.machine}"
        )


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
def recorded_environments() -> dict[str, str]:
    """Environment fingerprint key -> canary pixel SHA-256 recorded for it."""
    raw: dict[str, Any] = json.loads(_data("environments.json"))
    return {
        Fingerprint(
            e["pillow"], e["freetype2"], e["raqm"], e["harfbuzz"], e["fribidi"], e["machine"]
        ).key: e["canary_pixel_sha256"]
        for e in raw["environments"]
    }


def check_environment() -> Fingerprint:
    """Fail closed unless this process runs in an environment the canary was recorded for."""
    fp = current_fingerprint()
    if fp.key not in recorded_environments():
        raise RenderEnvironmentError(
            "rendering environment is not pinned (no recorded canary): " + fp.key
        )
    return fp


def environment_problem() -> str | None:
    try:
        check_environment()
    except RenderEnvironmentError as exc:
        return str(exc)
    return None


def pixel_sha256(mode: str, size: tuple[int, int], raw: bytes) -> str:
    """Host-independent identity of a raster: mode, size and the raw pixel bytes."""
    head = f"{mode}:{size[0]}x{size[1]}:".encode()
    return hashlib.sha256(head + raw).hexdigest()
