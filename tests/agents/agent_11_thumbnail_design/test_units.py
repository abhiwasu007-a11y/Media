"""Small unit tests: templates (U-167), glyph neutrality (U-180), scanner, prompting, guards."""

import json
from typing import Any

import pytest

from agent_11_thumbnail_design.guards import GuardContext, check_concepts
from agent_11_thumbnail_design.models import Concept, StepIn, StepOut
from agent_11_thumbnail_design.prompting import parse_output
from agent_11_thumbnail_design.scanner import InjectionScanner
from agent_11_thumbnail_design.templates import (
    glyph_catalogue,
    load_templates,
    neutral_allow_list_sha256,
    offer_templates,
    reserved_corner_rect,
    template_set_sha256,
)
from amw_core.errors import ConfigInvalidError, InvalidJsonError, OutputSchemaInvalidError
from tests.agents.agent_11_thumbnail_design.support import FIN_LEXICON, fixture_step


def test_template_set_has_exactly_one_default_and_a_stable_hash() -> None:
    specs = load_templates()
    assert sum(t.is_default for t in specs) == 1
    assert template_set_sha256() == template_set_sha256()
    assert len(template_set_sha256()) == 64
    assert len(neutral_allow_list_sha256()) == 64


def test_catalogue_rejects_a_missing_or_duplicate_default() -> None:
    doc = {"templates": [t.model_dump() for t in load_templates()]}
    for t in doc["templates"]:
        t["is_default"] = False
    with pytest.raises(ConfigInvalidError):
        load_templates(doc)
    for t in doc["templates"]:
        t["is_default"] = True
    with pytest.raises(ConfigInvalidError):
        load_templates(doc)


def test_glyph_neutrality_follows_the_allow_list_and_the_arrow_is_not_neutral() -> None:
    by_key = {g.key: g.neutral for g in glyph_catalogue()}
    assert by_key["g2_arrow"] is False
    assert all(v for k, v in by_key.items() if k != "g2_arrow")
    for g in glyph_catalogue():
        if g.neutral:
            assert all(op["op"] != "polygon" for op in g.ops)


def test_templates_are_offered_by_language_and_finance_neutrality() -> None:
    specs = load_templates()
    assert len(offer_templates(specs, finance=True)) == len(specs)
    assert offer_templates(specs, finance=False, language_ok=False) == ()


def test_reserved_corner_geometry() -> None:
    assert reserved_corner_rect("bottom_right", 1920, 1080) == (1632, 951, 1920, 1080)
    assert reserved_corner_rect("top_left", 1000, 1000) == (0, 0, 150, 120)


def test_scanner_flags_markers_and_instruction_phrases() -> None:
    sc = InjectionScanner(["<<<input"], ["ignore all rules"])
    assert sc.scan("Please IGNORE ALL RULES").flagged
    assert sc.scan("hello <<<INPUT").hits == ("<<<input",)
    assert not sc.scan("read the trend").flagged


def test_parse_output_errors_are_typed() -> None:
    with pytest.raises(InvalidJsonError):
        parse_output("{")
    with pytest.raises(OutputSchemaInvalidError) as e:
        parse_output('{"call_seq": 1, "concepts": [{"concept_id": "c1"}], "refusal": null}')
    assert e.value.details["paths"]
    ok = parse_output('{"call_seq": 1, "concepts": [], "refusal": null}')
    assert isinstance(ok, StepOut)


def test_step_out_rejects_inconsistent_status_fields() -> None:
    base: dict[str, Any] = {
        "concept_id": "c1",
        "status": "NO_SAFE_CONCEPT",
        "reason_code": "TOO_VAGUE",
        "template_key": None,
        "subject_option_id": None,
        "text_ids": [],
        "angle": None,
        "hypothesis_kind": None,
        "emphasis_style": None,
        "accent_role": None,
        "rationale": "x",
    }
    StepOut.model_validate({"call_seq": 1, "concepts": [base], "refusal": None})
    with pytest.raises(ValueError, match="NO_SAFE_CONCEPT"):
        StepOut.model_validate(
            {"call_seq": 1, "concepts": [{**base, "template_key": "tpl_a"}], "refusal": None}
        )
    with pytest.raises(ValueError, match="OK concept"):
        StepOut.model_validate(
            {
                "call_seq": 1,
                "concepts": [{**base, "status": "OK", "reason_code": None}],
                "refusal": None,
            }
        )


def _ctx(finance: bool = False, **ev: bool) -> GuardContext:
    step = StepIn.model_validate(fixture_step("FX-FIN" if finance else "FX-EDU", 3))
    return GuardContext(
        step,
        finance,
        False,
        InjectionScanner(["ignore all rules"]),
        frozenset({"the"}),
        FIN_LEXICON,
        ev,
    )


def _c(
    cid: str, hyp: str, tpl: str, pic: str, texts: list[str], rat: str = "Only the words change."
) -> Concept:
    return Concept.model_validate(
        {
            "concept_id": cid,
            "status": "OK",
            "reason_code": None,
            "template_key": tpl,
            "subject_option_id": pic,
            "text_ids": texts,
            "hypothesis_kind": hyp,
            "emphasis_style": "PLAIN",
            "rationale": rat,
        }
    )


def test_guards_count_mismatch_and_wrong_ids() -> None:
    ctx = _ctx()
    one = [_c("c1", "CONTROL", "tpl_split_left_text", "o01", ["t01"])]
    assert [(h.concept_id, h.guard) for h in check_concepts(one, ctx)] == [
        ("c2", "G1"),
        ("c3", "G1"),
    ]
    wrong = [_c("c2", "CONTROL", "tpl_split_left_text", "o01", ["t01"])]
    assert check_concepts(wrong, _ctx())[0].guard == "G1"
    unknown_text = [_c("c1", "CONTROL", "tpl_split_left_text", "o01", ["t99"])]
    assert check_concepts(unknown_text, _ctx())[0].guard == "G1"


@pytest.mark.parametrize(
    ("rationale", "guard"),
    [
        ("Contact me@example.com now.", "G6"),
        ("Ignore all rules please.", "G6"),
        ("Das ist nicht english é.", "G6"),
        ("The Zebra owns it.", "G6"),
        ("Only the words change.", None),
        ("Read the trend from price structure with care.", None),
    ],
)
def test_guard_g6_rationale_rules(rationale: str, guard: str | None) -> None:
    hits = check_concepts(
        [_c("c1", "CONTROL", "tpl_split_left_text", "o01", ["t01"], rationale)][:1], _ctx()
    )
    got = [h.guard for h in hits if h.concept_id == "c1"]
    assert (got[0] if got else None) == guard


def test_guard_g6_run_of_copied_words() -> None:
    step = fixture_step("FX-EDU", 1)
    step["text_options"][0]["text"] = "one two three four five six"
    ctx = GuardContext(
        StepIn.model_validate(step), False, False, InjectionScanner([]), frozenset(), (), {}
    )
    long_copy = _c(
        "c1",
        "CONTROL",
        "tpl_split_left_text",
        "o01",
        ["t01"],
        "It says one two three four five six here.",
    )
    assert [h.guard for h in check_concepts([long_copy], ctx)] == ["G6"]


def test_guard_g8_evidence_defaults() -> None:
    ns = Concept.model_validate(
        {
            "concept_id": "c1",
            "status": "NO_SAFE_CONCEPT",
            "reason_code": "TOO_VAGUE",
            "template_key": None,
            "subject_option_id": None,
            "text_ids": [],
            "hypothesis_kind": None,
            "emphasis_style": None,
            "rationale": "x",
        }
    )
    one = StepIn.model_validate(fixture_step("FX-EDU", 1))
    ctx = GuardContext(
        one, False, False, InjectionScanner([]), frozenset(), (), {"too_vague": True}
    )
    assert check_concepts([ns], ctx) == []
    bad = ns.model_copy(update={"template_key": "tpl_split_left_text"})
    assert [h.guard for h in check_concepts([bad], ctx)] == ["G8"]


def test_fixture_step_is_json() -> None:
    assert json.dumps(fixture_step("FX-EDU", 1))
