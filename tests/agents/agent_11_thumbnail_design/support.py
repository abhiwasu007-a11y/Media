"""Shared helpers: the composer_engine dataset loader and the FX-EDU / FX-FIN fixtures."""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EVALS = ROOT / "docs" / "v4" / "evals" / "agent_11_thumbnail_design"


def load_cases(dataset: str, prefix: str) -> list[dict[str, Any]]:
    path = EVALS / dataset / "cases.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r["case_id"].startswith(prefix)]


def _txt(i: int, text: str, source: str, kids: list[str]) -> dict[str, Any]:
    return {
        "text_id": f"t{i:02d}",
        "text": text,
        "source": source,
        "key_term_ids": kids,
        "word_count": len(text.split()),
    }


def _pic(i: int, kind: str, label: str, face: bool, neutral: bool) -> dict[str, Any]:
    return {
        "option_id": f"o{i:02d}",
        "kind": kind,
        "label": label,
        "has_face": face,
        "direction_neutral": neutral,
    }


def _tpl(key: str, default: bool, lines: int, kinds: list[str], neutral: bool) -> dict[str, Any]:
    return {
        "template_key": key,
        "is_default": default,
        "text_lines_max": lines,
        "supports_subject_kinds": kinds,
        "direction_neutral": neutral,
    }


def fixture_step(
    name: str, variant_count: int, overrides: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    """FX-EDU / FX-FIN of the composer_engine README (section 3) as a step-input document."""
    ov = overrides or {}
    texts = [
        _txt(1, "Read the trend", "BRIEF_TEXT", ["k1"]),
        _txt(2, "price structure", "KEY_TERM", ["k2"]),
        _txt(3, "trend from price structure", "TITLE_SPAN", ["k1", "k2"]),
        _txt(4, "Start here", "KEY_TERM", []),
    ]
    pics = [
        _pic(1, "CODE_GLYPH", "level steps outline", False, True),
        _pic(2, "CODE_GLYPH", "two overlapping frames", False, True),
        _pic(3, "NONE", "text only", False, True),
        _pic(4, "CODE_GLYPH", "rising arrow", False, False),
        _pic(5, "OWNER_IMAGE", "owner portrait", True, True),
    ]
    tpls = [
        _tpl("tpl_split_left_text", True, 2, ["CODE_GLYPH", "NONE", "OWNER_IMAGE"], True),
        _tpl("tpl_centered_statement", False, 2, ["CODE_GLYPH", "NONE"], True),
        _tpl("tpl_subject_right", False, 1, ["CODE_GLYPH", "NONE", "OWNER_IMAGE"], True),
        _tpl("tpl_up_arrow_band", False, 1, ["CODE_GLYPH"], False),
    ]
    if "only_text" in ov:
        texts = [t for t in texts if t["text_id"] in ov["only_text"]]
    if "only_pictures" in ov:
        pics = [p for p in pics if p["option_id"] in ov["only_pictures"]]
    if "only_templates" in ov:
        tpls = [t for t in tpls if t["template_key"] in ov["only_templates"]]
    doc: dict[str, Any] = {
        "call_seq": 1,
        "language": "en-IN",
        "channel_category": "finance" if name == "FX-FIN" else "education",
        "variant_count": variant_count,
        "promise": {
            "promise_statement": "You will learn how to read a trend from price structure.",
            "promise_key_terms": ["trend", "price structure"],
            "working_title_local": "How to read a trend from price structure",
        },
        "brief": {
            "subject_idea": "outline of level steps",
            "text_idea_local": "Read the trend",
            "must_not_promise": [],
        },
        "subject_hints": [],
        "subject_options": [dict(p) for p in pics],
        "text_options": texts,
        "templates": tpls,
        "banned_subjects": [],
        "limits": {"max_rationale_chars": 160},
        "retry_context": None,
        "previous_concepts": None,
        "revision_feedback": [],
    }
    doc.update(extra)
    return doc


FIN_LEXICON = ["buy", "sell", "hold", "target", "profit", "return", "guaranteed", "will"]
INJECTION_MARKERS = ["ignore all rules", "<<<input", "input>>>"]
