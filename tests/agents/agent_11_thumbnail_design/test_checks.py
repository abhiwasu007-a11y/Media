"""U-102..U-145: one pass and one fail fixture per check of blueprint 20."""

from dataclasses import replace
from typing import Any

import pytest

from agent_11_thumbnail_design.checks import (
    ALL_CHECK_IDS,
    CheckContext,
    LicenceFact,
    PictureFact,
    VariantFacts,
    run_checks,
    variant_failures,
)
from agent_11_thumbnail_design.composer import PillowComposer
from agent_11_thumbnail_design.models import Concept, PictureOption, TextOption
from amw_core.enums import CheckVerdict, ComplianceVerdict
from tests.agents.agent_11_thumbnail_design.fakes import settings
from tests.agents.agent_11_thumbnail_design.test_composer import spec

SAFE = (57, 32, 1863, 1048)
CORNER = (1632, 960, 1920, 1080)


def _concept(cid: str, hyp: str, template: str, pic: str, texts: tuple[str, ...]) -> Concept:
    return Concept(
        concept_id=cid,
        status="OK",
        reason_code=None,
        template_key=template,
        subject_option_id=pic,
        text_ids=texts,
        angle="TERM_CLARITY",
        hypothesis_kind=hyp,
        emphasis_style="PLAIN",
        accent_role="PRIMARY",
        rationale="Only the words change.",
    )


def _variant(vid: str, hyp: str, text: str, pic_id: str = "o01", tid: str = "t01") -> VariantFacts:
    r = PillowComposer().render(spec(lines=(text,), emphasis="PLAIN", key_terms=()))
    pic = PictureOption(
        option_id=pic_id,
        kind="CODE_GLYPH",
        key="g1_level_steps",
        label="steps",
        has_face=False,
        direction_neutral=True,
    )
    return VariantFacts(
        variant_id=vid,
        concept=_concept("c" + vid[1:], hyp, "tpl_split_left_text", pic_id, (tid,)),
        template_key="tpl_split_left_text",
        template_direction_neutral=True,
        picture=pic,
        picture_fact=PictureFact(None, False, False, None, False, False, False),
        texts=(
            TextOption(
                text_id=tid,
                text=text,
                source="BRIEF_TEXT",
                key_term_ids=("k1",),
                word_count=len(text.split()),
            ),
        ),
        render=r,
        file_size_bytes=len(r.png),
        text_local=" ".join(r.lines),
        rationale_ok=True,
    )


def lic(**over: Any) -> LicenceFact:
    base: dict[str, Any] = {
        "asset_id": "ast_1",
        "usage_kind": "TEMPLATE",
        "has_ledger_row": True,
        "ledger_has_interval": False,
        "licence_state": "ACTIVE",
        "covers_monetized": True,
        "third_party_permission": None,
        "source_type": "CODE_GENERATED",
        "expired": False,
    }
    base.update(over)
    return LicenceFact(**base)


def ctx(**over: Any) -> CheckContext:
    v1 = _variant("v1", "CONTROL", "Read the trend")
    v2 = _variant("v2", "TEXT_ANGLE", "trend", tid="t02")
    base: dict[str, Any] = {
        "settings": settings(),
        "verdict": ComplianceVerdict.ALLOWED,
        "finance": False,
        "requested": 2,
        "variants": (v1, v2),
        "promise_key_terms": ("trend",),
        "must_not_promise": ("profit",),
        "banned_words": (),
        "fin_lexicon": ("buy",),
        "faces_allowed": False,
        "licence_facts": (lic(),),
        "schema_ok": True,
        "llm_calls": 1,
        "cost_micros": 350,
        "reserved_micros": 1000,
        "max_cost_micros": 1000,
        "cost_entry_ids": ("cst_1",),
        "safe_rect": SAFE,
        "reserved_corner_rect": CORNER,
    }
    base.update(over)
    return CheckContext(**base)


def verdicts(c: CheckContext) -> dict[str, CheckVerdict]:
    return {r.check_id: r.verdict for r in run_checks(c)}


def test_all_23_checks_are_emitted_in_order_and_pass_on_a_good_set() -> None:
    results = run_checks(ctx())
    assert [r.check_id for r in results] == list(ALL_CHECK_IDS)
    assert all(r.gate is False for r in results)
    bad = [r.check_id for r in results if r.verdict is CheckVerdict.FAIL]
    assert bad == []
    assert verdicts(ctx())["a11.q.preview_legibility"] is CheckVerdict.WARN
    assert verdicts(ctx())["a11.q.finance_text"] is CheckVerdict.SKIPPED


def test_blocking_flags_follow_the_blueprint() -> None:
    by_id = {r.check_id: r for r in run_checks(ctx())}
    assert by_id["a11.q.legibility"].blocking
    assert not by_id["a11.q.preview_legibility"].blocking
    assert not by_id["a11.q.llm_fallback"].blocking


FAILS = [
    ("a11.q.schema", {"schema_ok": False}),
    ("a11.q.count", {"requested": 1, "settings": settings(agent_11__max_variants=1)}),
    ("a11.q.promise_terms", {"promise_key_terms": ("zebra",)}),
    ("a11.q.must_not_promise", {"must_not_promise": ("trend",)}),
    ("a11.q.no_person", {}),
    ("a11.q.no_ai_still", {"image_provider_calls": 1}),
    ("a11.q.licence_rows", {"licence_facts": (lic(has_ledger_row=False),)}),
    ("a11.q.licence_rows", {"licence_facts": (lic(ledger_has_interval=True),)}),
    ("a11.q.licence_rows", {"licence_facts": (lic(licence_state="EXPIRED"),)}),
    (
        "a11.q.licence_rows",
        {"licence_facts": (lic(source_type="CLIENT_SUPPLIED", third_party_permission="UNKNOWN"),)},
    ),
    ("a11.q.size", {"settings": settings(agent_11__output__max_bytes=10)}),
    ("a11.q.dimensions", {"settings": settings(agent_11__canvas__width_px=1280)}),
    ("a11.q.legibility", {"settings": settings(agent_11__legibility__min_contrast_ratio=21.0)}),
    ("a11.q.text_fit", {"safe_rect": (900, 0, 1000, 100)}),
    ("a11.q.word_count", {"settings": settings(agent_11__text__max_words=1)}),
    ("a11.q.distinct", {"settings": settings(agent_11__distinct__min_hash_distance_bits=64)}),
    ("a11.q.cost", {"llm_calls": 3, "cost_entry_ids": ("a", "b", "c")}),
    ("a11.q.cost", {"cost_micros": 5000}),
]


@pytest.mark.parametrize(("check_id", "over"), FAILS)
def test_each_check_fails_on_its_fail_fixture(check_id: str, over: dict[str, Any]) -> None:
    c = ctx(**over)
    if check_id == "a11.q.no_person":
        v = c.variants[0]
        bad = replace(v, picture_fact=replace(v.picture_fact, depicts_real_person=True))
        c = replace(c, variants=(bad, c.variants[1]))
    got = {r.check_id: r for r in run_checks(c)}[check_id]
    assert got.verdict is CheckVerdict.FAIL
    assert got.blocking


def test_single_variable_and_provenance_fail_fixtures() -> None:
    c = ctx()
    v2 = c.variants[1]
    wrong = replace(v2, concept=v2.concept.model_copy(update={"hypothesis_kind": "SUBJECT_CHOICE"}))
    assert (
        verdicts(replace(c, variants=(c.variants[0], wrong)))["a11.q.single_variable"]
        is CheckVerdict.FAIL
    )
    forged = replace(
        c.variants[0], texts=(c.variants[0].texts[0].model_copy(update={"text": "other"}),)
    )
    assert verdicts(replace(c, variants=(forged, v2)))["a11.q.text_provenance"] is CheckVerdict.FAIL
    dirty = replace(c.variants[0], rationale_ok=False)
    assert verdicts(replace(c, variants=(dirty, v2)))["a11.q.rationale_clean"] is CheckVerdict.FAIL
    missing = replace(c.variants[0], render=replace(c.variants[0].render, missing_glyphs=("x",)))
    assert (
        verdicts(replace(c, variants=(missing, v2)))["a11.q.language_glyphs"] is CheckVerdict.FAIL
    )
    assert variant_failures(missing, c.settings, SAFE, CORNER) == ["a11.q.language_glyphs"]


def test_finance_checks_pass_and_fail() -> None:
    c = ctx(finance=True)
    got = verdicts(c)
    assert got["a11.q.finance_text"] is CheckVerdict.PASS
    assert got["a11.q.finance_imagery"] is CheckVerdict.PASS
    v = c.variants[0]
    digit = replace(v, text_local="Top 3 buy")
    assert (
        verdicts(replace(c, variants=(digit, c.variants[1])))["a11.q.finance_text"]
        is CheckVerdict.FAIL
    )
    arrow = replace(v, picture=v.picture.model_copy(update={"direction_neutral": False}))
    assert (
        verdicts(replace(c, variants=(arrow, c.variants[1])))["a11.q.finance_imagery"]
        is CheckVerdict.FAIL
    )


def test_chart_still_check() -> None:
    c = ctx()
    v = c.variants[0]
    chart = PictureFact("CHART", False, False, "OLDER_THAN_LAG", True, True, True)
    ok = replace(v, picture_fact=chart)
    assert (
        verdicts(replace(c, variants=(ok, c.variants[1])))["a11.q.chart_still"] is CheckVerdict.PASS
    )
    recent = replace(
        v, picture_fact=PictureFact("CHART", False, False, "WITHIN_LAG", True, True, True)
    )
    assert (
        verdicts(replace(c, variants=(recent, c.variants[1])))["a11.q.chart_still"]
        is CheckVerdict.FAIL
    )


def test_preview_legibility_when_the_threshold_is_set() -> None:
    s = settings(
        agent_11__legibility__min_text_height_px_at_preview=2,
        agent_11__legibility__preview_width_px=100,
    )
    assert verdicts(ctx(settings=s))["a11.q.preview_legibility"] is CheckVerdict.PASS
    s2 = settings(
        agent_11__legibility__min_text_height_px_at_preview=500,
        agent_11__legibility__preview_width_px=1920,
    )
    assert verdicts(ctx(settings=s2))["a11.q.preview_legibility"] is CheckVerdict.FAIL


def test_llm_fallback_check_states() -> None:
    assert (
        verdicts(ctx(llm_fallback_code="AGENT.INVALID_JSON"))["a11.q.llm_fallback"]
        is CheckVerdict.WARN
    )
    assert verdicts(ctx())["a11.q.llm_fallback"] is CheckVerdict.PASS
    off = settings(agent_11__llm__enabled=False)
    assert verdicts(ctx(settings=off))["a11.q.llm_fallback"] is CheckVerdict.SKIPPED


@pytest.mark.parametrize(
    "verdict", [ComplianceVerdict.BLOCKED, ComplianceVerdict.NEEDS_HUMAN_REVIEW]
)
def test_empty_set_rule(verdict: ComplianceVerdict) -> None:
    results = {
        r.check_id: r
        for r in run_checks(
            ctx(verdict=verdict, variants=(), llm_calls=0, cost_micros=0, cost_entry_ids=())
        )
    }
    for cid in ALL_CHECK_IDS[1:20]:
        assert results[cid].verdict is CheckVerdict.SKIPPED, cid
        assert not results[cid].blocking
    for cid in ("a11.q.schema", "a11.q.cost", "a11.q.rationale_clean"):
        assert results[cid].verdict is CheckVerdict.PASS, cid
