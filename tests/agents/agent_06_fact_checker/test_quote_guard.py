"""Claim-level fake-quote guard (QUOTE-GUARD-2, CCR-303 PROPOSED): pure function of the claim text
and configuration. SYNTHETIC text only."""

from typing import Any

import pytest

from agent_06_fact_checker.models import VerificationClaim
from agent_06_fact_checker.quote_guard import GuardReason, guard_reason
from amw_core.errors import ConfigInvalidError
from tests.agents.agent_06_fact_checker.support import make_settings
from tests.agents.agent_06_fact_checker.test_verification_step import claim

pytestmark = pytest.mark.unit

SIX = "one two three four five six"
MR_SIX = "वेळ कमी नसतो तो वापरण्याची इच्छा"  # INVENTED, six words


def vc(**over: Any) -> VerificationClaim:
    return VerificationClaim.model_validate(claim(1, **{"claim_type": "FACTUAL", **over}))


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({}, None),
        ({"quote": f'A "{SIX}" B'}, GuardReason.QUOTE_SPAN),
        ({"quote": f"A “{SIX}” B"}, GuardReason.QUOTE_SPAN),
        ({"quote": f"A «{SIX}» B"}, GuardReason.QUOTE_SPAN),
        ({"quote": f'टेस्टर "{MR_SIX}"'}, GuardReason.QUOTE_SPAN),
        ({"normalized_claim": f'He called it "{SIX}".'}, GuardReason.QUOTE_SPAN),
        ({"quote": 'The "stoic" school'}, None),  # below the configured length
        ({"quote": "X said time is short"}, GuardReason.ATTRIBUTION),
        ({"quote": "X WROTE that time is short"}, GuardReason.ATTRIBUTION),
        ({"normalized_claim": "X stated a view."}, GuardReason.ATTRIBUTION),
        ({"quote": "टेस्टर म्हणाले वेळ कमी आहे"}, GuardReason.ATTRIBUTION),
        ({"quote": "टेस्टर यांनी लिहिले की वेळ कमी आहे"}, GuardReason.ATTRIBUTION),
        ({"quote": "the word saidless is not a pattern hit"}, None),
        ({"claim_type": "QUOTED_THIRD_PARTY", "quote": f'A "{SIX}"'}, None),  # typed elsewhere
    ],
)
def test_guard_reason(over: dict[str, Any], expected: GuardReason | None) -> None:
    assert guard_reason(vc(**over), make_settings()) is expected


def test_guard_follows_the_configuration_not_literals() -> None:
    c = vc(quote="X said time is short")
    assert guard_reason(c, make_settings(quote_attribution_patterns=[r"\bsaid\b"])) is not None
    assert guard_reason(c, make_settings(quote_attribution_patterns=[r"\bwrote\b"])) is None
    spans = vc(quote=f'A "{SIX}"')
    assert guard_reason(spans, make_settings(quote_guard_min_words=7)) is None
    assert guard_reason(spans, make_settings(quote_guard_min_words=6)) is GuardReason.QUOTE_SPAN


@pytest.mark.parametrize(
    "over",
    [
        {"quote_attribution_patterns": []},  # empty would switch the guard off silently
        {"quote_attribution_patterns": ["(unclosed"]},
        {"quote_guard_min_words": 0},
    ],
)
def test_guard_configuration_is_validated(over: dict[str, Any]) -> None:
    with pytest.raises((ConfigInvalidError, ValueError)):
        make_settings(**over)
