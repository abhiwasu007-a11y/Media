"""QUOTE-VERIFY: exact match, source rules, fake-quote guard, credits. Synthetic text only."""

# ruff: noqa: RUF001, PT018

from datetime import date
from pathlib import Path

import pytest

from agent_06_fact_checker.config import default_verdict_map
from agent_06_fact_checker.library.credits import (
    CreditProblem,
    UsedWork,
    WorkUse,
    check_credits,
    credit_line,
)
from agent_06_fact_checker.library.quotes import (
    QuoteAction,
    QuoteCheckResult,
    QuoteCode,
    QuoteSettings,
    QuoteSubmission,
    QuoteVerifier,
    find_exact,
    find_quoted_spans,
    normalise_quote_text,
    split_sections,
    unchecked_quotes,
)
from agent_06_fact_checker.library.reader import CheckoutLibraryReader, KnowledgeLibraryReader
from agent_06_fact_checker.models import ReasonCode, RevisionAction, Verdict
from amw_core.enums import ClaimStatus
from tests.agents.agent_06_fact_checker.library_support import (
    FILES,
    JOB_DATE,
    make_reader,
    records,
)

pytestmark = pytest.mark.unit
STRICT = QuoteSettings(require_locator=True, guard_min_words=4)
LOOSE = QuoteSettings(require_locator=False, guard_min_words=4)
AUTHOR = "Aelius Testor"


class SpyReader:
    """Wraps a real reader and records which paths were read."""

    def __init__(self, inner: CheckoutLibraryReader) -> None:
        self._inner = inner
        self.paths: list[str] = []

    @property
    def commit_sha(self) -> str:
        return self._inner.commit_sha

    def read_text(self, relative_path: str) -> str:
        self.paths.append(relative_path)
        return self._inner.read_text(relative_path)


def sub(
    text: str,
    *,
    work: str | None = "orig",
    loc: str | None = "I.1",
    author: str = AUTHOR,
    cid: str = "c1",
) -> QuoteSubmission:
    return QuoteSubmission(cid, text, author, work, loc)


def check(
    tmp_path: Path,
    s: QuoteSubmission,
    settings: QuoteSettings = STRICT,
    job_date: date = JOB_DATE,
) -> QuoteCheckResult:
    verifier = QuoteVerifier(records(), make_reader(tmp_path), settings)
    return verifier.verify([s], job_date=job_date)[0]


def test_exact_quote_with_reference_is_kept(tmp_path: Path) -> None:
    r = check(tmp_path, sub("It is not time we lack but the will to hold it."))
    assert (r.code, r.action, r.status) == (
        QuoteCode.VERIFIED_EXACT,
        QuoteAction.KEEP,
        ClaimStatus.VERIFIED,
    )
    assert r.locator_verified is True and r.reason is None and r.revision_action is None
    assert r.occurrences == 1 and r.match_start is not None and r.match_end is not None
    assert r.pd_reason is not None


def test_whitespace_and_quote_marks_are_normalised_only(tmp_path: Path) -> None:
    quote = 'Short life is a "borrowed" coat, said the clerk.'
    assert check(tmp_path, sub(quote, loc="II.1")).code is QuoteCode.VERIFIED_EXACT
    spaced = "Short  life \n is a “borrowed”  coat, said the clerk."
    assert check(tmp_path, sub(spaced, loc="II.1")).code is QuoteCode.VERIFIED_EXACT
    apostrophe = "He wore it's patches with pride."
    assert check(tmp_path, sub(apostrophe, loc="II.1")).code is QuoteCode.VERIFIED_EXACT


@pytest.mark.parametrize(
    "fake",
    [
        "It is not time we lack but the will to hold them.",  # one word changed
        "it is not time we lack but the will to hold it.",  # case
        "It is not time we lack, but the will to hold it.",  # punctuation added
        "It is not time we lack but the will to hold it...",  # ellipsis is literal
        "It is not time we lack but the wi​ll to hold it.",  # zero-width char
        "It is not time we lack but the will to hold it—",  # dash differs
        "It is not timе we lack but the will to hold it.",  # Cyrillic look-alike e
        "ime we lack but the will to hold it",  # starts inside a word
        "It is not time we lack but the will to hol",  # ends inside a word
        "A completely invented sentence about harbours.",
    ],
)
def test_changed_quote_is_a_fake_and_blocks_the_claim(tmp_path: Path, fake: str) -> None:
    r = check(tmp_path, sub(fake))
    assert r.code is QuoteCode.NOT_IN_SOURCE
    assert r.action is QuoteAction.BLOCK_CLAIM and r.status is ClaimStatus.CONTRADICTED
    assert r.reason is ReasonCode.QUOTE_NOT_ATTRIBUTABLE
    assert r.revision_action is RevisionAction.REMOVE_OR_REWORD


def test_quote_from_another_section_has_a_wrong_reference(tmp_path: Path) -> None:
    r = check(tmp_path, sub("A lamp unlit gives no account of the dark.", loc="I.1"))
    assert r.code is QuoteCode.LOCATOR_MISMATCH and r.action is QuoteAction.BLOCK_CLAIM


def test_unknown_reference_is_blocked_and_missing_reference_removed(tmp_path: Path) -> None:
    assert check(tmp_path, sub("A lamp unlit gives no account of the dark.", loc="IX.9")).code is (
        QuoteCode.LOCATOR_NOT_FOUND
    )
    missing = check(tmp_path, sub("A lamp unlit gives no account of the dark.", loc=None))
    assert (missing.code, missing.action) == (QuoteCode.LOCATOR_MISSING, QuoteAction.REMOVE_QUOTE)
    assert missing.status is ClaimStatus.NEEDS_SUBSTANTIATION


def test_reference_is_optional_only_when_configured(tmp_path: Path) -> None:
    ok = check(tmp_path, sub("A lamp unlit gives no account of the dark.", loc=None), LOOSE)
    assert ok.code is QuoteCode.VERIFIED_EXACT and ok.locator_verified is False
    bad = check(tmp_path, sub("A lamp that never existed.", loc=None), LOOSE)
    assert bad.code is QuoteCode.NOT_IN_SOURCE


def test_sections_are_found_by_marker_and_preface_is_no_section(tmp_path: Path) -> None:
    pre = "Preface line before any section marker."
    assert check(tmp_path, sub(pre, loc="I.1")).code is QuoteCode.NOT_IN_SOURCE
    assert check(tmp_path, sub(pre, loc=None), LOOSE).code is QuoteCode.NOT_IN_SOURCE


def test_text_without_markers_or_with_repeated_marker_cannot_verify_a_reference(
    tmp_path: Path,
) -> None:
    plain = check(tmp_path, sub("A plain text", work="plain", loc="1"))
    assert plain.code is QuoteCode.LOCATOR_UNVERIFIABLE and plain.action is QuoteAction.REMOVE_QUOTE
    dup = check(tmp_path, sub("First body line here.", work="dup", loc="A"))
    assert dup.code is QuoteCode.LOCATOR_UNVERIFIABLE


def test_misattribution_is_blocked(tmp_path: Path) -> None:
    r = check(
        tmp_path,
        sub("A lamp unlit gives no account of the dark.", author="Quintus Fictus", loc="I.2"),
    )
    assert r.code is QuoteCode.ATTRIBUTION_MISMATCH and r.action is QuoteAction.BLOCK_CLAIM
    same = check(
        tmp_path,
        sub("A lamp unlit gives no account of the dark.", author="  aelius   TESTOR ", loc="I.2"),
    )
    assert same.code is QuoteCode.VERIFIED_EXACT


def test_pd_translation_is_quotable(tmp_path: Path) -> None:
    s = sub("Every harbour was once an open shore.", work="trans", loc="1", author="Quintus Fictus")
    assert check(tmp_path, s).code is QuoteCode.VERIFIED_EXACT


def test_copyrighted_or_unknown_work_is_refused_and_its_text_is_never_read(tmp_path: Path) -> None:
    spy = SpyReader(make_reader(tmp_path))
    verifier = QuoteVerifier(records(), spy, STRICT)
    results = verifier.verify(
        [
            sub(
                "This sentence must never be read by the verifier.",
                work="modern",
                loc="1",
                author="Quintus Fictus",
                cid="a",
            ),
            sub("anything", work="unknown", loc="1", cid="b"),
            sub("anything", work="nonexistent", loc="1", cid="c"),
            sub("anything", work=None, loc="1", cid="d"),
            sub("   ", cid="e"),
        ],
        job_date=JOB_DATE,
    )
    assert [r.code for r in results] == [
        QuoteCode.NOT_PUBLIC_DOMAIN,
        QuoteCode.NOT_PUBLIC_DOMAIN,
        QuoteCode.NO_SOURCE,
        QuoteCode.NO_SOURCE,
        QuoteCode.EMPTY_QUOTE,
    ]
    assert [r.action for r in results[:2]] == [QuoteAction.BLOCK_CLAIM] * 2
    assert spy.paths == []  # no passage of a non-PD work is ever read


def test_public_domain_follows_the_job_date_year(tmp_path: Path) -> None:
    edge = records()["orig"].model_copy(update={"author_death_year": 1965})
    verifier = QuoteVerifier({"orig": edge}, make_reader(tmp_path), STRICT)
    s = sub("A lamp unlit gives no account of the dark.", loc="I.2")
    assert verifier.verify([s], job_date=date(2025, 12, 31))[0].code is QuoteCode.NOT_PUBLIC_DOMAIN
    assert verifier.verify([s], job_date=date(2026, 1, 1))[0].code is QuoteCode.VERIFIED_EXACT


def test_text_is_read_once_per_work(tmp_path: Path) -> None:
    spy = SpyReader(make_reader(tmp_path))
    verifier = QuoteVerifier(records(), spy, STRICT)
    verifier.verify(
        [
            sub("A lamp unlit gives no account of the dark.", loc="I.2", cid=str(i))
            for i in range(3)
        ],
        job_date=JOB_DATE,
    )
    assert spy.paths == ["phil/original.txt"]


def test_results_carry_no_source_or_quote_text(tmp_path: Path) -> None:
    quote = "It is not time we lack but the will to hold it."
    r = check(tmp_path, sub(quote))
    dumped = r.model_dump_json()
    for line in FILES["phil/original.txt"].splitlines():
        assert len(line) < 12 or line not in dumped
    assert quote not in dumped and "river of days" not in dumped
    assert len(r.quote_sha256) == 64
    assert isinstance(SpyReader(make_reader(tmp_path)), KnowledgeLibraryReader)


def test_result_maps_into_the_existing_agent_06_verdicts(tmp_path: Path) -> None:
    verdicts = default_verdict_map()
    ok = check(tmp_path, sub("A lamp unlit gives no account of the dark.", loc="I.2"))
    fake = check(tmp_path, sub("A lamp made up.", loc="I.2"))
    removed = check(tmp_path, sub("A lamp made up.", loc=None))
    assert verdicts[ok.status] is Verdict.ALLOWED
    assert verdicts[fake.status] is Verdict.BLOCKED
    assert verdicts[removed.status] is Verdict.NEEDS_HUMAN_REVIEW


def test_matching_helpers() -> None:
    assert normalise_quote_text("  a  b\n\tc ") == "a b c"
    assert find_exact("abc def abc", "abc") == (0, 3, 2)
    assert find_exact("xabc abc", "abc") == (5, 8, 1)
    assert find_exact("abc", "") is None
    sections = split_sections("§ 1\nalpha\n§  2 \nbeta\ngamma\n")
    assert dict(sections.by_locator) == {"1": "alpha", "2": "beta gamma"}


SCRIPT = (
    "He said “It is not time we lack but the will to hold it.” and then "
    '"a made up line of four words" and also «another invented line for the guard», '
    'plus "short one".'
)


def test_fake_quote_guard_flags_every_unchecked_long_quote() -> None:
    checked = [sub("It is not time we lack but the will to hold it.")]
    spans = find_quoted_spans(SCRIPT)
    assert [s.words for s in spans] == [12, 7, 6, 2]
    flagged = unchecked_quotes(SCRIPT, checked, min_words=4)
    assert [SCRIPT[s.start : s.end] for s in flagged] == [
        "a made up line of four words",
        "another invented line for the guard",
    ]
    assert unchecked_quotes(SCRIPT, checked, min_words=1)[-1].words == 2
    assert unchecked_quotes(SCRIPT, [], min_words=13) == []


def test_guard_accepts_whitespace_and_quote_variants_of_a_checked_quote() -> None:
    script = 'He said "It is   not time we lack but the will to hold it." today.'
    assert (
        unchecked_quotes(
            script, [sub("It is not time we lack but the will to hold it.")], min_words=3
        )
        == []
    )


def test_credit_lines_and_further_reading(tmp_path: Path) -> None:
    recs = records()
    trans = credit_line(recs["trans"], WorkUse.QUOTED)
    assert trans == "Quintus Fictus, On trans, translated by Mary Invented, 1890. Public domain."
    assert credit_line(recs["orig"], WorkUse.QUOTED) == "Aelius Testor, On orig. Public domain."
    further = credit_line(recs["modern"], WorkUse.IDEAS_ONLY)
    assert (
        further
        == "Further reading: Quintus Fictus, On modern, translated by Living Translator, 1985."
    )
    desc = f"Video about time.\n\n{trans}\n{further}"
    used = [UsedWork("trans", WorkUse.QUOTED), UsedWork("modern", WorkUse.IDEAS_ONLY)]
    assert check_credits(used, recs, desc, job_date=JOB_DATE) == []


def test_credit_findings(tmp_path: Path) -> None:
    recs = records()
    used = [
        UsedWork("modern", WorkUse.QUOTED),
        UsedWork("trans", WorkUse.QUOTED),
        UsedWork("modern", WorkUse.IDEAS_ONLY),
        UsedWork("ghost", WorkUse.IDEAS_ONLY),
    ]
    found = check_credits(used, recs, "Nothing credited here.", job_date=JOB_DATE)
    assert [(f.work_id, f.problem) for f in found] == [
        ("modern", CreditProblem.QUOTED_WORK_NOT_PUBLIC_DOMAIN),
        ("trans", CreditProblem.CREDIT_MISSING),
        ("modern", CreditProblem.CREDIT_MISSING),
        ("ghost", CreditProblem.UNKNOWN_WORK),
    ]
    assert not check_credits(
        [UsedWork("trans", WorkUse.QUOTED)], recs, "no translator named", job_date=JOB_DATE
    )[0:0]


def test_translator_name_is_required_in_the_credit(tmp_path: Path) -> None:
    recs = records()
    partial = "Quintus Fictus, On trans. Public domain."
    found = check_credits([UsedWork("trans", WorkUse.QUOTED)], recs, partial, job_date=JOB_DATE)
    assert [f.problem for f in found] == [CreditProblem.CREDIT_MISSING]
