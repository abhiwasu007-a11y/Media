"""PASS6-N / CCR-273 (PROPOSED): ``rule_packs.non_finance_categories`` config."""

import pytest

from amw_core.config import (
    ALWAYS_FINANCE_CATEGORIES,
    DEFAULT_NON_FINANCE_CATEGORIES,
    DOCUMENTED_RULE_PACK_CATEGORIES,
    RulePackSettings,
    effective_non_finance_categories,
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


@pytest.mark.parametrize(
    "bad",
    ["finance", "advertising", "ad_sector", "brand_safety", "philosophy", "YouTube_General", ""],
)
def test_widening_the_list_is_refused_in_config(bad: str) -> None:
    # the override may only NARROW the packaged list: advertising / ad_sector / brand_safety are
    # documented categories but left out on purpose; finance and unknown values likewise
    with pytest.raises(ValueError, match="only narrow"):
        RulePackSettings(non_finance_categories=frozenset({bad}))
    with pytest.raises(ConfigInvalidError):
        load_settings(environ={"AMW_RULE_PACKS__NON_FINANCE_CATEGORIES": f'["{bad}"]'})
    with pytest.raises(ConfigInvalidError):  # a valid entry next to a widening one is refused too
        load_settings(environ={"AMW_RULE_PACKS__NON_FINANCE_CATEGORIES": f'["kids", "{bad}"]'})


def test_the_packaged_list_never_holds_an_always_finance_category() -> None:
    assert not DEFAULT_NON_FINANCE_CATEGORIES & ALWAYS_FINANCE_CATEGORIES
    assert {"finance", "advertising", "ad_sector", "brand_safety"} == set(ALWAYS_FINANCE_CATEGORIES)
    assert (
        RulePackSettings(non_finance_categories=frozenset()).non_finance_categories == frozenset()
    )


@pytest.mark.parametrize(
    "configured",
    ["finance", "youtube_general", ["youtube_general"], {"youtube_general": 1}, 7, None, b"kids"],
)
def test_effective_set_accepts_only_a_frozenset_or_tuple_of_str(configured: object) -> None:
    # a bare str (substring / iteration attack), list, mapping, bytes, None: no category at all
    assert effective_non_finance_categories(configured) == frozenset()


def test_effective_set_can_never_hold_finance_whatever_the_input() -> None:
    attack = frozenset({"finance", "advertising", "ad_sector", "brand_safety", "kids", 7})
    assert effective_non_finance_categories(attack) == frozenset({"kids"})
    assert effective_non_finance_categories(("finance", "health")) == frozenset({"health"})
    # RulePackSettings built around its validator (model_construct) is still capped
    bypass = RulePackSettings.model_construct(non_finance_categories=frozenset({"finance", "kids"}))
    assert resolve_channel_category("finance", bypass) is ChannelCategory.FINANCE
    assert resolve_channel_category("kids", bypass) is ChannelCategory.NON_FINANCE


def test_owner_can_narrow_the_list_and_the_job_resolver_follows_it() -> None:
    cfg = load_settings(environ={"AMW_RULE_PACKS__NON_FINANCE_CATEGORIES": '["kids"]'})
    assert resolve_channel_category("kids", cfg.rule_packs) is ChannelCategory.NON_FINANCE
    assert resolve_channel_category("youtube_general", cfg.rule_packs) is ChannelCategory.FINANCE


@pytest.mark.parametrize(
    "attack",
    [
        {"finance"},  # a caller-built set that names finance
        frozenset({"finance"}),
        "finance",  # a bare str would substring-match ("xx" in "xxyy")
        "xxyy",
        ["finance"],
        ("finance",),
        {"youtube_general"},  # even a legitimate-looking set is not a RulePackSettings
    ],
)
def test_the_category_set_is_not_a_caller_argument(attack: object) -> None:
    for raw in ("finance", "xx", "youtube_general", "non-finance", "advertising"):
        assert resolve_channel_category(raw, attack) is ChannelCategory.FINANCE  # type: ignore[arg-type]


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
