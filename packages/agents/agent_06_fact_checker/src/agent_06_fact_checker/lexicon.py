"""Lexicon matching for the deterministic FIN pre-filters (13 5.4; CCR-046).

Pure functions over *lexicons supplied by the rule-pack record*: this module owns the matching
rules only (NFC, case folding, word boundaries that respect Devanagari combining marks, optional
suffix / clitic forms from the lexicon's own suffix lists), never a word list.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|in|co|io|net|org|me|ly|link)(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
Suffixes = Mapping[str, Sequence[str]]
"""Suffix / clitic lists per script family: ``latin`` and ``deva``."""


_INVISIBLE = dict.fromkeys(
    [0x00AD, 0x180E, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0x2061, 0x2062, 0x2063, 0xFEFF]
)


def normalise_for_matching(text: str) -> str:
    """THE single normalisation of every lexicon match: invisible / zero-width characters removed
    (a ZWSP inside "Buy" or a ZWNJ inside a Devanagari word must not defeat a filter), NFKC (width
    and compatibility forms), case folded. One function so it can be swapped for the shared
    ``amw_core`` text normaliser when that module is merged."""
    stripped = text.translate(_INVISIBLE)
    return unicodedata.normalize("NFKC", stripped).casefold()


norm = normalise_for_matching


def _word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_" or unicodedata.category(ch).startswith("M")


def suffix_families(by_language: Mapping[str, Sequence[str]]) -> Suffixes:
    """Group the lexicon's per-language suffix lists by script: Latin or Devanagari."""
    latin = [s for lang in ("en", "hinglish") for s in by_language.get(lang, ())]
    deva = [s for lang in ("mr", "hi") for s in by_language.get(lang, ())]
    return {"latin": tuple(norm(s) for s in latin), "deva": tuple(norm(s) for s in deva)}


def all_markers(markers: Mapping[str, Iterable[str]]) -> tuple[str, ...]:
    """Union of every language's list (a script may mix languages; stricter, never looser)."""
    seen: dict[str, None] = {}
    for words in markers.values():
        for word in words:
            n = norm(word).strip()
            if n:
                seen.setdefault(n, None)
    return tuple(seen)


def term_spans(hay: str, term: str, suffixes: Suffixes | None = None) -> list[tuple[int, int]]:
    """Occurrences of ``term`` in the *normalised* ``hay`` as a whole word or phrase, optionally
    followed by one suffix / clitic of the term's script family (Marathi ``वाढेलच``)."""
    needle = norm(term).strip()
    if not needle:
        return []
    family = "deva" if _DEVANAGARI.search(needle) else "latin"
    tails = ("", *((suffixes or {}).get(family, ())))
    found: list[tuple[int, int]] = []
    start = hay.find(needle)
    while start >= 0:
        end = start + len(needle)
        if start == 0 or not _word_char(hay[start - 1]):
            for tail in tails:
                stop = end + len(tail)
                if tail and not hay.startswith(tail, end):
                    continue
                if stop == len(hay) or not _word_char(hay[stop]):
                    found.append((start, stop))
                    break
        start = hay.find(needle, start + 1)
    return found


def find_marker(text: str, markers: Iterable[str], suffixes: Suffixes | None = None) -> str | None:
    """First marker found in ``text`` as a whole word or phrase, else ``None``."""
    hay = norm(text)
    for marker in markers:
        if term_spans(hay, marker, suffixes):
            return marker
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
