"""Unit tests of the pure functions of blueprint 10 (U-01 ... U-38)."""

# ruff: noqa: PT018

from datetime import date

import pytest

from agent_06_fact_checker.batches import build_batches
from agent_06_fact_checker.config import FactCheckSettings, VerifyPolicy
from agent_06_fact_checker.conflicts import find_pairs
from agent_06_fact_checker.evidence import Candidate, ClaimEvidence
from agent_06_fact_checker.extraction import (
    apply_flags,
    batch_segments,
    claim_verdict,
    recompute,
    structural_problems,
    with_flag,
)
from agent_06_fact_checker.lexicon import all_markers, find_marker, find_patterns, find_urls
from agent_06_fact_checker.models import (
    ChartDataRef,
    ChartFacts,
    ClaimMode,
    DataAge,
    EvidenceSourceKind,
    ExtractedClaim,
    ExtractionInput,
    ReasonCode,
    Segment,
    Verdict,
    VerificationClaim,
    VerifyMode,
    most_severe,
)
from agent_06_fact_checker.numbers import missing_numerals, numerals
from agent_06_fact_checker.planner import plan_claims, reject_blocked_input
from agent_06_fact_checker.price_age import classify, resolve_chart_ages, stricter
from agent_06_fact_checker.scan import scan_correction
from agent_06_fact_checker.windows import window
from amw_core.enums import ClaimType, RuleSeverity
from amw_core.errors import ConfigInvalidError, InputInvalidError
from tests.agents.agent_06_fact_checker.support import (
    SCRIPT,
    TEST_MARKERS,
    make_settings,
)

pytestmark = pytest.mark.unit
CLM = "clm_0192f5b0-0000-7000-8000-0000000000{:02x}"


def ex_claim(**over: object) -> ExtractedClaim:
    base: dict[str, object] = {
        "local_id": "c1",
        "segment_id": "s1",
        "char_start": 0,
        "char_end": 5,
        "quote": "hello",
        "normalized_claim": "hello",
        "claim_type": "FACTUAL",
        "time_reference_kind": "TIMELESS",
        "instrument": None,
        "chart_data_ref": None,
        "requires_citation": False,
        "citation_refs": [],
        "rule_flags": [],
        "proposed_verdict": "ALLOWED",
        "rationale": "r",
    }
    base.update(over)
    return ExtractedClaim.model_validate(base)


def v_claim(n: int, ctype: str = "FACTUAL", **over: object) -> VerificationClaim:
    base: dict[str, object] = {
        "claim_id": CLM.format(n),
        "local_id": f"c{n}",
        "segment_id": "s1",
        "quote": "q",
        "normalized_claim": "the price rises on monday",
        "claim_type": ctype,
        "time_reference_kind": "TIMELESS",
        "instrument": None,
        "chart_data_ref": None,
        "requires_citation": True,
        "citation_refs": [],
        "extraction_verdict": "ALLOWED",
    }
    base.update(over)
    return VerificationClaim.model_validate(base)


# ---------------------------------------------------------------- D0
def test_u01_price_age_boundaries() -> None:
    end = date(2026, 1, 1)
    assert classify(date(2026, 1, 31), date(2026, 1, 31), 30) is DataAge.WITHIN_LAG
    assert classify(end, date(2026, 1, 31), 30) is DataAge.OLDER_THAN_LAG  # exactly the lag
    assert classify(end, date(2026, 1, 30), 30) is DataAge.WITHIN_LAG
    assert classify(None, date(2026, 1, 30), 30) is DataAge.UNKNOWN
    with pytest.raises(ConfigInvalidError):
        classify(end, end, -1)


def test_u01_never_more_permissive_and_basis_rules() -> None:
    assert stricter(DataAge.OLDER_THAN_LAG, DataAge.WITHIN_LAG) is DataAge.WITHIN_LAG
    assert stricter(DataAge.WITHIN_LAG, DataAge.OLDER_THAN_LAG) is DataAge.WITHIN_LAG
    assert stricter(None, DataAge.UNKNOWN) is DataAge.UNKNOWN
    assert stricter(DataAge.UNKNOWN, None) is DataAge.UNKNOWN
    refs = (
        ChartDataRef(ref_id="chart_1", instrument="N", data_age_vs_lag=DataAge.OLDER_THAN_LAG),
        ChartDataRef(
            ref_id="chart_2",
            instrument="N",
            data_age_vs_lag=DataAge.OLDER_THAN_LAG,
            data_age_basis="CONSTRAINT",
        ),
        ChartDataRef(ref_id="chart_3", instrument="N", data_age_vs_lag=None),
        ChartDataRef(ref_id="chart_4", instrument="N", data_age_vs_lag=DataAge.OLDER_THAN_LAG),
    )
    ends = {
        "chart_1": date(2026, 11, 10),  # measured: 8 days old, supplied claims it is old
        "chart_2": date(2026, 11, 10),  # constraint: kept
        "chart_3": date(2026, 11, 10),  # schematic: kept null
    }
    out = {
        r.ref_id: r.data_age_vs_lag for r in resolve_chart_ages(refs, ends, date(2026, 11, 18), 30)
    }
    assert out == {
        "chart_1": DataAge.WITHIN_LAG,
        "chart_2": DataAge.OLDER_THAN_LAG,
        "chart_3": None,
        "chart_4": DataAge.OLDER_THAN_LAG,  # no known range end: supplied value kept
    }
    with pytest.raises(ConfigInvalidError):
        resolve_chart_ages(refs, {}, date(2026, 11, 18), 30, "TRADING_DAYS")


# ---------------------------------------------------------------- lexicon
def test_marker_matching_is_whole_word_and_lexicon_driven() -> None:
    markers = all_markers(TEST_MARKERS)
    assert find_marker("the target was reached", markers) == "target"
    assert find_marker("a targeted approach", markers) is None
    assert find_marker("it WILL double", markers) == "will"
    assert find_marker("likely  to rise", markers) is None  # double space is a different phrase
    assert find_marker("anything", ()) is None  # no lexicon, no hit: nothing is hard-coded
    assert find_marker("कधी target गाठला", all_markers({"mr": ("target", "")})) == "target"


def test_marker_boundary_respects_devanagari_combining_marks() -> None:
    markers = all_markers({"mr": ("होईल",)})
    assert find_marker("तो वाढ होईल आज", markers) == "होईल"
    assert find_marker("तो वाढ होईलच", markers) is None


def test_urls_and_referral_patterns() -> None:
    text = "go to https://x.example/ref?c=1 or www.broker.in/open or broker.com now code: AB12CD"
    assert len(find_urls(text)) == 3
    assert find_patterns(text, [r"\bcode[:=]\s?[A-Z0-9]{4,}\b"])
    assert not find_urls("plain words only. e.g. nothing")


# ---------------------------------------------------------------- D1-D11 helpers
def test_u02_batching_never_splits_a_segment() -> None:
    segs = [Segment(segment_id=f"s{i}", text="x" * 40, visual_refs=[]) for i in range(1, 6)]
    batches = batch_segments(segs, 100)
    assert [len(b.segments) for b in batches] == [2, 2, 1]
    assert [s.segment_id for b in batches for s in b.segments] == [s.segment_id for s in segs]
    assert len(batch_segments(segs[:1], 10)) == 1  # oversize single segment: own batch


def test_flags_are_only_raised_never_lowered() -> None:
    flags = with_flag((), "FIN-R9", RuleSeverity.WARNING, "x")
    assert (
        with_flag(flags, "FIN-R9", RuleSeverity.BLOCKING, "y")[0].severity is RuleSeverity.BLOCKING
    )
    blocking = with_flag((), "FIN-R9", RuleSeverity.BLOCKING, "x")
    assert with_flag(blocking, "FIN-R9", RuleSeverity.WARNING, "y") == blocking
    assert with_flag((), "FIN-R8", RuleSeverity.WARNING, "  ")[0].evidence == "FIN-R8"


def test_u05_u06_verdict_recomputation() -> None:
    cited = ex_claim(requires_citation=True, citation_refs=["kch_x"])
    assert claim_verdict(cited) is Verdict.ALLOWED
    assert claim_verdict(ex_claim(requires_citation=True)) is Verdict.NEEDS_HUMAN_REVIEW
    warn = ex_claim(rule_flags=[{"rule_id": "FIN-R8", "severity": "WARNING", "evidence": "e"}])
    assert claim_verdict(warn) is Verdict.NEEDS_HUMAN_REVIEW
    block = ex_claim(rule_flags=[{"rule_id": "FIN-R1", "severity": "BLOCKING", "evidence": "e"}])
    assert claim_verdict(block) is Verdict.BLOCKED
    out, overall, changed = recompute([cited, warn, block], ["s2"])
    assert overall.proposed_verdict is Verdict.BLOCKED
    assert overall.blocking_rule_ids == ("FIN-R1",)
    assert changed == 2  # the model said ALLOWED for the warning and the blocking claim
    assert [c.proposed_verdict for c in out] == [
        Verdict.ALLOWED,
        Verdict.NEEDS_HUMAN_REVIEW,
        Verdict.BLOCKED,
    ]
    _, only_unattached, _ = recompute([cited], ["s2"])
    assert only_unattached.proposed_verdict is Verdict.NEEDS_HUMAN_REVIEW  # never silently ALLOWED
    assert most_severe() is Verdict.ALLOWED


def test_structural_problems_name_ids_not_text() -> None:
    segs = {"s1": Segment(segment_id="s1", text="hello world", visual_refs=[])}
    bad = [
        ex_claim(quote="hellX"),
        ex_claim(local_id="c2", char_end=99, quote="hello"),
        ex_claim(local_id="c2", segment_id="s9"),
        ex_claim(local_id="c3", chart_data_ref="chart_9"),
        ex_claim(local_id="c4", citation_refs=["nope"]),
    ]
    problems = structural_problems(bad, segs, frozenset({"chart_1"}), frozenset({"kch_a"}))
    assert len(problems) == 6
    assert not any("hellX" in p for p in problems)
    assert structural_problems([ex_claim()], segs, frozenset(), frozenset()) == []


def test_d10_drops_fin_flags_when_finance_pack_is_inactive() -> None:
    inp = ExtractionInput.model_validate(
        {
            "script_id": SCRIPT,
            "script_version": 1,
            "language": "en",
            "channel_category": "general",
            "owner_sebi_registration": "UNREGISTERED",
            "active_rule_packs": ["rp.youtube_general"],
            "segments": [{"segment_id": "s1", "text": "hello", "visual_refs": []}],
            "chart_data_refs": [],
            "available_citations": [],
            "our_method_release_approved": False,
        }
    )
    claim = ex_claim(
        rule_flags=[
            {"rule_id": "FIN-R1", "severity": "BLOCKING", "evidence": "e"},
            {"rule_id": "YTG-R1", "severity": "WARNING", "evidence": "e"},
        ]
    )
    out, unattached, dropped = apply_flags([claim], inp, {}, {}, None, make_settings())
    assert dropped == 1 and unattached == []
    assert [f.rule_id for f in out[0].rule_flags] == ["YTG-R1"]


# ---------------------------------------------------------------- numbers (U-26)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("24,000 and 1,00,000", ["24000", "100000"]),
        ("२५% आणि ३३.३", ["25", "33.3"]),
        ("ratio 2:1 holds", ["2:1"]),
        ("RSI 14, 1,2", ["14", "1", "2"]),
        ("no digits", []),
    ],
)
def test_u26_numerals(text: str, expected: list[str]) -> None:
    assert [n.text for n in numerals(text)] == expected


def test_u26_guard_rounding_and_ratio() -> None:
    claim = numerals("33% of 2:1 setups")
    assert missing_numerals(claim, ["about 33.3 percent, ratio 2:1"], True) == []
    assert [n.text for n in missing_numerals(claim, ["about 33.3 percent, ratio 2:1"], False)] == [
        "33"
    ]
    assert [n.text for n in missing_numerals(numerals("25%"), ["one in four"], True)] == ["25"]
    assert [n.text for n in missing_numerals(numerals("2:1"), ["a 3:1 ratio"], True)] == ["2:1"]
    assert missing_numerals(numerals("50"), ["50.0"], True) == []
    assert [n.text for n in missing_numerals(numerals("33.35"), ["33.3"], True)] == ["33.35"]


# ---------------------------------------------------------------- windows (U-23)
def test_u23_windows_keep_offsets_and_pick_overlap() -> None:
    sentences = [f"Filler sentence number {i} says nothing." for i in range(30)]
    sentences[17] = "Stop loss orders close positions automatically."
    text = " ".join(sentences)
    wins = window(text, {"stop", "loss", "positions"}, 200, 1)
    assert len(wins) == 1
    assert "Stop loss" in wins[0].text
    assert text[wins[0].offset : wins[0].offset + len(wins[0].text)] == wins[0].text
    assert window("short text", set(), 200, 3)[0].offset == 0
    long_sentence = "x" * 500
    assert all(len(w.text) <= 200 for w in window(long_sentence, set(), 200, 5))


# ---------------------------------------------------------------- scan (U-29)
def test_u29_correction_scanner() -> None:
    advice = {"en": ("buy", "sell")}
    assert scan_correction("see https://x.example", [], advice) == ["URL"]
    assert scan_correction("use code: ABCD12", [r"code: \w+"], advice) == ["REFERRAL"]
    assert scan_correction("target is ₹ 24,000", [], advice) == ["PRICE_LEVEL"]
    assert scan_correction("you should buy now", [], advice) == ["ADVICE_WORD"]
    assert (
        scan_correction("The source states the win rate is about one in three.", [], advice) == []
    )


# ---------------------------------------------------------------- conflicts (U-37)
def test_u37_conflict_candidates_are_recall_oriented() -> None:
    s = make_settings()
    a = v_claim(1, normalized_claim="the break-even win rate is 33 percent")
    b = v_claim(2, normalized_claim="the break-even win rate is 50 percent")
    c = v_claim(3, normalized_claim="the index rises above resistance often")
    d = v_claim(4, normalized_claim="the index falls below resistance often")
    e = v_claim(5, normalized_claim="the break-even win rate is not 33 percent")
    f = v_claim(6, normalized_claim="completely unrelated sentence here")
    pairs = find_pairs([a, b, c, d, e, f], s)
    assert ("c1", "c2") in pairs  # numeral differs
    assert ("c3", "c4") in pairs  # opposite pair above / below
    assert ("c1", "c5") in pairs  # negation differs
    assert all("c6" not in p for p in pairs)
    assert find_pairs([a, b], make_settings(conflict_max_pairs=0)) == []
    opp = find_pairs(
        [
            v_claim(1, normalized_claim="price rises above the level"),
            v_claim(2, normalized_claim="price falls below the level"),
        ],
        make_settings(conflict_opposites={"en": [["rises", "falls"]]}),
    )
    assert opp == [("c1", "c2")]


# ---------------------------------------------------------------- planner (U-20, U-42)
def test_u20_policy_table_modes() -> None:
    s = make_settings()
    facts = {
        "chart_1": ChartFacts.model_validate(
            {
                "ref_id": "chart_1",
                "instrument": "N",
                "facts": [{"fact_id": "f01", "statement": "s"}],
            }
        )
    }
    claims = [
        v_claim(1, "FACTUAL"),
        v_claim(2, "RECOMMENDATION"),
        v_claim(3, "HISTORICAL_MARKET", chart_data_ref="chart_1"),
        v_claim(4, "HISTORICAL_MARKET"),
        v_claim(5, "OPINION", requires_citation=False),
        v_claim(6, "OPINION", requires_citation=True),
        v_claim(7, "QUOTED_THIRD_PARTY"),
        v_claim(8, "QUOTED_THIRD_PARTY", citation_refs=["kch_a"]),
    ]
    modes = [(p.mode, p.reason) for p in plan_claims(claims, VerifyMode.EVIDENCE, s, facts)]
    assert modes == [
        (ClaimMode.EVIDENCE, None),
        (ClaimMode.SKIPPED, ReasonCode.SKIPPED_BY_POLICY),
        (ClaimMode.SKIPPED, ReasonCode.CHART_PENDING),
        (ClaimMode.EVIDENCE, None),
        (ClaimMode.SKIPPED, ReasonCode.SKIPPED_BY_POLICY),
        (ClaimMode.EVIDENCE, None),
        (ClaimMode.CODE_ONLY, ReasonCode.QUOTE_NOT_ATTRIBUTABLE),
        (ClaimMode.EVIDENCE, None),
    ]
    chart = plan_claims([claims[2]], VerifyMode.CHART_FACTS, s, facts)[0]
    assert chart.mode is ClaimMode.CHART_FACTS
    nofacts = plan_claims([claims[2]], VerifyMode.CHART_FACTS, s, {})[0]
    assert (nofacts.mode, nofacts.reason) == (ClaimMode.CODE_ONLY, ReasonCode.NO_CHART_FACTS)


def test_policy_table_must_be_complete() -> None:
    table = {t: VerifyPolicy.SKIPPED for t in ClaimType if t is not ClaimType.OPINION}
    with pytest.raises(ConfigInvalidError):
        make_settings(policy=table)
    with pytest.raises(ConfigInvalidError):
        make_settings(min_tier_for_verified="Z")
    with pytest.raises(ConfigInvalidError):
        make_settings(tier_order=["A_PRIMARY", "A_PRIMARY"])


def test_u42_blocked_input_and_shape_rejections() -> None:
    good = [v_claim(1)]
    reject_blocked_input(good, "ALLOWED", VerifyMode.EVIDENCE)
    with pytest.raises(InputInvalidError):
        reject_blocked_input(good, "BLOCKED", VerifyMode.EVIDENCE)
    with pytest.raises(InputInvalidError):
        reject_blocked_input(
            [v_claim(1, extraction_verdict="BLOCKED")], "ALLOWED", VerifyMode.EVIDENCE
        )
    with pytest.raises(InputInvalidError):
        reject_blocked_input([], "ALLOWED", VerifyMode.EVIDENCE)
    reject_blocked_input(
        [], "ALLOWED", VerifyMode.CHART_FACTS
    )  # nothing to check: succeeds at once
    with pytest.raises(InputInvalidError):
        reject_blocked_input(good, "ALLOWED", VerifyMode.CHART_FACTS)


def test_tier_floor_uses_unranked_tier_for_missing_tier() -> None:
    s: FactCheckSettings = make_settings()
    assert s.meets_tier_floor("A_PRIMARY") and s.meets_tier_floor("C_SECONDARY")
    assert not s.meets_tier_floor("D_UNVERIFIED")
    assert not s.meets_tier_floor(None)  # CCR-053: no tier counts as D_UNVERIFIED


# ---------------------------------------------------------------- batches (U-30)
def test_u30_pair_members_share_a_batch_and_ids_are_code_assigned() -> None:
    s = make_settings(max_claims_per_call=2)
    plans = plan_claims([v_claim(i) for i in range(1, 6)], VerifyMode.EVIDENCE, s, {})

    def ev(n: int) -> ClaimEvidence:
        cand = Candidate(
            f"kch_{n}",
            EvidenceSourceKind.KNOWLEDGE_CHUNK,
            0,
            "text",
            4,
            "a" * 64,
            None,
            False,
            True,
        )
        return ClaimEvidence(candidates=[cand])

    sendable = [(p, ev(i)) for i, p in enumerate(plans)]
    batches = build_batches(sendable, [("c1", "c5")], s)
    homes = {lid: b.index for b in batches for lid in b.local_ids}
    assert homes["c1"] == homes["c5"]
    assert all(len(b.local_ids) <= 2 or {"c1", "c5"} <= set(b.local_ids) for b in batches)
    first = batches[0]
    assert sorted(first.evidence) == [f"p{i:02d}" for i in range(1, len(first.evidence) + 1)]
