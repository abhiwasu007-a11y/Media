"""Pure text helpers shared by the checks and the assembler (no I/O, no logging)."""

import re
import unicodedata
from fractions import Fraction

_JOINERS = ("\u200d", "\u200c")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.?!\u0964])(\s+)(?=[^\W\d_])")
_WCHAR = r"(?:[^\W_]|[\u0900-\u0963\u0966-\u097f])"
_WORD = re.compile(rf"{_WCHAR}+(?:['\u2019\-]{_WCHAR}+)*", re.UNICODE)
_BRACKETED = re.compile(r"\([^()]*\)")
DEVANAGARI = re.compile(r"[\u0900-\u097f]")


def normalise(text: str) -> str:
    """NFC, case-folded, punctuation replaced by single spaces (used for comparisons only)."""
    folded = unicodedata.normalize("NFC", text).casefold()
    return " ".join(_WORD.findall(folded))


def words(text: str) -> list[str]:
    return normalise(text).split()


def split_sentences(text: str) -> list[str]:
    """Split at a terminator followed by whitespace and a letter (blueprint 10.6 ``Segmenter``).

    The text itself is never altered except that surrounding whitespace is trimmed.
    """
    stripped = text.strip()
    parts: list[str] = []
    start = 0
    for match in _SENTENCE_BOUNDARY.finditer(stripped):
        parts.append(stripped[start : match.start()].strip())
        start = match.end()
    parts.append(stripped[start:].strip())
    return [p for p in parts if p]


def speech_chars(text: str) -> int:
    """Approximate extended-grapheme count excluding whitespace (blueprint 10.6 unit note).

    Combining marks and a character that follows a virama (conjuncts) join the previous cluster.
    The exact unit **REQUIRES REVIEW (Phase 1)** once a speech rate is measured.
    """
    count = 0
    joined = False
    for ch in unicodedata.normalize("NFC", text):
        if ch.isspace():
            joined = False
            continue
        category = unicodedata.category(ch)
        if category in ("Mn", "Mc", "Me") or ch in _JOINERS:
            joined = unicodedata.combining(ch) == 9 or (joined and ch in _JOINERS)
            continue
        if joined:
            joined = False
            continue
        count += 1
    return count


def word_count(text: str) -> int:
    return len(text.split())


def strip_brackets(text: str) -> str:
    """Text with every ``( ... )`` group removed (bracketed English terms)."""
    previous = None
    current = text
    while previous != current:
        previous = current
        current = _BRACKETED.sub(" ", current)
    return current


def ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def to_fraction(value: float | int) -> Fraction:
    """Exact fraction of a configuration number (avoids float artefacts like 240.00000000000003)."""
    return Fraction(str(value))


def has_devanagari(text: str) -> bool:
    return DEVANAGARI.search(text) is not None
