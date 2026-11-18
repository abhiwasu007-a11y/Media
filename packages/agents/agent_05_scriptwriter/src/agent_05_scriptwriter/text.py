"""Pure text helpers shared by the checks and the assembler (no I/O, no logging)."""

import re
import unicodedata
from dataclasses import dataclass
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


# Letters of other scripts that render like Latin letters (matching only, never in output).
_CONFUSABLES = {
    "\u0430": "a",
    "\u0435": "e",
    "\u043e": "o",
    "\u0440": "p",
    "\u0441": "c",
    "\u0443": "y",
    "\u0445": "x",
    "\u0456": "i",
    "\u0455": "s",
    "\u0458": "j",
    "\u043d": "h",
    "\u043a": "k",
    "\u0442": "t",
    "\u043c": "m",
    "\u0410": "A",
    "\u0412": "B",
    "\u0415": "E",
    "\u041a": "K",
    "\u041c": "M",
    "\u041d": "H",
    "\u041e": "O",
    "\u0420": "P",
    "\u0421": "C",
    "\u0422": "T",
    "\u0425": "X",
    "\u0391": "A",
    "\u0392": "B",
    "\u0395": "E",
    "\u0397": "H",
    "\u0399": "I",
    "\u039a": "K",
    "\u039c": "M",
    "\u039d": "N",
    "\u039f": "O",
    "\u03a1": "P",
    "\u03a4": "T",
    "\u03a5": "Y",
    "\u03a7": "X",
    "\u03bf": "o",
    "\u03bd": "v",
}


@dataclass(frozen=True, slots=True)
class Normalised:
    """Text prepared for matching plus, per character, its index in the original text."""

    text: str
    offsets: tuple[int, ...]


def normalise_for_matching(text: str) -> Normalised:
    """The ONE normalisation used before every lexicon match (blueprint 6.4, review M2).

    NFKC per character; every format character (Unicode category Cf: zero-width space, ZWJ, ZWNJ,
    soft hyphen, word joiner, bidi marks) is dropped; look-alike Cyrillic/Greek letters are folded
    to Latin. The result is for comparison only: the script text itself is never altered. Will be
    replaced by the shared ``amw_core.text_normalise`` when that module exists (same signature).
    """
    out: list[str] = []
    offsets: list[int] = []
    for index, ch in enumerate(text):
        for piece in unicodedata.normalize("NFKC", ch):
            if unicodedata.category(piece) == "Cf":
                continue
            out.append(_CONFUSABLES.get(piece, piece))
            offsets.append(index)
    return Normalised("".join(out), tuple(offsets))


def invisible_characters(text: str) -> list[str]:
    """Format characters that are not a joiner next to Devanagari (hiding places for evasion)."""
    found: list[str] = []
    for i, ch in enumerate(text):
        if unicodedata.category(ch) != "Cf":
            continue
        if ch in _JOINERS and (
            (i > 0 and DEVANAGARI.match(text[i - 1]))
            or (i + 1 < len(text) and DEVANAGARI.match(text[i + 1]))
        ):
            continue
        found.append(f"U+{ord(ch):04X}")
    return found
