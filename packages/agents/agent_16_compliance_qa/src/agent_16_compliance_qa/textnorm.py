"""The ONE text-normalisation seam of Agent 16 (review B2).

Every lexicon, number and money test of the pre-filter and the uniqueness masked-identity check
runs on ``normalise_for_matching(text)``, and lexicon entries are normalised with the same
function. ``amw_core.text_normalise.normalise_for_matching`` (PR #41) is not on ``origin/main``
yet; when it merges, this function becomes a thin call to it (core_need) and the tests below it
stay as they are.

Defeated evasions (tests: ``test_prefilter_normalisation``):

* invisible / format characters inside words: zero-width space / joiner / non-joiner, word
  joiner, soft hyphen, BOM, bidi controls, variation selectors (Unicode ``Cf``, ``Mn`` variation
  selectors), and controls, private-use and unassigned code points;
* compatibility forms: full-width letters and digits, ligatures, mathematical alphanumerics,
  super- and subscripts (NFKC);
* look-alike letters from Cyrillic, Greek, Armenian and small capitals mapped to Latin
  (``_CONFUSABLES``) and combining diacritics stacked on Latin letters;
* Devanagari: nukta dropped (क़ -> क), chandrabindu folded to anusvara, any decimal digit
  (Devanagari and others) mapped to ASCII;
* whitespace runs collapsed to one space; ``casefold``.

PROVISIONAL, REQUIRES REVIEW (Phase 1): the confusables table (a linguist / the owner confirms
it). Known limit: a real Cyrillic / Greek word made only of table letters folds to Latin; for the
pre-filter that only adds judge work (it never clears an item).
"""

import unicodedata
from typing import Final

_CONFUSABLES: Final[dict[str, str]] = {
    # Cyrillic, Greek, Armenian, Latin small capitals and dotless letters -> Latin (escaped:
    # the source holds no look-alike character itself)
    "\u0430": "a", "\u0432": "b", "\u0435": "e", "\u0451": "e", "\u043a": "k", "\u043c": "m",
    "\u043d": "h", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0442": "t", "\u0443": "y",
    "\u0445": "x", "\u0455": "s", "\u0456": "i", "\u0457": "i", "\u0458": "j", "\u0501": "d",
    "\u051b": "q", "\u051d": "w", "\u04bb": "h", "\u04cf": "l", "\u044c": "b", "\u0410": "a",
    "\u0412": "b", "\u0415": "e", "\u041a": "k", "\u041c": "m", "\u041d": "h", "\u041e": "o",
    "\u0420": "p", "\u0421": "c", "\u0422": "t", "\u0423": "y", "\u0425": "x", "\u0405": "s",
    "\u0406": "i", "\u0408": "j", "\u03b1": "a", "\u03b2": "b", "\u03b5": "e", "\u03b7": "n",
    "\u03b9": "i", "\u03ba": "k", "\u03bd": "v", "\u03bf": "o", "\u03c1": "p", "\u03c4": "t",
    "\u03c5": "u", "\u03c7": "x", "\u03c9": "w", "\u0391": "a", "\u0392": "b", "\u0395": "e",
    "\u0396": "z", "\u0397": "h", "\u0399": "i", "\u039a": "k", "\u039c": "m", "\u039d": "n",
    "\u039f": "o", "\u03a1": "p", "\u03a4": "t", "\u03a5": "y", "\u03a7": "x", "\u0561": "w",
    "\u0563": "q", "\u0566": "q", "\u0570": "h", "\u0578": "n", "\u057d": "u", "\u0581": "g",
    "\u0585": "o", "\u0584": "p", "\u0555": "o", "\u054d": "u", "\u0299": "b", "\u0262": "g",
    "\u029c": "h", "\u026a": "i", "\u029f": "l", "\u0274": "n", "\u0280": "r", "\u028f": "y",
    "\u1d00": "a", "\u1d04": "c", "\u1d05": "d", "\u1d07": "e", "\u1d0a": "j", "\u1d0b": "k",
    "\u1d0d": "m", "\u1d0f": "o", "\u1d18": "p", "\u1d1b": "t", "\u1d1c": "u", "\u1d20": "v",
    "\u1d21": "w", "\u1d22": "z", "\u0131": "i", "\u0237": "j", "\u0251": "a", "\u0261": "g",
}  # fmt: skip
_DROP_CATEGORIES: Final = frozenset({"Cf", "Cc", "Co", "Cn", "Cs"})
_NUKTA: Final = "़"
_CHANDRABINDU: Final = "ँ"
_ANUSVARA: Final = "ं"
_TATWEEL: Final = "ـ"


def _devanagari(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ" or "꣠" <= ch <= "ꣿ"


def _drop(ch: str) -> bool:
    if ch in (_NUKTA, _TATWEEL) or "︀" <= ch <= "️":
        return True
    return unicodedata.category(ch) in _DROP_CATEGORIES and not ch.isspace()


_MAX_PASSES: Final = 4


def normalise_for_matching(text: str) -> str:
    """Folded text for every compliance match (see the module docstring); idempotent: NFC and
    casefold can create characters that fold again, so the pass reruns until stable."""
    current = text
    for _ in range(_MAX_PASSES):
        folded = _one_pass(current)
        if folded == current:
            return folded
        current = folded
    return current


def _one_pass(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    out: list[str] = []
    base_is_devanagari = False
    space = False
    for ch in decomposed:
        if ch.isspace():
            space = bool(out)
            continue
        if _drop(ch):
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("M"):
            if not base_is_devanagari:
                continue  # combining diacritic stacked on a non-Devanagari letter
            out.append(_ANUSVARA if ch == _CHANDRABINDU else ch)
            continue
        if space:
            out.append(" ")
            space = False
        if cat == "Nd":
            out.append(str(unicodedata.digit(ch)))
            base_is_devanagari = False
            continue
        base_is_devanagari = _devanagari(ch)
        out.append(_CONFUSABLES.get(ch, ch))
    return unicodedata.normalize("NFC", "".join(out)).casefold()
