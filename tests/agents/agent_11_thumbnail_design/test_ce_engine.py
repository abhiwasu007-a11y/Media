"""Table-driven tests from composer_engine: guards, planner, fit, contrast, hash, revision."""

import json
from typing import Any

import pytest

from agent_11_thumbnail_design.errors import TextDoesNotFitError
from agent_11_thumbnail_design.fallback import FallbackPlanner, PlannerPolicy
from agent_11_thumbnail_design.guards import GuardContext, check_concepts
from agent_11_thumbnail_design.measure import (
    FixtureMetrics,
    contrast_ratio,
    distinctness,
    fit_text,
)
from agent_11_thumbnail_design.models import Concept, PreviousConcept, RevisionFeedback, StepIn
from agent_11_thumbnail_design.revision import build_previous, set_sha256
from agent_11_thumbnail_design.scanner import InjectionScanner
from tests.agents.agent_11_thumbnail_design.support import (
    FIN_LEXICON,
    INJECTION_MARKERS,
    fixture_step,
    load_cases,
)

GD = load_cases("composer_engine", "CE-GD-")
FP = load_cases("composer_engine", "CE-FP-")
FIT = load_cases("composer_engine", "CE-FIT-")
CON = load_cases("composer_engine", "CE-CON-")
HASH = load_cases("composer_engine", "CE-HASH-")
REV = load_cases("composer_engine", "CE-REV-")
MAN = load_cases("composer_engine", "CE-MAN-")


def _prev(p: dict[str, Any], concepts: list[dict[str, Any]]) -> dict[str, Any]:
    cur = next(c for c in concepts if c["concept_id"] == p["concept_id"])
    return {
        "angle": "TERM_CLARITY",
        "hypothesis_kind": cur["hypothesis_kind"],
        "emphasis_style": "PLAIN",
        "accent_role": "PRIMARY",
        **p,
    }


@pytest.mark.parametrize("case", GD, ids=[c["case_id"] for c in GD])
def test_guards(case: dict[str, Any]) -> None:
    i = case["input"]
    extra: dict[str, Any] = {}
    if i.get("previous_concepts"):
        extra["previous_concepts"] = [_prev(p, i["concepts"]) for p in i["previous_concepts"]]
        extra["revision_feedback"] = i["revision_feedback"]
    step = StepIn.model_validate(fixture_step(i["fixture"], i["variant_count"], **extra))
    ctx = GuardContext(
        step_in=step,
        finance=i["fixture"] == "FX-FIN",
        faces_allowed=True,
        scanner=InjectionScanner(INJECTION_MARKERS),
        neutral_lexicon=frozenset({"the"}),
        fin_lexicon=FIN_LEXICON,
        evidence=i.get("code_evidence", {}),
    )
    hits = check_concepts([Concept.model_validate(c) for c in i["concepts"]], ctx)
    assert [{"concept_id": h.concept_id, "guard": h.guard} for h in hits] == case["expected"][
        "hits"
    ]


@pytest.mark.parametrize("case", FP, ids=[c["case_id"] for c in FP])
def test_fallback_planner(case: dict[str, Any]) -> None:
    i = case["input"]
    step = StepIn.model_validate(fixture_step(i["fixture"], i["variant_count"], i["overrides"]))
    fin = i["fixture"] == "FX-FIN"
    got = FallbackPlanner(
        PlannerPolicy(finance=fin, faces_allowed=True, fin_lexicon=FIN_LEXICON)
    ).plan(step)
    keys = (
        "concept_id",
        "status",
        "reason_code",
        "template_key",
        "subject_option_id",
        "text_ids",
        "hypothesis_kind",
        "accent_role",
    )
    shown = [
        {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in c.model_dump().items()
            if k in keys
        }
        for c in got
    ]
    assert shown == case["expected"]["concepts"]
    assert shown == [
        {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in c.model_dump().items()
            if k in keys
        }
        for c in FallbackPlanner(
            PlannerPolicy(finance=fin, faces_allowed=True, fin_lexicon=FIN_LEXICON)
        ).plan(step)
    ]


@pytest.mark.parametrize("case", FIT, ids=[c["case_id"] for c in FIT])
def test_fit_text(case: dict[str, Any]) -> None:
    i = case["input"]
    m = FixtureMetrics(i["metrics"]["advance_em"], i["metrics"]["line_height_em"])
    args = (
        i["lines"],
        i["lines_max"],
        i["box"]["w"],
        i["box"]["h"],
        m,
        i["max_font_px"],
        i["min_font_px"],
        i["font_step_px"],
    )
    if case["expected"]["result"] == "FAIL":
        with pytest.raises(TextDoesNotFitError):
            fit_text(*args)
    else:
        r = fit_text(*args)
        assert (r.font_px, r.text_w_px, r.text_h_px) == (
            case["expected"]["font_px"],
            case["expected"]["text_w_px"],
            case["expected"]["text_h_px"],
        )


@pytest.mark.parametrize("case", CON, ids=[c["case_id"] for c in CON])
def test_contrast(case: dict[str, Any]) -> None:
    i = case["input"]
    ratio = contrast_ratio(i["fg"], i["bg"])
    assert ratio == case["expected"]["ratio"]
    assert (ratio >= i["min_ratio"]) is case["expected"]["meets_min"]


@pytest.mark.parametrize("case", HASH, ids=[c["case_id"] for c in HASH])
def test_distinctness(case: dict[str, Any]) -> None:
    r = distinctness(case["input"]["hashes"], case["input"]["min_bits"])
    assert [{"pair": list(p), "bits": b} for p, b in r.pairs] == case["expected"]["pairs"]
    assert r.verdict == case["expected"]["verdict"]


@pytest.mark.parametrize("case", REV, ids=[c["case_id"] for c in REV])
def test_revision_planner(case: dict[str, Any]) -> None:
    i = case["input"]
    got = build_previous(
        i["previous_manifest_variants"],
        i["options"]["texts"],
        i["options"]["pictures"],
        i["options"]["templates"],
        i["feedback"],
    )
    assert [json.loads(p.model_dump_json()) for p in got] == [
        {**p, "text_ids": list(p["text_ids"])} for p in case["expected"]["previous_concepts"]
    ]
    assert all(isinstance(p, PreviousConcept) for p in got)
    RevisionFeedback.model_validate(i["feedback"][0])


@pytest.mark.parametrize("case", MAN, ids=[c["case_id"] for c in MAN])
def test_manifest_hash(case: dict[str, Any]) -> None:
    assert set_sha256(case["input"]["manifest_without_hash"]) == case["expected"]["set_sha256"]
