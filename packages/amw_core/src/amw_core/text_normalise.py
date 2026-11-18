"""Shared text normalisation for compliance matching (finance rules, copy guard).

Every compliance-sensitive check (the FIN-R1..R13 lexicons, the copyright copy guard) must
match on the output of this module, never on raw text, and must normalise its lexicon
entries with the same function. Defeated evasions: zero-width / soft-hyphen / bidi /
variation-selector characters inside words, Cyrillic / Greek / fullwidth / small-capital
look-alike letters, combining diacritics stacked on letters, Devanagari nukta / chandrabindu
variants, two-part independent vowels (for example U+0905 U+093E for U+0906), Devanagari
and other decimal digits, and scripts guessed from language tags instead of the text.

Pure functions, stdlib ``unicodedata`` only, no network, no I/O.

Public API (lanes call exactly these):

* ``normalise_for_matching(text, options=DEFAULT_OPTIONS) -> NormalisedText``
* ``NormalisedText.original_span(start, end) -> tuple[int, int]`` and
  ``NormalisedText.quote(start, end) -> str`` (map a match back to the ORIGINAL text)
* ``tokenize(normalised) -> tuple[Token, ...]``
* ``dominant_script(text, *, threshold=DOMINANCE_THRESHOLD) -> Script``
* ``stem_affixes(token, suffixes=DEFAULT_SUFFIXES, *, min_stem=2, max_strips=1) -> str``
* ``word_ngrams(tokens, n) -> tuple[NGram, ...]`` and ``shingle_set(tokens, n)``

Offset map: text is split into clusters (one base character plus its combining marks, after
the invisible characters are dropped; a whitespace run is one cluster). Each cluster is
normalised on its own and every output character records the ``[start, end)`` span of its
source cluster in the original string. Known limit: compositions that cross cluster
boundaries (Hangul conjoining jamo L+V) are not composed; irrelevant for Latin/Devanagari.

Input size: texts longer than ``MAX_INPUT_CHARS`` (1,000,000) raise ``InputInvalidError``;
callers chunk longer documents. Pure-ASCII text takes a linear fast path. Cost is linear;
measured about 0.3 s for 1M ASCII characters, about 8 s for 1M characters of mixed (6-8 s, machine dependent)
Latin / Devanagari / look-alike text and up to about 19 s for 1M varied clusters
(provisional). Output is bounded too (``MAX_OUTPUT_CHARS``, character expansion).
Memory: one span tuple per output character.

Stability: the function reruns on its own output until the text no longer changes (NFKC and
casefold can create characters whose neighbours then re-cluster), so
``normalise(normalise(x).text).text == normalise(x).text`` always holds (seeded property test,
60,000 strings). Offsets of every pass are composed back to the original string.

``quote()`` / ``original_span`` return whole source clusters. The look-alike fold is decided per
WORD, so quoting a fragment of a word and normalising it alone can differ from the match
("buy" + Greek sigma + Cyrillic O: the Cyrillic O folds inside the word, not alone). Quoting a
whole word between real whitespace re-normalises to the same text (tested). A match range that
ends in a collapsed space maps to the whole whitespace run.

Removed as invisible or decorative: format characters (Cf), private use (Co), unassigned (Cn),
lone surrogates (Cs), controls, U+0345, U+0640 tatweel, U+FFFC, U+2011 non-breaking hyphen.
Ordinary hyphens and other punctuation inside words are NOT removed (caller policy).

Known gaps (not folded; lexicon authors list both spellings; REQUIRES REVIEW, linguist):
anusvara versus nasal + virama (संकट / सङ्कट, हिंदी / हिन्दी), ऑ versus आ and ॉ versus ा, and
spelling variants such as शेअर / शेयर. A safe fold would have to look across clusters and
decide per word; that is a language decision, not a Unicode one. Residual look-alike risk: a
real Cyrillic or Greek word made only of table letters folds to Latin in upper case
(Cyrillic capital SO + O + ER -> "cop"; Greek capital ALPHA NU ALPHA -> "ana"),
while its lower-case form with letters outside the table stays; the table is PROVISIONAL.

PROVISIONAL, REQUIRES REVIEW (owner / linguist): the confusables table, the two-part vowel
table, ``DEFAULT_SUFFIXES``, ``DOMINANCE_THRESHOLD`` and the option defaults.
"""

import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from amw_core.errors import InputInvalidError

__all__ = [
    "DEFAULT_OPTIONS",
    "DEFAULT_SUFFIXES",
    "DOMINANCE_THRESHOLD",
    "MAX_INPUT_CHARS",
    "MAX_OUTPUT_CHARS",
    "NGram",
    "NormaliseOptions",
    "NormalisedText",
    "Script",
    "Token",
    "dominant_script",
    "normalise_for_matching",
    "shingle_set",
    "stem_affixes",
    "tokenize",
    "word_ngrams",
]


class Script(StrEnum):
    """Script of a text, decided by counting its letters (never by a language tag)."""

    LATIN = "LATIN"
    DEVANAGARI = "DEVANAGARI"
    MIXED = "MIXED"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class NormaliseOptions:
    """Switches for the lossy folds. Defaults favour catching evasions (provisional)."""

    strip_nukta: bool = True
    """Drop U+093C NUKTA (so U+0958 QA matches U+0915 KA)."""
    fold_chandrabindu: bool = True
    """Treat U+0901 CHANDRABINDU as U+0902 ANUSVARA."""
    strip_diacritics: bool = True
    """Drop every combining mark on a Latin letter, and generic combining diacritics
    (U+0300 block and its extensions) on any other base; Devanagari signs are kept."""


DEFAULT_OPTIONS = NormaliseOptions()

DOMINANCE_THRESHOLD = 0.8
"""Share of letters one script needs to be dominant; below it the text is MIXED (provisional)."""

MAX_INPUT_CHARS = 1_000_000
"""Longest text ``normalise_for_matching`` accepts; longer input raises ``InputInvalidError``.
Callers chunk longer documents (for example by paragraph) and shift the offsets themselves.
Cost is linear in the length (one long combining cluster included). Measured on the
development machine: about 0.3 s for 1M ASCII characters, about 8 s for 1M characters of mixed (6-8 s, machine dependent)
Latin / Devanagari text, up to about 19 s for 1M varied clusters (provisional). Memory is one
span tuple per output character."""

MAX_OUTPUT_CHARS = 1_000_000
"""Longest normalised text; compatibility characters can expand a lot (U+FDFA becomes 18
characters), so the OUTPUT is bounded too and a larger result raises ``InputInvalidError``."""

_MAX_PASSES = 8
_SPACE = " "
_NUKTA = "\u093c"
_VIRAMA = "\u094d"
_CHANDRABINDU = "\u0901"
_ANUSVARA = "\u0902"

# Removed for matching (not replaced by a space). Categories Cf (zero-width space / joiners,
# BOM, soft hyphen, bidi marks and isolates, word joiner, invisible operators, tags), Co
# (private use), Cn (unassigned and noncharacters), Cs (lone surrogates) and non-whitespace
# controls (Cc) are removed by category; these are the other invisible or decorative extras.
_REMOVED_EXTRA = frozenset(
    {
        0x034F,  # COMBINING GRAPHEME JOINER
        0x0345,  # COMBINING GREEK YPOGEGRAMMENI (casefold would turn it into a letter, iota)
        0x0640,  # ARABIC TATWEEL (a letter-modifier that is only decoration inside a word)
        0x2011,  # NON-BREAKING HYPHEN (NFKC would turn it into a visible hyphen inside a word)
        0xFFFC,  # OBJECT REPLACEMENT CHARACTER
        0x115F,  # HANGUL CHOSEONG FILLER
        0x1160,  # HANGUL JUNGSEONG FILLER
        0x3164,  # HANGUL FILLER
        0xFFA0,  # HALFWIDTH HANGUL FILLER
        0x180B,  # MONGOLIAN FREE VARIATION SELECTOR ONE
        0x180C,  # MONGOLIAN FREE VARIATION SELECTOR TWO
        0x180D,  # MONGOLIAN FREE VARIATION SELECTOR THREE
        0x180F,  # MONGOLIAN FREE VARIATION SELECTOR FOUR
    }
)
_VARIATION_SELECTOR_RANGES = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))
# Visible blanks that are not Unicode whitespace: treated as a space.
_EXTRA_SPACES = frozenset({"\u2800"})  # BRAILLE PATTERN BLANK
# Script-neutral combining diacritics (Unicode script "Inherited").
_GENERIC_MARK_RANGES = (
    (0x0300, 0x036F),
    (0x1AB0, 0x1AFF),
    (0x1DC0, 0x1DFF),
    (0x20D0, 0x20FF),
    (0xFE20, 0xFE2F),
)
_DEVANAGARI_RANGES = ((0x0900, 0x097F), (0xA8E0, 0xA8FF), (0x1CD0, 0x1CFF), (0x11B00, 0x11B5F))

# Curated look-alike table, written for this module (not copied from external data). Keys are
# base letters as they stand after NFD (folded before and after NFKC and casefold); values are
# lowercase ASCII. Uppercase forms are folded before casefolding because their lowercase forms
# no longer look Latin (Cyrillic VE -> ve).
_CONFUSABLES: dict[str, str] = {
    # Cyrillic capitals
    "\u0410": "a",  # A
    "\u0412": "b",  # VE
    "\u0415": "e",  # IE
    "\u041a": "k",  # KA
    "\u041c": "m",  # EM
    "\u041d": "h",  # EN
    "\u041e": "o",  # O
    "\u0420": "p",  # ER
    "\u0421": "c",  # ES
    "\u0422": "t",  # TE
    "\u0423": "y",  # U
    "\u0425": "x",  # HA
    "\u0405": "s",  # DZE
    "\u0406": "i",  # BYELORUSSIAN-UKRAINIAN I
    "\u0408": "j",  # JE
    "\u04ae": "y",  # STRAIGHT U
    "\u04ba": "h",  # SHHA
    "\u04c0": "l",  # PALOCHKA
    "\u051a": "q",  # QA
    "\u051c": "w",  # WE
    # Cyrillic small letters
    "\u0430": "a",
    "\u0435": "e",
    "\u043e": "o",
    "\u0440": "p",
    "\u0441": "c",
    "\u0443": "y",
    "\u0445": "x",
    "\u0455": "s",
    "\u0456": "i",
    "\u0458": "j",
    "\u04af": "y",
    "\u04bb": "h",
    "\u04cf": "l",
    "\u0501": "d",
    "\u051b": "q",
    "\u051d": "w",
    # Greek capitals
    "\u0391": "a",  # ALPHA
    "\u0392": "b",  # BETA
    "\u0395": "e",  # EPSILON
    "\u0396": "z",  # ZETA
    "\u0397": "h",  # ETA
    "\u0399": "i",  # IOTA
    "\u039a": "k",  # KAPPA
    "\u039c": "m",  # MU
    "\u039d": "n",  # NU
    "\u039f": "o",  # OMICRON
    "\u03a1": "p",  # RHO
    "\u03a4": "t",  # TAU
    "\u03a5": "y",  # UPSILON
    "\u03a7": "x",  # CHI
    # Greek small letters
    "\u03b1": "a",
    "\u03b9": "i",
    "\u03ba": "k",
    "\u03bd": "v",
    "\u03bf": "o",
    "\u03c1": "p",
    "\u03c5": "u",
    "\u03f2": "c",  # LUNATE SIGMA
    "\u03f3": "j",  # YOT
    # Latin variants that NFKC leaves alone
    "\u0131": "i",  # DOTLESS I
    "\u0237": "j",  # DOTLESS J
    "\u0261": "g",  # SCRIPT G
    "\u1d00": "a",  # small capital letters
    "\u0299": "b",
    "\u1d04": "c",
    "\u1d05": "d",
    "\u1d07": "e",
    "\u0262": "g",
    "\u029c": "h",
    "\u026a": "i",
    "\u1d0a": "j",
    "\u1d0b": "k",
    "\u029f": "l",
    "\u1d0d": "m",
    "\u0274": "n",
    "\u1d0f": "o",
    "\u1d18": "p",
    "\u0280": "r",
    "\ua731": "s",
    "\u1d1b": "t",
    "\u1d1c": "u",
    "\u1d20": "v",
    "\u1d21": "w",
    "\u028f": "y",
    "\u1d22": "z",
}

# Two-part Devanagari independent vowels -> the single code point (curated subset of the
# "do not use" sequences of The Unicode Standard, Devanagari chapter). Applied in order, so
# a sequence built on U+0906 is folded after U+0905 U+093E became U+0906.
_VOWEL_SEQUENCES: tuple[tuple[str, str], ...] = (
    ("\u0905\u093e", "\u0906"),  # A + AA sign -> AA
    ("\u0905\u0946", "\u0904"),  # A + short E sign -> short A
    ("\u0905\u0949", "\u0911"),  # A + candra O sign -> candra O
    ("\u0905\u094a", "\u0912"),  # A + short O sign -> short O
    ("\u0905\u094b", "\u0913"),  # A + O sign -> O
    ("\u0905\u094c", "\u0914"),  # A + AU sign -> AU
    ("\u0905\u0945", "\u0972"),  # A + candra E sign -> candra A (Marathi)
    ("\u090f\u0945", "\u090d"),  # E + candra E sign -> candra E
    ("\u090f\u0946", "\u090e"),  # E + short E sign -> short E
    ("\u090f\u0947", "\u0910"),  # E + E sign -> AI
    ("\u0906\u0945", "\u0911"),  # AA + candra E sign -> candra O
    ("\u0906\u0947", "\u0913"),  # AA + E sign -> O
    ("\u0906\u0948", "\u0914"),  # AA + AI sign -> AU
)


def _in_ranges(cp: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(low <= cp <= high for low, high in ranges)


def _is_removed(ch: str) -> bool:
    cp = ord(ch)
    if cp in _REMOVED_EXTRA or _in_ranges(cp, _VARIATION_SELECTOR_RANGES):
        return True
    category = unicodedata.category(ch)
    if category in {"Cf", "Co", "Cn", "Cs"}:
        return True  # format, private-use, unassigned (incl. noncharacters), lone surrogate
    return category == "Cc" and not ch.isspace()


def _is_space(ch: str) -> bool:
    return ch.isspace() or ch in _EXTRA_SPACES or unicodedata.category(ch) in {"Zs", "Zl", "Zp"}


def _is_mark(ch: str) -> bool:
    return unicodedata.category(ch).startswith("M")


def _letter_script(ch: str) -> Script:
    """LATIN, DEVANAGARI or OTHER for one character (meant for letters and marks)."""
    if _in_ranges(ord(ch), _DEVANAGARI_RANGES):
        return Script.DEVANAGARI
    if "LATIN" in unicodedata.name(ch, ""):
        return Script.LATIN
    return Script.OTHER


@dataclass(frozen=True, slots=True)
class NormalisedText:
    """Normalised text plus, per normalised character, its ``[start, end)`` span in ``original``."""

    original: str
    text: str
    spans: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        if len(self.spans) != len(self.text):
            raise InputInvalidError(
                "offset map length differs from normalised text",
                details={"text_length": len(self.text), "spans_length": len(self.spans)},
            )

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        """Map the normalised range ``[start, end)`` to a range of ``original``."""
        if not 0 <= start <= end <= len(self.text):
            raise InputInvalidError(
                "range outside the normalised text",
                details={"start": start, "end": end, "length": len(self.text)},
            )
        if start == end:
            if start < len(self.text):
                position = self.spans[start][0]
            else:
                position = self.spans[-1][1] if self.spans else 0
            return position, position
        return self.spans[start][0], self.spans[end - 1][1]

    def quote(self, start: int, end: int) -> str:
        """The ORIGINAL text behind the normalised range ``[start, end)``."""
        low, high = self.original_span(start, end)
        return self.original[low:high]


def _clusters(text: str) -> list[tuple[str, int, int]]:
    """Split into (characters, start, end) clusters in linear time (marks are joined once)."""
    parts: list[list[str]] = []
    bounds: list[list[int]] = []
    for index, ch in enumerate(text):
        if _is_removed(ch):
            continue
        if _is_space(ch):
            parts.append([_SPACE])
            bounds.append([index, index + 1])
        elif parts and parts[-1][0] != _SPACE and _is_mark(ch):
            parts[-1].append(ch)
            bounds[-1][1] = index + 1
        else:
            parts.append([ch])
            bounds.append([index, index + 1])
    return [("".join(p), b[0], b[1]) for p, b in zip(parts, bounds, strict=True)]


def _fold_confusables(text: str) -> str:
    return "".join(_CONFUSABLES.get(ch, ch) for ch in text)


def _strip_diacritics(text: str) -> str:
    """Drop marks that sit on a Latin base (the nearest base before them) and generic marks.

    Decided on the text itself, not on the first character of the cluster: an expansion such as
    U+0149 or U+037A puts a Latin letter in front of marks that were first seen on another base.
    This is exactly the decision a second pass over the output would take (idempotence).
    """
    out: list[str] = []
    base = Script.OTHER
    for ch in text:
        if _is_mark(ch):
            if base is Script.LATIN or _in_ranges(ord(ch), _GENERIC_MARK_RANGES):
                continue
        else:
            base = _letter_script(ch)
        out.append(ch)
    return "".join(out)


def _fold_digits(text: str) -> str:
    return "".join(
        str(unicodedata.decimal(ch)) if unicodedata.category(ch) == "Nd" else ch for ch in text
    )


def _canonical_devanagari(text: str, options: NormaliseOptions) -> str:
    if options.strip_nukta:
        text = text.replace(_NUKTA, "")
    if options.fold_chandrabindu:
        text = text.replace(_CHANDRABINDU, _ANUSVARA)
    for sequence, replacement in _VOWEL_SEQUENCES:
        text = text.replace(sequence, replacement)
    return text


@lru_cache(maxsize=65536)
def _normalise_cluster(cluster: str, options: NormaliseOptions, *, fold: bool) -> str:
    if cluster == _SPACE:
        return _SPACE

    def confusables(text: str) -> str:
        return _fold_confusables(text) if fold else text

    # Fold before NFKC too: NFKC turns some look-alikes (U+03F2 lunate sigma) into non-look-alikes.
    text = confusables(unicodedata.normalize("NFD", cluster))
    text = confusables(unicodedata.normalize("NFD", unicodedata.normalize("NFKC", text)))
    text = confusables(unicodedata.normalize("NFD", text.casefold()))
    if options.strip_diacritics:
        text = _strip_diacritics(text)
    text = _canonical_devanagari(_fold_digits(text), options)
    text = unicodedata.normalize("NFKC", text)
    return _strip_diacritics(text) if options.strip_diacritics else text


def _is_word_char(ch: str) -> bool:
    return unicodedata.category(ch)[0] in {"L", "M", "N"}


def _letters(parts: Sequence[str]) -> list[str]:
    return [ch for part in parts for ch in part if unicodedata.category(ch).startswith("L")]


def _choose_fold(plain: Sequence[str], folded: Sequence[str]) -> list[str]:
    """Per word (a run of clusters holding letters, marks or digits) pick the folded form.

    A word keeps its unfolded form only when, after folding, it still holds letters of another
    script (not Latin, not Devanagari) and it held no Latin letter before folding: genuine
    Cyrillic / Greek words stay readable, while a Latin word laced with look-alikes, or a word
    made only of look-alikes, folds to Latin (the evasion case).
    """
    chosen = list(folded)
    index = 0
    while index < len(plain):
        if not any(_is_word_char(ch) for ch in plain[index]):
            index += 1
            continue
        end = index
        while end < len(plain) and any(_is_word_char(ch) for ch in plain[end]):
            end += 1
        had_latin = any(_letter_script(ch) is Script.LATIN for ch in _letters(plain[index:end]))
        foreign = any(_letter_script(ch) is Script.OTHER for ch in _letters(folded[index:end]))
        if foreign and not had_latin:
            chosen[index:end] = plain[index:end]
        index = end
    return chosen


def _normalise_ascii(text: str) -> NormalisedText:
    """Linear fast path, identical in result to the general path for pure-ASCII input."""
    chars: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, ch in enumerate(text):
        if ch.isspace():
            if chars and chars[-1] == _SPACE:
                spans[-1] = (spans[-1][0], index + 1)
            elif chars:
                chars.append(_SPACE)
                spans.append((index, index + 1))
        elif ch >= " " and ch != "\x7f":
            chars.append(ch.lower())
            spans.append((index, index + 1))
    if chars and chars[-1] == _SPACE:
        chars.pop()
        spans.pop()
    return NormalisedText(original=text, text="".join(chars), spans=tuple(spans))


def normalise_for_matching(
    text: str, options: NormaliseOptions = DEFAULT_OPTIONS
) -> NormalisedText:
    """NFKC + casefold + invisible removal + confusable/digit/Devanagari folds + one space.

    Invisible characters are REMOVED (a word broken by U+200B stays one word); whitespace runs
    become one space and leading/trailing whitespace is dropped. Look-alike letters fold to
    Latin per word (see ``_choose_fold``). Apply the same function to lexicon entries before
    comparing. Idempotent (the function reruns on its own output until the text is stable;
    property-tested): ``normalise(normalise(x).text).text == normalise(x).text``.
    """
    if len(text) > MAX_INPUT_CHARS:
        raise InputInvalidError(
            "text is longer than the normalisation limit; chunk it first",
            details={"length": len(text), "max_chars": MAX_INPUT_CHARS},
        )
    if text.isascii():
        return _normalise_ascii(text)
    current = _normalise_once(text, options)
    for _ in range(_MAX_PASSES):
        # NFKC / casefold can create new characters (U+0149, U+037A, U+FCF2, Thai SARA AM) whose
        # neighbours then re-cluster; run again on the output until it is stable. The offsets of
        # each pass are composed, so every output character still maps to the ORIGINAL text.
        following = _normalise_once(current.text, options)
        if following.text == current.text:
            return current
        spans = tuple((current.spans[a][0], current.spans[b - 1][1]) for a, b in following.spans)
        current = NormalisedText(original=text, text=following.text, spans=spans)
    raise InputInvalidError(  # pragma: no cover - no input is known to need more passes
        "normalisation did not reach a stable text", details={"passes": _MAX_PASSES}
    )


def _normalise_once(text: str, options: NormaliseOptions) -> NormalisedText:
    clusters = _clusters(text)
    plain = [_normalise_cluster(c, options, fold=False) for c, _, _ in clusters]
    folded = [_normalise_cluster(c, options, fold=True) for c, _, _ in clusters]
    produced = sum(map(len, folded))
    if produced > MAX_OUTPUT_CHARS:
        raise InputInvalidError(
            "normalised text would exceed the output limit (character expansion)",
            details={"output_length": produced, "max_output_chars": MAX_OUTPUT_CHARS},
        )
    chars: list[str] = []
    spans: list[tuple[int, int]] = []
    for (_, start, end), output in zip(clusters, _choose_fold(plain, folded), strict=True):
        for ch in output:
            if _is_space(ch):
                if chars and chars[-1] == _SPACE:
                    spans[-1] = (spans[-1][0], end)
                    continue
                if not chars:
                    continue
                ch = _SPACE
            chars.append(ch)
            spans.append((start, end))
    if chars and chars[-1] == _SPACE:
        chars.pop()
        spans.pop()
    return NormalisedText(original=text, text="".join(chars), spans=tuple(spans))


@dataclass(frozen=True, slots=True)
class Token:
    """One whole word of a normalised text; ``start``/``end`` index ``NormalisedText.text``."""

    text: str
    start: int
    end: int


def tokenize(normalised: NormalisedText) -> tuple[Token, ...]:
    """Whole-word tokens: runs of letters, combining marks and digits.

    Combining marks (Devanagari vowel signs, virama, anusvara) always stay with their base, so
    a token never splits inside an akshara. A token also splits where letters change between
    Latin, Devanagari and other scripts (``"शेअरbuy"`` -> ``"शेअर"``, ``"buy"``).
    """
    text = normalised.text
    tokens: list[Token] = []
    start: int | None = None
    last_script: Script | None = None
    for index, ch in enumerate(text):
        major = unicodedata.category(ch)[0]
        if major not in {"L", "M", "N"}:
            if start is not None:
                tokens.append(Token(text[start:index], start, index))
            start, last_script = None, None
            continue
        if major == "L":
            script = _letter_script(ch)
            if start is not None and last_script is not None and script is not last_script:
                tokens.append(Token(text[start:index], start, index))
                start = None
            last_script = script
        if start is None:
            start = index
    if start is not None:
        tokens.append(Token(text[start:], start, len(text)))
    return tuple(tokens)


def dominant_script(
    text: str | NormalisedText, *, threshold: float = DOMINANCE_THRESHOLD
) -> Script:
    """Count the letters of the normalised text by script; never consults a language tag.

    Look-alike letters inside Latin words count as Latin (they are folded first); genuine
    Cyrillic / Greek words count as OTHER. A script whose share of the
    letters is at least ``threshold`` is dominant; otherwise MIXED. No letters: OTHER.
    """
    if not 0.5 < threshold <= 1.0:
        raise InputInvalidError("threshold must be in (0.5, 1]", details={"threshold": threshold})
    normalised = text if isinstance(text, NormalisedText) else normalise_for_matching(text)
    counts = Counter(
        _letter_script(ch) for ch in normalised.text if unicodedata.category(ch).startswith("L")
    )
    total = counts.total()
    if total == 0:
        return Script.OTHER
    script, count = counts.most_common(1)[0]
    return script if count / total >= threshold else Script.MIXED


# PROVISIONAL, REQUIRES REVIEW (owner / linguist): closed list of common Marathi and Hindi
# postpositions / case and verb endings, for lexicon matching ONLY (never for display).
_RAW_SUFFIXES: tuple[str, ...] = (
    # Marathi
    "ला",
    "ना",
    "चा",
    "ची",
    "चे",
    "च्या",
    "ने",
    "नी",
    "मध्ये",
    "मधे",
    "साठी",
    "वर",
    "वरून",
    "ून",
    "हून",
    "पासून",
    "पर्यंत",
    "कडे",
    "कडून",
    "शी",
    "ही",
    "च",
    "ेल",
    "ेलच",
    "णार",
    "णारा",
    "णारी",
    "णारे",
    "ायला",
    # Hindi
    "का",
    "की",
    "के",
    "को",
    "से",
    "में",
    "पर",
    "वाला",
    "वाली",
    "वाले",
    "ों",
    "ें",
)
DEFAULT_SUFFIXES: tuple[str, ...] = tuple(
    dict.fromkeys(normalise_for_matching(suffix).text for suffix in _RAW_SUFFIXES)
)
"""Default suffix list, already normalised with ``normalise_for_matching`` (provisional)."""


def _base_count(text: str) -> int:
    return sum(1 for ch in text if not _is_mark(ch))


def stem_affixes(
    token: str,
    suffixes: Sequence[str] = DEFAULT_SUFFIXES,
    *,
    min_stem: int = 2,
    max_strips: int = 1,
) -> str:
    """OPTIONAL lexicon-matching helper: strip the longest listed suffix, up to ``max_strips``.

    ``token`` and ``suffixes`` must already be normalised. A suffix is stripped only when the
    stem keeps at least ``min_stem`` base characters (combining marks do not count) and does
    not end in a virama (the suffix would have been half of a conjunct). Match a lexicon entry
    when either the token or its stem equals the (normalised) entry. DEVANAGARI ONLY: Latin
    (Hinglish) suffixes are not stripped, so list romanised forms in the lexicon. Known
    gaps: locative -त / -ात, oblique plurals leave a stem vowel ("बाजाराचे" -> "बाजारा"),
    and a few words over-strip ("खालच" -> "खाल"). Provisional list,
    REQUIRES REVIEW (owner / linguist).
    """
    if min_stem < 1 or max_strips < 1:
        raise InputInvalidError(
            "min_stem and max_strips must be at least 1",
            details={"min_stem": min_stem, "max_strips": max_strips},
        )
    ordered = sorted({suffix for suffix in suffixes if suffix}, key=lambda s: (-len(s), s))
    stem = token
    for _ in range(max_strips):
        for suffix in ordered:
            candidate = stem[: -len(suffix)]
            if (
                stem.endswith(suffix)
                and _base_count(candidate) >= min_stem
                and not candidate.endswith(_VIRAMA)
            ):
                stem = candidate
                break
        else:
            break
    return stem


@dataclass(frozen=True, slots=True)
class NGram:
    """``n`` consecutive token texts; ``start``/``end`` index ``NormalisedText.text``."""

    words: tuple[str, ...]
    start: int
    end: int


def _check_n(n: int) -> None:
    if n < 1:
        raise InputInvalidError("n-gram size must be at least 1", details={"n": n})


def word_ngrams(tokens: Sequence[Token], n: int) -> tuple[NGram, ...]:
    """Word n-grams (shingles) over tokens, in order; empty when there are fewer than ``n``."""
    _check_n(n)
    return tuple(
        NGram(
            words=tuple(token.text for token in tokens[i : i + n]),
            start=tokens[i].start,
            end=tokens[i + n - 1].end,
        )
        for i in range(len(tokens) - n + 1)
    )


def shingle_set(tokens: Sequence[Token], n: int) -> frozenset[tuple[str, ...]]:
    """The set of word n-grams (without positions), for overlap measures in the copy guard."""
    return frozenset(gram.words for gram in word_ngrams(tokens, n))
