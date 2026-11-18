"""Text normalisation shared by the option builder, guards and checks (blueprint 6.2)."""

import re
import unicodedata

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)
FIN_SYMBOLS = frozenset("₹$€£¥%")


def normalise(text: str) -> str:
    """NFC, collapsed whitespace, stripped. The displayed text keeps case and spelling."""
    return _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()


def fold(text: str) -> str:
    return normalise(text).casefold()


def words(text: str) -> list[str]:
    return normalise(text).split(" ") if normalise(text) else []


def folded_words(text: str) -> list[str]:
    """Case-folded words with edge punctuation removed (whole-word matching)."""
    out = [_PUNCT.sub("", w) for w in fold(text).split(" ")]
    return [w for w in out if w]


def contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    if n == 0 or n > len(haystack):
        return False
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def has_digit_or_symbol(text: str) -> bool:
    return any(ch.isdigit() or ch in FIN_SYMBOLS for ch in text)
