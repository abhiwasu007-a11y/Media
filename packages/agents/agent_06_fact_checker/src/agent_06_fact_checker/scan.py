"""``CorrectionScanner`` (P10): a suggested correction must not carry a URL, a referral code, a
price or level for a current instrument, or recommendation wording (blueprint 10.4)."""

import re
from collections.abc import Mapping, Sequence

from agent_06_fact_checker.lexicon import find_marker, find_patterns, find_urls

_LEVEL = re.compile(r"(?:₹|rs\.?|inr)\s?\d[\d,]*(?:\.\d+)?", re.IGNORECASE)  # currency-marked price


def scan_correction(
    text: str,
    referral_patterns: Sequence[str],
    advice_words: Mapping[str, tuple[str, ...]],
) -> list[str]:
    """Finding names (never the text) for a correction that must be dropped."""
    findings: list[str] = []
    if find_urls(text):
        findings.append("URL")
    if find_patterns(text, referral_patterns):
        findings.append("REFERRAL")
    if _LEVEL.search(text):
        findings.append("PRICE_LEVEL")
    words = [w for ws in advice_words.values() for w in ws]
    if find_marker(text, words):
        findings.append("ADVICE_WORD")
    return findings
