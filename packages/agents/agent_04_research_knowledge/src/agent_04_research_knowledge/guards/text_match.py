# ruff: noqa: RUF001
"""Text normalisation and script detection for copy matching: the ONE place for both.

``normalise_for_matching`` is the single entry point of the package (the coordinator will swap it
for the shared ``amw_core.text_normalise`` once that lands; nothing else may tokenise text).

Order (every step defends against a known evasion of the copy guard):
1. NFKC (compatibility forms, full-width letters, precomposed Devanagari nukta letters decompose);
2. delete format characters (category Cf: ZWSP, ZWNJ, ZWJ, soft hyphen, bidi marks, BOM): they are
   removed, never turned into word separators;
3. casefold;
4. fold confusables (Cyrillic and Greek look-alikes, dotless i, long s) to Latin;
5. Devanagari canonical form: nukta deleted, chandrabindu to anusvara;
6. tokenise: letters, combining marks and digits form words, everything else separates.
"""

import unicodedata
from collections import Counter

_CONFUSABLES = str.maketrans(
    {
        # Cyrillic
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
        "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
        "һ": "h", "ԁ": "d", "ԛ": "q", "ԝ": "w", "к": "k",
        "н": "h", "т": "t", "в": "b", "м": "m",
        # Greek
        "ο": "o", "α": "a", "ν": "v", "ρ": "p", "ι": "i",
        "κ": "k", "υ": "u", "χ": "x", "τ": "t",
        # Latin look-alikes
        "ı": "i", "ſ": "s",
    }
)  # fmt: skip
_NUKTA = "़"
_CHANDRABINDU = "ँ"
_ANUSVARA = "ं"


def fold_text(text: str) -> str:
    """Steps 1 to 5: the canonical string used for matching."""
    nfkc = unicodedata.normalize("NFKC", text)
    visible = "".join(c for c in nfkc if unicodedata.category(c) != "Cf")
    folded = visible.casefold().translate(_CONFUSABLES)
    return folded.replace(_NUKTA, "").replace(_CHANDRABINDU, _ANUSVARA)


def normalise_for_matching(text: str) -> list[str]:
    """Word tokens of ``text`` in canonical form (step 6 on top of ``fold_text``)."""
    out: list[str] = []
    word: list[str] = []
    for ch in fold_text(text):
        if unicodedata.category(ch)[0] in "LMN":
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def _script_of(ch: str) -> str | None:
    if not unicodedata.category(ch).startswith("L"):
        return None
    name = unicodedata.name(ch, "")
    return name.split(" ", 1)[0] if name else None


def dominant_script(text: str) -> str | None:
    """Script with the most letters in the folded text (``LATIN``, ``DEVANAGARI``...), else None.

    Decided by the actual characters, never by a language tag.
    """
    counts = Counter(s for ch in fold_text(text) if (s := _script_of(ch)) is not None)
    return counts.most_common(1)[0][0] if counts else None


def scripts_differ(a: str, b: str) -> bool:
    """True only when both texts have a determinable script and the scripts really differ."""
    sa, sb = dominant_script(a), dominant_script(b)
    return sa is not None and sb is not None and sa != sb
