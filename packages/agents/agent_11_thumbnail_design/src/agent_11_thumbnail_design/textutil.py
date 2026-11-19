"""Text normalisation shared by the option builder, guards and checks (blueprint 6.2)."""

import re
import unicodedata

from amw_core.text_normalise import normalise_for_matching, tokenize

_WS = re.compile(r"\s+")
FIN_SYMBOLS = frozenset("₹$€£¥%")


def normalise(text: str) -> str:
    """NFC, collapsed whitespace, stripped. The displayed text keeps case and spelling."""
    return _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()


def fold(text: str) -> str:
    """Matching form from the shared core normaliser (CCR-105): NFKC, casefold, invisible and
    look-alike folds, Devanagari canonical forms. Never used for displayed text."""
    return normalise_for_matching(text).text


def words(text: str) -> list[str]:
    return normalise(text).split(" ") if normalise(text) else []


def folded_words(text: str) -> list[str]:
    """Whole-word tokens of the shared core normaliser; whole-word matching only (no stemming,
    no prefix match), so an inflected form is a different word (blueprint 6.2)."""
    return [t.text for t in tokenize(normalise_for_matching(text))]


def contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    if n == 0 or n > len(haystack):
        return False
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def has_digit_or_symbol(text: str) -> bool:
    return any(ch.isdigit() or ch in FIN_SYMBOLS for ch in text)
