"""Text normalisation shared by the option builder, guards and checks (blueprint 6.2)."""

import re
import unicodedata

_WS = re.compile(r"\s+")
FIN_SYMBOLS = frozenset("₹$€£¥%")


def normalise(text: str) -> str:
    """NFC, collapsed whitespace, stripped. The displayed text keeps case and spelling."""
    return _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()


def fold(text: str) -> str:
    return normalise(text).casefold()


def words(text: str) -> list[str]:
    return normalise(text).split(" ") if normalise(text) else []


def _is_edge_noise(ch: str) -> bool:
    """Punctuation (P*) and symbols (S*) only. Letters, digits and combining marks (Devanagari
    vowel signs, virama, anusvara: categories Mc/Mn) are part of the word and are never stripped."""
    return unicodedata.category(ch)[0] in ("P", "S")


def _strip_edges(word: str) -> str:
    start, end = 0, len(word)
    while start < end and _is_edge_noise(word[start]):
        start += 1
    while end > start and _is_edge_noise(word[end - 1]):
        end -= 1
    return word[start:end]


def folded_words(text: str) -> list[str]:
    """Case-folded words with edge punctuation removed; whole-word matching only (no stemming,
    no prefix match), so an inflected form is a different word (blueprint 6.2)."""
    out = [_strip_edges(w) for w in fold(text).split(" ")]
    return [w for w in out if w]


def contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    if n == 0 or n > len(haystack):
        return False
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def has_digit_or_symbol(text: str) -> bool:
    return any(ch.isdigit() or ch in FIN_SYMBOLS for ch in text)
