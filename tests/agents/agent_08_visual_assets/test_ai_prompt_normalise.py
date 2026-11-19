"""CCR-105 / P4-21: the AI-prompt lexicon guard matches through ``amw_core.text_normalise``."""

# ruff: noqa: RUF001  -- look-alike letters are the test data of this module.

import pytest

from agent_08_visual_assets.sources.ai_prompt import (
    AiPromptComposer,
    Lexicon,
    PromptRejection,
)

pytestmark = pytest.mark.unit

LEX = Lexicon("lx", presenter_terms=["news anchor"], market_data_terms=["stock chart"])


def _compose(description: str, category: str = "finance") -> PromptRejection | None:
    return AiPromptComposer.compose(
        description=description,
        channel_category=category,
        style="flat",
        max_chars=200,
        needs_real_person=False,
        lexicon=LEX,
    ).rejection


@pytest.mark.parametrize(
    "description",
    [
        "a news anchor at a desk",
        "a NEWS   Anchor at a desk",
        "a news anc​hor at a desk",  # zero-width space inside a word
        "a newѕ anchor at a desk",  # Cyrillic s
        "a ｎews anchor at a desk",  # fullwidth n
    ],
)
def test_presenter_term_is_found_through_unicode_evasions(description: str) -> None:
    assert _compose(description) is PromptRejection.PRESENTER_OR_REAL_PERSON


def test_market_data_term_and_whole_word_boundary() -> None:
    assert _compose("a stock c­hart on a wall") is PromptRejection.MARKET_DATA_VISUAL
    assert _compose("a stock chartreuse wall") is None  # whole words only
    assert _compose("a news anchor at a desk", category="education") is None
