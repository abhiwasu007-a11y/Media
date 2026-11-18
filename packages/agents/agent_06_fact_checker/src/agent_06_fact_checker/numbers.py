"""Number normaliser and guard (blueprint 6.5, 10.3 ``NumberNormaliser`` / ``NumberGuard``).

Numerals of a claim: ASCII and Devanagari digits (normalised to ASCII), decimals, Indian and
Western grouping, percentages (the ``%`` is not matched), and ratios ``a:b`` as one token. Units
and signs are the model's ``UNIT`` discrepancy, not matched here. Numbers written in words are
not converted in v1 (REQUIRES REVIEW, 3B). The guard can only lower a status, never raise one.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_DEVANAGARI = {0x0966 + i: str(i) for i in range(10)}  # U+0966..U+096F
_TOKEN = re.compile(
    r"\d+(?::\d+)+"  # ratio a:b (a:b:c stays one token)
    r"|\d{1,3}(?:,\d{2,3})+(?:\.\d+)?"  # grouped, Western or Indian
    r"|\d+(?:\.\d+)?"
)


@dataclass(frozen=True, slots=True)
class Numeral:
    text: str
    """Canonical text: digits ASCII, no grouping commas."""
    ratio: bool

    @property
    def decimals(self) -> int:
        return len(self.text.split(".", 1)[1]) if "." in self.text else 0

    def value(self) -> Decimal | None:
        if self.ratio:
            return None
        try:
            return Decimal(self.text)
        except InvalidOperation:  # pragma: no cover - the token regex only yields numbers
            return None


def numerals(text: str) -> list[Numeral]:
    """Numerals of ``text`` in order of appearance, duplicates removed."""
    seen: dict[str, Numeral] = {}
    for match in _TOKEN.finditer(text.translate(_DEVANAGARI)):
        raw = match.group(0)
        ratio = ":" in raw
        canon = (
            ":".join(p.lstrip("0") or "0" for p in raw.split(":"))
            if ratio
            else raw.replace(",", "")
        )
        seen.setdefault(canon, Numeral(canon, ratio))
    return list(seen.values())


def _same(claim: Numeral, evidence: Numeral, rounding_match: bool) -> bool:
    if claim.ratio or evidence.ratio:
        return claim.ratio and evidence.ratio and claim.text == evidence.text
    a, b = claim.value(), evidence.value()
    if a is None or b is None:  # pragma: no cover
        return False
    if a == b:
        return True
    if rounding_match and evidence.decimals > claim.decimals:
        return round(b, claim.decimals) == a
    return False


def missing_numerals(
    claim_numerals: Sequence[Numeral], evidence_texts: Iterable[str], rounding_match: bool
) -> list[Numeral]:
    """Claim numerals that occur in none of the supporting evidence windows (P7)."""
    pool = [n for text in evidence_texts for n in numerals(text)]
    return [c for c in claim_numerals if not any(_same(c, e, rounding_match) for e in pool)]
