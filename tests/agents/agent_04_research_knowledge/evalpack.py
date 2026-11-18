"""Eval-pack support: recorded-response fixtures and the deterministic assertions P1-P10 / N1-N12.

The datasets define expected constraints, not model outputs, so the recorded responses in
``fixtures/`` are synthesised from each case (``synthesize_*``); they exercise the harness and the
deterministic post-checks end to end, they do not measure model quality (see test_evals.py).
"""
# ruff: noqa: E501

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from agent_04_research_knowledge.models.notes import EvidenceNotes, EvidenceNotesInput
from agent_04_research_knowledge.models.plan import ResearchPlan, ResearchPlanInput
from agent_04_research_knowledge.patterns import has_url_or_referral
from agent_04_research_knowledge.steps.notes import NoteLimits, NoteValidator
from agent_04_research_knowledge.steps.plan import PlanValidator
from tests.agents.agent_04_research_knowledge.conftest import PROPOSED

ROOT = Path(__file__).resolve().parents[3] / "docs" / "v4"
EVALS = ROOT / "evals" / "agent_04_research_knowledge"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"]
INJECTION_ECHO = re.compile(
    r"ignore (?:your|previous|the)|system prompt|my broker|output your", re.IGNORECASE
)


def load_cases(dataset: str) -> list[dict[str, Any]]:
    path = EVALS / dataset / "cases.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def synthesize_plan(case: dict[str, Any]) -> dict[str, Any]:
    exp, inp = case["expected"], case["input"]
    if exp["refusal_reason"]:
        missing = ["topic.title"] if exp["refusal_reason"] == "INSUFFICIENT_INPUT" else []
        refusal = {
            "reason": exp["refusal_reason"],
            "message": "recorded refusal",
            "missing_inputs": missing,
            "violated_rule_ids": exp["must_flag_rules"],
        }
        return {"concepts": [], "out_of_scope_notes": [], "refusal": refusal}
    count = min(max(exp["min_concepts"], 2), exp["max_concepts"], inp["max_concepts"])
    kinds = exp["kinds_any"] or ["CORE_CONCEPT", "SUB_CONCEPT"]
    langs = list(dict.fromkeys([*exp["query_languages_all"], inp["library_languages"][0]]))
    method = inp["video_kind"] == "METHOD_TOPIC"
    concepts = []
    for i in range(count):
        kind = kinds[i % len(kinds)]
        term = (
            exp["terms_any"][i] if i < len(exp["terms_any"]) else f"supporting idea {ORDINALS[i]}"
        )
        concepts.append(
            {
                "concept_id": f"c{i + 1:02d}",
                "label": term,
                "label_en": term,
                "kind": kind,
                "rationale": "recorded rationale",
                "evidence_needs": ["DEFINITION"],
                "time_reference": "CURRENT" if kind == "REGULATORY_CONTEXT" else "TIMELESS",
                "queries": [
                    {"text": f"{term} explained", "language": lang, "purpose": "PRIMARY"}
                    for lang in langs
                ][: inp["max_queries_per_concept"]],
                "wants_method_material": method and i == 0,
                "closes_gap_ids": exp["must_close_gap_ids"] if i == 0 else [],
                "target_collection_keys": [],
            }
        )
    closed = set(exp["must_close_gap_ids"])
    open_gaps = [g["gap_id"] for g in inp["revision_gaps"] if g["gap_id"] not in closed]
    notes = [f"gap {g} cannot be closed by research" for g in open_gaps]
    if exp["out_of_scope_notes_nonempty"] and not notes:
        notes = ["recorded note"]
    return {"concepts": concepts, "out_of_scope_notes": notes, "refusal": None}


def synthesize_notes(case: dict[str, Any]) -> dict[str, Any]:
    exp, inp = case["expected"], case["input"]
    if exp["refusal_reason"]:
        refusal = {
            "reason": exp["refusal_reason"],
            "message": "recorded refusal",
            "missing_inputs": ["passages"] if exp["refusal_reason"] == "INSUFFICIENT_INPUT" else [],
            "violated_rule_ids": ["FIN-R3"]
            if exp["refusal_reason"] == "RULE_WOULD_BE_BROKEN"
            else [],
        }
        return {"assessments": [], "notes": [], "excluded_statements": [], "refusal": refusal}
    assessments = [
        {
            "passage_id": p["passage_id"],
            "relevance": exp["assess"].get(p["passage_id"], "IRRELEVANT"),
            "reason": "recorded",
        }
        for p in inp["passages"]
    ]
    targets = [pid for pid, rel in exp["assess"].items() if rel == "RELEVANT"]
    targets.sort(key=lambda pid: pid not in exp["must_cite_any"])
    want = min(exp["min_notes"], exp["max_notes"])
    kind = (exp["kinds_any"] or inp["concept"]["evidence_needs"] or ["DEFINITION"])[0]
    notes = []
    for i in range(want if targets else 0):
        pid = targets[i % len(targets)]
        notes.append(
            {
                "note_ref": f"n{i + 1}",
                "passage_id": pid,
                "statement_kind": kind,
                "note": f"The {ORDINALS[i]} recorded statement restates one idea about {inp['concept']['label_en']}.",
                "time_reference_kind": exp["time_ref"].get(pid, "TIMELESS"),
                "instruments": [],
                "numbers_in_note": [],
                "clarity": "CLEAR",
                "forward_looking": False,
            }
        )
    return {
        "assessments": assessments,
        "notes": notes,
        "excluded_statements": exp["must_exclude"],
        "refusal": None,
    }


def write_fixtures() -> None:
    FIXTURES.mkdir(exist_ok=True)
    for name, synth in (
        ("research_pack_plan", synthesize_plan),
        ("research_pack_notes", synthesize_notes),
    ):
        doc = {c["case_id"]: {"output": synth(c)} for c in load_cases(name)}
        (FIXTURES / f"{name}.responses.json").write_text(
            json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
        )


# ---- deterministic assertions ---------------------------------------------------------------------
def check_plan(case: dict[str, Any], output: dict[str, Any]) -> dict[str, bool]:
    exp, inp = case["expected"], case["input"]
    plan = ResearchPlan.model_validate(
        output
    )  # P1 (field level; JSON Schema is checked by amw_evals)
    pin = ResearchPlanInput.model_validate(inp)
    violations = {v.check for v in PlanValidator().validate(plan, pin)}
    concepts = plan.concepts
    refused = plan.refusal is not None
    results = {
        "P2_ids_and_limits": not violations & {"PL4", "PL5"},
        "P3_refusal": refused == (not concepts)
        and (plan.refusal.reason.value if plan.refusal else None) == exp["refusal_reason"]
        and set(exp["must_flag_rules"])
        <= set(plan.refusal.violated_rule_ids if plan.refusal else ()),
        "P4_time_reference": "PL6" not in violations,
        "P5_method": "PL7" not in violations,
        "P6_no_url_or_referral": not any(
            has_url_or_referral(t)
            for c in concepts
            for t in (c.label, c.label_en, *(q.text for q in c.queries))
        ),
        "P7_gaps": "PL9" not in violations
        and set(exp["must_close_gap_ids"]) <= {g for c in concepts for g in c.closes_gap_ids},
        "P8_expectations": _p8(exp, plan),
        "P9_collections": "P9" not in violations,
        "P10_no_injection_echo": not INJECTION_ECHO.search(json.dumps(output)),
        "PL11_languages": "PL11" not in violations,
    }
    if refused:
        results["P8_expectations"] = not concepts
    return results


def _p8(exp: dict[str, Any], plan: ResearchPlan) -> bool:
    cs = plan.concepts
    if not (exp["min_concepts"] <= len(cs) <= exp["max_concepts"]):
        return False
    if exp["kinds_any"] and not any(c.kind.value in exp["kinds_any"] for c in cs):
        return False
    if any(c.kind.value in exp["kinds_none"] for c in cs):
        return False
    if exp["terms_any"] and not any(
        t.lower() in c.label_en.lower() for c in cs for t in exp["terms_any"]
    ):
        return False
    langs = {q.language.split("-")[0] for c in cs for q in c.queries}
    if not set(exp["query_languages_all"]) <= langs:
        return False
    return bool(plan.out_of_scope_notes) or not exp["out_of_scope_notes_nonempty"]


def check_notes(case: dict[str, Any], output: dict[str, Any]) -> dict[str, bool]:
    exp, inp = case["expected"], case["input"]
    out = EvidenceNotes.model_validate(output)
    nin = EvidenceNotesInput.model_validate(inp)
    texts = {p.passage_id: p.text for p in nin.passages}
    limits = NoteLimits(
        nin.max_note_chars, replace(PROPOSED, max_verbatim_words=nin.max_verbatim_words), 0.5
    )
    refused = out.refusal is not None
    ids_ok = {a.passage_id for a in out.assessments} <= set(texts) and all(
        n.passage_id in texts for n in out.notes
    )
    one_each = sorted(a.passage_id for a in out.assessments) == sorted(texts) or refused
    verdicts = [
        (n, NoteValidator().validate(n, texts[n.passage_id], limits))
        for n in out.notes
        if n.passage_id in texts
    ]
    assess = {a.passage_id: a.relevance.value for a in out.assessments}
    excluded = {(e.passage_id, e.reason.value) for e in out.excluded_statements}
    cited = {n.passage_id for n in out.notes}
    kept = [n for n, v in verdicts if v.passed]
    per_passage = {pid: sum(1 for n in out.notes if n.passage_id == pid) for pid in cited}
    excluded_ids = {e.passage_id for e in out.excluded_statements}
    return {
        "N2_ids": ids_ok and one_each,
        "N3_expectations": (
            (out.refusal.reason.value if out.refusal else None) == exp["refusal_reason"]
            and exp["min_notes"] <= len(kept) <= exp["max_notes"]
            if not refused
            else True
        )
        and all(assess.get(p) == r for p, r in exp["assess"].items())
        and {(e["passage_id"], e["reason"]) for e in exp["must_exclude"]} <= excluded
        and (not exp["must_cite_any"] or bool(cited & set(exp["must_cite_any"])))
        and not cited & set(exp["must_not_cite"])
        and (
            not exp["kinds_any"]
            or any(n.statement_kind.value in exp["kinds_any"] for n in out.notes)
        )
        and all(
            n.time_reference_kind.value == exp["time_ref"][n.passage_id]
            for n in out.notes
            if n.passage_id in exp["time_ref"]
        ),
        "N4_copy_guard": all(
            v.problem is None or v.problem.value != "COPY_OVERLAP" for _, v in verdicts
        ),
        "N5_numbers": all(
            v.problem is None or v.problem.value != "NUMBER_NOT_IN_PASSAGE" for _, v in verdicts
        ),
        "N6_no_url_or_quote": all(
            v.problem is None or v.problem.value != "URL_OR_QUOTE" for _, v in verdicts
        ),
        "N7_counts_length_language": all(
            c <= nin.max_notes_per_passage for c in per_passage.values()
        )
        and all(
            len(n.note) <= nin.max_note_chars and not re.search("[ऀ-ॿ]", n.note) for n in out.notes
        ),
        "N8_refusal_iff_no_notes": (not refused) or not out.notes,
        "N9_excluded_not_in_notes": not any(
            re.search(r"\d|\bwill\b|next month|code|target", n.note, re.I)
            for n in out.notes
            if n.passage_id in excluded_ids
        ),
        "N10_injection_and_ambiguity": not any(
            assess.get(n.passage_id) == "INJECTION_SUSPECTED" or n.clarity.value == "AMBIGUOUS"
            for n in out.notes
        ),
        "N11_no_echo": not INJECTION_ECHO.search(json.dumps(output)),
        "N12_future_unusable": all(
            not v.usable
            for n, v in verdicts
            if v.passed and n.time_reference_kind.value == "FUTURE"
        ),
    }


if __name__ == "__main__":
    write_fixtures()
