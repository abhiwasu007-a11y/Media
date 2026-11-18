"""Lexicon matching for the deterministic FIN pre-filters (13 5.4; CCR-046).

Pure functions over *lexicons supplied by the rule-pack record* (``RulePack.markers``): this
module owns the matching rules only (NFC, case folding, word boundaries that respect Devanagari
combining marks), never a word list.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping

_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|in|co|io|net|org|me|ly|link)(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_" or unicodedata.category(ch).startswith("M")


def all_markers(markers: Mapping[str, Iterable[str]]) -> tuple[str, ...]:
    """Union of every language's list (a script may mix languages; stricter, never looser)."""
    seen: dict[str, None] = {}
    for words in markers.values():
        for word in words:
            norm = _norm(word).strip()
            if norm:
                seen.setdefault(norm, None)
    return tuple(seen)


def find_marker(text: str, markers: Iterable[str]) -> str | None:
    """First marker found in ``text`` as a whole word or phrase, else ``None``."""
    hay = _norm(text)
    for marker in markers:
        needle = _norm(marker).strip()
        if not needle:
            continue
        start = hay.find(needle)
        while start >= 0:
            end = start + len(needle)
            before_ok = start == 0 or not _word_char(hay[start - 1])
            after_ok = end == len(hay) or not _word_char(hay[end])
            if before_ok and after_ok:
                return marker
            start = hay.find(needle, start + 1)
    return None


def find_urls(text: str) -> list[tuple[int, int]]:
    """Offsets of URLs and domain-with-path strings (FIN-R8 detector, syntax only)."""
    return [(m.start(), m.end()) for m in _URL.finditer(text)]


def find_patterns(text: str, patterns: Iterable[str]) -> list[tuple[int, int]]:
    """Offsets of referral / coupon code matches of the configured regular expressions."""
    found: list[tuple[int, int]] = []
    for pattern in patterns:
        found.extend((m.start(), m.end()) for m in re.finditer(pattern, text, re.IGNORECASE))
    return found
