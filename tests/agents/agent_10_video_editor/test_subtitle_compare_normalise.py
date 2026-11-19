"""P4-21 review: the subtitle-vs-script comparison removes invisible characters only.

Meaning-bearing characters (sign, currency, percent, digits, Devanagari nasalisation) stay exact,
so a real difference between subtitle and script is never scored as identical."""

import pytest

from agent_10_video_editor.inputs import ScriptStrings
from agent_10_video_editor.qc.stage import _word_overlap_permille, _words
from agent_10_video_editor.subtitles import Cue

pytestmark = pytest.mark.unit


def _overlap(script_text: str, cue_text: str) -> int:
    script = ScriptStrings(segments={"s1": script_text})
    return _word_overlap_permille([Cue(1, 0, 1, cue_text)], ["s1"], script)


def test_invisible_characters_case_and_whitespace_are_ignored() -> None:
    assert _words("Buy​ NOW,­ today!") == ["buy", "now,", "today!"]
    assert _words("a\n\t b") == ["a", "b"]
    assert _overlap("one two three", "ONE tw​o  three") == 1000


@pytest.mark.parametrize(
    ("script", "cue"),
    [
        ("profit +5%", "profit -5%"),  # sign
        ("5%", "-5%"),
        ("price ₹500", "price $500"),  # currency
        ("₹5,000", "₹5.000"),  # separator
        ("50% loss", "50 loss"),  # percent
        ("ratio 1:2", "ratio 1/2"),
        ("10² units", "102 units"),  # superscript
        ("हँस", "हंस"),  # chandrabindu vs anusvara
        ("ज़रा", "जरा"),  # nukta
        ("résumé", "resume"),  # diacritics
    ],
)
def test_meaning_bearing_differences_are_not_hidden(script: str, cue: str) -> None:
    assert _overlap(script, cue) < 1000


def test_changed_words_are_still_flagged() -> None:
    assert _overlap("one two three", "one two BUY NOW") == 571
