"""Claim-level fake-quote guard (D12, CCR-291 item 7, CCR-303 PROPOSED).

A claim that is NOT typed as a quote but carries a quotation or attributes words to a person
must never get a model verdict: the model cannot prove a quote (the library check can). The guard
is a pure function of the claim text and CONFIGURATION (D16: the span length and the attribution
patterns are settings, never literals); it does not depend on whether a ``QuoteCheck`` is
configured, so a stage with no check can still refuse to send such a claim to the model.

A claim is guarded when ``claim.quote`` or ``claim.normalized_claim``

* holds a span in quotation marks of ``quote_guard_min_words`` words or more
  (``QUOTE_SPAN``), or
* matches one of ``quote_attribution_patterns`` (``ATTRIBUTION``): an attribution WITHOUT
  quotation marks (``X said ...``, ``X wrote that ...`` and the Marathi equivalents).

A guarded claim is routed to the quote check; what the check cannot prove ends in human review
(never the model)."""

from enum import StrEnum

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.lexicon import find_patterns
from agent_06_fact_checker.library.quotes import find_quoted_spans, normalise_quote_text
from agent_06_fact_checker.models import VerificationClaim
from amw_core.enums import ClaimType


class GuardReason(StrEnum):
    QUOTE_SPAN = "QUOTE_SPAN"
    ATTRIBUTION = "ATTRIBUTION"


def guard_reason(claim: VerificationClaim, settings: FactCheckSettings) -> GuardReason | None:
    """Why the claim is guarded, or ``None`` (typed quote claims are handled elsewhere)."""
    if claim.claim_type is ClaimType.QUOTED_THIRD_PARTY:
        return None
    texts = (claim.quote, claim.normalized_claim)
    for text in texts:
        if any(s.words >= settings.quote_guard_min_words for s in find_quoted_spans(text)):
            return GuardReason.QUOTE_SPAN
    for text in texts:
        if find_patterns(normalise_quote_text(text), settings.quote_attribution_patterns):
            return GuardReason.ATTRIBUTION
    return None
