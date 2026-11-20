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
neighbouring claims is joined (``guard_reasons``)."""

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from itertools import pairwise
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


def _has_span(texts: Sequence[str], settings: FactCheckSettings) -> bool:
    marks = settings.quote_marks.compiled()
    return any(
        s.words >= settings.quote_guard_min_words for text in texts for s in marks.spans(text)
    )


def _texts(claim: VerificationClaim) -> tuple[str, str]:
    return (claim.quote, claim.normalized_claim)


def _reason(texts: Sequence[str], settings: FactCheckSettings) -> GuardReason | None:
    if _has_span(texts, settings):
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
    """``local_id`` -> reason for every guarded claim. A quotation split across two neighbouring
    claims (one opens, the next closes) is not a span in either: the texts of two neighbours that
    are both unguarded are joined, and when the join holds a span both are guarded."""
    out: dict[str, GuardReason] = {}
    for claim in claims:
        reason = guard_reason(claim, settings)
        if reason is not None:
            out[claim.local_id] = reason
    for left, right in pairwise(claims):
        if (
            left.local_id in out
            or right.local_id in out
            or ClaimType.QUOTED_THIRD_PARTY in (left.claim_type, right.claim_type)
        ):
            continue
        joined = [f"{a} {b}" for a, b in zip(_texts(left), _texts(right), strict=True)]
        if _has_span(joined, settings):
            out[left.local_id] = out[right.local_id] = GuardReason.QUOTE_SPAN
    return out
