"""Table-driven tests U-21..U-44 from composer_engine (CE-TOB, CE-SOB)."""

from typing import Any

import pytest

from agent_11_thumbnail_design.scanner import InjectionScanner
from agent_11_thumbnail_design.subject_options import (
    AssetFacts,
    GlyphFacts,
    PictureBuildConfig,
    build_picture_options,
)
from agent_11_thumbnail_design.text_options import TextBuildConfig, build_text_options
from tests.agents.agent_11_thumbnail_design.support import load_cases

TOB = load_cases("composer_engine", "CE-TOB-")
SOB = load_cases("composer_engine", "CE-SOB-")


@pytest.mark.parametrize("case", TOB, ids=[c["case_id"] for c in TOB])
def test_text_option_builder(case: dict[str, Any]) -> None:
    i = case["input"]
    cfg = TextBuildConfig(
        i["config"]["max_words"], i["config"]["max_chars"], i["config"]["max_options"]
    )
    got = build_text_options(
        working_title_local=i["working_title_local"],
        promise_key_terms=i["promise_key_terms"],
        brief_text=i["brief_text"],
        banned_words=i["banned_words"],
        must_not_promise=i["must_not_promise"],
        finance=i["finance"],
        cfg=cfg,
        lexicon=i["lexicon"],
        scanner=InjectionScanner(i["injection_markers"]),
    )
    assert [o.model_dump(mode="json") for o in got.options] == [
        {**o, "key_term_ids": list(o["key_term_ids"])} for o in case["expected"]["text_options"]
    ]
    assert [e.model_dump(mode="json") for e in got.excluded] == case["expected"]["excluded"]
    again = build_text_options(
        working_title_local=i["working_title_local"],
        promise_key_terms=i["promise_key_terms"],
        brief_text=i["brief_text"],
        banned_words=i["banned_words"],
        must_not_promise=i["must_not_promise"],
        finance=i["finance"],
        cfg=cfg,
        lexicon=i["lexicon"],
        scanner=InjectionScanner(i["injection_markers"]),
    )
    assert again == got


@pytest.mark.parametrize("case", SOB, ids=[c["case_id"] for c in SOB])
def test_subject_option_builder(case: dict[str, Any]) -> None:
    i = case["input"]
    c = i["config"]
    got = build_picture_options(
        assets=[AssetFacts(**a) for a in i["assets"]],
        glyphs=[GlyphFacts(**g) for g in i["glyphs"]],
        finance=i["finance"],
        cfg=PictureBuildConfig(
            c["min_w"], c["min_h"], c["faces_allowed"], c["chart_still_allowed"]
        ),
    )
    assert [o.model_dump(mode="json") for o in got.options] == case["expected"]["picture_options"]
    assert [e.as_dict() for e in got.excluded] == case["expected"]["excluded"]
