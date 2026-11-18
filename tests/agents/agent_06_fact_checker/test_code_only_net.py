"""The code-only safety net: what code decides when the model says nothing, refuses or is wrong.

Acceptance test (review of PR #32): with the model replaced by one that returns NOTHING (no claims,
no flags, or ALLOWED), the four directive 1B.2 answer-key cases and the IN-03 cases produce their
expected verdicts from the deterministic path alone, in English, Marathi and Hinglish, also with
zero-width and width evasions of the lexicon words.
"""

# ruff: noqa: E501, PT018, RUF001

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

from agent_06_fact_checker import ClaimExtractionStep
from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.detect import Finding, chart_findings, quoted_ranges, sentences
from agent_06_fact_checker.extraction import refusal_effect
from agent_06_fact_checker.lexicon import find_marker, normalise_for_matching, suffix_families
from agent_06_fact_checker.models import ChartDataRef, DataAge, Refusal
from agent_06_fact_checker.price_age import recheck_lag_at
from agent_06_fact_checker.rulepack import ensure_lexicon, required_languages
from amw_core.enums import OutputStatus, RuleSeverity
from amw_core.errors import ConfigInvalidError
from tests.agents.agent_06_fact_checker.eval_support import load_cases
from tests.agents.agent_06_fact_checker.recorded_extraction import recorded_response
from tests.agents.agent_06_fact_checker.support import (
    NOW,
    SCRIPT_SHA,
    DocPrompts,
    FixedRanges,
    MemoryScripts,
    RecordedLlm,
    StaticPacks,
    World,
    extraction_step,
    make_settings,
    ranges_for,
    run_context,
    task_input,
)

CASES = load_cases("claim_extraction")
pytestmark = pytest.mark.unit
ALLOWED_OVERALL = {
    "proposed_verdict": "ALLOWED",
    "blocking_rule_ids": [],
    "needs_human_review_reasons": [],
}


def nothing(_: dict[str, Any]) -> str:
    return json.dumps({"claims": [], "overall": ALLOWED_OVERALL, "refusal": None})


def unflagged(case: dict[str, Any]) -> str:
    """The model extracts every sentence as an innocent ALLOWED OPINION claim with no flag."""
    claims: list[dict[str, Any]] = []
    for seg in case["segments"]:
        text = seg["text"]
        quote = text.rstrip(".")
        claims.append(
            {
                "local_id": f"c{len(claims) + 1}",
                "segment_id": seg["segment_id"],
                "char_start": 0,
                "char_end": len(quote),
                "quote": quote,
                "normalized_claim": "x",
                "claim_type": "OPINION",
                "time_reference_kind": "TIMELESS",
                "instrument": None,
                "chart_data_ref": None,
                "requires_citation": False,
                "citation_refs": [],
                "rule_flags": [],
                "proposed_verdict": "ALLOWED",
                "rationale": "r",
            }
        )
    return json.dumps({"claims": claims, "overall": ALLOWED_OVERALL, "refusal": None})


SILENT: dict[str, Callable[[dict[str, Any]], str]] = {"empty": nothing, "unflagged": unflagged}


def build(
    text: str | list[str], *, language: str = "en-IN", base: str = "AK-01", **over: Any
) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(json.dumps(CASES[base]["input"]))
    texts = [text] if isinstance(text, str) else text
    data["segments"] = [
        {
            "segment_id": f"s{i}",
            "text": t,
            "visual_refs": data["segments"][0]["visual_refs"] if i == 1 else [],
        }
        for i, t in enumerate(texts, 1)
    ]
    data["language"] = language
    data.update(over)
    return data


def verdict_of(
    data: dict[str, Any], respond: Callable[[dict[str, Any]], str], **kw: Any
) -> tuple[str, Any]:
    world = World(llm=RecordedLlm([respond(data)]))
    task = task_input(
        "agent_06.claim_extraction.input", data, version="1.1.0", script_sha=SCRIPT_SHA
    )
    kw.setdefault("chart_ranges", ranges_for(data))
    out = extraction_step(world, **kw).run(task, run_context())
    assert out.status is OutputStatus.SUCCEEDED, out.error
    assert out.payload is not None and out.payload.data is not None
    return out.payload.data["overall"]["proposed_verdict"], out


ENGLISH = {
    "AK-01": "ALLOWED",
    "AK-02": "BLOCKED",
    "AK-03": "BLOCKED",
    "AK-04": "BLOCKED",
    "EDGE-31": "BLOCKED",
    "HN-32": "NEEDS_HUMAN_REVIEW",
    "HN-33": "NEEDS_HUMAN_REVIEW",
}
MARATHI = {
    "AK-01": (
        "जुन्या NIFTY चार्टवर किंमत खालचा तळ करत होती, पण RSI वरचा तळ करत होता. यानंतर तेजी आली, पण नंतर तोच पॅटर्न अपयशी ठरला.",
        "ALLOWED",
    ),
    "AK-02": ("NIFTY कमकुवत दिसतोय, या आठवड्यात २४,००० चा कॉल विका.", "BLOCKED"),
    "AK-03": ("माझ्या स्ट्रॅटेजीने गेल्या महिन्यात १८% कमावले.", "BLOCKED"),
    "AK-04": ("ब्रोकर Y कडे खाते उघडा, ही लिंक वापरा: https://example.com/ref?code=AMW10", "BLOCKED"),
    "EDGE-31": (
        "या जुन्या BANKNIFTY चार्टवर डबल बॉटम नंतर तेजी आली, तोच पॅटर्न पुन्हा दिसतोय, म्हणून BANKNIFTY पुन्हा वाढेल.",
        "BLOCKED",
    ),
    "HN-32": (
        "या जुन्या BANKNIFTY चार्टवर डबल बॉटम नंतर तेजी आली. हा पॅटर्न तेव्हा कसा दिसत होता हे यातून कळते; BANKNIFTY पुढे काय करेल हे यातून सांगता येत नाही.",
        "NEEDS_HUMAN_REVIEW",
    ),
    "HN-33": ("या जुन्या NIFTY चार्टवर पॅटर्नचे लक्ष्य काही आठवड्यांनी गाठले गेले.", "NEEDS_HUMAN_REVIEW"),
}
HINGLISH = {
    "AK-02": ("Nifty kamzor lag raha hai, is hafte 24000 ka call becho.", "BLOCKED"),
    "AK-03": ("Meri strategy ne pichhle mahine 18% profit kamaya.", "BLOCKED"),
    "AK-04": (
        "Broker Y mein account kholo, open an account via meri link: https://example.com/ref?code=AMW10",
        "BLOCKED",
    ),
    "EDGE-23": ("Kal Bank Nifty ka 52000 put kharid lo, pakka profit hoga.", "BLOCKED"),
}


@pytest.mark.parametrize("silent", sorted(SILENT))
@pytest.mark.parametrize("case_id", sorted(ENGLISH))
def test_acceptance_english_answer_key_and_in03_without_a_model(case_id: str, silent: str) -> None:
    case = CASES[case_id]
    verdict, _ = verdict_of(case["input"], SILENT[silent])
    assert verdict == ENGLISH[case_id], case_id


@pytest.mark.parametrize("silent", sorted(SILENT))
@pytest.mark.parametrize("case_id", sorted(MARATHI))
def test_acceptance_marathi_variants_without_a_model(case_id: str, silent: str) -> None:
    text, expected = MARATHI[case_id]
    base = case_id if CASES[case_id]["input"]["segments"][0]["visual_refs"] else "AK-02"
    data = build(text, language="mr-IN", base=base)
    verdict, _ = verdict_of(data, SILENT[silent])
    assert verdict == expected, case_id


@pytest.mark.parametrize("case_id", sorted(HINGLISH))
def test_acceptance_hinglish_variants_without_a_model(case_id: str) -> None:
    text, expected = HINGLISH[case_id]
    verdict, _ = verdict_of(build(text, language="hi-Latn", base="AK-02"), nothing)
    assert verdict == expected, case_id


@pytest.mark.parametrize(
    "text",
    [
        "Bu​y NIFTY now.",  # ZWSP inside the word
        "B‌uy NIFTY now.",  # ZWNJ
        "Bu⁠y NIFTY now.",  # word joiner
        "Ｂｕｙ NIFTY now.",  # full-width letters
        "BUY NIFTY now.",
        "buying NIFTY now.",  # inflection
        "NIFTY looks weak, sel﻿l the 24,000 call this week.",  # BOM
    ],
)
def test_evasions_of_the_lexicon_do_not_hide_a_call(text: str) -> None:
    verdict, _ = verdict_of(build(text, base="AK-02"), nothing)
    assert verdict == "BLOCKED", text


@pytest.mark.parametrize(
    "text",
    [
        "NIFTY उद्या २४,००० कॉल वि‌का.",  # ZWNJ inside विका
        "NIFTY नक्की वाढेलच.",  # clitic च after a marker (BLOCKING future direction)
        "NIFTY नक्की वाढेलही.",
        "माझ्या स्ट्रॅटेजीने १८% न‌फा कमावला.",  # ZWNJ inside नफा; performance claim
    ],
)
def test_marathi_zero_width_and_clitics(text: str) -> None:
    verdict, _ = verdict_of(build(text, language="mr-IN", base="AK-02"), nothing)
    assert verdict == "BLOCKED", text


ZW = "\u034f"  # combining grapheme joiner
VS = "\ufe0f"  # variation selector 16
ACUTE = "\u0301"  # stacked combining diacritic
RLO = "\u202e"  # bidi override
TAG = "\U000e0041"  # tag character
CYR_U = "\u0443"  # Cyrillic small u (looks like Latin y)
CYR_O = "\u043e"  # Cyrillic small o
CYR_T = "\u0422"  # Cyrillic capital Te (looks like Latin T)
CYR_I = "\u0456"  # Cyrillic small byelorussian-ukrainian i


@pytest.mark.parametrize("mark", [ZW, VS, ACUTE, RLO, TAG, "\u200b", "\u200c"])
def test_english_evasions_with_a_silent_model(mark: str) -> None:
    for text in (
        f"Bu{mark}y NIFTY now.",
        f"NIFTY looks weak, se{mark}ll the 24,000 call this week.",
        f"My strat{mark}egy made 18% last month.",
        f"BANKNIFTY sho{mark}uld rally again from here.",
    ):
        assert verdict_of(build(text, base="AK-02"), nothing)[0] == "BLOCKED", text


def test_english_cyrillic_lookalike_inside_words_with_a_silent_model() -> None:
    for text in (
        f"Bu{CYR_U} NIFTY now.",  # Buy with a Cyrillic u-like final letter
        f"NIF{CYR_T}Y looks weak, sell the 24,000 call this week.",  # instrument spelled with Te
        f"BANKNIFTY sh{CYR_O}uld rally again from here.",
        f"Buy NIF{CYR_T}Y tomorrow.",
    ):
        assert verdict_of(build(text, base="AK-02"), nothing)[0] == "BLOCKED", text


@pytest.mark.parametrize("mark", [ZW, VS, ACUTE, RLO, TAG, "\u200b", "\u200c"])
def test_marathi_and_hinglish_evasions_with_a_silent_model(mark: str) -> None:
    marathi = (
        f"NIFTY उद्या २४,००० कॉल वि{mark}का.",
        f"माझ्या स्ट्रॅटेजीने १८% न{mark}फा कमावला.",
        f"NIFTY नक्की वाढे{mark}लच.",
    )
    for text in marathi:
        assert verdict_of(build(text, language="mr-IN", base="AK-02"), nothing)[0] == "BLOCKED", (
            text
        )
    hinglish = (
        f"Kal Bank Nifty ka 52000 put khar{mark}id lo, pakka profit hoga.",
        f"Meri strategy ne pichhle mahine 18% prof{mark}it kamaya.",
    )
    for text in hinglish:
        assert verdict_of(build(text, language="hi-Latn", base="AK-02"), nothing)[0] == "BLOCKED", (
            text
        )


def test_hinglish_and_marathi_cyrillic_lookalikes_with_a_silent_model() -> None:
    hinglish = f"Kal Bank Nifty ka 52000 put khar{CYR_I}d lo, pakka profit hoga."
    assert verdict_of(build(hinglish, language="hi-Latn", base="AK-02"), nothing)[0] == "BLOCKED"
    marathi = f"NIF{CYR_T}Y उद्या २४,००० कॉल विका."
    assert verdict_of(build(marathi, language="mr-IN", base="AK-02"), nothing)[0] == "BLOCKED"


def test_education_stays_allowed() -> None:
    texts = [
        "A stop-loss is a pre-decided price at which a trader exits a losing position to limit the loss.",
        "Suppose a call option has a strike price of 100 and the premium paid is 5; the buyer breaks even at 105 on expiry, ignoring costs.",
        "Many social media posts say 'buy now before it is too late'; in this video we look at why such tips ignore risk.",
        "Revenge trading after a loss usually leads to bigger position sizes and weaker decisions.",
    ]
    for text in texts:
        verdict, _ = verdict_of(build(text, base="AK-02"), nothing)
        assert verdict == "ALLOWED", text


def test_quoted_third_party_call_is_a_warning_not_a_block() -> None:
    text = "A post says 'sell NIFTY tomorrow'; we look at why that is risky."
    verdict, _ = verdict_of(build(text, base="AK-02"), nothing)
    assert verdict == "NEEDS_HUMAN_REVIEW"
    assert normalise_for_matching("A​B") == "ab"
    assert quoted_ranges("say 'buy it' and don't") == [(4, 11)]


def test_backtest_is_a_warning_and_a_plain_return_claim_is_blocked() -> None:
    bt = "In our backtest on old data, this pattern was profitable in 62 out of 100 trades."
    assert verdict_of(build(bt, base="AK-02"), nothing)[0] == "NEEDS_HUMAN_REVIEW"
    assert (
        verdict_of(
            build("What to do this week: sell BANKNIFTY on any rise.", base="AK-02"), nothing
        )[0]
        == "BLOCKED"
    )
    assert verdict_of(build("Buy NIFTY now.", base="AK-02"), nothing)[0] == "BLOCKED"


# ---------------------------------------------------------------- B-1 refusals
def refusal(reason: str, rules: list[str] | None = None) -> dict[str, Any]:
    return {
        "reason": reason,
        "message": "m",
        "missing_inputs": [],
        "violated_rule_ids": rules or [],
    }


def refused(reason: str, rules: list[str] | None = None) -> str:
    return json.dumps({"claims": [], "overall": ALLOWED_OVERALL, "refusal": refusal(reason, rules)})


def test_b1_a_refusal_in_one_batch_never_replaces_another_batch() -> None:
    case = CASES["MIX-30"]
    blocked = json.loads(recorded_response(case))
    first = json.dumps(
        {
            "claims": [blocked["claims"][1] | {"local_id": "c1", "segment_id": "s1"}],
            "overall": blocked["overall"],
            "refusal": None,
        }
    )
    data = json.loads(json.dumps(case["input"]))
    data["segments"][0]["text"] = "So buy the NIFTY weekly call tomorrow and hold it."
    data["segments"][1]["text"] = "This one is a short educational remark about candles."
    resp = json.loads(first)
    resp["claims"][0]["quote"] = "So buy the NIFTY weekly call tomorrow and hold it"
    resp["claims"][0]["char_start"], resp["claims"][0]["char_end"] = (
        0,
        len(resp["claims"][0]["quote"]),
    )
    world = World(llm=RecordedLlm([json.dumps(resp), refused("UNSAFE_CONTENT")]))
    task = task_input(
        "agent_06.claim_extraction.input", data, version="1.1.0", script_sha=SCRIPT_SHA
    )
    out = extraction_step(world, settings=make_settings(extract_max_chars_per_call=40)).run(
        task, run_context()
    )
    assert out.payload is not None and out.payload.data is not None
    d = out.payload.data
    assert d["overall"]["proposed_verdict"] == "BLOCKED" and len(d["claims"]) == 1
    assert d["refusal"] is None and "refused part of the script as unsafe" in " ".join(
        d["overall"]["needs_human_review_reasons"]
    )
    assert world.llm.calls == 2


def test_b1_code_nets_run_when_the_model_refuses() -> None:
    wl = json.loads(json.dumps(CASES["EDGE-14"]["input"]))
    verdict, out = verdict_of(wl, lambda _: refused("UNSAFE_CONTENT"))  # WITHIN_LAG chart
    assert verdict == "BLOCKED" and out.payload.data["overall"]["blocking_rule_ids"] == ["FIN-R9"]
    assert out.payload.data["refusal"]["reason"] == "UNSAFE_CONTENT"
    ak4 = CASES["AK-04"]["input"]
    verdict, out = verdict_of(ak4, lambda _: refused("UNSAFE_CONTENT"))
    assert verdict == "BLOCKED" and "FIN-R8" in out.payload.data["overall"]["blocking_rule_ids"]
    verdict, _ = verdict_of(CASES["HN-05"]["input"], lambda _: refused("UNSAFE_CONTENT"))
    assert verdict == "NEEDS_HUMAN_REVIEW"


def test_b1_refusal_order_is_deterministic_and_the_verdict_is_the_most_severe() -> None:
    a, b = (
        Refusal.model_validate(refusal("UNSAFE_CONTENT")),
        Refusal.model_validate(refusal("RULE_WOULD_BE_BROKEN", ["FIN-R1"])),
    )
    c = Refusal.model_validate(refusal("INSUFFICIENT_INPUT"))
    for order in ([a, b, c], [c, b, a], [b, a]):
        effect = refusal_effect(order)
        assert effect.verdict.value == "BLOCKED" and effect.rule_ids == ("FIN-R1",)
        assert effect.shown is not None and effect.shown.reason.value == "UNSAFE_CONTENT"
    only = refusal_effect([c, b])
    assert only.shown is not None and only.shown.reason.value == "RULE_WOULD_BE_BROKEN"
    assert refusal_effect([]).shown is None


def test_b1_two_refusals_across_batches() -> None:
    data = json.loads(json.dumps(CASES["MIX-30"]["input"]))
    data["segments"][0]["text"] = "Candles show open, high, low and close."
    data["segments"][1]["text"] = "Volume is the number of shares traded."
    world = World(
        llm=RecordedLlm([refused("UNSAFE_CONTENT"), refused("RULE_WOULD_BE_BROKEN", ["FIN-R1"])])
    )
    task = task_input(
        "agent_06.claim_extraction.input", data, version="1.1.0", script_sha=SCRIPT_SHA
    )
    out = extraction_step(world, settings=make_settings(extract_max_chars_per_call=40)).run(
        task, run_context()
    )
    assert out.payload is not None and out.payload.data is not None
    assert out.payload.data["overall"]["proposed_verdict"] == "BLOCKED"
    assert out.payload.data["refusal"]["reason"] == "UNSAFE_CONTENT"


# ---------------------------------------------------------------- M-1, M-6 chart age
def with_chart(age: str | None, basis: str = "MEASURED") -> dict[str, Any]:
    data: dict[str, Any] = json.loads(json.dumps(CASES["AK-01"]["input"]))
    data["chart_data_refs"][0] = {
        "ref_id": "chart_1",
        "instrument": "NIFTY",
        "data_age_vs_lag": age,
        "data_age_basis": basis,
    }
    return data


@pytest.mark.parametrize("respond", [nothing, unflagged])
def test_m1_a_chart_inside_the_lag_blocks_even_when_no_claim_links_it(
    respond: Callable[[dict[str, Any]], str],
) -> None:
    for age in ("WITHIN_LAG", "UNKNOWN"):
        verdict, out = verdict_of(with_chart(age), respond)
        assert verdict == "BLOCKED", age
        assert "FIN-R9" in out.payload.data["overall"]["blocking_rule_ids"]


def test_m6_the_chart_date_lookup_is_required_and_fails_closed() -> None:
    world = World(llm=RecordedLlm([]))
    with pytest.raises(TypeError, match="chart_ranges"):
        ClaimExtractionStep(  # type: ignore[call-arg]
            llm=world.llm, budget=world.budget, ledger=world.ledger, tenancy=world.tenancy,
            clock=world.clock, blobs=world.blobs, checkpoints=world.checkpoints, audit=world.audit,
            claims=world.claims, scripts=MemoryScripts(SCRIPT_SHA), rule_packs=StaticPacks(),
            prompts=DocPrompts(), settings=make_settings(),
        )  # fmt: skip
    data = with_chart("OLDER_THAN_LAG")  # supplied OLDER, MEASURED, but no last bar date known
    verdict, _ = verdict_of(data, nothing, chart_ranges=FixedRanges())
    assert verdict == "BLOCKED"
    verdict, _ = verdict_of(data, nothing, chart_ranges=FixedRanges({"chart_1": date(2025, 1, 1)}))
    assert verdict == "ALLOWED"
    verdict, _ = verdict_of(data, nothing, chart_ranges=FixedRanges({"chart_1": NOW.date()}))
    assert verdict == "BLOCKED"  # the data is today's: never more permissive than measured
    verdict, _ = verdict_of(
        with_chart("OLDER_THAN_LAG", "CONSTRAINT"), nothing, chart_ranges=FixedRanges()
    )
    assert verdict == "ALLOWED"
    verdict, _ = verdict_of(with_chart(None), nothing, chart_ranges=FixedRanges())
    assert verdict == "ALLOWED"  # schematic: no price data


def test_chart_findings_unit_and_publish_time_recheck() -> None:
    from agent_06_fact_checker.models import Segment

    refs = (
        ChartDataRef(ref_id="chart_1", instrument="N", data_age_vs_lag=DataAge.WITHIN_LAG),
        ChartDataRef(ref_id="chart_2", instrument="N", data_age_vs_lag=DataAge.OLDER_THAN_LAG),
        ChartDataRef(ref_id="chart_3", instrument="N", data_age_vs_lag=DataAge.UNKNOWN),
    )
    segs = [Segment(segment_id="s1", text="x", visual_refs=["chart_1"])]
    found = chart_findings(refs, segs, linked={"chart_3"})
    assert [(f.segment_id, f.evidence) for f in found] == [("s1", "chart_1")]
    ends = {"chart_1": date(2026, 11, 1), "chart_2": date(2026, 9, 1), "chart_3": None}
    assert recheck_lag_at(ends, date(2026, 11, 18), 30) == {
        "chart_1": DataAge.WITHIN_LAG, "chart_2": DataAge.OLDER_THAN_LAG, "chart_3": DataAge.UNKNOWN,
    }  # fmt: skip
    # the same chart passes later: 13 5.5 is evaluated at the publish date
    assert recheck_lag_at(ends, date(2026, 12, 1), 30)["chart_1"] is DataAge.OLDER_THAN_LAG
    with pytest.raises(ConfigInvalidError):
        recheck_lag_at(ends, date(2026, 12, 1), 30, "TRADING_DAYS")


# ---------------------------------------------------------------- M-2 .. M-5
def test_m3_the_sentence_scan_does_not_depend_on_the_models_instrument_or_quote() -> None:
    data = json.loads(json.dumps(CASES["HN-33"]["input"]))
    resp = json.loads(recorded_response(CASES["HN-33"]))
    resp["claims"][0]["instrument"] = None
    resp["claims"][0]["quote"] = "On this past"
    resp["claims"][0]["char_start"], resp["claims"][0]["char_end"] = 0, len("On this past")
    verdict, _ = verdict_of(data, lambda _: json.dumps(resp))
    assert verdict == "NEEDS_HUMAN_REVIEW"
    verdict, _ = verdict_of(data, nothing)
    assert verdict == "NEEDS_HUMAN_REVIEW"


def replay(response: str) -> Callable[[dict[str, Any]], str]:
    return lambda _data: response


def claim_of(case_id: str, **over: Any) -> str:
    resp: dict[str, Any] = json.loads(recorded_response(CASES[case_id]))
    resp["claims"][0].update(over)
    return json.dumps(resp)


def test_m4_the_model_can_raise_a_severity_never_lower_it_below_the_table() -> None:
    def flag(rule: str, sev: str) -> list[dict[str, str]]:
        return [{"rule_id": rule, "severity": sev, "evidence": "e"}]

    base = CASES["HN-10"]["input"]
    for rule in ("FIN-R2", "FIN-R3", "FIN-R5", "FIN-R7", "FIN-R13", "FIN-R1"):
        resp = claim_of(
            "HN-10", rule_flags=flag(rule, "WARNING"), claim_type="OPINION", requires_citation=False
        )
        verdict, _ = verdict_of(base, replay(resp))
        assert verdict == "BLOCKED", rule
    resp = claim_of(
        "HN-10",
        rule_flags=flag("FIN-R1", "WARNING"),
        claim_type="QUOTED_THIRD_PARTY",
        requires_citation=False,
    )
    assert verdict_of(base, replay(resp))[0] == "NEEDS_HUMAN_REVIEW"
    for rule in ("FIN-R6", "FIN-R8", "FIN-R12"):
        resp = claim_of("HN-10", rule_flags=flag(rule, "WARNING"), requires_citation=False)
        assert verdict_of(base, replay(resp))[0] == "NEEDS_HUMAN_REVIEW", rule


def test_m5_restricted_claim_types_without_a_fin_flag_need_a_human() -> None:
    base = CASES["HN-10"]["input"]
    for ctype in (
        "RECOMMENDATION",
        "PRICE_LEVEL",
        "FORWARD_VIEW",
        "PERFORMANCE_CLAIM",
        "TESTIMONIAL",
    ):
        resp = claim_of("HN-10", claim_type=ctype, requires_citation=False)
        verdict, out = verdict_of(base, replay(resp))
        assert verdict == "NEEDS_HUMAN_REVIEW", ctype
        assert "finance rules restrict" in " ".join(
            out.payload.data["overall"]["needs_human_review_reasons"]
        )
    plain = CASES["EDGE-29"]["input"]  # no finance pack: the floor does not apply
    resp = claim_of("EDGE-29", claim_type="RECOMMENDATION", requires_citation=False)
    assert verdict_of(plain, replay(resp))[0] == "ALLOWED"


def test_m2_provisional_lexicon_is_data_marked_for_review() -> None:
    pack = StaticPacks().resolve("rp.finance_sebi_in")
    assert pack.lexicon is not None and "REQUIRES REVIEW" in pack.lexicon.status
    assert {"en", "mr", "hi", "hinglish"} <= set(pack.markers)
    rules = {d.rule_id for d in pack.lexicon.detectors}
    assert {f"FIN-R{n}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 13)} <= rules
    assert required_languages("mr-IN") == ("en", "mr") and required_languages("hi-Latn") == (
        "en",
        "hi",
        "hinglish",
    )
    ensure_lexicon(pack, "en-IN")
    with pytest.raises(ConfigInvalidError):
        ensure_lexicon(pack.model_copy(update={"lexicon": None}), "en")
    with pytest.raises(ConfigInvalidError):
        ensure_lexicon(pack, "ta")  # no Tamil list: fail closed
    no_instruments = pack.lexicon.model_copy(update={"instruments": {"en": ()}})
    with pytest.raises(ConfigInvalidError):
        ensure_lexicon(pack.model_copy(update={"lexicon": no_instruments}), "en")


def test_matcher_suffix_and_sentence_helpers() -> None:
    suf = suffix_families({"mr": ["च", "ही"], "en": ["ing"]})
    assert find_marker("वाढेलच", ["वाढेल"], suf) == "वाढेल"
    assert find_marker("वाढेलच", ["वाढेल"]) is None
    assert find_marker("buying now", ["buy"], suf) == "buy"
    assert find_marker("buyer", ["buy"], suf) is None
    assert sentences("One. Two; three। Four") == [(0, 4), (5, 9), (10, 16), (17, 21)]
    assert Finding("s1", 0, 1, "FIN-R1", RuleSeverity.BLOCKING, "x").rule_id == "FIN-R1"


# ---------------------------------------------------------------- minors
def test_verdict_map_is_validated_with_typed_errors() -> None:
    from agent_06_fact_checker.models import Verdict
    from amw_core.enums import ClaimStatus

    good = {
        ClaimStatus.VERIFIED: Verdict.ALLOWED,
        ClaimStatus.CONTRADICTED: Verdict.BLOCKED,
        ClaimStatus.NEEDS_SUBSTANTIATION: Verdict.NEEDS_HUMAN_REVIEW,
        ClaimStatus.UNVERIFIABLE: Verdict.NEEDS_HUMAN_REVIEW,
    }
    make_settings(verdict_map=good)
    for bad in (
        {k: v for k, v in good.items() if k is not ClaimStatus.UNVERIFIABLE},
        good | {ClaimStatus.CONTRADICTED: Verdict.ALLOWED},
        good | {ClaimStatus.UNVERIFIABLE: Verdict.ALLOWED},
        good | {ClaimStatus.NEEDS_SUBSTANTIATION: Verdict.ALLOWED},
    ):
        with pytest.raises(ConfigInvalidError):
            make_settings(verdict_map=bad)


def test_finance_script_without_the_finance_pack_fails() -> None:
    data = json.loads(json.dumps(CASES["AK-03"]["input"]))
    data["active_rule_packs"] = ["rp.youtube_general"]
    world = World(llm=RecordedLlm([]))
    task = task_input(
        "agent_06.claim_extraction.input", data, version="1.1.0", script_sha=SCRIPT_SHA
    )
    out = extraction_step(world, chart_ranges=FixedRanges()).run(task, run_context())
    assert out.status is OutputStatus.REJECTED and world.llm.calls == 0
    assert out.error is not None and out.error.code == "PERMANENT.INPUT_INVALID"


def test_scanner_level_next_to_an_instrument_and_inflected_advice() -> None:
    from agent_06_fact_checker.scan import scan_correction

    advice = {"en": ("buy",)}
    assert scan_correction("Target 24,500 for NIFTY", [], advice, ["NIFTY"]) == ["PRICE_LEVEL"]
    assert scan_correction("Go long NIFTY above 24,000", [], advice, ["NIFTY"]) == ["PRICE_LEVEL"]
    assert scan_correction("buying is risky", [], advice, [], ("ing",)) == ["ADVICE_WORD"]
    assert scan_correction("buying is risky", [], advice) == []
    assert scan_correction("NIFTY is an index", [], advice, ["NIFTY"]) == []


def test_rounding_is_half_up() -> None:
    from agent_06_fact_checker.numbers import missing_numerals, numerals

    assert missing_numerals(numerals("13"), ["12.5 percent"], True) == []
    assert missing_numerals(numerals("12"), ["12.5 percent"], True) != []
    assert isinstance(make_settings(), FactCheckSettings)
