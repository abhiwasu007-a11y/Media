# ruff: noqa: RUF001
"""Claim-level fake-quote guard (QUOTE-GUARD-2, CCR-303 PROPOSED): pure function of the claim text
and configuration. SYNTHETIC text only."""

import time
import unicodedata
from typing import Any

import pytest

from agent_06_fact_checker.models import VerificationClaim
from agent_06_fact_checker.pattern_safety import validate_pattern
from agent_06_fact_checker.quote_guard import GuardReason, guard_reason, guard_reasons
from agent_06_fact_checker.quote_marks import QuoteMarkConfig, default_quote_marks, seed_data
from amw_core.errors import ConfigInvalidError
from tests.agents.agent_06_fact_checker.support import QUOTE_GUARD_SEED, make_settings
from tests.agents.agent_06_fact_checker.test_verification_step import claim

pytestmark = pytest.mark.unit

SIX = "one two three four five six"
MR_SIX = "वेळ कमी नसतो तो वापरण्याची इच्छा"  # INVENTED, six words
PAIRS = [tuple(p) for p in seed_data()["quote_marks"]["pairs"]]


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
        ({"quote": f"टेस्टर ‘{MR_SIX}’"}, GuardReason.QUOTE_SPAN),  # Marathi single
        ({"normalized_claim": f'He called it "{SIX}".'}, GuardReason.QUOTE_SPAN),
        ({"quote": 'The "stoic" school'}, None),  # below the configured length
        ({"quote": "Seneca’s view and the world’s end, said nobody"}, GuardReason.ATTRIBUTION),
        ({"quote": "Seneca’s view and the world’s end and more words here now"}, None),
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


@pytest.mark.parametrize(
    "text",
    [  # every attribution form of the seeded production list
        "म्हणाला",
        "म्हणाली",
        "म्हणाले",
        "तो म्हणतो",
        "ती म्हणते",
        "ते म्हणतात",
        "असे म्हणे",
        "त्याने म्हटले",
        "तो म्हटला",
        "ती म्हटली",
        "तो म्हटलं",
        "यांनी म्हटले",
        "यांच्या मते",
        "सेनेकाच्या  मते",
        "असे म्हणतात",
        "त्याने लिहिले",
        "तो लिहितो",
        "ती लिहिते",
        "त्याने सांगितले",
        "सेनेकानुसार",
        "अहवालानुसार",
        "Seneca said",
        "he says",
        "she wrote",
        "he writes",
        "according to Seneca",
        "According   to him",
        "in the words of Seneca",
        "as Seneca put it",
        "as the old Stoic put it",
        "as one wise Roman put it",
    ],
)
def test_seeded_attribution_patterns(text: str) -> None:
    assert guard_reason(vc(quote=text), make_settings()) is GuardReason.ATTRIBUTION


@pytest.mark.parametrize(
    "text",
    [
        "Seneca believed time is short",
        "He believes it",
        "Cicero argued the point",
        "She argues that",
        "They claimed it",
        "He claims so",
        "सेनेका मानतो",
        "ते मानतात",
        "सेनेकाने असे मानले",
        "तो मानत होता",
    ],
)
def test_seeded_reported_speech_patterns_route_to_human_review(text: str) -> None:
    assert guard_reason(vc(quote=text), make_settings()) is GuardReason.REPORTED_SPEECH


def test_a_span_or_attribution_wins_over_reported_speech() -> None:
    both = vc(quote=f'He argued and said "{SIX}"')
    assert guard_reason(both, make_settings()) is GuardReason.QUOTE_SPAN
    assert (
        guard_reason(vc(quote="He argued and said it"), make_settings()) is GuardReason.ATTRIBUTION
    )


@pytest.mark.parametrize(("opening", "closing"), PAIRS)
def test_every_configured_mark_pair_makes_a_span(opening: str, closing: str) -> None:
    text = f"A {opening}{SIX}{closing} B"
    assert guard_reason(vc(quote=text), make_settings()) is GuardReason.QUOTE_SPAN
    short = f"A {opening}one two{closing} B"
    assert guard_reason(vc(quote=short), make_settings()) is None


@pytest.mark.parametrize(
    "text",
    ["»{}«", "„{}“", "「{}」", "‘{}’", "‹{}›", "＂{}＂", '"{}”', '«{}"', "“{}’", "„{}”"],
)
def test_the_marks_the_first_review_measured_as_unguarded(text: str) -> None:
    assert guard_reason(vc(quote=text.format(SIX)), make_settings()) is GuardReason.QUOTE_SPAN


def test_every_unicode_initial_and_final_quote_mark_is_covered_by_the_configuration() -> None:
    marks = default_quote_marks()
    for cp in range(0x110000):
        ch = chr(cp)
        cat = unicodedata.category(ch)
        if cat == "Pi":
            assert marks.is_opener(ch), hex(cp)
        if cat == "Pf":
            assert marks.is_closer(ch), hex(cp)


def test_unicode_categories_catch_a_mark_the_pair_table_forgot() -> None:
    cfg = QuoteMarkConfig(
        pairs=(('"', '"'),),
        opening_categories=("Pi",),
        closing_categories=("Pf",),
        invisible_separators=("​",),
    )
    marks = cfg.compiled()
    assert [s.words for s in marks.spans("x ⸂a b c⸃ y")] == [3]
    assert marks.spans("it’s and the world’s end") == []  # a closing mark never opens
    assert marks.spans('one "unclosed quote here') == []
    assert marks.spans('"a\nb"') == []  # a span never crosses a line break


def test_mark_configuration_is_validated() -> None:
    base: dict[str, Any] = {
        "pairs": (('"', '"'),),
        "opening_categories": ("Pi",),
        "closing_categories": ("Pf",),
        "invisible_separators": ("​",),
    }
    for bad in (
        {"pairs": (("a", "b"),)},  # letters are no marks
        {"pairs": (("((", "))"),)},
        {"pairs": ()},
        {"opening_categories": ("Lu",)},
        {"invisible_separators": ("a",)},
    ):
        with pytest.raises((ConfigInvalidError, ValueError)):
            QuoteMarkConfig(**{**base, **bad})


def test_invisible_characters_cannot_hide_a_word_boundary_or_split_a_word() -> None:
    zwsp, zwj, zwnj, shy = "​", "‍", "‌", "­"
    joined = zwsp.join(SIX.split())  # six words joined by zero-width spaces
    assert guard_reason(vc(quote=f'A "{joined}" B'), make_settings()) is GuardReason.QUOTE_SPAN
    assert guard_reason(vc(quote=f'A "{joined[:20]}"'), make_settings()) is None
    for hidden in (zwj, zwnj, shy, zwsp):  # an attribution word with an invisible character
        assert (
            guard_reason(vc(quote=f"टेस्टर म्ह{hidden}णाला"), make_settings())
            is GuardReason.ATTRIBUTION
        )
        assert (
            guard_reason(vc(quote=f"X sa{hidden}id it"), make_settings()) is GuardReason.ATTRIBUTION
        )
    decomposed = unicodedata.normalize("NFD", "café said")
    assert guard_reason(vc(quote=decomposed), make_settings()) is GuardReason.ATTRIBUTION


def test_guard_follows_the_configuration_not_literals() -> None:
    c = vc(quote="X said time is short")
    assert guard_reason(c, make_settings(quote_attribution_patterns=[r"\bsaid\b"])) is not None
    assert guard_reason(c, make_settings(quote_attribution_patterns=[r"\bwrote\b"])) is None
    spans = vc(quote=f'A "{SIX}"')
    assert guard_reason(spans, make_settings(quote_guard_min_words=7)) is None
    assert guard_reason(spans, make_settings(quote_guard_min_words=6)) is GuardReason.QUOTE_SPAN
    rep = vc(quote="He argued it")
    assert guard_reason(rep, make_settings(quote_reported_speech_patterns=[r"\bhinted\b"])) is None


def test_a_quote_split_across_two_neighbouring_claims_is_guarded_in_both() -> None:
    first = vc(quote="He added “one two three")
    second = VerificationClaim.model_validate(
        claim(2, claim_type="FACTUAL", quote="four five six seven” and left")
    )
    s = make_settings()
    assert guard_reason(first, s) is None
    assert guard_reason(second, s) is None
    reasons = guard_reasons([first, second], s)
    assert reasons == {
        first.local_id: GuardReason.QUOTE_SPAN,
        second.local_id: GuardReason.QUOTE_SPAN,
    }
    far = VerificationClaim.model_validate(claim(3, claim_type="FACTUAL"))
    assert guard_reasons([first, far, second], s) == {}  # not neighbours: listed as open


@pytest.mark.parametrize(
    "over",
    [
        {"quote_attribution_patterns": []},  # empty would switch the guard off silently
        {"quote_reported_speech_patterns": []},
        {"quote_attribution_patterns": ["(unclosed"]},
        {"quote_reported_speech_patterns": ["(unclosed"]},
        {"quote_attribution_patterns": ["(a+)+$"]},
        {"quote_guard_min_words": 0},
        {"quote_pattern_max_length": 0},
    ],
)
def test_guard_configuration_is_validated(over: dict[str, Any]) -> None:
    with pytest.raises((ConfigInvalidError, ValueError)):
        make_settings(**over)


@pytest.mark.parametrize(
    "pattern",
    [
        "(a+)+$",
        "(a*)*",
        "(?:a|a)*b",
        "(?:a+){2,}",
        "(?:ab|cd)+",
        r"(a)\1",
        "a{1,500}",
        "(?:(?:ab)+c)+",
        "x" * 201,
    ],
)
def test_unsafe_patterns_are_rejected_at_load_time(pattern: str) -> None:
    with pytest.raises(ConfigInvalidError):
        validate_pattern(pattern, max_length=200, max_repeat=20)


@pytest.mark.parametrize(
    "pattern", [r"\bsaid\b", r"\s+\S+(?:\s+\S+)?", r"(?:a|b)", r"a{1,20}", "म्हणा(?:ला|ली)"]
)
def test_safe_patterns_are_accepted(pattern: str) -> None:
    validate_pattern(pattern, max_length=200, max_repeat=20)


def test_the_seeded_lists_pass_the_safety_check_and_run_fast_on_hostile_input() -> None:
    lim = (
        QUOTE_GUARD_SEED["quote_pattern_max_length"],
        QUOTE_GUARD_SEED["quote_pattern_max_repeat"],
    )
    patterns = (
        *QUOTE_GUARD_SEED["quote_attribution_patterns"],
        *QUOTE_GUARD_SEED["quote_reported_speech_patterns"],
    )
    assert len(patterns) >= 15
    for pattern in patterns:
        validate_pattern(pattern, max_length=lim[0], max_repeat=lim[1])
    hostile = vc(quote=("as a " * 400)[:2000], normalized_claim="aaaa " * 190)
    started = time.monotonic()
    guard_reason(hostile, make_settings())
    assert time.monotonic() - started < 5


def test_the_seed_file_states_that_it_needs_editor_review() -> None:
    assert "REQUIRES REVIEW" in seed_data()["status"]
    assert "NOT complete" in seed_data()["status"]
