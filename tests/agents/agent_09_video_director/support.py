# ruff: noqa: E501
"""Shared fixtures for the agent_09 tests: sample script, timeline, fake LLM, recorder."""

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_09_video_director.config import Agent09Config, base_for_tests
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
from agent_09_video_director.step import ShotPlanRequest, ShotPlanStep, Verification
from amw_adapters.common import FixtureStore
from amw_adapters.llm.fake import FakeLlmAdapter
from amw_adapters.llm.protocol import LlmRequest, LlmResponse
from amw_core.ids import ORG, Prefix, new_id

REPO = Path(__file__).resolve().parents[3]
PROMPT_PATH = REPO / "docs/v4/prompts/agent_09_video_director/shot_direction.v1.md"
EVALS = REPO / "docs/v4/evals/agent_09_video_director"
ORG_ID = str(ORG.new())
TASK_ID = str(new_id(Prefix.TASK))
SHA_A = "a" * 64
INPUT_RE = re.compile(r"<<<INPUT\n(.*)\nINPUT>>>", re.S)
DEP_OFF = {
    "real_person": False, "identifiable_person": False, "market_direction_imagery": False,
    "market_data_screen": False, "brand_or_logo": False, "ai_presenter": False,
    "realistic_event_depiction": False, "schematic": False,
}  # fmt: skip
WORDS = ["hands", "desk", "window", "notebook", "lamp", "plant", "shelf", "cup", "door", "path"]


def cfg(**over: object) -> Agent09Config:
    """Test config: the README base plus the optional keys that the sample plan needs."""
    base = base_for_tests()
    values: dict[str, Any] = {
        "held_max_ms": 8000, "first_dropoff_start_ms": 8000, "first_dropoff_end_ms": 40_000,
        "midpoint_half_width_ms": 15_000, "jl_offset_ms": 400, "jl_every_nth": 1,
        "transition_max_ms": 500, "end_screen_length_ms": 20_000, "tier_e_plan_permille": 500,
        "fallback_max_share_permille": 500,
    }  # fmt: skip
    values.update(over)
    return Agent09Config.model_validate({**base.model_dump(), **values})


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sample_script(aspect: AspectRatio = AspectRatio.LANDSCAPE) -> tuple[ScriptDoc, dict[str, int]]:
    """Long-form: 3 sections, a chart scene, an interrupt, a recap and a disclaimer."""
    if aspect is AspectRatio.PORTRAIT:
        kinds = [SegmentKind.SHORT_HOOK, SegmentKind.SHORT_HOOK, *([SegmentKind.BODY] * 5)]
        segs = [
            Segment(segment_id=f"s{i}", kind=k, scene_id="sc1" if i <= 2 else "sc2",
                    text=f"narration {i}", parent_segment_ids=(f"p{i}",))
            for i, k in enumerate(kinds, start=1)
        ]  # fmt: skip
        pscenes: tuple[Scene, ...] = (
            Scene(scene_id="sc1", segment_ids=("s1", "s2"), beat="HOOK",
                  on_screen_text=("Key idea",)),
            Scene(scene_id="sc2", segment_ids=tuple(f"s{i}" for i in range(3, 8)),
                  on_screen_text=("Habit",)),
        )  # fmt: skip
        script = ScriptDoc(script_id="scr_x", version=1, language="en-IN", aspect_ratio=aspect,
                           scenes=pscenes, segments=tuple(segs))  # fmt: skip
        durs = {f"s{i}": d for i, d in enumerate([2600, 2800, 3500, 4200, 3900, 4100, 3000], 1)}
        return script, durs
    plan: list[tuple[str, str, str, SegmentKind, int]] = [
        ("s1", "sec1.sc1", "sec1", SegmentKind.HOOK_PROOF, 5200),
        ("s2", "sec1.sc1", "sec1", SegmentKind.HOOK_WHY, 6100),
        ("s3", "sec1.sc1", "sec1", SegmentKind.HOOK_COVERS, 5000),
        ("s4", "sec1.sc2", "sec1", SegmentKind.BODY, 7000),
        ("s5", "sec2.sc1", "sec2", SegmentKind.BODY, 9000),
        ("s6", "sec2.sc2", "sec2", SegmentKind.BODY, 12_000),
        ("s7", "sec2.sc3", "sec2", SegmentKind.BODY, 8000),
        ("s8", "sec2.sc3", "sec2", SegmentKind.BODY, 6500),
        ("s9", "sec3.sc1", "sec3", SegmentKind.RECAP, 9000),
        ("s10", "sec3.sc2", "sec3", SegmentKind.DISCLAIMER, 6000),
    ]
    segments = tuple(
        Segment(segment_id=i, kind=k, scene_id=sc, section_id=sec, text=f"narration {i}")
        for i, sc, sec, k, _ in plan
    )
    scenes: tuple[Scene, ...] = (
        Scene(scene_id="sec1.sc1", section_id="sec1", beat="HOOK", segment_ids=("s1", "s2", "s3"),
              on_screen_text=("Core idea",)),
        Scene(scene_id="sec1.sc2", section_id="sec1", segment_ids=("s4",)),
        Scene(scene_id="sec2.sc1", section_id="sec2", segment_ids=("s5",),
              on_screen_text=("First term", "Second term")),
        Scene(scene_id="sec2.sc2", section_id="sec2", segment_ids=("s6",), chart_id="chart_hist1",
              change_beats=2, explanatory=False, tier_hint=Tier.C),
        Scene(scene_id="sec2.sc3", section_id="sec2", segment_ids=("s7", "s8"),
              interrupt={"device": "GRAPHIC"}),
        Scene(scene_id="sec3.sc1", section_id="sec3", beat="RECAP", segment_ids=("s9",)),
        Scene(scene_id="sec3.sc2", section_id="sec3", beat="DISCLAIMER", segment_ids=("s10",),
              explanatory=False),
    )  # fmt: skip
    sections = tuple(
        Section(section_id=sid, heading_local=f"Heading {sid}",
                scene_ids=tuple(sc.scene_id for sc in scenes if sc.section_id == sid))
        for sid in ("sec1", "sec2", "sec3")
    )  # fmt: skip
    script = ScriptDoc(
        script_id="scr_x", version=1, language="en-IN", aspect_ratio=aspect, sections=sections,
        scenes=scenes, segments=segments,
        chart_requests=(ChartRequest(chart_id="chart_hist1", first_segment_id="s6"),),
        disclaimer_slots=(DisclaimerSlot(slot_id="ds1", segment_id="s10", text_sha256=sha("disc")),),
    )  # fmt: skip
    return script, {i: d for i, _, _, _, d in plan}


def timeline_for(durations: dict[str, int], gap: int = 0) -> NarrationTimeline:
    t = 0
    segs = []
    for sid, d in durations.items():
        segs.append(TimelineSegment(segment_id=sid, start_ms=t, end_ms=t + d))
        t += d + gap
    return NarrationTimeline(source="PROVIDER_CLIPS", segments=tuple(segs))


def respond(request: LlmRequest) -> str:
    """A compliant model: one direction per slot, no digits, no names, text only from options."""
    m = INPUT_RE.search(request.messages[0].content)
    if m is None:
        raise ValueError("no data block")
    data = json.loads(m.group(1))
    portrait = data["aspect_ratio"] == "9:16"
    out = []
    for slot in data["slots"]:
        interrupt = slot["role"] == "INTERRUPT_REQUIRED"
        device = slot["allowed_devices"][0] if interrupt and slot["allowed_devices"] else None
        word = WORDS[int(slot["slot_id"][2:]) % len(WORDS)]
        kind = "FOOTAGE"
        out.append(
            {
                "slot_id": slot["slot_id"], "status": "OK", "reason_code": None,
                "intent_kind": kind,
                "intent_text": f"Close-up of {word} on a wooden table, soft light, shallow depth.",
                "framing": ["CLOSE_UP", "WIDE", "MEDIUM", "DETAIL"][int(slot["slot_id"][2:]) % 4],
                "motion": "PUNCH_IN" if interrupt else "SLOW_PUSH_IN",
                "still_ok": data["capabilities"]["still_allowed"], "needs_ai_video": False,
                "interrupt_device": device, "transition_hint": "CUT",
                "text_ids": [slot["text_options"][0]["text_id"]] if slot["text_options"] else [],
                "subject_anchor": "CENTER" if portrait else None, "depiction": dict(DEP_OFF),
                "rationale": "The picture supports the point being made.",
            }
        )  # fmt: skip
    return json.dumps({"batch_id": data["batch_id"], "directions": out, "refusal": None})


class _Responder(FixtureStore):
    def __init__(self, fn: Callable[[LlmRequest], str]) -> None:
        super().__init__(Path("/nonexistent"))
        self.fn = fn
        self.current: LlmRequest | None = None

    def find(self, adapter: str, operation: str, request: Any) -> dict[str, Any] | None:
        assert self.current is not None
        return {"text": self.fn(self.current)}


class ResponderLlm(FakeLlmAdapter):
    """FakeLlmAdapter whose text comes from a function of the request (scripted responses)."""

    def __init__(self, fn: Callable[[LlmRequest], str] = respond, **kw: Any) -> None:
        self.responder = _Responder(fn)
        super().__init__(fixtures=self.responder, **kw)
        self.requests: list[LlmRequest] = []

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        self.responder.current = request
        self.requests.append(request)
        return super().complete(request, idempotency_key=idempotency_key)


class Recorder:
    def __init__(self) -> None:
        self.rows: list[tuple[str, int]] = []

    def record(self, response: LlmResponse, idempotency_key: str) -> str:
        self.rows.append((idempotency_key, response.usage.amount_micros))
        return f"cst_{len(self.rows):04d}"


def make_request(script: ScriptDoc, durations: dict[str, int], **over: Any) -> ShotPlanRequest:
    tl = timeline_for(durations)
    aspect = script.aspect_ratio
    base: dict[str, Any] = {
        "org_id": ORG_ID, "task_id": TASK_ID, "declared_orgs": (ORG_ID,),
        "uris": (f"amw-blob://{ORG_ID}/jobs/script.json",),
        "production_type_key": "SHORTS" if aspect is AspectRatio.PORTRAIT else "CHANNEL_LONG_FORM",
        "aspect_ratio": aspect, "script": script, "script_sha256": SHA_A, "script_ref_sha256": SHA_A,
        "verification": Verification(SHA_A, "ALLOWED"), "timeline": tl, "timeline_sha256": "b" * 64,
        "brand": BrandKit(intro_ref="template:sting_a", intro_duration_ms=1200,
                          lower_third_template_ref="template:lt"),
        "channel_category": "finance", "limits": Limits(ai_still_allowed=True),
        "max_calls": 50, "max_cost_micros": 10**9, "worst_case_call_micros": 1000,
    }  # fmt: skip
    base.update(over)
    return ShotPlanRequest(**base)


def make_step(
    llm: FakeLlmAdapter | None = None,
    config: Agent09Config | None = None,
    recorder: Recorder | None = None,
) -> tuple[ShotPlanStep, ResponderLlm, Recorder]:
    llm_ = llm or ResponderLlm()
    rec = recorder or Recorder()
    step = ShotPlanStep(
        llm=llm_, prompts=FilePromptStore(PROMPT_PATH), recorder=rec, cfg=config or cfg()
    )
    return step, llm_ if isinstance(llm_, ResponderLlm) else ResponderLlm(), rec


def ctx_of(res: Any, req: ShotPlanRequest, config: Agent09Config | None = None) -> Any:
    """A CheckContext for a finished plan (checks are re-run by tests on tampered plans)."""
    from agent_09_video_director.checks import CheckContext
    from agent_09_video_director.timeline.timemap import build_time_map

    return CheckContext(
        plan=res.plan, script=req.script,
        tm=build_time_map([s.segment_id for s in req.script.segments], req.timeline),
        cfg=config or cfg(), limits=req.limits, channel_category=req.channel_category,
        accepted=res.accepted, slot_ids=list(res.accepted), banned_subjects=req.banned_subjects,
        jl_eligible_count=3,
    )  # fmt: skip
