"""PASS6-N / CCR-273 (PROPOSED): ``rule_packs.non_finance_categories`` config."""

import pytest

from amw_core.config import (
    DEFAULT_NON_FINANCE_CATEGORIES,
    DOCUMENTED_RULE_PACK_CATEGORIES,
    RulePackSettings,
    load_settings,
)
from amw_core.errors import ConfigInvalidError
from amw_orchestrator.executor import ChannelCategory, resolve_channel_category

pytestmark = pytest.mark.unit


def test_default_is_documented_non_finance_channel_categories_only() -> None:
    assert load_settings(environ={}).rule_packs.non_finance_categories == (
        DEFAULT_NON_FINANCE_CATEGORIES
    )
    assert {"youtube_general", "health", "kids", "political_news"} == set(
        DEFAULT_NON_FINANCE_CATEGORIES
    )
    assert "finance" not in DEFAULT_NON_FINANCE_CATEGORIES
    assert DEFAULT_NON_FINANCE_CATEGORIES < DOCUMENTED_RULE_PACK_CATEGORIES


@pytest.mark.parametrize("bad", ["finance", "philosophy", "YouTube_General", ""])
def test_finance_or_undocumented_category_is_refused_in_config(bad: str) -> None:
    with pytest.raises(ValueError, match="documented non-finance"):
        RulePackSettings(non_finance_categories=frozenset({bad}))
    with pytest.raises(ConfigInvalidError):
        load_settings(environ={"AMW_RULE_PACKS__NON_FINANCE_CATEGORIES": f'["{bad}"]'})


def test_owner_can_narrow_the_list_and_the_job_resolver_follows_it() -> None:
    cfg = load_settings(environ={"AMW_RULE_PACKS__NON_FINANCE_CATEGORIES": '["kids"]'})
    allowed = cfg.rule_packs.non_finance_categories
    assert resolve_channel_category("kids", allowed) is ChannelCategory.NON_FINANCE
    assert resolve_channel_category("youtube_general", allowed) is ChannelCategory.FINANCE


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("youtube_general", ChannelCategory.NON_FINANCE),  # the philosophy channel (sample #1)
        ("health", ChannelCategory.NON_FINANCE),
        ("kids", ChannelCategory.NON_FINANCE),
        ("political_news", ChannelCategory.NON_FINANCE),
        ("finance", ChannelCategory.FINANCE),
        ("advertising", ChannelCategory.FINANCE),
        ("ad_sector", ChannelCategory.FINANCE),
        ("brand_safety", ChannelCategory.FINANCE),
        ("YouTube_General", ChannelCategory.FINANCE),  # exact match only
        ("philosophy", ChannelCategory.FINANCE),
        (None, ChannelCategory.FINANCE),
        ("", ChannelCategory.FINANCE),
    ],
)
def test_job_category_from_documented_channel_categories(
    raw: str | None, expected: ChannelCategory
) -> None:
    assert resolve_channel_category(raw) is expected
