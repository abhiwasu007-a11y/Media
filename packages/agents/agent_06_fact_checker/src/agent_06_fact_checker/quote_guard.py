"""Claim-level fake-quote guard (D12, CCR-291 item 7, CCR-303 PROPOSED).

A claim that is NOT typed as a quote but carries a quotation, attributes words to a person, or
reports a person's view must never get a model verdict: the model cannot prove a quote (the
library check can). The guard is a pure function of the claim text and CONFIGURATION (D16: the
quotation marks, the span length and every pattern are settings, never literals in the code; the
seeded production lists are data, ``data/quote_guard.seed.json``); it does not depend on whether a
``QuoteCheck`` is configured, so a stage with no check can still refuse to send such a claim to
the model.

A claim is guarded when ``claim.quote`` or ``claim.normalized_claim``

* holds a span in quotation marks (any opening mark followed by any closing mark, see
  ``quote_marks``) of ``quote_guard_min_words`` words or more (``QUOTE_SPAN``), or
* matches one of ``quote_attribution_patterns`` (``ATTRIBUTION``): an attribution WITHOUT
  quotation marks (``X said ...``, ``X wrote that ...`` and the Marathi equivalents), or
* matches one of ``quote_reported_speech_patterns`` (``REPORTED_SPEECH``): a person's view in
  reported speech (``X believed ...``). The library cannot prove reported speech, so it goes
  to HUMAN REVIEW, never to the library check and never to the model.

Matching runs on NFC text with invisible characters removed (a zero-width joiner inside a word must
not defeat a pattern; a zero-width space still separates words). A quotation split across two
neighbouring claims, up to ``quote_split_window_claims`` of them, is joined (``guard_reasons``).

HUMAN-REVIEW list vs QUOTE-CHECK list: ``quote_attribution_patterns`` (a named speaker: said,
wrote, म्हणाला) goes through the exact-quote check; ``quote_reported_speech_patterns`` (a view or
a bare source word: believed, thought, per, नुसार, च्या मते) goes to human review. The bare
``नुसार`` / ``मते`` (``अहवालानुसार``, ``नियमानुसार``) are in the human-review list on purpose:
they name no person, so the library check has nothing to compare."""

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.models import VerificationClaim
from agent_06_fact_checker.quote_marks import seed_data
from amw_core.enums import ClaimType


class GuardReason(StrEnum):
    QUOTE_SPAN = "QUOTE_SPAN"
    ATTRIBUTION = "ATTRIBUTION"
    REPORTED_SPEECH = "REPORTED_SPEECH"


def load_quote_guard_seed() -> dict[str, Any]:
    """The seeded production data as ``FactCheckSettings`` keyword arguments. PROVISIONAL: the
    lists need editor review (REQUIRES REVIEW (Phase 1): Marathi editor / owner) and are not
    complete. The span length (``quote_guard_min_words``) is NOT seeded: the owner sets it."""
    raw = seed_data()
    return {
        "quote_marks": raw["quote_marks"],
        "quote_attribution_patterns": raw["attribution_patterns"],
        "quote_reported_speech_patterns": raw["reported_speech_patterns"],
        "quote_split_window_claims": raw["split_window_claims"],
        "quote_pattern_max_length": raw["pattern_limits"]["max_length"],
        "quote_pattern_max_repeat": raw["pattern_limits"]["max_repeat"],
    }


def _matches(texts: Sequence[str], patterns: Sequence[str], settings: FactCheckSettings) -> bool:
    marks = settings.quote_marks.compiled()
    for text in texts:
        for variant in (marks.strip(text), marks.clean(text)):
            if any(re.search(p, variant, re.IGNORECASE) for p in patterns):
                return True
    return False


def _span_hits(
    texts: Sequence[str], settings: FactCheckSettings, *, unbounded: bool = False
) -> list[tuple[int, int]]:
    """Offsets (marks included) of the spans of ``texts`` that are long enough."""
    marks = settings.quote_marks.compiled()
    return [
        (s.start - 1, s.end + 1)
        for text in texts
        for s in marks.spans(text, unbounded=unbounded)
        if s.words >= settings.quote_guard_min_words
    ]


def _texts(claim: VerificationClaim) -> tuple[str, str]:
    return (claim.quote, claim.normalized_claim)


def _reason(texts: Sequence[str], settings: FactCheckSettings) -> GuardReason | None:
    if _span_hits(texts, settings):
        return GuardReason.QUOTE_SPAN
    if _matches(texts, settings.quote_attribution_patterns, settings):
        return GuardReason.ATTRIBUTION
    if _matches(texts, settings.quote_reported_speech_patterns, settings):
        return GuardReason.REPORTED_SPEECH
    return None


def guard_reason(claim: VerificationClaim, settings: FactCheckSettings) -> GuardReason | None:
    """Why the claim is guarded, or ``None`` (typed quote claims are handled elsewhere)."""
    if claim.claim_type is ClaimType.QUOTED_THIRD_PARTY:
        return None
    return _reason(_texts(claim), settings)


def guard_reasons(
    claims: Sequence[VerificationClaim], settings: FactCheckSettings
) -> Mapping[str, GuardReason]:
    """``local_id`` -> reason for every guarded claim. A quotation split over consecutive claims
    (one opens, a later one closes, up to ``quote_split_window_claims`` claims) is not a span in
    any single claim: the texts of every window of 2 .. N neighbours (none typed as a quote) are
    joined, and the claims that the span touches are guarded (already guarded ones keep their
    reason). A joined window is scanned without the span-length bound (it is longer than one
    claim by construction), so a long split quote is not dropped."""
    out: dict[str, GuardReason] = {}
    for claim in claims:
        reason = guard_reason(claim, settings)
        if reason is not None:
            out[claim.local_id] = reason
    total = len(claims)
    for start in range(total):
        for size in range(2, settings.quote_split_window_claims + 1):
            window = claims[start : start + size]
            if len(window) < size:
                break
            if any(c.claim_type is ClaimType.QUOTED_THIRD_PARTY for c in window):
                break
            for field in range(2):
                parts = [_texts(c)[field] for c in window]
                spans = _span_hits([" ".join(parts)], settings, unbounded=True)
                if not spans:
                    continue
                offset = 0
                for claim, part in zip(window, parts, strict=True):
                    lo, hi = offset, offset + len(part)
                    if any(a < hi and lo < b for a, b in spans):
                        out.setdefault(claim.local_id, GuardReason.QUOTE_SPAN)
                    offset = hi + 1
    return out
