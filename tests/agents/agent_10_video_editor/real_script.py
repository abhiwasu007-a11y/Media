"""A real ``agent_05.script_document``: emitted by Agent 05's own assembler (the producer), then
serialised the way Agent 05 writes the blob. Tests only: production code of Agent 10 never imports
Agent 05 (it reads the document through its own slice model, CCR-200)."""

import math
from typing import Any

from agent_05_scriptwriter.assemble.assembler import AssemblyInput, assemble
from agent_05_scriptwriter.assemble.parts import DisclaimerTemplate
from agent_05_scriptwriter.contracts import DocPromise, PlanOutput, Scene
from tests.agents.agent_05_scriptwriter import support as sp

HOOK_SEGMENTS = 3
SEGMENTS_PER_SECTION = 4  # two scenes of two sentences (``section_json``)
DISCLAIMER_TEXT = "This video is education only and is not investment advice."


def real_script_document(
    min_segments: int,
    *,
    text_overrides: dict[str, str] | None = None,
    on_screen: tuple[str, ...] = (),
    disclaimer: bool = False,
) -> dict[str, Any]:
    """The JSON document Agent 05 emits, with at least ``min_segments`` segments (s1, s2, ...).
    ``text_overrides`` replaces the text of named segments in the emitted document;
    ``on_screen`` is written on the first scene of section 1."""
    count = max(1, math.ceil((min_segments - HOOK_SEGMENTS) / SEGMENTS_PER_SECTION))
    plan = PlanOutput.model_validate(sp.plan_json(count))
    sections = [
        plan.sections[i].model_copy(update={"section_id": f"sec{i + 1}"}) for i in range(count)
    ]
    scenes: dict[str, list[Scene]] = {}
    for index in range(count):
        sid = f"sec{index + 1}"
        raw = sp.section_json(
            {
                "section_plan": {
                    "section_id": sid,
                    "concept_ids": ["k1"],
                    "needs_interrupt": False,
                    "section_kind": "CONCEPT",
                },
                "concept_briefs": [{"concept_id": "k1", "citation_refs": ["kch_x"]}],
            }
        )
        if index == 0:
            raw["scenes"][0]["on_screen_text"] = list(on_screen)
        scenes[sid] = [Scene.model_validate(s) for s in raw["scenes"]]
    assert plan.hooks[0].beats
    assert plan.title_promise
    document = assemble(
        AssemblyInput(
            script_id="scr_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8001",
            job_id="job_x",
            channel_id="chn_x",
            language="en-IN",
            version=1,
            iteration=0,
            promise=DocPromise(**plan.title_promise.model_dump()),
            hook_beats=plan.hooks[0].beats,
            hook_chart_id="chart_1",
            sections=sections,
            section_scenes=scenes,
            concept_map={"k1": "c01", "k2": "c02"},
            hook_options=[],
            description_draft=None,
            thumbnail_brief=None,
            rate_cps=None,
            disclaimer_template=DisclaimerTemplate("r", "v", DISCLAIMER_TEXT)
            if disclaimer
            else None,
            disclaimer_placements=["END"] if disclaimer else [],
        )
    ).document
    data: dict[str, Any] = document.model_dump(mode="json")
    overrides = text_overrides or {}
    for segment in data["segments"]:
        if segment["segment_id"] in overrides:
            segment["text"] = overrides[segment["segment_id"]]
    return data
