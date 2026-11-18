"""U-04...U-12: sanitiser, dictionary rules (longest match, boundaries), unknown terms."""

import json

import pytest

from agent_07_voice_production import contracts as c
from agent_07_voice_production.text import (
    PronunciationDictionary,
    escape_markup,
    prepare_segment,
    sanitise,
    scan_unknown_terms,
    term_hash,
)
from amw_core.errors import CorruptedOutputError, InputInvalidError

pytestmark = pytest.mark.unit


def entry(
    eid: str,
    value: str,
    text: str,
    *,
    kind: str = "WORD",
    mode: str = "SPOKEN_FORM",
    case: bool = True,
) -> dict[str, object]:
    return {
        "entry_id": eid,
        "kind": "OTHER",
        "match": {"type": kind, "value": value, "case_sensitive": case},
        "replacement": {"mode": mode, "text": text},
    }


def dictionary(*entries: dict[str, object], language: str = "mr-IN") -> PronunciationDictionary:
    doc = {
        "dictionary_key": "test-dict",
        "language": language,
        "version": 1,
        "entries": list(entries),
    }
    return PronunciationDictionary.from_bytes(json.dumps(doc).encode(), None, "mr-IN")


def segment(text: str, sid: str = "s1") -> c.ScriptSegment:
    return c.ScriptSegment(
        segment_id=sid, text=text, pace=c.Pace.NORMAL, emotion=c.Emotion.NEUTRAL, scene_id="sc"
    )


def test_sanitise_nfc_controls_whitespace_and_zwj() -> None:
    assert sanitise("a\u0007  b\t\nc​") == "a b c"
    assert sanitise("क्‍ष") == "क्‍ष"  # ZWJ kept for Devanagari conjuncts
    assert sanitise("é") == "é"  # NFC
    assert sanitise("\u0007  ​ ") == ""


def test_escape_markup_never_interpreted() -> None:
    assert escape_markup('a < b & <break time="5s"/>') == 'a &lt; b &amp; &lt;break time="5s"/&gt;'
    assert escape_markup("a{b}", extra_delimiters=("{",)) == "a&#123;b}"


def test_longest_match_wins_and_matches_do_not_overlap() -> None:
    d = dictionary(
        entry("d1", "Nifty", "निफ्टी", kind="LITERAL"),
        entry("d2", "Bank Nifty", "बँक निफ्टी", kind="LITERAL"),
    )
    out = d.apply("Bank Nifty आणि Nifty", phoneme_support=False)
    assert out.text == "बँक निफ्टी आणि निफ्टी"
    assert [(h.entry_id, h.count) for h in out.hits] == [("d2", 1), ("d1", 1)]


def test_word_entry_respects_latin_and_devanagari_boundaries() -> None:
    d = dictionary(entry("d1", "RSI", "आर एस आय"), entry("d3", "भाव", "भा व"))
    assert d.apply("ARSIX RSIX RSI-रेषा", phoneme_support=False).text == "ARSIX RSIX आर एस आय-रेषा"
    assert d.apply("भावना आणि भाव", phoneme_support=False).text == "भावना आणि भा व"


def test_case_insensitive_entry() -> None:
    d = dictionary(entry("d1", "rsi", "आर एस आय", case=False))
    assert d.apply("RSI rsi Rsi", phoneme_support=False).hits[0].count == 3


def test_phoneme_entries_skipped_without_support() -> None:
    d = dictionary(entry("d1", "Nifty", "n-i", kind="LITERAL", mode="PHONEME"))
    skipped = d.apply("Nifty", phoneme_support=False)
    assert skipped.text == "Nifty"
    assert skipped.skipped_phoneme_entries == 1
    assert skipped.expected_matches == 0
    assert d.apply("Nifty", phoneme_support=True).text == "n-i"


def test_chained_rewrite_is_rejected_at_load() -> None:
    with pytest.raises(InputInvalidError):
        dictionary(entry("d1", "A", "B"), entry("d2", "B", "C"))


def test_duplicate_ids_and_conflicting_matches_rejected() -> None:
    with pytest.raises(InputInvalidError):
        dictionary(entry("d1", "A", "x"), entry("d1", "B", "y"))
    with pytest.raises(InputInvalidError):
        dictionary(entry("d1", "A", "x"), entry("d2", "A", "y"))


def test_dictionary_hash_and_language_are_verified() -> None:
    doc = json.dumps(
        {"dictionary_key": "test-dict", "language": "mr-IN", "version": 1, "entries": []}
    ).encode()
    with pytest.raises(CorruptedOutputError):
        PronunciationDictionary.from_bytes(doc, "0" * 64, "mr-IN")
    with pytest.raises(InputInvalidError):
        PronunciationDictionary.from_bytes(doc, None, "hi-IN")
    with pytest.raises(InputInvalidError):
        PronunciationDictionary.from_bytes(b"{}", None, "mr-IN")


def test_prepare_segment_order_and_limits() -> None:
    d = dictionary(entry("d1", "RSI", "आर एस आय"))
    prep = prepare_segment(
        segment("RSI < 30"), d, phoneme_support=False, max_chars_per_request=None
    )
    assert prep.spoken_text == "आर एस आय &lt; 30"
    assert prep.characters == len(prep.spoken_text)
    assert len(prep.spoken_text_sha256) == 64
    assert prep.hits[0].segment_id == "s1"
    with pytest.raises(InputInvalidError):
        prepare_segment(segment("\u0007 "), d, phoneme_support=False, max_chars_per_request=None)
    with pytest.raises(InputInvalidError):
        prepare_segment(segment("x" * 41), d, phoneme_support=False, max_chars_per_request=40)


def test_unknown_terms_by_hash_with_markup_numerals_and_candidates() -> None:
    scenes = [
        c.ScriptScene(
            scene_id="sc",
            deliberate_pause_ms=0,
            pronunciation_candidates=("RSI", "Relative Strength Index"),
        )
    ]
    seg = segment("RSI म्हणजे Relative Strength Index 14 <b>")
    d = dictionary(entry("d1", "RSI", "आर एस आय"))
    spoken = d.apply(sanitise(seg.text), phoneme_support=False).text
    terms = scan_unknown_terms(
        org_wire_id="org_x",
        segments=[seg],
        scenes=scenes,
        original_texts={"s1": seg.text},
        substituted_texts={"s1": spoken},
    )
    sources = {t.source for t in terms}
    assert sources == {
        c.UnknownTermSource.SCRIPT_CANDIDATE,
        c.UnknownTermSource.NUMERAL,
        c.UnknownTermSource.MARKUP_CHARACTER,
    }
    assert term_hash("org_x", "RSI") not in {t.term_sha256 for t in terms}  # RSI was covered
    assert term_hash("org_x", "Relative Strength Index") in {t.term_sha256 for t in terms}


def test_term_hash_is_org_bound_and_normalised() -> None:
    assert term_hash("org_a", "RSI") != term_hash("org_b", "RSI")
    assert term_hash("org_a", " rsi ") == term_hash("org_a", "RSI")
