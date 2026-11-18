"""The timing skeleton (P5, P6): slots tiling [0, content_end] from the measured timeline.

Pure: script + TimeMap + hook + config in, ``Slot`` list out. The model never sees or changes
times, counts or roles.
"""

from collections.abc import Sequence

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import (
    Device,
    DirectionSlot,
    Held,
    HeldReason,
    IntentKind,
    InterruptWindow,
    Limits,
    Origin,
    SceneVisualIntent,
    ScriptDoc,
    Segment,
    SegmentKind,
    Slot,
    SlotRole,
    TextOption,
)
from agent_09_video_director.mathx import round_half_up  # noqa: F401  (re-exported for tests)
from agent_09_video_director.problems import input_invalid, loop_cap
from agent_09_video_director.timeline.grid import GridSlot, build_slots, plan_chart
from agent_09_video_director.timeline.hook import HookInfo
from agent_09_video_director.timeline.interrupts import SlotSpan, place_interrupts
from agent_09_video_director.timeline.timemap import TimeMap


def _runs(segments: Sequence[Segment]) -> list[list[Segment]]:
    runs: list[list[Segment]] = []
    for seg in segments:
        is_disc = seg.kind is SegmentKind.DISCLAIMER
        if runs and (runs[-1][0].kind is SegmentKind.DISCLAIMER) == is_disc:
            runs[-1].append(seg)
        else:
            runs.append([seg])
    return runs


def build_skeleton(
    script: ScriptDoc, tm: TimeMap, hook: HookInfo, cfg: Agent09Config, limits: Limits
) -> list[Slot]:
    seg_by_id = {s.segment_id: s for s in script.segments}
    chart_by_scene = {sc.scene_id: sc.chart_id for sc in script.scenes if sc.chart_id}
    for req in script.chart_requests:
        seg = seg_by_id.get(req.first_segment_id)
        if (
            seg is None
            or chart_by_scene.get(seg.scene_id) != req.chart_id
            or not req.must_be_historical
        ):
            raise input_invalid("CHART_REQUEST_UNMATCHED")
    scene_first = [tm.start(sc.segment_ids[0]) if sc.segment_ids else -1 for sc in script.scenes]
    if any(f < 0 for f in scene_first):
        raise input_invalid("SCENE_WITHOUT_SEGMENTS")
    boundaries = tm.segment_starts()
    hook_ids = set(hook.segment_ids)
    section_first_scene = {
        sec.section_id: sec.scene_ids[0] for sec in script.sections if sec.scene_ids
    }
    slots: list[Slot] = []
    scripted_interrupt_ids: list[str] = []
    for i, sc in enumerate(script.scenes):
        t0 = 0 if i == 0 else scene_first[i]
        t1 = scene_first[i + 1] if i + 1 < len(script.scenes) else tm.content_end_ms
        if t1 <= t0:
            raise input_invalid("SCENE_SPAN_EMPTY")
        segs = [seg_by_id[s] for s in sc.segment_ids]
        in_hook = any(s.segment_id in hook_ids for s in segs)
        runs = _runs(segs)
        scene_slots_start = len(slots)
        for r, run in enumerate(runs):
            r0 = t0 if r == 0 else tm.start(run[0].segment_id)
            r1 = t1 if r + 1 == len(runs) else tm.start(runs[r + 1][0].segment_id)
            grid: list[GridSlot]
            origin = Origin.MODEL
            kind: IntentKind | None = None
            chart_id: str | None = None
            if run[0].kind is SegmentKind.DISCLAIMER:
                grid = [GridSlot(r0, r1, Held(reason=HeldReason.DISCLAIMER, max_ms=r1 - r0))]
                origin, kind = Origin.CODE_DISCLAIMER, IntentKind.TEXT_CARD
            elif sc.chart_id:
                grid = [plan_chart(change_beats=sc.change_beats, t0=r0, t1=r1, cfg=cfg)]
                origin, kind, chart_id = Origin.CODE_CHART, IntentKind.CHART, sc.chart_id
            else:
                role = "HOOK" if in_hook else ("RECAP" if sc.beat == "RECAP" else "EXPLAIN")
                grid = build_slots(
                    beat=sc.beat,
                    explanatory=sc.explanatory,
                    change_beats=sc.change_beats,
                    t0=r0,
                    t1=r1,
                    target_gap_ms=cfg.pacing_gap(sc.beat, role),
                    sentence_boundaries_ms=boundaries,
                    cfg=cfg,
                    deliberate_pause=sc.deliberate_pause_ms is not None,
                )
            for g in grid:
                names = [
                    s.segment_id
                    for s in run
                    if tm.start(s.segment_id) < g.end_ms and tm.end(s.segment_id) > g.start_ms
                ] or [run[0].segment_id]
                slots.append(
                    Slot(
                        slot_id=f"sl{len(slots) + 1:02d}",
                        scene_id=sc.scene_id,
                        section_id=sc.section_id,
                        start_ms=g.start_ms,
                        end_ms=g.end_ms,
                        segment_ids=tuple(names),
                        role=SlotRole.HOOK
                        if in_hook and origin is Origin.MODEL
                        else SlotRole.EXPLAIN,
                        intent_kind=kind,
                        origin=origin,
                        held=g.held,
                        change_events_ms=g.change_events_ms,
                        explanatory=sc.explanatory and origin is Origin.MODEL,
                        chart_id=chart_id,
                    )
                )
                if len(slots) > cfg.max_slots:
                    raise loop_cap("agent_09.max_slots", cfg.max_slots)
        # roles: recap / section opener / script-planned interrupt (first model slot of the scene)
        model_idx = [
            j for j in range(scene_slots_start, len(slots)) if slots[j].origin is Origin.MODEL
        ]
        for ord_, j in enumerate(range(scene_slots_start, len(slots))):
            slots[j] = slots[j].model_copy(update={"ordinal": ord_})
        if model_idx:
            first = model_idx[0]
            if not in_hook and sc.beat == "RECAP":
                for j in model_idx:
                    slots[j] = slots[j].model_copy(update={"role": SlotRole.RECAP})
            if (
                sc.section_id
                and section_first_scene.get(sc.section_id) == sc.scene_id
                and not in_hook
            ):
                slots[first] = slots[first].model_copy(update={"role": SlotRole.SECTION_OPENER})
            if sc.interrupt is not None:
                slots[first] = slots[first].model_copy(
                    update={
                        "role": SlotRole.INTERRUPT_REQUIRED,
                        "interrupt_window": InterruptWindow.SCRIPT_PLANNED,
                    }
                )
                scripted_interrupt_ids.append(slots[first].slot_id)
    spans = [SlotSpan(s.slot_id, s.start_ms, s.end_ms) for s in slots if s.origin is Origin.MODEL]
    placement = place_interrupts(spans, tm.content_end_ms, cfg, scripted_interrupt_ids)
    for forced in placement.forced:
        idx = next(j for j, s in enumerate(slots) if s.slot_id == forced.slot_id)
        slots[idx] = slots[idx].model_copy(
            update={"role": SlotRole.INTERRUPT_REQUIRED, "interrupt_window": forced.window}
        )
    return slots


def allowed_devices(limits: Limits) -> tuple[Device, ...]:
    base = (Device.CUTAWAY_BROLL, Device.GRAPHIC, Device.ZOOM, Device.ANGLE_CHANGE)
    return (*base, Device.SOUND_CUE) if limits.sfx_library_enabled else base


def direction_slots(
    slots: Sequence[Slot],
    script: ScriptDoc,
    tm: TimeMap,
    limits: Limits,
) -> list[DirectionSlot]:
    """Only MODEL slots, with the narration excerpt and the script's own text options."""
    seg_by_id = {s.segment_id: s for s in script.segments}
    scene_by_id = {s.scene_id: s for s in script.scenes}
    section_by_id = {s.section_id: s for s in script.sections}
    out: list[DirectionSlot] = []
    for slot in slots:
        if slot.origin is not Origin.MODEL:
            continue
        sc = scene_by_id[slot.scene_id]
        sec = section_by_id.get(sc.section_id or "")
        out.append(
            DirectionSlot(
                slot_id=slot.slot_id,
                scene_id=slot.scene_id,
                section_kind=sec.section_kind if sec else None,
                role=slot.role,
                duration_ms=slot.duration_ms,
                narration_excerpt=" ".join(seg_by_id[s].text for s in slot.segment_ids),
                scene_visual_intent=SceneVisualIntent(
                    tier_hint=sc.tier_hint, description=sc.visual_description
                ),
                text_options=tuple(
                    TextOption(text_id=f"t{n}", text=t)
                    for n, t in enumerate(sc.on_screen_text, start=1)
                ),
                allowed_devices=allowed_devices(limits)
                if slot.role is SlotRole.INTERRUPT_REQUIRED
                else (),
            )
        )
    return out
