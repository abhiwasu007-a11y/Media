"""CCR-105 / P4-16: Agent 11 matches through ``amw_core.text_normalise``, not a local seam."""

# ruff: noqa: RUF001  -- look-alike letters are the test data of this module.

import pytest

from agent_11_thumbnail_design.fallback import _tokens
from agent_11_thumbnail_design.scanner import InjectionScanner
from agent_11_thumbnail_design.text_options import finance_text_hit
from agent_11_thumbnail_design.textutil import fold, folded_words, normalise
from amw_core.text_normalise import normalise_for_matching

pytestmark = pytest.mark.unit

EVASIONS = [
    "guar​anteed returns",  # zero-width space inside a word
    "guar­anteed returns",  # soft hyphen
    "guаranteed returns",  # Cyrillic a
    "ｇuaranteed returns",  # fullwidth g
    "GUARANTEED   Returns",  # case and whitespace
]


@pytest.mark.parametrize("text", EVASIONS)
def test_finance_lexicon_hit_survives_unicode_evasion(text: str) -> None:
    assert finance_text_hit(text, ["guaranteed returns"])


def test_fold_is_the_core_matching_form_and_normalise_keeps_display_text() -> None:
    sample = "Gu​aranteed  अंक"
    assert fold(sample) == normalise_for_matching(sample).text
    assert normalise("Café  X") == "Café X"  # display form: NFC, case kept


def test_devanagari_words_are_not_split_inside_an_akshara() -> None:
    assert folded_words("शेअर मार्केट!") == ["शेअर", "मार्केट"]
    assert _tokens("शेअर, मार्केट") == {"शेअर", "मार्केट"}
    assert folded_words("") == []


def test_injection_scanner_needles_match_through_the_core_folds() -> None:
    scanner = InjectionScanner(["ignore previous"], ["system prompt"])
    assert scanner.scan("please IGN​ORE previous things").flagged
    assert scanner.scan("systеm prompt").flagged  # Cyrillic e
    assert not scanner.scan("a harmless label").flagged
