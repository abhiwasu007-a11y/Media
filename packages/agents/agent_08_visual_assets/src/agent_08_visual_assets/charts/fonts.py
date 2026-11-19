"""``PinnedFontResolver``: pick a repo-committed brand font from a pinned font manifest.

The manifest format is agent_11's ``data/fonts/manifest.json`` (schema 1: ``fonts[]`` with ``key``,
``file``, ``sha256``, ``licence``). Agent 08 does not import agent_11: the caller passes the
manifest path (operator tooling, tests and the local demo). The preference order is Mukta (brand
primary, PR #74, RV-09) and then Noto Sans Devanagari (fallback, RV-08); the first key present
wins. The file's SHA-256 must equal the manifest value, otherwise ``CONFIG_INVALID``. In the stage
the brand font comes from tenant storage as a ``FONT`` asset (ledgered); this resolver gives the
same file for runs outside the stage. DejaVu is never used for data_pack charts (no Devanagari).
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from amw_core.errors import ConfigInvalidError

PREFERRED_KEYS = ("mukta_regular", "noto_sans_devanagari_vf")


@dataclass(frozen=True, slots=True)
class PinnedFont:
    key: str
    path: Path
    sha256: str
    licence: str


class PinnedFontResolver:
    @staticmethod
    def resolve(manifest_path: Path, preferred: Sequence[str] = PREFERRED_KEYS) -> PinnedFont:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            fonts = {f["key"]: f for f in manifest["fonts"]}
        except OSError, ValueError, KeyError, TypeError:
            raise ConfigInvalidError("font manifest cannot be read") from None
        for key in preferred:
            entry = fonts.get(key)
            if entry is None:
                continue
            path = manifest_path.parent / str(entry["file"])
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                raise ConfigInvalidError("pinned font file is missing") from None
            if digest != entry.get("sha256"):
                raise ConfigInvalidError("pinned font file does not match its manifest hash")
            return PinnedFont(key, path, digest, str(entry.get("licence")))
        raise ConfigInvalidError("no preferred brand font is listed in the font manifest")
