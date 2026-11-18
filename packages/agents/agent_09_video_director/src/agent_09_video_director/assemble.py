"""PlanAssembler (F-25): slots + accepted directions -> the ShotPlan. Pure and deterministic."""

import hashlib
import itertools
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import (
    Anchor,
    AspectRatio,
    AudioPlan,
    BrandKit,
    DeliberateHold,
    Depict,
    Direction,
    Framing,
    HookFacts,
    IntentKind,
    InterruptInfo,
    InterruptSummary,
    JlCutSummary,
    Limits,
    Motion,
    Origin,
    Refusal,
    ScriptDoc,
    SegmentKind,
    Shot,
    ShotPlan,
    Slot,
    Stats,
    TextRef,
    TextRefDisclaimer,
    TextRefScene,
    Tier,
    TierBudget,
    Transition,
    TransitionKind,
)
from agent_09_video_director.direction.runner import Accepted
from agent_09_video_director.problems import input_invalid
from agent_09_video_director.timeline.audio import plan_audio
from agent_09_video_director.timeline.hook import HookInfo
from agent_09_video_director.timeline.jl import BoundaryInfo, JlShot, plan_jl
from agent_09_video_director.timeline.overlays import build_chapters, plan_end_screen, plan_overlays
from agent_09_video_director.timeline.tiers import TierShot, plan_tiers
from agent_09_video_director.timeline.timemap import TimeMap
from agent_09_video_director.timeline.transitions import BoundaryKind, plan_transition
from agent_09_video_director.timeline.vertical import map_parent_shots, plan_vertical


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def plan_hash(plan: ShotPlan) -> str:
    """SHA-256 of the canonical JSON without ``provenance`` (determinism hash, 8.2)."""
    doc = plan.model_dump(mode="json", exclude={"provenance"})
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AssembleInput:
    script: ScriptDoc
    script_sha256: str
    timeline_sha256: str
    tm: TimeMap
    hook: HookInfo
    slots: Sequence[Slot]
    accepted: Mapping[str, Accepted]
    brand: BrandKit
    limits: Limits
    cfg: Agent09Config
    iteration: int = 0
    refusal: Refusal | None = None
    parent_shots: Mapping[str, Sequence[str]] | None = None


def _text_refs(slot: Slot, direction: Direction | None, script: ScriptDoc) -> tuple[TextRef, ...]:
    if slot.origin is Origin.CODE_DISCLAIMER:
        by_seg = {d.segment_id: d for d in script.disclaimer_slots}
        for seg_id in slot.segment_ids:
            d = by_seg.get(seg_id)
            if d is not None:
                return (TextRefDisclaimer(disclaimer_slot_id=d.slot_id, sha256=d.text_sha256),)
        return ()
    if direction is None:
        return ()
    scene = next(s for s in script.scenes if s.scene_id == slot.scene_id)
    refs: list[TextRef] = []
    for tid in direction.text_ids:
        idx = int(tid[1:]) - 1
        refs.append(
            TextRefScene(
                scene_id=scene.scene_id, index=idx, sha256=sha256_text(scene.on_screen_text[idx])
            )
        )
    return tuple(refs)


def _boundary_kind(a: Shot, b: Shot) -> BoundaryKind:
    if a.section_id != b.section_id:
        return "SECTION"
    return "SCENE" if a.scene_id != b.scene_id else "SHOT"


@dataclass(frozen=True, slots=True)
class Assembled:
    plan: ShotPlan
    jl_eligible_count: int


def assemble_plan(inp: AssembleInput) -> Assembled:
    cfg, script, tm = inp.cfg, inp.script, inp.tm
    seg_start = {s: tm.start(s) for s in tm.order}
    scene_first = {sc.scene_id: sc.segment_ids[0] for sc in script.scenes}
    # 1. one shot per slot
    drafts: list[Shot] = []
    for seq, slot in enumerate(inp.slots, start=1):
        acc = inp.accepted.get(slot.slot_id)
        d = acc.direction if acc is not None else None
        if slot.origin is Origin.MODEL:
            if d is None:
                raise input_invalid("DIRECTION_MISSING")
            kind = IntentKind(d.intent_kind or "DIAGRAM")
            text, framing, motion = d.intent_text, d.framing, d.motion
            depict = Depict(
                realistic_event_depiction=d.depiction.realistic_event_depiction,
                schematic=d.depiction.schematic,
            )
            origin = acc.origin if acc else Origin.MODEL
        else:
            kind = slot.intent_kind or IntentKind.DIAGRAM
            text, framing, motion = "", Framing.NONE, Motion.STATIC
            depict = Depict(realistic_event_depiction=False, schematic=True)
            origin = slot.origin
        scene = next(s for s in script.scenes if s.scene_id == slot.scene_id)
        interrupt = (
            InterruptInfo(device=d.interrupt_device, window=slot.interrupt_window)
            if d is not None
            and d.interrupt_device is not None
            and slot.interrupt_window is not None
            else None
        )
        drafts.append(
            Shot(
                shot_id=f"sh{seq:02d}",
                seq=seq,
                scene_id=slot.scene_id,
                section_id=slot.section_id,
                start_ms=slot.start_ms,
                end_ms=slot.end_ms,
                duration_ms=slot.duration_ms,
                segment_ids=slot.segment_ids,
                intent_kind=kind,
                intent_text=text,
                framing=framing,
                motion=motion,
                allowed_tiers=(Tier.C,),
                tier_hint=scene.tier_hint,
                fallback_template_key=inp.brand.fallback_template_key,
                explanatory=slot.explanatory,
                held=slot.held,
                change_events_ms=slot.change_events_ms,
                interrupt=interrupt,
                transition_in=Transition(kind=TransitionKind.CUT, duration_ms=0),
                cut_offset_ms=0,
                jl_kind=None,
                chart_id=slot.chart_id,
                text_refs=_text_refs(slot, d, script),
                depiction=depict,
                origin=origin,
                content_key=sha256_text(f"{slot.scene_id}|{slot.ordinal}|{text}"),
                vertical=None,
                parent_shot_id=None,
            )
        )
    # 2. J/L cuts on sentence-aligned scene / section boundaries
    eligible = {
        b.start_ms
        for a, b in itertools.pairwise(drafts)
        if a.scene_id != b.scene_id
        and any(seg_start[s] == b.start_ms for s in scene_first.values() if s in seg_start)
    }
    kind_by_seg = {s.segment_id: s.kind for s in script.segments}
    info: dict[int, BoundaryInfo] = {}
    for a, b in itertools.pairwise(drafts):
        first_seg = b.segment_ids[0]
        info[b.start_ms] = BoundaryInfo(
            next_shot_is_chart=b.intent_kind is IntentKind.CHART,
            next_first_segment_starts_here=seg_start.get(first_seg) == b.start_ms,
            next_segment_is_disclaimer=b.origin is Origin.CODE_DISCLAIMER
            or kind_by_seg[first_seg] is SegmentKind.DISCLAIMER,
            previous_segment_is_disclaimer=a.origin is Origin.CODE_DISCLAIMER,
        )
    jl = plan_jl(
        [
            JlShot(
                s.shot_id,
                s.start_ms,
                s.end_ms,
                s.intent_kind is IntentKind.CHART,
                s.change_events_ms,
            )
            for s in drafts
        ],
        cfg,
        inp.hook.end_ms,
        eligible_boundaries_ms=eligible,
        info=info,
    )
    shifts = {c.to_shot_id: c for c in jl.applied}
    by_id = {s.shot_id: s for s in drafts}
    for cut in jl.applied:
        by_id[cut.from_shot_id] = by_id[cut.from_shot_id].model_copy(update={"end_ms": cut.cut_ms})
        by_id[cut.to_shot_id] = by_id[cut.to_shot_id].model_copy(
            update={"start_ms": cut.cut_ms, "cut_offset_ms": cut.cut_offset_ms, "jl_kind": cut.kind}
        )
    shots = [by_id[s.shot_id] for s in drafts]
    shots = [s.model_copy(update={"duration_ms": s.end_ms - s.start_ms}) for s in shots]
    # 3. transitions
    out_shots: list[Shot] = []
    for i, s in enumerate(shots):
        if i == 0:
            out_shots.append(s)
            continue
        prev = shots[i - 1]
        acc = inp.accepted.get(inp.slots[i].slot_id)
        hint = acc.direction.transition_hint.value if acc is not None else None
        tr = plan_transition(
            cfg,
            boundary=_boundary_kind(prev, s),
            hint=hint,
            shorter_neighbour_ms=min(prev.duration_ms, s.duration_ms),
            shifted_by_jl=s.shot_id in shifts,
        )
        out_shots.append(s.model_copy(update={"transition_in": tr}))
    shots = out_shots
    # 4. tiers
    tier_inputs = []
    for slot, s in zip(inp.slots, shots, strict=True):
        acc = inp.accepted.get(slot.slot_id)
        d = acc.direction if acc and acc.origin is not Origin.FALLBACK else None
        tier_inputs.append(
            TierShot(
                s.shot_id,
                s.duration_ms,
                s.intent_kind,
                bool(d and d.still_ok),
                bool(d and d.needs_ai_video),
            )
        )
    content_end = tm.content_end_ms
    tiers = plan_tiers(tier_inputs, content_end, inp.limits, cfg)
    shots = [s.model_copy(update={"allowed_tiers": tiers.allowed[s.shot_id]}) for s in shots]
    # 5. vertical + parent mapping
    anchors: list[Anchor | None] = []
    for slot in inp.slots:
        acc = inp.accepted.get(slot.slot_id)
        anchors.append(acc.direction.subject_anchor if acc is not None else None)
    verts = plan_vertical(script.aspect_ratio, anchors)
    parents: tuple[str | None, ...] = tuple(None for _ in shots)
    if inp.parent_shots is not None and script.aspect_ratio is AspectRatio.PORTRAIT:
        parent_of = {s.segment_id: s.parent_segment_ids for s in script.segments}
        parents = map_parent_shots([s.segment_ids for s in shots], parent_of, inp.parent_shots)
    shots = [
        s.model_copy(update={"vertical": v, "parent_shot_id": p})
        for s, v, p in zip(shots, verts, parents, strict=True)
    ]
    # 6. chapters, overlays, end screen, audio
    first_seg_of_scene = {sc.scene_id: sc.segment_ids[0] for sc in script.scenes}
    section_start = {
        sec.section_id: 0 if i == 0 else tm.start(first_seg_of_scene[sec.scene_ids[0]])
        for i, sec in enumerate(script.sections)
        if sec.scene_ids
    }
    chapters = build_chapters(script.sections, section_start, script.aspect_ratio)
    overlays = plan_overlays(
        shots,
        hook_end_ms=inp.hook.end_ms,
        content_end_ms=content_end,
        brand=inp.brand,
        chapters=chapters,
        aspect=script.aspect_ratio,
        cfg=cfg,
    )
    end_screen, pauses = plan_end_screen(content_end, cfg)
    total = end_screen.end_ms if end_screen else content_end
    interrupts = tuple(
        InterruptSummary(shot_id=s.shot_id, device=s.interrupt.device, window=s.interrupt.window)
        for s in shots
        if s.interrupt is not None
    )
    holds = tuple(
        DeliberateHold(
            start_ms=s.start_ms, end_ms=s.end_ms, shot_id=s.shot_id, reason=s.held.reason
        )
        for s in shots
        if s.held is not None
    )
    jl_summary = tuple(
        JlCutSummary(
            boundary_ms=c.boundary_ms,
            kind=c.kind,
            offset_ms=c.cut_offset_ms,
            from_shot_id=c.from_shot_id,
            to_shot_id=c.to_shot_id,
        )
        for c in jl.applied
    ) + tuple(JlCutSummary(boundary_ms=k.boundary_ms, skipped_reason=k.reason) for k in jl.skipped)
    events = sorted({s.start_ms for s in shots} | {e for s in shots for e in s.change_events_ms})
    gaps = [b - a for a, b in itertools.pairwise(events)] or [content_end]
    fallback_n = sum(1 for s in shots if s.origin is Origin.FALLBACK)
    stats = Stats(
        slot_count=len(shots),
        llm_slot_count=sum(1 for sl in inp.slots if sl.origin is Origin.MODEL),
        fallback_count=fallback_n,
        repaired_count=sum(1 for s in shots if s.origin is Origin.REPAIRED),
        change_events_total=len(events),
        max_gap_ms=max(gaps),
        min_gap_ms=min(gaps),
    )
    realism = tuple(
        {
            "shot_id": s.shot_id,
            "realistic_event_depiction": s.depiction.realistic_event_depiction,
            "schematic": s.depiction.schematic,
            "origin": s.origin.value,
            "refusal_reason": (
                inp.accepted[sl.slot_id].refusal_reason if sl.slot_id in inp.accepted else None
            ),
        }
        for sl, s in zip(inp.slots, shots, strict=True)
    )
    audio: AudioPlan = plan_audio(total, interrupts, inp.limits, pauses)
    plan = ShotPlan(
        script_id=script.script_id,
        script_version=script.version,
        script_sha256=inp.script_sha256,
        language=script.language,
        aspect_ratio=script.aspect_ratio,
        iteration=inp.iteration,
        narration_timeline_sha256=inp.timeline_sha256,
        content_end_ms=content_end,
        total_duration_ms=total,
        hook=HookFacts(
            end_ms=inp.hook.end_ms,
            first_payoff_ms=inp.hook.first_payoff_ms,
            segment_ids=inp.hook.segment_ids,
        ),
        shots=tuple(shots),
        overlays=overlays,
        audio_plan=audio,
        chapters=chapters,
        deliberate_hold=holds,
        interrupts=interrupts,
        jl_cuts=jl_summary,
        tier_budget=TierBudget(
            worst_case_e_share_permille=tiers.worst_case_e_share_permille,
            e_limit_permille=tiers.e_limit_permille,
            ai_video_allowed_ms=tiers.ai_video_allowed_ms,
            ai_video_limit_ms=tiers.ai_video_limit_ms,
        ),
        stats=stats,
        refusal=inp.refusal,
        realism=realism,
    )
    return Assembled(plan, jl.eligible_count)
