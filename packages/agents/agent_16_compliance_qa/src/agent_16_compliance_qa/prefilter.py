"""PreFilter (C2, F-10; blueprint section 6.2): selects judge candidates. It only **adds** work:
an item without any signal is not sent to the judge, and deterministic rules still apply to it.
Lexicons are versioned config (``compliance.prefilter.lexicon.<lang>``); their Marathi / Hindi
completeness is REQUIRES REVIEW (Phase 1) (owner confirmation, OI-6). Also QuoteVerifier (F-12).
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Final

from agent_16_compliance_qa.config import Lexicon
from agent_16_compliance_qa.judge.models import ItemClaim
from amw_core.text_normalise import normalise_for_matching

_CLAIM_RULES: Final[Mapping[str, tuple[str, ...]]] = {
    "RECOMMENDATION": ("FIN-R1",),
    "FORWARD_VIEW": ("FIN-R3", "FIN-R13"),
    "PRICE_LEVEL": ("FIN-R2",),
    "PERFORMANCE_CLAIM": ("FIN-R6",),
    "HYPOTHETICAL_EXAMPLE": ("FIN-R6",),  # CCR-109 (13 FIN-R6: result display of a hypothetical)
    "TESTIMONIAL": ("FIN-R7",),
    "PROMOTION": ("FIN-R8",),
}
_NUMBER = re.compile(r"[0-9]")
_MONEY_OR_PCT = re.compile(
    r"[0-9]\s*%|%\s*[0-9]|₹|\$|\brs\.?\s*[0-9]|[0-9]+\s*(?:lakh|crore|लाख|कोटी|करोड)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://|www\.|\?ref=|utm_", re.IGNORECASE)


def _norm(text: str) -> str:
    """The shared matching core (``amw_core.text_normalise``, CCR-105): every lexicon, number
    and money test runs on its output and lexicon entries are normalised with the same
    function (review B2). Its digit fold maps every decimal digit to ASCII, so the number and
    money patterns see ASCII digits only."""
    return normalise_for_matching(text).text


_SPLIT_RUN = re.compile(r"(?<![^\W\d_])[^\W\d_](?:[-._*·•/\s][^\W\d_]){2,}(?![^\W\d_])")
"""Three or more single letters, each separated by ONE separator (``b-u-y``, ``b.u.y``,
``b u y``): a word split to dodge the lexicon (re-review m1)."""
_SEPARATOR = re.compile(r"[-._*·•/\s]")


def collapse_split_words(text: str) -> str:
    """Joins separator-split letter runs back into a word for the lexicon match only (a signal
    for the pre-filter, not a fold of the text: the judge still reads the original item).
    Ordinary text has no run of three single letters, so it is unchanged (tested)."""
    return _SPLIT_RUN.sub(lambda m: _SEPARATOR.sub("", m.group(0)), text)


def contains_any(text: str, words: Iterable[str]) -> bool:
    """Whole-word match for single ASCII words, substring match for phrases and other scripts;
    also on the text with separator-split words joined (``b-u-y`` matches ``buy``)."""
    plain = _norm(text)
    joined = collapse_split_words(plain)
    hays = (plain,) if joined == plain else (plain, joined)
    for w in words:
        needle = _norm(w)
        if not needle:
            continue
        for hay in hays:
            if needle.isascii() and " " not in needle:
                if re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", hay):
                    return True
            elif needle in hay:
                return True
    return False


def future_marker(text: str, lexicon: Lexicon) -> bool:
    return contains_any(text, lexicon.future_markers)


def select_rules(
    text: str,
    named_instruments: Iterable[str],
    claims: Iterable[ItemClaim],
    lexicon: Lexicon,
    active_rules: frozenset[str],
) -> tuple[str, ...]:
    """Rule IDs (sorted) the item must be judged against; empty = not a judge candidate."""
    instruments = [n for n in named_instruments if n]
    text = _norm(text)
    rules: set[str] = set()
    for c in claims:
        rules.update(c.rule_flags)
        rules.update(_CLAIM_RULES.get(c.claim_type, ()))
    if instruments:
        rules.add("FIN-R13")  # every segment that names an instrument (13 section 5.13 S7)
        if future_marker(text, lexicon):
            rules.update(("FIN-R3", "FIN-R13"))
    if contains_any(text, lexicon.imperative_verbs):
        rules.add("FIN-R1")
    if _NUMBER.search(text) and (instruments or contains_any(text, lexicon.level_words)):
        rules.add("FIN-R2")
    if _MONEY_OR_PCT.search(text) and contains_any(text, lexicon.person_markers):
        rules.update(("FIN-R6", "FIN-R7"))
    if _URL.search(text) or contains_any(text, lexicon.promotion_words):
        rules.update(("FIN-R5", "FIN-R8"))
    if contains_any(text, lexicon.group_words):
        rules.add("FIN-R5")
    if contains_any(text, lexicon.identity_markers):
        rules.add("YTG-R2")
    if contains_any(text, lexicon.child_markers):
        rules.add("YTG-R7")
    return tuple(sorted(rules & active_rules))


def quote_verified(quote: str | None, text: str) -> bool:
    """D-3 / F-12: exact substring after NFC normalisation only."""
    if not quote:
        return False
    return unicodedata.normalize("NFC", quote) in unicodedata.normalize("NFC", text)
