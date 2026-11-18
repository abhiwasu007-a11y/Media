"""CCR-105 / P4-21: the subtitle-vs-script comparison uses ``amw_core.text_normalise``."""

# ruff: noqa: RUF001  -- look-alike letters are the test data of this module.

import pytest

from agent_10_video_editor.inputs import ScriptStrings
from agent_10_video_editor.qc.stage import _word_overlap_permille, _words
from agent_10_video_editor.subtitles import Cue

pytestmark = pytest.mark.unit


def test_invisible_and_case_variants_are_the_same_words() -> None:
    assert _words("Buy​ NOW, today!") == ["buy", "now", "today"]
    assert _words("शेअर मार्केट") == ["शेअर", "मार्केट"]


def test_overlap_is_stable_under_unicode_noise_and_still_flags_changed_words() -> None:
    script = ScriptStrings(segments={"s1": "one two three"})
    same = [Cue(1, 0, 1, "ONE tw​o thrеe")]  # zero-width space, Cyrillic e
    assert _word_overlap_permille(same, ["s1"], script) == 1000
    tampered = [Cue(1, 0, 1, "one two BUY NOW")]
    assert _word_overlap_permille(tampered, ["s1"], script) == 571
