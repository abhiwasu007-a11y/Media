# ruff: noqa: RUF001
"""Quote guard 2, minors of the independent review of PR 118: linear scan, word counting through
invisible characters and hyphens, multi-line spans, seed lists, the claim window.
SYNTHETIC text only (no library text)."""

import pytest

from agent_06_fact_checker.models import VerificationClaim
from agent_06_fact_checker.quote_guard import GuardReason, guard_reason, guard_reasons
from agent_06_fact_checker.quote_marks import QuoteMarkConfig, WorkCounter, seed_data
from tests.agents.agent_06_fact_checker.support import make_settings
from tests.agents.agent_06_fact_checker.test_verification_step import claim

pytestmark = pytest.mark.unit

WORDS = ["one", "two", "three", "four", "five", "six"]
SIX = " ".join(WORDS)


def vc(n: int = 1, **over: object) -> VerificationClaim:
    return VerificationClaim.model_validate(claim(n, **{"claim_type": "FACTUAL", **over}))


def marks() -> object:
    return make_settings().quote_marks.compiled()


# (1) linear scan ----------------------------------------------------------------------------


@pytest.mark.parametrize("opener", ["„", "「", "‚", "❮", "«", '"'])
def test_an_opener_without_a_closer_costs_linear_work(opener: str) -> None:
    table = make_settings().quote_marks.compiled()
    work = WorkCounter()
    n = 20000
    text = opener * n if opener not in {'"'} else '"' + "a" * (n - 1)
    table.spans(text, work)
    assert work.steps <= 3 * n + 10, work.steps  # the old scan did ~n*n/2 = 2e8 steps here


def test_work_stays_linear_for_many_spans_and_for_unclosed_runs_between_them() -> None:
    table = make_settings().quote_marks.compiled()
    work = WorkCounter()
    chunk = f"„{'x' * 50} “{SIX}” "  # an unclosed low-9 mark... closed by the next curly mark
    text = chunk * 300
    out = table.spans(text, work)
    assert out  # spans were found
    assert work.steps <= 4 * len(text) + 10


def test_a_long_claim_with_a_stray_opener_is_still_decided() -> None:
    text = "„" * 2000
    assert guard_reason(vc(quote=text), make_settings()) is None  # no closer: no span, no hang


# (2) word counting --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "glue",
    ["‌", "‍", "⁠", "﻿", "­", "-", "‐", "‑", "–", "—"],
)
def test_invisible_characters_and_hyphens_between_words_do_not_hide_a_span(glue: str) -> None:
    glued = glue.join(WORDS)
    assert guard_reason(vc(quote=f'A "{glued}" B'), make_settings()) is GuardReason.QUOTE_SPAN
    five = glue.join(WORDS[:5])
    assert guard_reason(vc(quote=f'A "{five}" B'), make_settings()) is None  # 5 < 6


def test_the_strip_set_is_configuration() -> None:
    cfg = seed_data()["quote_marks"]
    cfg = {**cfg, "word_count_separators": []}
    table = QuoteMarkConfig.model_validate(cfg).compiled()
    assert [s.words for s in table.spans(f'"{"-".join(WORDS)}"')] == [1]  # nothing configured
    seeded = make_settings().quote_marks.compiled()
    assert [s.words for s in seeded.spans(f'"{"-".join(WORDS)}"')] == [6]


# (3) multi-line spans -----------------------------------------------------------------------


def test_a_quoted_verse_over_several_lines_is_a_span() -> None:
    verse = "“one two three\nfour five\nsix seven”"
    assert guard_reason(vc(quote=f"He recited it. {verse}"), make_settings()) is (
        GuardReason.QUOTE_SPAN
    )
    assert guard_reason(vc(quote="“one two\nthree”"), make_settings()) is None  # 3 words < 6


def test_a_span_longer_than_the_configured_bound_is_no_span() -> None:
    limit = make_settings().quote_marks.max_quote_span_chars
    long_inner = ("w " * limit)[: limit + 50]
    table = make_settings().quote_marks.compiled()
    assert table.spans(f"“{long_inner}”") == []
    assert len(table.spans("“" + "w " * (limit // 2 - 1) + "”")) == 1


def test_a_stray_mark_on_an_earlier_line_does_not_hide_a_later_quote() -> None:
    text = 'the bolt is 5" long\n"alpha beta gamma delta epsilon zeta eta"'
    table = make_settings().quote_marks.compiled()
    assert max(sp.words for sp in table.spans(text)) == 7  # per-line spans AND cross-line spans
    assert guard_reason(vc(quote=text), make_settings()) is GuardReason.QUOTE_SPAN


def test_the_union_is_sorted_unique_and_never_less_than_the_whole_text_scan() -> None:
    table = make_settings().quote_marks.compiled()
    text = "“one two”\n“three four five six seven eight”\nx\n“a b”"
    out = table.spans(text)
    assert [(m.start, m.end) for m in out] == sorted({(m.start, m.end) for m in out})
    assert len(out) == 3


def test_a_split_quote_longer_than_the_span_bound_is_still_guarded_in_its_claims() -> None:
    limit = make_settings().quote_marks.max_quote_span_chars
    chunk = "w " * (limit // 4)  # three chunks together exceed the bound
    a = vc(1, quote="He said “" + chunk)
    b = vc(2, quote=chunk)
    c = vc(3, quote=chunk + "” and left")
    assert len(chunk) * 3 > limit
    got = guard_reasons([a, b, c], make_settings(quote_split_window_claims=3))
    assert set(got) == {a.local_id, b.local_id, c.local_id}


# (4) seed lists, human review versus quote check --------------------------------------------


@pytest.mark.parametrize("text", ["नियमानुसार", "अहवालानुसार", "त्याच्या मते", "thought", "per Seneca"])
def test_bare_source_words_are_human_review_not_quote_check(text: str) -> None:
    assert guard_reason(vc(quote=text), make_settings()) is GuardReason.REPORTED_SPEECH


CORPUS = [  # 21 ORDINARY claims (invented), the kind a script holds; what the guard does with each
    ("Revenue grew 12 per cent last year.", None),  # "per" counts only before a capitalised name
    ("Risking 1% per trade costs 5% after five losses.", None),
    ("The city has 40 parks.", None),
    ("The bridge opened in 1932.", None),
    ("The company reported a loss of 3 million.", None),
    ("Water boils at a lower temperature at altitude.", None),
    ("The report said revenue grew by 12 per cent.", GuardReason.ATTRIBUTION),
    ("The minister says the road will open soon.", GuardReason.ATTRIBUTION),
    ("According to the survey, 60 per cent of homes have a fan.", GuardReason.ATTRIBUTION),
    ("The author wrote three books in ten years.", GuardReason.ATTRIBUTION),
    ("Rainfall was above average in the region.", None),
    ("The school has 500 students and 20 teachers.", None),
    ("Prices rose after the new tax came into force.", None),
    ("The festival is held every year in spring.", GuardReason.REPORTED_SPEECH),
    ("अहवालानुसार शहरात ४० उद्याने आहेत.", GuardReason.REPORTED_SPEECH),
    ("नियमानुसार अर्ज दहा दिवसांत द्यावा.", GuardReason.REPORTED_SPEECH),
    ("पूल १९३२ मध्ये सुरू झाला.", None),
    ("कंपनीला तीन कोटींचा तोटा झाला.", None),
    ("मंत्री म्हणाले रस्ता लवकर सुरू होईल.", GuardReason.ATTRIBUTION),
    ("नदी तीनशे किलोमीटर लांब आहे.", None),
    ("शाळेत पाचशे विद्यार्थी आहेत.", None),
]


def test_false_positive_count_on_a_synthetic_corpus_of_21_ordinary_claims() -> None:
    assert len(CORPUS) == 21
    settings = make_settings()
    got = [guard_reason(vc(quote=text), settings) for text, _ in CORPUS]
    assert got == [expected for _, expected in CORPUS]
    guarded = [g for g in got if g is not None]
    # Measured and reported in the PR: 8 of 21 ordinary claims go to a human or the quote check.
    assert len(guarded) == 8
    assert sum(g is GuardReason.ATTRIBUTION for g in guarded) == 5  # quote-check list
    assert sum(g is GuardReason.REPORTED_SPEECH for g in guarded) == 3  # human-review list


# (5) window ---------------------------------------------------------------------------------


def test_a_three_way_split_quote_is_guarded_in_all_three_claims() -> None:
    a = vc(1, quote="He added “one two")
    b = vc(2, quote="three four")
    c = vc(3, quote="five six seven” and left")
    s = make_settings(quote_split_window_claims=3)
    assert all(guard_reason(x, s) is None for x in (a, b, c))
    assert set(guard_reasons([a, b, c], s)) == {a.local_id, b.local_id, c.local_id}
    narrow = make_settings(quote_split_window_claims=2)
    assert guard_reasons([a, b, c], narrow) == {}  # two-claim windows never hold six words


def test_a_non_neighbour_split_is_guarded_inside_the_window_and_not_beyond_it() -> None:
    first = vc(1, quote="He added “one two three")
    gap = vc(2, quote="a filler remark")
    last = vc(3, quote="four five six seven” and left")
    after = vc(4, quote="the next topic")
    wide = make_settings(quote_split_window_claims=3)
    got = guard_reasons([first, gap, last, after], wide)
    assert set(got) == {first.local_id, gap.local_id, last.local_id}  # `after` is not touched
    assert guard_reasons([first, gap, last], make_settings(quote_split_window_claims=2)) == {}
    far = [first, gap, vc(5, quote="more"), last]
    assert guard_reasons(far, wide) == {}  # four apart: beyond a window of 3 (documented limit)
    assert set(guard_reasons(far, make_settings(quote_split_window_claims=4))) == {
        c.local_id for c in far
    }


def test_a_typed_quote_claim_inside_the_window_is_not_joined() -> None:
    first = vc(1, quote="He added “one two three")
    typed = VerificationClaim.model_validate(claim(2, claim_type="QUOTED_THIRD_PARTY"))
    last = vc(3, quote="four five six seven” and left")
    assert guard_reasons([first, typed, last], make_settings(quote_split_window_claims=3)) == {}


def test_already_guarded_claims_keep_their_reason_in_a_window() -> None:
    first = vc(1, quote="Seneca said “one two three")
    last = vc(2, quote="four five six seven” and left")
    got = guard_reasons([first, last], make_settings())
    assert got[first.local_id] is GuardReason.ATTRIBUTION
    assert got[last.local_id] is GuardReason.QUOTE_SPAN


def test_window_setting_is_validated() -> None:
    with pytest.raises(ValueError, match="quote_split_window_claims"):
        make_settings(quote_split_window_claims=1)
