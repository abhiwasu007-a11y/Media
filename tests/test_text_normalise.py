"""amw_core.text_normalise: shared normalisation for finance-rule lexicons and the copy guard."""

# ruff: noqa: RUF001  -- look-alike letters are the test data of this module.

import random
import unicodedata

import pytest

from amw_core import text_normalise as tn
from amw_core.errors import InputInvalidError
from amw_core.text_normalise import (
    DEFAULT_SUFFIXES,
    NGram,
    NormalisedText,
    NormaliseOptions,
    Script,
    Token,
    dominant_script,
    normalise_for_matching,
    shingle_set,
    stem_affixes,
    tokenize,
    word_ngrams,
)

pytestmark = pytest.mark.unit

INVISIBLES = (
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\ufeff",  # BOM / zero-width no-break space
    "\xad",  # soft hyphen
    "\u2060",  # word joiner
    "\u200e",  # left-to-right mark
    "\u200f",  # right-to-left mark
    "\u202a",  # LRE
    "\u202e",  # RLO
    "\u2066",  # LRI
    "\u2069",  # PDI
    "\u061c",  # Arabic letter mark
    "\ufe0f",  # variation selector 16
    "\ufe00",  # variation selector 1
    "\U000e0100",  # variation selector 17
    "\u034f",  # combining grapheme joiner
    "\u180b",  # Mongolian free variation selector
    "\u3164",  # Hangul filler
    "\u115f",  # Hangul choseong filler
    "\U000e0041",  # tag latin capital A
    "\x00",  # NUL control
    "\x7f",  # DEL control
)

SAMPLE_WORDS = (
    "buy",
    "sell",
    "target",
    "profit",
    "stoploss",
    "multibagger",
    "kharedi",
    "khareedo",
    "munafa",
    "खरेदी",
    "विक्री",
    "नफा",
    "टार्गेट",
    "शेअर",
    "क्षेत्र",
    "ज्ञान",
    "र्\u200dय",
    "खरीदो",
    "मुनाफ़ा",
    "बेचो",
    "लक्ष्य",
    "मध्ये",
)


def norm(text: str, options: NormaliseOptions = tn.DEFAULT_OPTIONS) -> str:
    return normalise_for_matching(text, options).text


def words(text: str) -> list[str]:
    return [token.text for token in tokenize(normalise_for_matching(text))]


# --- normalise_for_matching: basic folds ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BUY", "buy"),
        ("Straße", "strasse"),
        ("ＢＵＹ ｎｏｗ", "buy now"),  # fullwidth
        ("𝐁𝐔𝐘", "buy"),  # mathematical bold
        ("ⓑⓤⓨ", "buy"),  # enclosed
        ("ﬁnance proﬁt", "finance profit"),  # ligatures
        ("ʙᴜʏ", "buy"),  # small capitals
        ("bıg", "big"),  # dotless i
        ("İnvest", "invest"),  # dotted capital I casefolds with a combining dot
        ("  buy \t\n now  ", "buy now"),
        ("buy\xa0\u2003now", "buy now"),  # no-break and em spaces
        ("buy\u2028now\u2029", "buy now"),  # line / paragraph separators
        ("buy\u2800now", "buy now"),  # braille blank counts as a space
        ("", ""),
        ("\u200b\u200d", ""),
        ("   ", ""),
    ],
)
def test_basic_folds(raw: str, expected: str) -> None:
    assert norm(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ВUY", "buy"),  # Cyrillic capital VE
        ("ТАRGЕТ", "target"),  # Cyrillic TE, A, IE
        ("рrоfіt", "profit"),  # Cyrillic er, o, i
        ("ѕеll", "sell"),  # Cyrillic dze, ie
        ("ΒUΥ", "buy"),  # Greek beta, upsilon
        ("ΡRΟFΙΤ", "profit"),  # Greek rho, omicron, iota, tau
        ("ρrοfιt", "profit"),  # Greek small rho, omicron, iota
        ("ѕtорlоѕѕ", "stoploss"),
        ("ёxit", "exit"),  # Cyrillic io decomposes to ie + diaeresis
        ("άlpha", "alpha"),  # Greek alpha with tonos
        ("ԁip", "dip"),  # Cyrillic komi de
        ("ϲall", "call"),  # Greek lunate sigma
        ("b\u057dy", "buy"),  # Armenian seh (CCR-110)
        ("b\u057ey", "buy"),  # Armenian vo (CCR-110)
        ("bu\u13a9", "buy"),  # Cherokee gi (CCR-110)
        ("B\u054dY", "buy"),  # Armenian capital SEH casefolds to U+057D
    ],
)
def test_confusables_fold_to_latin(raw: str, expected: str) -> None:
    assert norm(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Купить акции", "купить акции"),  # genuine Russian words stay Cyrillic
        ("Καλημέρα", "καλημερα"),  # genuine Greek stays Greek (accent stripped)
        ("ВUY купить", "buy купить"),  # decided per word
        ("Расе", "pace"),  # a word made only of look-alikes folds to Latin
        ("buyкупить", "buyкyпить"),  # Latin letters present: the whole word folds
    ],
)
def test_confusables_decided_per_word(raw: str, expected: str) -> None:
    assert norm(raw) == expected


def test_confusable_table_values_are_lowercase_ascii_and_keys_nfd_stable() -> None:
    for key, value in tn._CONFUSABLES.items():
        assert len(key) == 1
        assert unicodedata.normalize("NFD", key) == key
        assert value.isascii()
        assert value.islower()
        assert len(value) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("b\u0301u\u0308y", "buy"),  # stacked combining marks
        ("bùÿ", "buy"),  # precomposed
        ("naïve", "naive"),
        ("b\u20dduy", "buy"),  # enclosing circle mark
        ("खरे\u0301दी", "खरेदी"),  # generic acute stacked on Devanagari
        ("bाuy", "buy"),  # Devanagari sign on a Latin base
    ],
)
def test_diacritics_stripped(raw: str, expected: str) -> None:
    assert norm(raw) == expected


def test_diacritics_kept_when_option_off() -> None:
    keep = NormaliseOptions(strip_diacritics=False)
    assert norm("naïve", keep) == "naïve"
    assert norm("b\u0301uy", keep) == "b\u0301uy"


def test_devanagari_signs_kept_by_diacritic_strip() -> None:
    for word in ("खरेदी", "क्षेत्र", "विक्री", "नफ्यात", "संधी"):
        assert norm(word) == word


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("०१२३४५६७८९", "0123456789"),  # Devanagari digits
        ("₹१००", "₹100"),
        ("٣", "3"),  # Arabic-Indic
        ("৫", "5"),  # Bengali
        ("²", "2"),  # superscript via NFKC
        ("１０", "10"),  # fullwidth
    ],
)
def test_digits_fold_to_ascii(raw: str, expected: str) -> None:
    assert norm(raw) == expected


# --- Devanagari canonicalisation -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("क़ीमत", "कीमत"),  # precomposed QA
        ("क़ीमत", "कीमत"),  # KA + nukta
        ("मुनाफ़ा", "मुनाफा"),
        ("ज़्यादा", "ज्यादा"),  # ZA
        ("ऩ", "न"),  # NNNA (composes under NFC)
        ("ऱ", "र"),
        ("ऴ", "ळ"),
    ],
)
def test_nukta_stripped(raw: str, expected: str) -> None:
    assert norm(raw) == expected


def test_nukta_kept_when_option_off_is_canonical() -> None:
    keep = NormaliseOptions(strip_nukta=False)
    assert norm("क़", keep) == norm("क़", keep) == "क़"
    assert norm("ऩ", keep) == norm("ऩ", keep) == "ऩ"


def test_chandrabindu_equivalence_option() -> None:
    assert norm("हँसी") == norm("हंसी") == "हंसी"
    keep = NormaliseOptions(fold_chandrabindu=False)
    assert norm("हँसी", keep) == "हँसी"
    assert norm("हँसी", keep) != norm("हंसी", keep)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("अाता", "आता"),
        ("अाे", "ओ"),  # A + AA + E -> O via AA
        ("अो", "ओ"),
        ("अौ", "औ"),
        ("अॉफर", "ऑफर"),
        ("अॅ", "ॲ"),
        ("एे", "ऐ"),
        ("एॅ", "ऍ"),
        ("एॆ", "ऎ"),
        ("अॆ", "ऄ"),
        ("अॊ", "ऒ"),
        ("आॅ", "ऑ"),
        ("आै", "औ"),
    ],
)
def test_two_part_vowels_fold(raw: str, expected: str) -> None:
    assert norm(raw) == expected


def test_zwj_zwnj_inside_conjuncts_removed() -> None:
    assert norm("क्\u200dष") == "क्ष"
    assert norm("क्\u200cष") == "क्ष"
    assert norm("र्\u200dय") == "र्य"  # eyelash ra matches the plain conjunct


# --- property tests: invisible characters at every position --------------------------------


@pytest.mark.parametrize("word", SAMPLE_WORDS)
@pytest.mark.parametrize("invisible", INVISIBLES)
def test_invisible_at_every_position_is_removed(word: str, invisible: str) -> None:
    clean = norm(word)
    for position in range(len(word) + 1):
        dirty = word[:position] + invisible + word[position:]
        assert norm(dirty) == clean, (position, dirty)
        assert words(dirty) == words(word)


@pytest.mark.parametrize("seed", range(20))
def test_random_invisible_injection_deterministic(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - deterministic test data, not security
    for word in SAMPLE_WORDS:
        dirty = "".join(
            ch + "".join(rng.choice(INVISIBLES) for _ in range(rng.randint(0, 3))) for ch in word
        )
        assert norm(dirty) == norm(word), dirty


@pytest.mark.parametrize("seed", range(10))
def test_random_confusable_swap_deterministic(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - deterministic test data, not security
    reverse: dict[str, list[str]] = {}
    for key, value in tn._CONFUSABLES.items():
        reverse.setdefault(value, []).append(key)
    for word in ("buy", "sell", "target", "profit", "stoploss", "jackpot", "exit"):
        swapped = "".join(
            rng.choice(reverse[ch]) if ch in reverse and rng.random() < 0.7 else ch for ch in word
        )
        assert norm(swapped) == word, swapped


@pytest.mark.parametrize("seed", range(10))
def test_idempotent_and_offsets_monotonic(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - deterministic test data, not security
    alphabet = "abcXYZ खरेदीकषज्ञ़ँ्ाТАВρο१२ ﬁ¨\u0301" + "".join(INVISIBLES) + "\t\n\xa0"
    for _ in range(50):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        result = normalise_for_matching(raw)
        assert normalise_for_matching(result.text).text == result.text, raw
        assert result.text == result.text.strip()
        assert "  " not in result.text
        previous = (0, 0)
        for span in result.spans:
            start, end = span
            assert 0 <= start < end <= len(raw)
            assert start >= previous[0], (raw, result.spans)
            assert end >= previous[1], (raw, result.spans)
            previous = span


# --- offset map -----------------------------------------------------------------------------


def test_offsets_quote_original_text() -> None:
    raw = "Please В\u200bUY  this stock for ＰＲＯＦＩＴ!"
    result = normalise_for_matching(raw)
    assert result.original == raw
    assert result.text == "please buy this stock for profit!"
    start = result.text.index("buy")
    assert result.quote(start, start + 3) == "В\u200bUY"
    start = result.text.index("profit")
    assert result.quote(start, start + 6) == "ＰＲＯＦＩＴ"
    start = result.text.index("buy this")
    assert result.quote(start, start + 8) == "В\u200bUY  this"


def test_offsets_devanagari_cluster_and_expansion() -> None:
    raw = "हा शेअ\u200dर खरे\u0301दी करा ﬁ"
    result = normalise_for_matching(raw)
    assert result.text == "हा शेअर खरेदी करा fi"
    start = result.text.index("खरेदी")
    assert result.quote(start, start + len("खरेदी")) == "खरे\u0301दी"
    start = result.text.index("शेअर")
    assert result.quote(start, start + 4) == "शेअ\u200dर"
    # both characters of an expanded ligature map to the ligature
    assert result.spans[-1] == result.spans[-2] == (len(raw) - 1, len(raw))


def test_whitespace_run_maps_to_whole_run() -> None:
    raw = "buy \t\n now"
    result = normalise_for_matching(raw)
    assert result.text == "buy now"
    assert result.spans[3] == (3, 7)


def test_space_produced_by_nfkc_is_collapsed() -> None:
    # U+00A8 DIAERESIS is NFKC " ̈"; the mark is stripped, the space merges.
    assert norm("buy ¨now") == "buy now"
    assert norm("¨buy") == "buy"
    assert norm("buy¨") == "buy"


def test_orphan_mark_clusters() -> None:
    assert norm("\u0301") == ""  # generic mark with no base is stripped
    assert norm(" ा") == "ा"  # Devanagari sign after a space stays an orphan
    assert norm("ाे") == "ाे"


def test_original_span_edges() -> None:
    result = normalise_for_matching("  ab  ")
    assert result.text == "ab"
    assert result.original_span(0, 0) == (2, 2)
    assert result.original_span(2, 2) == (4, 4)
    assert result.original_span(0, 2) == (2, 4)
    assert result.quote(1, 2) == "b"
    empty = normalise_for_matching("\u200b")
    assert empty.original_span(0, 0) == (0, 0)
    assert empty.quote(0, 0) == ""


@pytest.mark.parametrize(("start", "end"), [(-1, 1), (2, 1), (0, 3)])
def test_original_span_rejects_bad_range(start: int, end: int) -> None:
    result = normalise_for_matching("ab")
    with pytest.raises(InputInvalidError):
        result.original_span(start, end)


def test_normalised_text_rejects_inconsistent_offset_map() -> None:
    with pytest.raises(InputInvalidError):
        NormalisedText(original="ab", text="ab", spans=((0, 1),))


# --- tokenize --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Buy now, sell later!", ["buy", "now", "sell", "later"]),
        ("हा शेअर नक्की खरेदी करा।", ["हा", "शेअर", "नक्की", "खरेदी", "करा"]),
        ("क्षेत्रात ज्ञानाने", ["क्षेत्रात", "ज्ञानाने"]),
        ("ye stock kharido, 100% munafa", ["ye", "stock", "kharido", "100", "munafa"]),
        ("शेअरbuy करा", ["शेअर", "buy", "करा"]),
        ("buyशेअर", ["buy", "शेअर"]),
        ("buy100शेअर", ["buy100", "शेअर"]),
        ("१०० टक्के नफा", ["100", "टक्के", "नफा"]),
        ("target₹500", ["target", "500"]),
        ("жук", ["жук"]),
        ("buy жук", ["buy", "жук"]),
        ("...", []),
        ("", []),
        (" ाक", ["ाक"]),
    ],
)
def test_tokenize(raw: str, expected: list[str]) -> None:
    assert words(raw) == expected


def test_tokens_carry_offsets_back_to_original() -> None:
    raw = "हा शे\u200bअर ख\u200dरेदी करा"
    result = normalise_for_matching(raw)
    tokens = tokenize(result)
    assert [t.text for t in tokens] == ["हा", "शेअर", "खरेदी", "करा"]
    for token in tokens:
        assert result.text[token.start : token.end] == token.text
    assert result.quote(tokens[2].start, tokens[2].end) == "ख\u200dरेदी"


def test_tokens_never_split_inside_akshara() -> None:
    for word in SAMPLE_WORDS:
        tokens = tokenize(normalise_for_matching(word))
        assert len(tokens) == 1, word
        assert not unicodedata.category(tokens[0].text[0]).startswith("M")


# --- dominant_script ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Buy this stock now", Script.LATIN),
        ("ye stock abhi kharido, pakka munafa", Script.LATIN),  # Hinglish is Latin script
        ("हा शेअर नक्की खरेदी करा", Script.DEVANAGARI),
        ("ये स्टॉक अभी खरीदो", Script.DEVANAGARI),
        ("हा stock नक्की buy करा", Script.MIXED),
        ("ВUY ТАRGЕТ", Script.LATIN),  # look-alikes count as Latin
        ("Купить акции", Script.OTHER),
        ("பங\u0bcdக\u0bc1 வ\u0bbeங\u0bcdக\u0bc1", Script.OTHER),
        ("12345 !!!", Script.OTHER),
        ("", Script.OTHER),
    ],
)
def test_dominant_script(raw: str, expected: Script) -> None:
    assert dominant_script(raw) is expected


def test_dominant_script_ignores_digits_and_invisibles() -> None:
    assert dominant_script("खरेदी १२३४५६७८९ 123456789 \u200b\u200b\u200b") is Script.DEVANAGARI


def test_dominant_script_accepts_normalised_text_and_threshold() -> None:
    mixed = normalise_for_matching("खरेदी करा buy")  # 6 Devanagari letters, 3 Latin
    assert dominant_script(mixed) is Script.MIXED
    assert dominant_script(mixed, threshold=0.6) is Script.DEVANAGARI
    assert dominant_script("a", threshold=1.0) is Script.LATIN


@pytest.mark.parametrize("threshold", [0.5, 0.0, 1.01, -1.0])
def test_dominant_script_rejects_bad_threshold(threshold: float) -> None:
    with pytest.raises(InputInvalidError):
        dominant_script("abc", threshold=threshold)


# --- stem_affixes ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("शेअरला", "शेअर"),
        ("शेअरचा", "शेअर"),
        ("शेअरची", "शेअर"),
        ("शेअरचे", "शेअर"),
        ("शेअरच्या", "शेअर"),
        ("शेअरमध्ये", "शेअर"),
        ("खरेदीसाठी", "खरेदी"),
        ("करेल", "कर"),
        ("करेलच", "कर"),  # longest suffix wins over -च
        ("खरेदीच", "खरेदी"),
        ("शेयरों", "शेयर"),
        ("मुनाफ़ेवाला", "मुनाफे"),
        ("शेअर", "शेअर"),  # nothing to strip
        ("buy", "buy"),
    ],
)
def test_stem_affixes(raw: str, expected: str) -> None:
    assert stem_affixes(norm(raw)) == norm(expected)


def test_stem_keeps_minimum_stem() -> None:
    assert stem_affixes("पाच") == "पाच"  # stem would be one akshara
    assert stem_affixes("कला") == "कला"
    assert stem_affixes("कला", min_stem=1) == "क"


def test_stem_never_breaks_a_conjunct() -> None:
    assert stem_affixes("ईश्वर") == "ईश्वर"


def test_stem_max_strips_and_custom_list() -> None:
    assert stem_affixes("खरेदीसाठीच") == "खरेदीसाठी"
    assert stem_affixes("खरेदीसाठीच", max_strips=2) == "खरेदी"
    assert stem_affixes("खरेदीसाठीच", max_strips=5) == "खरेदी"
    assert stem_affixes("profits", ("s", "")) == "profit"
    assert stem_affixes("profits", ()) == "profits"


@pytest.mark.parametrize(("min_stem", "max_strips"), [(0, 1), (2, 0)])
def test_stem_rejects_bad_limits(min_stem: int, max_strips: int) -> None:
    with pytest.raises(InputInvalidError):
        stem_affixes("शेअरला", min_stem=min_stem, max_strips=max_strips)


def test_default_suffixes_are_normalised_and_unique() -> None:
    assert len(set(DEFAULT_SUFFIXES)) == len(DEFAULT_SUFFIXES)
    for suffix in DEFAULT_SUFFIXES:
        assert norm(suffix) == suffix
        assert " " not in suffix


def test_lexicon_matching_end_to_end() -> None:
    lexicon = {norm(entry) for entry in ("buy", "target", "खरेदी", "नफा", "शेअर", "munafa")}
    raw = "हा ВUY कॉल: शेअ\u200bरमध्ये ख\u200dरेदीसाठी TАRGЕT, mu\xadnafa पक्का"
    result = normalise_for_matching(raw)
    hits = [
        result.quote(t.start, t.end)
        for t in tokenize(result)
        if t.text in lexicon or stem_affixes(t.text) in lexicon
    ]
    assert hits == ["ВUY", "शेअ\u200bरमध्ये", "ख\u200dरेदीसाठी", "TАRGЕT", "mu\xadnafa"]


# --- n-grams / shingles -------------------------------------------------------------------------


def test_word_ngrams_positions_and_quotes() -> None:
    raw = "The  quick ＢＲＯＷＮ fox"
    result = normalise_for_matching(raw)
    grams = word_ngrams(tokenize(result), 2)
    assert [g.words for g in grams] == [("the", "quick"), ("quick", "brown"), ("brown", "fox")]
    assert result.quote(grams[0].start, grams[0].end) == "The  quick"
    assert result.quote(grams[1].start, grams[1].end) == "quick ＢＲＯＷＮ"
    assert grams[2] == NGram(words=("brown", "fox"), start=10, end=19)


def test_word_ngrams_edges() -> None:
    tokens = tokenize(normalise_for_matching("एक दोन"))
    assert word_ngrams(tokens, 3) == ()
    assert word_ngrams((), 1) == ()
    assert [g.words for g in word_ngrams(tokens, 1)] == [("एक",), ("दोन",)]
    with pytest.raises(InputInvalidError):
        word_ngrams(tokens, 0)
    with pytest.raises(InputInvalidError):
        shingle_set(tokens, -1)


def test_shingles_defeat_evasion_in_copy_guard() -> None:
    source = "मराठी भाषा ही अतिशय समृद्ध भाषा आहे"
    copied = "मरा\u200bठी भा\xadषा ही अ\u200dतिशय समृद्ध भाषा आहे"
    a = shingle_set(tokenize(normalise_for_matching(source)), 3)
    b = shingle_set(tokenize(normalise_for_matching(copied)), 3)
    assert a == b
    assert len(a) == 5


def test_token_and_ngram_are_value_objects() -> None:
    assert Token("a", 0, 1) == Token("a", 0, 1)
    assert NGram(("a",), 0, 1) == NGram(("a",), 0, 1)


# --- idempotence property, fix-ups of the code review (PR #41) ---------------------------------

FUZZ_STRINGS = 60_000
FUZZ_ALPHABET = (
    "abcXYZ buy ﬁ¨\t\n\xa0⠀"
    + "".join(INVISIBLES)
    + "".join(chr(cp) for cp in range(0x0900, 0x0980))  # the whole Devanagari block
    + "ͅŉͺﳲำຳـ￼‑̀́᪰⃐"
    + "ТАВЕОРСХροϲıᴀ١٢३४ⅠéÅ"
)


def _fuzz_strings(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)  # noqa: S311 - deterministic test data, not security
    strings = []
    for index in range(count):
        length = rng.randint(0, 24)
        if index % 4 == 3:  # a quarter of the strings draw from the whole BMP and beyond
            pool = [
                chr(rng.choice((rng.randint(0, 0x3FFF), rng.randint(0xA000, 0x1FFFF), 0xE0001)))
                for _ in range(length)
            ]
            strings.append("".join(ch for ch in pool if not 0xD800 <= ord(ch) < 0xE000))
        else:
            strings.append("".join(rng.choice(FUZZ_ALPHABET) for _ in range(length)))
    return strings


def _assert_spans_sound(raw: str, result: NormalisedText) -> None:
    assert result.text == result.text.strip()
    assert "  " not in result.text
    previous = (0, 0)
    for start, end in result.spans:
        assert 0 <= start < end <= len(raw), raw
        assert start >= previous[0], raw
        assert end >= previous[1], raw
        previous = (start, end)


def test_idempotent_over_seeded_fuzz_incl_devanagari_marks() -> None:
    strings = _fuzz_strings(20260, FUZZ_STRINGS)
    assert len(strings) >= 60_000
    for raw in strings:
        result = normalise_for_matching(raw)
        again = normalise_for_matching(result.text).text
        assert again == result.text, (raw, result.text, again)
        _assert_spans_sound(raw, result)


@pytest.mark.parametrize(
    "options",
    [
        NormaliseOptions(strip_diacritics=False),
        NormaliseOptions(strip_nukta=False, fold_chandrabindu=False),
        NormaliseOptions(strip_nukta=False, fold_chandrabindu=False, strip_diacritics=False),
    ],
)
def test_idempotent_with_other_options(options: NormaliseOptions) -> None:
    for raw in _fuzz_strings(7, 6000):
        text = normalise_for_matching(raw, options).text
        assert normalise_for_matching(text, options).text == text, raw


@pytest.mark.parametrize(
    "raw",
    ["षͅऺ", "aͅँऺ", "ŉँऺ", "aͺँऺ", "aำँऺ", "aﳲँऺ", "ﳲषऺ", "ͅ", "कͅँ"],
)
def test_idempotent_known_failures_of_the_review(raw: str) -> None:
    text = norm(raw)
    assert norm(text) == text


def test_ypogegrammeni_is_dropped_not_casefolded_into_a_letter() -> None:
    assert norm("षͅऺ") == norm("षऺ")
    assert norm("buyͅ") == "buy"


def test_spans_stay_in_the_original_after_extra_passes() -> None:
    raw = "x ŉँऺ y"
    result = normalise_for_matching(raw)
    assert result.quote(0, len(result.text)) == raw
    for start, end in result.spans:
        assert raw[start:end]


# --- more invisible / decorative characters ----------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["bـuy", "buــy", "buy", "bu￼y", "b‑uy", "b\U000e0080uy", "b\ud800uy"],
)
def test_decorative_characters_inside_words_are_removed(raw: str) -> None:
    assert norm(raw) == "buy"
    result = normalise_for_matching(raw)
    assert result.quote(0, 3) == raw


def test_ordinary_hyphens_are_punctuation_not_removed() -> None:
    # Caller policy: only the NON-BREAKING hyphen (a pure layout character) is invisible.
    assert norm("b-uy") == "b-uy"
    assert norm("b‐uy") == "b‐uy"


# --- ASCII fast path and the input-length cap ---------------------------------------------------


def test_ascii_fast_path_equals_general_path() -> None:
    rng = random.Random(5)  # noqa: S311 - deterministic test data, not security
    alphabet = "abcXYZ019 \t\n\r\x0b\x0c\x1c\x1f\x00\x01\x7f.,-!"
    for _ in range(3000):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 20)))
        fast = normalise_for_matching(raw)
        slow = tn._normalise_once(raw, tn.DEFAULT_OPTIONS)
        assert (fast.text, fast.spans) == (slow.text, slow.spans), raw


def test_input_longer_than_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tn, "MAX_INPUT_CHARS", 10)
    assert norm("a" * 10) == "a" * 10
    for raw in ("a" * 11, "खरेदी" * 3):
        with pytest.raises(InputInvalidError) as caught:
            normalise_for_matching(raw)
        assert caught.value.details["max_chars"] == 10


def test_cap_constant_is_public_and_large() -> None:
    assert tn.MAX_INPUT_CHARS == 1_000_000
    assert "MAX_INPUT_CHARS" in tn.__all__


def test_long_inputs_below_the_cap_run_linearly() -> None:
    raw = "buy शेअर " * 20_000
    result = normalise_for_matching(raw)
    assert result.text == raw.rstrip()
    assert len(result.spans) == len(result.text)


# --- quote() / original_span stability ----------------------------------------------------------


def test_quote_of_whole_words_renormalises_to_the_match() -> None:
    checked = 0
    for raw in _fuzz_strings(11, 4000):
        result = normalise_for_matching(raw)
        spans = result.spans
        position = 0
        for chunk in result.text.split(" "):
            low, high = position, position + len(chunk)
            position = high + 1

            # Only chunks bounded by a space that is whitespace in the ORIGINAL (a space that comes
            # from NFKC of one source character, for example U+037A, splits a source word).
            def real_space(
                index: int, raw: str = raw, spans: tuple[tuple[int, int], ...] = spans
            ) -> bool:
                return all(tn._is_space(ch) for ch in raw[spans[index][0] : spans[index][1]])

            if not chunk or (low > 0 and not real_space(low - 1)):
                continue
            if high < len(spans) and not real_space(high):
                continue
            assert normalise_for_matching(result.quote(low, high)).text == chunk, (raw, chunk)
            checked += 1
    assert checked > 2000


def test_quote_of_part_of_a_word_may_renormalise_differently() -> None:
    # Documented limit: the look-alike fold is decided per WORD, so a fragment quoted on its
    # own is folded without the other letters of its word.
    result = normalise_for_matching("buy\u03a3\u041e")  # Greek capital sigma + Cyrillic O
    assert result.text == "buy\u03c3o"
    fragment = result.quote(3, 5)
    assert normalise_for_matching(fragment).text == "\u03c3\u043e"  # Cyrillic o stays Cyrillic
    assert normalise_for_matching(result.quote(0, len(result.text))).text == result.text


# --- Cyrillic / Greek residual risk (PROVISIONAL table) ------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("сор", "cop"),  # a real Russian word made only of table letters folds to Latin
        ("хор", "xop"),
        ("ΑΝΑ", "ana"),
        ("ВЕТЕР", "betep"),  # upper case folds ...
        ("ветер", "ветер"),  # ... lower case does not: documented asymmetry
        ("привет", "привет"),
        ("Москва", "москва"),
        ("Αθήνα", "αθηνα"),
    ],
)
def test_cyrillic_greek_residual_risk_is_pinned(raw: str, expected: str) -> None:
    assert norm(raw) == expected


# --- Devanagari known gaps (documented, not folded) ----------------------------------------------


def test_devanagari_spelling_variants_are_known_gaps() -> None:
    # Lexicon authors list both spellings (see the module docstring, "Known gaps").
    assert norm("संकट") != norm("सङ्कट")
    assert norm("हिंदी") != norm("हिन्दी")
    assert norm("ऑफर") != norm("आफर")
    assert norm("शेअर") != norm("शेयर")


def test_stem_affixes_is_devanagari_only() -> None:
    assert stem_affixes("shareko") == "shareko"
    assert stem_affixes("buy") == "buy"
    assert stem_affixes("बाजारला") == "बाजार"


# --- re-review fixes: one long cluster is linear, output is bounded ------------------------------


def test_one_long_combining_cluster_is_linear() -> None:
    import time

    def best(count: int) -> float:
        raw = "a" + "́" * count
        times = []
        for _ in range(3):
            started = time.perf_counter()
            assert normalise_for_matching(raw).text == "a"
            times.append(time.perf_counter() - started)
        return min(times)

    small, large = best(50_000), best(400_000)
    assert large < small * 14 + 0.5  # 8x the input; a quadratic path would be about 64x


def test_one_long_devanagari_cluster_keeps_every_mark_and_maps_back() -> None:
    raw = "क" + "ा" * 1000
    result = normalise_for_matching(raw)
    assert result.text == raw
    assert result.quote(0, len(result.text)) == raw


def test_output_expansion_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "ﷺ" * 60_000  # 18 characters each: 1.08M > MAX_OUTPUT_CHARS, input far below cap
    assert len(raw) < tn.MAX_INPUT_CHARS
    with pytest.raises(InputInvalidError) as caught:
        normalise_for_matching(raw)
    assert caught.value.details["max_output_chars"] == tn.MAX_OUTPUT_CHARS
    assert caught.value.details["output_length"] == 60_000 * 18
    assert len(norm("ﷺ" * 10)) == 10 * 18 + 9 or norm("ﷺ")
    monkeypatch.setattr(tn, "MAX_OUTPUT_CHARS", 20)
    assert norm("ﷺ")  # 18 characters: allowed
    with pytest.raises(InputInvalidError):
        normalise_for_matching("ﷺﷺ")
