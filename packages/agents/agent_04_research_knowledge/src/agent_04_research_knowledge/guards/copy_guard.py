"""CopyGuard (blueprint 10.6; YTG-R9, 13 section 8, IN-08).

Normalisation: NFKC, case-fold, punctuation stripped, word tokens. The guard fails a note that
shares ``max_verbatim_words`` or more consecutive words with its passage, or whose word n-gram
overlap ratio reaches ``max_overlap_ratio``. A pair in two different languages is skipped and
flagged ``CROSS_LANGUAGE`` (compensating controls: blueprint 10.6).
"""

import re
import unicodedata
from dataclasses import dataclass

CROSS_LANGUAGE = "CROSS_LANGUAGE"
_DEVANAGARI = re.compile("[ऀ-ॿ]")
_LATIN = re.compile("[A-Za-z]")


def normalise(text: str) -> list[str]:
    """NFKC, case-fold, every punctuation or symbol character becomes a separator."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    chars = [" " if unicodedata.category(c)[0] in {"P", "S", "Z", "C"} else c for c in folded]
    return "".join(chars).split()


def _shingles(words: list[str], n: int) -> set[tuple[str, ...]]:
    if n <= 0 or len(words) < n:
        return set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def longest_shared_run(note_words: list[str], passage_words: list[str]) -> int:
    """Longest run of consecutive words that appears in both lists (dynamic programming)."""
    if not note_words or not passage_words:
        return 0
    best = 0
    previous = [0] * (len(passage_words) + 1)
    for nw in note_words:
        current = [0] * (len(passage_words) + 1)
        for j, pw in enumerate(passage_words, start=1):
            if nw == pw:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def _primary(tag: str | None) -> str | None:
    return tag.split("-", 1)[0].lower() if tag else None


def _script_language(text: str) -> str:
    return "dev" if len(_DEVANAGARI.findall(text)) > len(_LATIN.findall(text)) else "lat"


def is_cross_language(
    note: str, passage: str, note_language: str | None, passage_language: str | None
) -> bool:
    """Language tags decide when both are known; else the dominant script decides."""
    a, b = _primary(note_language), _primary(passage_language)
    if a and b:
        return a != b
    return _script_language(note) != _script_language(passage)


@dataclass(frozen=True, slots=True)
class CopyResult:
    longest_shared_run: int
    overlap_ratio: float
    passed: bool
    skipped_reason: str | None


class CopyGuard:
    """Pure; no I/O. Numbers only are returned (never text), so results may be logged."""

    def check(
        self,
        note: str,
        passage: str,
        n: int,
        max_ratio: float,
        *,
        max_verbatim_words: int,
        note_language: str | None = "en",
        passage_language: str | None = None,
    ) -> CopyResult:
        if is_cross_language(note, passage, note_language, passage_language):
            return CopyResult(0, 0.0, True, CROSS_LANGUAGE)
        note_words, passage_words = normalise(note), normalise(passage)
        run = longest_shared_run(note_words, passage_words)
        note_shingles = _shingles(note_words, n)
        ratio = (
            len(note_shingles & _shingles(passage_words, n)) / len(note_shingles)
            if note_shingles
            else 0.0
        )
        passed = run < max_verbatim_words and ratio < max_ratio
        return CopyResult(run, ratio, passed, None)
