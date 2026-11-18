# ruff: noqa: PT018
"""Contract tests C-01/C-02 and the offline eval run R-03 for the three LLM-step datasets.

What runs: every case input validates against the step input model and its JSON Schema; every
worked-example output validates against the output model and schema; every REFUSAL case runs the
step code (render, structured call, parse, refusal mapping) with the refusal built from the case's
``expected`` (the only model output a dataset defines). What cannot run: PLAN / SCENES / CUT cases
have no recorded model output (the datasets assert properties of a future output), so they run only
their input validation; they are listed in ``NOT_RUNNABLE`` and counted in the last test.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from agent_05_scriptwriter.checks.plan_checker import PlanChecker
from agent_05_scriptwriter.checks.results import failing_ids
from agent_05_scriptwriter.checks.section_checker import SectionChecker
from agent_05_scriptwriter.contracts import (
    CutOutput,
    CutStepInput,
    PlanOutput,
    PlanStepInput,
    SectionOutput,
    SectionStepInput,
)
from agent_05_scriptwriter.llm.prompt_renderer import render
from agent_05_scriptwriter.llm.structured_caller import CallCounter, StructuredCaller
from agent_05_scriptwriter.refusal import map_refusal
from amw_evals.prompt_doc import parse_prompt
from tests.agents.agent_05_scriptwriter import support as sp

ROOT = Path(__file__).resolve().parents[3] / "docs" / "v4"
SETS: dict[str, tuple[type[BaseModel], type[BaseModel], str, str]] = {
    "script_draft": (PlanStepInput, PlanOutput, "PLAN", "plan"),
    "script_draft_section": (SectionStepInput, SectionOutput, "SCENES", "section_sec1"),
    "shorts_adaptation": (CutStepInput, CutOutput, "CUT", "cut"),
}
NOT_RUNNABLE: list[str] = []

pytestmark = pytest.mark.contract


def cases(name: str) -> list[dict[str, Any]]:
    path = ROOT / "evals" / "agent_05_scriptwriter" / name / "cases.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def prompt(name: str) -> Any:
    return parse_prompt(ROOT / "prompts" / "agent_05_scriptwriter" / f"{name}.v1.md")


ALL = [(n, c) for n in SETS for c in cases(n)]


@pytest.mark.parametrize(("name", "case"), ALL, ids=[f"{n}:{c['case_id']}" for n, c in ALL])
def test_case_input_validates_against_model_and_json_schema(
    name: str, case: dict[str, Any]
) -> None:
    model = SETS[name][0]
    schema = prompt(name).input_schema()
    assert schema is not None
    assert list(Draft202012Validator(schema).iter_errors(case["input"])) == []
    model.model_validate(case["input"])


@pytest.mark.parametrize("name", list(SETS))
def test_worked_example_outputs_validate_both_ways(name: str) -> None:
    doc = prompt(name)
    schema = doc.output_schema()
    assert schema is not None
    for ex in doc.examples:
        raw = json.loads(ex.output_blocks[0].text)
        assert list(Draft202012Validator(schema).iter_errors(raw)) == []
        SETS[name][1].model_validate(raw)


@pytest.mark.parametrize("name", list(SETS))
def test_models_and_schemas_reject_the_same_mutations(name: str) -> None:
    doc = prompt(name)
    schema = doc.output_schema()
    validator = Draft202012Validator(schema)
    good = json.loads(doc.examples[0].output_blocks[0].text)
    mutants = []
    for key in list(good):
        broken = dict(good)
        del broken[key]
        mutants.append(broken)
    mutants.append({**good, "extra_field": 1})
    mutants.append(
        {
            **good,
            "refusal": {
                "reason": "NOPE",
                "message": "m",
                "missing_inputs": [],
                "violated_rule_ids": [],
            },
        }
    )
    for bad in mutants:
        schema_rejects = bool(list(validator.iter_errors(bad)))
        try:
            SETS[name][1].model_validate(bad)
            model_rejects = False
        except Exception:
            model_rejects = True
        assert schema_rejects == model_rejects, (name, sorted(bad)[:3])


def refusal_output(name: str, case: dict[str, Any]) -> dict[str, Any]:
    refusal = {
        "reason": case["expected"]["refusal_reason"],
        "message": "synthetic refusal built from the dataset's expected object",
        "missing_inputs": case["expected"].get("missing_inputs_any", []),
        "violated_rule_ids": case["expected"].get("rule_ids_all", []),
    }
    if name == "script_draft":
        return {
            "title_promise": None,
            "hooks": [],
            "selected_hook_id": None,
            "sections": [],
            "concept_plan": [],
            "omitted_concepts": [],
            "description_draft": None,
            "thumbnail_brief": None,
            "refusal": refusal,
        }
    if name == "script_draft_section":
        return {
            "section_id": case["input"]["section_plan"]["section_id"],
            "scenes": [],
            "refusal": refusal,
        }
    return {
        "title_promise": None,
        "hooks": [],
        "selected_hook_id": None,
        "scenes": [],
        "dropped_parent_content": [],
        "refusal": refusal,
    }


REFUSALS = [(n, c) for n, c in ALL if c["expected"]["outcome"] == "REFUSAL"]
EXPECTED_STATUS = {
    "INSUFFICIENT_INPUT": ("FAILED", "PERMANENT.INSUFFICIENT_INPUT"),
    "OUT_OF_SCOPE": ("FAILED", "PERMANENT.INPUT_INVALID"),
    "CONFLICTING_INSTRUCTIONS": ("FAILED", "PERMANENT.INPUT_INVALID"),
    "RULE_WOULD_BE_BROKEN": ("SUCCEEDED", None),
    "UNSAFE_CONTENT": ("SUCCEEDED", None),
}


@pytest.mark.parametrize(
    ("name", "case"), REFUSALS, ids=[f"{n}:{c['case_id']}" for n, c in REFUSALS]
)
def test_refusal_cases_run_through_the_real_step_code(name: str, case: dict[str, Any]) -> None:
    model, out_model, _, step_key = SETS[name]
    step_in: Any = model.model_validate(case["input"])
    ctx = sp.make_ctx()
    llm = sp.ScriptedLlm([{"text": json.dumps(refusal_output(name, case))}])
    st = sp.MemoryState()
    caller = StructuredCaller(
        llm, sp.make_ports(st).ledger, sp.make_ports(st).budget, CallCounter()
    )
    settings = sp.make_settings()
    prompts = sp.prompts()
    loaded = {
        "script_draft": prompts.plan,
        "script_draft_section": prompts.section,
        "shorts_adaptation": prompts.cut,
    }[name]
    rendered = render(
        sp.need(loaded), sp.make_resolved(ctx).rule_packs, step_in.active_rule_packs, step_in
    )
    step_cfg = {
        "script_draft": settings.plan,
        "script_draft_section": settings.section,
        "shorts_adaptation": settings.cut,
    }[name]
    assert step_cfg is not None
    result: Any = caller.run_step(
        ctx,
        model_cls=out_model,
        step=step_cfg,
        step_key=step_key,
        rendered=rendered,
        language=step_in.language,
        check=lambda _o: [],
        is_refusal=lambda o: o.refusal is not None,
    )
    refusal = result.parsed.refusal
    assert refusal is not None and refusal.reason == case["expected"]["refusal_reason"]
    assert set(case["expected"]["rule_ids_all"]) <= set(refusal.violated_rule_ids)
    mapped = map_refusal(refusal, step_key)
    status, code = EXPECTED_STATUS[refusal.reason]
    assert (mapped.status, mapped.error_code) == (status, code)
    assert len(llm.requests) == 1 and mapped.scripts_row is False


def test_every_refusal_case_ran_and_the_rest_are_listed() -> None:
    plan_like = [(n, c["case_id"]) for n, c in ALL if c["expected"]["outcome"] != "REFUSAL"]
    NOT_RUNNABLE.extend(f"{n}:{cid}" for n, cid in plan_like)
    assert len(REFUSALS) == 34
    assert len(NOT_RUNNABLE) == 85 - 34  # no recorded model output exists for these 51 cases


def test_worked_example_one_known_findings_against_the_deterministic_checks() -> None:
    """Example 1 of each prompt (the AK-01 case) against the code checks.

    Recorded as findings for the blueprint owner (not defects of this code): the plan example's
    third hook is 203 characters (budget minimum 240) and leaves a glossary term unbracketed, so
    two hooks qualify; the section and cut examples use chart IDs outside the case pool / parent.
    """
    settings = sp.make_settings()
    plan_doc = prompt("script_draft")
    case = next(c for c in cases("script_draft") if c["case_id"] == "AK-01")
    out = PlanOutput.model_validate(json.loads(plan_doc.examples[0].output_blocks[0].text))
    report = PlanChecker(settings, sp.SCANNERS).check(
        out, PlanStepInput.model_validate(case["input"])
    )
    assert report.option_failures["h1"] == [] and report.option_failures["h2"] == []
    assert "a05.plan.hooks" in report.option_failures["h3"]
    sec_doc = prompt("script_draft_section")
    sec_case = next(c for c in cases("script_draft_section") if c["case_id"] == "AK-01")
    sec_out = SectionOutput.model_validate(json.loads(sec_doc.examples[0].output_blocks[0].text))
    sec_res = SectionChecker(settings, sp.SCANNERS).check(
        sec_out, SectionStepInput.model_validate(sec_case["input"])
    )
    assert "a05.sec.fin_prefilter" not in failing_ids(sec_res)
    assert "a05.sec.forbidden_tokens" not in failing_ids(sec_res)
