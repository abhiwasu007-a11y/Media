# ruff: noqa: PT018, RUF059
"""Branch tests of the plan, section, cut and whole-script checks, owner topic and task output."""

import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from agent_05_scriptwriter import ScriptDraftRequest, ScriptDraftStep
from agent_05_scriptwriter.checks.cut_checker import CutChecker
from agent_05_scriptwriter.checks.plan_checker import PlanChecker
from agent_05_scriptwriter.checks.results import failing_ids
from agent_05_scriptwriter.checks.section_checker import SectionChecker
from agent_05_scriptwriter.contracts import (
    CutOutput,
    CutStepInput,
    PlanOutput,
    PlanStepInput,
    ScriptDocument,
    SectionOutput,
    SectionStepInput,
)
from agent_05_scriptwriter.owner_topic import script_draft_input_from_owner_topic
from agent_05_scriptwriter.pre.brief_mapper import map_briefs
from agent_05_scriptwriter.steps.common import StepOutcome
from agent_05_scriptwriter.task_output import build_task_output
from amw_core.contracts.owner_topic import OwnerTopic
from amw_core.contracts.validation import validate_task_output
from amw_core.errors import InputInvalidError, QualityRepeatedFailureError
from tests.agents.agent_05_scriptwriter import support as sp
from tests.agents.agent_05_scriptwriter.test_shorts import parent_script, shorts_input

pytestmark = pytest.mark.unit


def plan_input(**over: Any) -> PlanStepInput:
    briefs = map_briefs(sp.make_pack(), [])
    data: dict[str, Any] = {
        "language": "en-IN",
        "channel_category": "finance",
        "owner_sebi_registration": "UNREGISTERED",
        "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
        "video_kind": "GENERAL",
        "topic": {
            "title": "Divergence on a past chart",
            "angle": None,
            "target_duration_ms": 480000,
        },
        "concept_briefs": [b.model_dump() for b in briefs.briefs],
        "available_citations": [c.model_dump() for c in briefs.available_citations],
        "latin_allow_list": ["NIFTY"],
        "speech_budget": None,
        "min_hook_options": 3,
        "max_hook_options": 5,
        "max_sections": 8,
        "hook_history": [],
        "course_chapter_pointer": None,
        "revision_feedback": None,
    }
    data.update(over)
    return PlanStepInput.model_validate(data)


def failing(plan: dict[str, Any], inp: PlanStepInput | None = None) -> list[str]:
    report = PlanChecker(sp.make_settings(), sp.SCANNERS).check(
        PlanOutput.model_validate(plan), inp or plan_input()
    )
    return failing_ids(report.results)


def test_valid_plan_passes_every_check() -> None:
    assert failing(sp.plan_json(3)) == []


def mutate(path: list[Any], value: Any, n: int = 3) -> dict[str, Any]:
    plan = copy.deepcopy(sp.plan_json(n))
    node = plan
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return plan


PLAN_CASES = [
    (mutate(["sections", 0, "share_permille"], 1), "a05.plan.sections"),
    (mutate(["sections", 2, "section_kind"], "CONCEPT"), "a05.plan.sections"),
    (mutate(["sections", 0, "needs_interrupt"], False), "a05.plan.sections"),
    (
        mutate(["title_promise", "working_title_local"], "A title without the term"),
        "a05.plan.promise",
    ),
    (mutate(["description_draft"], "No key word here at all."), "a05.plan.promise"),
    (mutate(["thumbnail_brief", "must_not_promise"], []), "a05.plan.promise"),
    (mutate(["title_promise", "promise_statement"], "A guaranteed outcome."), "a05.plan.promise"),
    (mutate(["omitted_concepts"], []), "a05.plan.concepts"),
    (mutate(["concept_plan", 0, "citation_refs"], ["kch_not_in_brief"]), "a05.plan.concepts"),
    (mutate(["omitted_concepts", 0, "reason"], "DURATION_LIMIT"), "a05.plan.concepts"),
    (mutate(["hooks", 1, "hook_style"], "CONCRETE_CASE"), "a05.plan.hooks"),
    (mutate(["hooks", 0, "beats", 0, "concrete_example"], None), "a05.plan.selection"),
    (
        mutate(
            ["hooks", 0, "beats", 0, "sentences", 0, "text"], "Welcome to the channel, divergence."
        ),
        "a05.plan.selection",
    ),
    (
        mutate(["description_draft"], "See http://x.test for the divergence lesson."),
        "a05.plan.forbidden_tokens",
    ),
    (
        mutate(["sections", 0, "purpose"], "Sell NIFTY now and use the divergence."),
        "a05.plan.fin_prefilter",
    ),
    (mutate(["sections", 0, "heading_local"], "Hello"), "a05.plan.sections"),
]


@pytest.mark.parametrize(("plan", "check_id"), PLAN_CASES)
def test_plan_mutations_fail_the_named_check(plan: dict[str, Any], check_id: str) -> None:
    if check_id == "a05.plan.sections" and plan["sections"][0]["heading_local"] == "Hello":
        plan["sections"][0]["concept_ids"] = ["k9"]
    if check_id == "a05.plan.sections" and not plan["sections"][0]["needs_interrupt"]:
        plan["sections"][1]["needs_interrupt"] = False
    assert check_id in failing(plan)


def test_plan_history_budget_and_method_gate() -> None:
    assert "a05.plan.selection" in failing(
        sp.plan_json(3),
        plan_input(hook_history=["A divergence showed up on an invented chart, option h1."]),
    )
    tight = plan_input(
        speech_budget={"hook_chars_min": 1, "hook_chars_max": 20, "beat_chars_target": 5}
    )
    assert "a05.plan.selection" in failing(sp.plan_json(3), tight)
    method = copy.deepcopy(plan_input().model_dump())
    method["concept_briefs"][1]["method_content"] = True
    method["concept_briefs"][1]["release_status"] = "NOT_RELEASED"
    assert "a05.plan.method_gate" in failing(sp.plan_json(3), PlanStepInput.model_validate(method))
    pointer = plan_input(course_chapter_pointer={"label": "Course chapter"})
    assert "a05.plan.sections" in failing(sp.plan_json(3), pointer)


def section_input(**over: Any) -> SectionStepInput:
    briefs = map_briefs(sp.make_pack(), [])
    data: dict[str, Any] = {
        "language": "en-IN",
        "channel_category": "finance",
        "owner_sebi_registration": "UNREGISTERED",
        "active_rule_packs": ["rp.youtube_general"],
        "video_kind": "GENERAL",
        "section_plan": {
            "section_id": "sec1",
            "section_kind": "CONCEPT",
            "heading_local": "Part one",
            "heading_en": "Part one",
            "purpose": "Teach it.",
            "concept_ids": ["k1"],
            "needs_interrupt": True,
            "is_case_study": False,
        },
        "concept_briefs": [b.model_dump() for b in briefs.briefs[:2]],
        "available_citations": [c.model_dump() for c in briefs.available_citations],
        "latin_allow_list": ["NIFTY"],
        "running_summary": {"sections_done": [], "terms_introduced": [], "previous_tail": []},
        "scene_budget": {
            "chars_min": None,
            "chars_max": None,
            "max_scenes": 4,
            "max_change_gap_ms": 5000,
            "speech_rate_cps": None,
        },
        "chart_ids_available": ["chart_2", "chart_3"],
        "revision_feedback": None,
        "previous_text": None,
    }
    data.update(over)
    return SectionStepInput.model_validate(data)


def sec_failing(out: dict[str, Any], inp: SectionStepInput | None = None, **kw: Any) -> list[str]:
    inp = inp or section_input()
    res = SectionChecker(sp.make_settings(), sp.SCANNERS).check(
        SectionOutput.model_validate(out), inp, **kw
    )
    return failing_ids(res)


def good_section(inp: SectionStepInput | None = None) -> dict[str, Any]:
    return sp.section_json((inp or section_input()).model_dump(mode="json"))


def test_valid_section_passes() -> None:
    assert sec_failing(good_section()) == []


def tweak(fn: Any, inp: SectionStepInput | None = None) -> dict[str, Any]:
    out = good_section(inp)
    fn(out)
    return out


def test_section_mutations() -> None:
    cases = [
        (
            lambda o: o["scenes"][0]["concept_refs"][0].update(citation_refs=["kch_zzz"]),
            "a05.sec.concepts",
        ),
        (lambda o: o["scenes"][0].update(concept_refs=[]), "a05.sec.concepts"),
        (
            lambda o: o["scenes"][0]["sentences"][0].update(text="Sell NIFTY this week for gain."),
            "a05.sec.fin_prefilter",
        ),
        (
            lambda o: o["scenes"][0]["sentences"][0].update(text="See http://x.test now."),
            "a05.sec.forbidden_tokens",
        ),
        (lambda o: [s.update(interrupt=None) for s in o["scenes"]], "a05.sec.cadence"),
        (lambda o: o["scenes"][0].update(method_label=True), "a05.sec.method_label"),
        (
            lambda o: o["scenes"][0]["sentences"][0].update(text="The RSI tool is used."),
            "a05.sec.lang",
        ),
        (
            lambda o: o["scenes"][0].update(
                chart_request={
                    "chart_id": "chart_9",
                    "chart_kind": "REAL_HISTORICAL",
                    "instrument": "NIFTY",
                    "timeframe": "1D",
                    "indicators": [],
                    "pattern_concept_id": "k1",
                    "outcome_shown": "BOTH",
                    "must_be_historical": True,
                }
            ),
            "a05.sec.chart_requests",
        ),
        (
            lambda o: o["scenes"][0].update(
                chart_request={
                    "chart_id": "chart_2",
                    "chart_kind": "REAL_HISTORICAL",
                    "instrument": None,
                    "timeframe": "1D",
                    "indicators": [],
                    "pattern_concept_id": "k1",
                    "outcome_shown": "BOTH",
                    "must_be_historical": True,
                }
            ),
            "a05.sec.chart_requests",
        ),
    ]
    for fn, check_id in cases:
        assert check_id in sec_failing(tweak(fn)), check_id
    # more scenes than the budget, and near copy against a cited text
    inp = section_input(
        scene_budget={
            "chars_min": None,
            "chars_max": None,
            "max_scenes": 1,
            "max_change_gap_ms": 5000,
            "speech_rate_cps": None,
        }
    )
    assert "a05.sec.budget_chars" in sec_failing(good_section(inp), inp)
    out = good_section()
    sentence = out["scenes"][0]["sentences"][0]["text"]
    assert "a05.sec.near_copy" in sec_failing(out, cited_texts={sp._CIT[0]: sentence})
    assert "a05.sec.chart_requests" in sec_failing(
        tweak(
            lambda o: o["scenes"][0].update(
                chart_request={
                    "chart_id": "chart_2",
                    "chart_kind": "SCHEMATIC",
                    "instrument": None,
                    "timeframe": "1D",
                    "indicators": [],
                    "pattern_concept_id": "k1",
                    "outcome_shown": "NOT_APPLICABLE",
                    "must_be_historical": True,
                }
            )
        ),
        used_chart_ids=["chart_2"],
    )


def test_case_study_section_rules_and_cadence_with_rate() -> None:
    plan = {
        "section_id": "sec2",
        "section_kind": "CASE_STUDY_HISTORICAL",
        "heading_local": "Past",
        "heading_en": "Past",
        "purpose": "Past chart.",
        "concept_ids": ["k2", "k1"],
        "needs_interrupt": False,
        "is_case_study": True,
    }
    rate = {
        "chars_min": None,
        "chars_max": None,
        "max_scenes": 4,
        "max_change_gap_ms": 5000,
        "speech_rate_cps": 5.0,
    }
    inp = section_input(section_plan=plan, scene_budget=rate)
    out = sp.section_json(inp.model_dump(mode="json"))
    found = sec_failing(out, inp)
    assert "a05.sec.concepts" in found and "a05.sec.chart_requests" in found
    assert "a05.sec.cadence" in found  # few change beats at a measured rate


def test_cut_checker_branches() -> None:
    doc, sha, cites_l, _ = parent_script()
    cites = {k: set(v) for k, v in cites_l.items()}
    from agent_05_scriptwriter.steps.shorts import parent_view

    step_in = CutStepInput.model_validate(
        {
            "language": "en-IN",
            "channel_category": "finance",
            "owner_sebi_registration": "UNREGISTERED",
            "active_rule_packs": ["rp.youtube_general"],
            "video_kind": "GENERAL",
            "parent": parent_view(doc, []).model_dump(mode="json"),
            "glossary_terms": [],
            "short_target_duration_ms": 45000,
            "max_duration_ms": 60000,
            "speech_budget": None,
            "owner_instruction": None,
            "latin_allow_list": [],
            "min_hook_options": 3,
            "max_hook_options": 5,
            "hook_history": [],
            "course_chapter_pointer": None,
            "revision_feedback": None,
            "previous_cut": None,
        }
    )
    good = sp.cut_json(step_in.model_dump(mode="json"), {k: sorted(v) for k, v in cites.items()})
    checker = CutChecker(sp.make_settings(), sp.SCANNERS)

    def run(cut: dict[str, Any], **kw: Any) -> list[str]:
        report = checker.check(CutOutput.model_validate(cut), step_in, parent_citations=cites, **kw)
        return failing_ids(report.results)

    assert run(good) == []
    bad = copy.deepcopy(good)
    bad["scenes"][0]["parent_segment_ids"] = ["s9999"]
    assert "a05.sh.provenance" in run(bad)
    bad = copy.deepcopy(good)
    bad["scenes"][0]["sentences"][0]["text"] = "A brand new number 12345 appears."
    assert "a05.sh.provenance" in run(bad)
    bad = copy.deepcopy(good)
    bad["scenes"][0]["chart_ref"] = "chart_77"
    assert "a05.sh.provenance" in run(bad)
    bad = copy.deepcopy(good)
    bad["scenes"][0]["concept_refs"][0]["citation_refs"] = ["kch_new"]
    assert "a05.sh.provenance" in run(bad)
    bad = copy.deepcopy(good)
    bad["dropped_parent_content"] = []
    assert "a05.sh.flags" in run(bad)
    bad = copy.deepcopy(good)
    bad["hooks"][0]["sentences"][0]["text"] = "Welcome to the channel, divergence."
    assert "a05.sh.hooks" in run(bad)
    bad = copy.deepcopy(good)
    bad["hooks"][1]["sentences"][0]["text"] = "Buy NIFTY with this plan, divergence."
    assert "a05.sh.fin_prefilter" in run(bad)


def test_cut_duration_with_a_rate() -> None:
    settings = sp.make_settings(speech_rate_cps={"en-IN": 0.5})
    doc, _, cites_l, _ = parent_script()
    cites = {k: set(v) for k, v in cites_l.items()}
    from agent_05_scriptwriter.steps.shorts import parent_view

    step_in = CutStepInput.model_validate(
        {
            "language": "en-IN",
            "channel_category": "finance",
            "owner_sebi_registration": "UNREGISTERED",
            "active_rule_packs": ["rp.youtube_general"],
            "video_kind": "GENERAL",
            "parent": parent_view(doc, []).model_dump(mode="json"),
            "glossary_terms": [],
            "short_target_duration_ms": 45000,
            "max_duration_ms": 60000,
            "speech_budget": None,
            "owner_instruction": None,
            "latin_allow_list": [],
            "min_hook_options": 3,
            "max_hook_options": 5,
            "hook_history": [],
            "course_chapter_pointer": None,
            "revision_feedback": None,
            "previous_cut": None,
        }
    )
    cut = CutOutput.model_validate(
        sp.cut_json(step_in.model_dump(mode="json"), {k: sorted(v) for k, v in cites.items()})
    )
    report = CutChecker(settings, sp.SCANNERS).check(cut, step_in, parent_citations=cites)
    assert "a05.sh.duration" in failing_ids(report.results)


def test_whole_script_checks_with_a_rate_and_task_output_paths() -> None:
    ctx = sp.make_ctx()
    st = sp.MemoryState()
    settings = sp.make_settings(
        speech_rate_cps={"en-IN": 12.0},
        hook_min_fill_ratio=0.1,
        size_tolerance=0.9,
        duration_tolerance=0.9,
        hook_beat_tolerance=0.9,
    )
    step = ScriptDraftStep(
        sp.ScriptedLlm(["VALID_PLAN", "VALID_SECTIONS"], 2),
        sp.make_ports(st),
        settings,
        sp.prompts(),
        sp.scanners_for,
    )
    out = step.run(ScriptDraftRequest(ctx, sp.make_input(), sp.make_resolved(ctx)))
    assert out.status in ("SUCCEEDED", "FAILED")
    if out.status == "SUCCEEDED":
        doc = ScriptDocument.model_validate(json.loads(st.saved_contents[sp.need(out.saved).uri]))
        assert all(s.est_duration_ms is not None for s in doc.segments)
        assert doc.chapters[0].est_start_ms == 0 and sp.draft(out).totals.est_duration_ms
    failed = StepOutcome("FAILED", None, [], error=QualityRepeatedFailureError("x"))
    validate_task_output(
        build_task_output(
            failed, ctx, now=datetime.now(UTC), duration_ms=1, attempt_no=1
        ).model_dump(mode="json"),
        version="1.0.0",
    )
    from amw_core.errors import BudgetExhaustedError, RateLimitedError

    susp = StepOutcome(
        "SUSPENDED", None, [], error=BudgetExhaustedError("x"), wait_reason="AWAITING_BUDGET"
    )
    validate_task_output(
        build_task_output(susp, ctx, now=datetime.now(UTC), duration_ms=1, attempt_no=1).model_dump(
            mode="json"
        ),
        version="1.0.0",
    )
    retry = StepOutcome("FAILED", None, [], error=RateLimitedError("x", retry_after_ms=1000))
    task = build_task_output(retry, ctx, now=datetime.now(UTC), duration_ms=1, attempt_no=2)
    assert task.next_action.type.value == "RETRY"


def test_owner_topic_maps_to_the_task_input() -> None:
    owner = OwnerTopic.model_validate(
        {
            "title": "Divergence on a past chart",
            "brief": "ignored here",
            "angle": "keep it simple",
            "schema_version": "1.0.0",
            "language": "mr-IN",
            "video_kind": "METHOD_TOPIC",
            "course_chapter_pointer": {"label": "Chapter label"},
            "owner_references": [],
            "target_duration_ms": 480000,
            "shorts_wanted": True,
        }
    )
    inp = script_draft_input_from_owner_topic(
        owner,
        channel_category="finance",
        active_rule_packs=["rp.youtube_general", "rp.finance_sebi_in"],
    )
    assert inp.topic.title == owner.title and inp.topic.angle == "keep it simple"
    assert (
        inp.video_kind == "METHOD_TOPIC"
        and sp.need(inp.course_chapter_pointer).label == "Chapter label"
    )
    assert inp.language == "mr-IN" and inp.iteration == 0 and inp.revision is None
    assert "brief" not in inp.model_dump()["topic"]
    bad = owner.model_copy(update={"language": "fr-FR"})
    with pytest.raises(InputInvalidError):
        script_draft_input_from_owner_topic(
            bad, channel_category="finance", active_rule_packs=["rp.youtube_general"]
        )


def test_shorts_input_fixture_is_valid() -> None:
    doc, sha, _, _ = parent_script()
    assert shorts_input(doc, sha).short_target_duration_ms == 45000
