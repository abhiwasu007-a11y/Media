# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated,index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""``s09_plan`` -> ``agent_09.shot_plan``.

Agent 09 takes a typed request (no ``TaskInput`` entry point and no reader of the Agent 05
document): the INPUT BUILDER below maps the stored script document and the measured narration
timeline onto ``ShotPlanRequest`` (integration finding: P4-10 input builders are not built).
"""

import json
from datetime import UTC, datetime
from typing import Any

from agent_09_video_director.contracts import (
    AspectRatio,
    BrandKit,
    ChartRequest,
    DisclaimerSlot,
    Limits,
    NarrationTimeline,
    Scene,
    ScriptDoc,
    Section,
    Segment,
    SegmentKind,
    Tier,
    TimelineSegment,
)
from agent_09_video_director.direction.prompt import FilePromptStore
from agent_09_video_director.output import build_task_output
from agent_09_video_director.step import ShotPlanRequest, ShotPlanStep, Verification
from amw_core.contracts import TaskOutput
from amw_core.ids import COST_ENTRY
from amw_orchestrator.executor import StageCall
from amw_orchestrator.metering import MeteredLlm
from tests.agents.agent_09_video_director import support as s9
from tests.dryrun.base import World, upstream, upstream_data
from tests.dryrun.kit import ref_ending
from tests.dryrun.llm import ScriptedLlm

_BEATS = {"HOOK_PROOF": "HOOK", "HOOK_WHY": "HOOK", "HOOK_COVERS": "HOOK"}


def responder(request: Any) -> str:
    """Agent 09's own compliant test responder, with PLUMBING intent texts."""
    doc = json.loads(s9.respond(request))
    for d in doc["directions"]:
        d["intent_text"] = "Plain abstract card on a calm background, slow push in."
        d["rationale"] = "PLUMBING scripted direction."
    return json.dumps(doc)


def script_view(doc: dict[str, Any], aspect: AspectRatio) -> ScriptDoc:
    """Input builder: Agent 05 script document -> Agent 09 ``ScriptDoc``."""
    # The 05 document puts the hook (and the disclaimer before section 1) outside every section;
    # Agent 09 starts chapter 1 at 0 ms and Agent 10 QC compares chapter starts with the first
    # shot of each section, so the lead-in scenes are attributed to the first section here.
    sections_in = doc.get("sections", [])
    first = sections_in[0]["section_id"] if sections_in else None
    lead = []
    for sc in doc["scenes"]:
        if sc.get("section_id") in (None, "hook"):
            lead.append(sc["scene_id"])
        else:
            break
    lead_set = set(lead)

    def sec_of(scene_id: str, value: str | None) -> str | None:
        return first if scene_id in lead_set else (None if value == "hook" else value)

    segments = tuple(
        Segment(
            segment_id=s["segment_id"],
            kind=SegmentKind(s["kind"]),
            scene_id=s["scene_id"],
            section_id=sec_of(s["scene_id"], s.get("section_id")),
            chart_ref=s.get("chart_ref"),
            parent_segment_ids=tuple(s.get("parent_segment_ids") or ()),
            text=s["text"],
        )
        for s in doc["segments"]
    )
    scenes = []
    for sc in doc["scenes"]:
        intent = sc.get("visual_intent") or {}
        scenes.append(
            Scene(
                scene_id=sc["scene_id"],
                section_id=sec_of(sc["scene_id"], sc.get("section_id")),
                beat=_BEATS.get(sc["beat"], sc["beat"]),
                segment_ids=tuple(sc["segment_ids"]),
                on_screen_text=tuple(sc.get("on_screen_text") or ()),
                tier_hint=Tier(intent.get("tier_hint", "C_CODE_MOTION")),
                visual_description=intent.get("description", ""),
                change_beats=intent.get("change_beats", 1),
                interrupt=({"device": sc["interrupt"]["kind"]} if sc.get("interrupt") else None),
                deliberate_pause_ms=sc.get("deliberate_pause_ms") or None,
                explanatory=bool(sc.get("explanatory", True)),
                chart_id=sc.get("chart_id"),
            )
        )
    sections = tuple(
        Section(
            section_id=s["section_id"],
            section_kind=s.get("section_kind", "CONCEPT"),
            heading_local=s.get("heading_local", ""),
            scene_ids=tuple(
                (lead if s["section_id"] == first else []) + list(s.get("scene_ids") or ())
            ),
        )
        for s in sections_in
    )
    return ScriptDoc(
        script_id=doc["script_id"],
        version=doc["version"],
        language=doc["language"],
        aspect_ratio=aspect,
        sections=sections,
        scenes=tuple(scenes),
        segments=segments,
        chart_requests=tuple(
            ChartRequest(chart_id=c["chart_id"], first_segment_id=c["first_segment_id"])
            for c in doc.get("chart_requests", [])
        ),
        disclaimer_slots=tuple(
            DisclaimerSlot(
                slot_id=d["slot_id"], segment_id=d["segment_id"], text_sha256=d["text_sha256"]
            )
            for d in doc.get("disclaimer_slots", [])
        ),
    )


class _Recorder:
    def record(self, response: Any, idempotency_key: str) -> str:
        return str(COST_ENTRY.new())


class PlanExecutor:
    def __init__(self, world: World) -> None:
        self.w = world

    def execute(self, call: StageCall) -> TaskOutput:
        shorts = call.job.production_type_key.value == "SHORTS"
        aspect = AspectRatio.PORTRAIT if shorts else AspectRatio.LANDSCAPE
        script_stage = "s05_shorts" if shorts else "s05_script"
        sref = ref_ending(upstream(call, script_stage), ".json")
        doc = self.w.blobs.read_json(sref.uri, sref.sha256)
        voice = upstream(call, "s07_voice")
        tl_ref = next(r for r in voice.output_refs if "timeline" in r.uri)
        tl_doc = self.w.blobs.read_json(tl_ref.uri, tl_ref.sha256)
        timeline = NarrationTimeline(
            source=tl_doc["source"],
            segments=tuple(
                TimelineSegment(
                    segment_id=s["segment_id"], start_ms=s["start_ms"], end_ms=s["end_ms"]
                )
                for s in tl_doc["segments"]
            ),
        )
        verify = upstream_data(call, "s06_verify")
        org = call.job.org_id
        prev_plan = None
        if call.prior_output is not None:
            from agent_09_video_director.contracts import ShotPlan

            pref = ref_ending(call.prior_output, ".json")
            prev_plan = ShotPlan.model_validate_json(self.w.blobs.read(pref.uri, pref.sha256))
        req = ShotPlanRequest(
            org_id=org,
            task_id=call.task_id,
            declared_orgs=(org,),
            uris=(sref.uri, tl_ref.uri),
            production_type_key="SHORTS" if shorts else "CHANNEL_LONG_FORM",
            aspect_ratio=aspect,
            script=script_view(doc, aspect),
            script_sha256=sref.sha256,
            script_ref_sha256=sref.sha256,
            verification=Verification(
                verify["script_sha256"], verify["overall"]["verification_verdict"]
            ),
            timeline=timeline,
            timeline_sha256=tl_ref.sha256,
            brand=BrandKit(
                intro_ref="tpl.plumbing_title",
                intro_duration_ms=1500,
                outro_ref="tpl.plumbing_end",
                fallback_template_key="tpl.abstract_motion",
            ),
            channel_category="finance",
            limits=Limits(ai_still_allowed=False),
            rule_packs={"rp.youtube_general": "PLUMBING YT", "rp.finance_sebi_in": "PLUMBING FIN"},
            rule_pack_versions={"rp.youtube_general": "1", "rp.finance_sebi_in": "1"},
            iteration=call.iteration,
            previous_plan=prev_plan,
            max_calls=call.resource_budget.max_llm_calls or 30,
            max_cost_micros=call.resource_budget.max_cost_micros,
            worst_case_call_micros=2_000,
        )
        step = ShotPlanStep(
            llm=MeteredLlm(ScriptedLlm(responder), self.w.meter, 2_000),
            prompts=FilePromptStore(s9.PROMPT_PATH),
            recorder=_Recorder(),
            cfg=s9.cfg(end_screen_length_ms=5000),
        )
        result = step.run(req)
        body = result.plan.model_dump_json().encode()
        uri, sha = self.w.blobs.put_bytes(
            "jobs", f"{call.job.job_id}/tasks/{call.task_id}/shot_plan.json", body
        )
        from agent_09_video_director.persistence import OutputRefData

        ref = OutputRefData(uri=uri, sha256=sha, size_bytes=len(body))
        return build_task_output(
            result, req.script, ref, now=datetime.now(UTC), duration_ms=1, currency="USD"
        )
