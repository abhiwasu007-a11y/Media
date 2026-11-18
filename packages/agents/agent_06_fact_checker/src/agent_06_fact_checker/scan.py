"""``CorrectionScanner`` (P10): a suggested correction must not carry a URL, a referral code, a
price or level for a current instrument, or recommendation wording (blueprint 10.4)."""

import re
from collections.abc import Iterable, Mapping, Sequence

from agent_06_fact_checker.lexicon import find_marker, find_patterns, find_urls, norm, term_spans
from agent_06_fact_checker.numbers import numerals

_CURRENCY_LEVEL = re.compile(r"(?:\u20b9|rs\.?|inr)\s?\d[\d,]*(?:\.\d+)?", re.IGNORECASE)


def scan_correction(
    text: str,
    referral_patterns: Sequence[str],
    advice_words: Mapping[str, tuple[str, ...]],
    instrument_names: Iterable[str] = (),
    advice_suffixes: Sequence[str] = (),
) -> list[str]:
    """Finding names (never the text) for a correction that must be dropped."""
    findings: list[str] = []
    hay = norm(text)
    if find_urls(text):
        findings.append("URL")
    if find_patterns(text, referral_patterns):
        findings.append("REFERRAL")
    near_instrument = any(term_spans(hay, n) for n in instrument_names) and bool(numerals(hay))
    if _CURRENCY_LEVEL.search(text) or near_instrument:
        findings.append("PRICE_LEVEL")
    words = [w for ws in advice_words.values() for w in ws]
    if find_marker(text, words, {"latin": tuple(advice_suffixes)}):
        findings.append("ADVICE_WORD")
    return findings
