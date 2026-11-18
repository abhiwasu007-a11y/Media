"""Text patterns shared by the note and plan validators (NT8, PL8): URL, e-mail, referral, quote."""

import re

URL = re.compile(
    r"(?:https?://|www\.)\S+|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:[a-z]{2,24})\b(?:/\S*)?",
    re.IGNORECASE,
)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
REFERRAL = re.compile(
    r"\b(?:referral|promo(?:tion)?\s*code|coupon|use\s+code|with\s+code|discount\s+code|"
    r"sign\s*up\s+(?:with|using|via)|open\s+(?:an\s+)?account\s+(?:with|via|using)|"
    r"affiliate|join\s+my\s+(?:group|channel))\b",
    re.IGNORECASE,
)
QUOTE_MARKS = re.compile('["“”„«»「」]')
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")


def has_url_or_referral(text: str) -> bool:
    return bool(URL.search(text) or EMAIL.search(text) or REFERRAL.search(text))


def has_quote_span(text: str) -> bool:
    return bool(QUOTE_MARKS.search(text))


def numbers_in(text: str) -> set[str]:
    """Numbers as written, normalised only by removing thousands separators and a final percent."""
    out: set[str] = set()
    for raw in NUMBER.findall(text):
        out.add(raw.replace(",", "").rstrip("%"))
    return out
