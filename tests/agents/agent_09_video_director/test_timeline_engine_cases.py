# ruff: noqa: PT018, E501
"""R-02: the deterministic ``timeline_engine`` dataset (TE-01..TE-39) run against the engine.

Table-driven from docs/v4/evals/agent_09_video_director/timeline_engine/cases.jsonl: the case's
``expected`` object is compared exactly (assertion T1); gate cases make zero model calls (T4);
every function is run twice (T5).
"""

import itertools
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from agent_09_video_director.assemble import derive_holds
from agent_09_video_director.checks import (
    check_cadence,
    check_chapters,
    check_end_screen,
    check_hook_no_brand,
    check_hook_window,
    check_interrupt_first,
    check_revision_addressed,
    check_tier_plan,
    check_tiling,
    check_transitions,
    check_vertical,
)
from agent_09_video_director.config import Agent09Config, base_for_tests
from agent_09_video_director.contracts import (
    Anchor,
    AspectRatio,
    BrandKit,
    Held,
    HeldReason,
    Limits,
    NarrationTimeline,
    Overlay,
    OverlayKind,
    Scene,
    ScriptDoc,
    Section,
    Segment,
    SegmentKind,
    Tier,
    Vertical,
)
from agent_09_video_director.gates import script_gate
from agent_09_video_director.timeline.audio import plan_audio
from agent_09_video_director.timeline.grid import build_slots, plan_chart
from agent_09_video_director.timeline.hook import TimedSegment, analyze_hook
from agent_09_video_director.timeline.interrupts import SlotSpan, place_interrupts
from agent_09_video_director.timeline.jl import BoundaryInfo, JlShot, plan_jl
from agent_09_video_director.timeline.overlays import (
    build_chapters,
    plan_brand_sting,
    plan_end_screen,
)
from agent_09_video_director.timeline.rebase import rebase_shots
from agent_09_video_director.timeline.tiers import TierShot, plan_tiers
from agent_09_video_director.timeline.timemap import build_time_map
from agent_09_video_director.timeline.transitions import plan_transition
from amw_core.enums import CheckVerdict
from amw_core.errors import AmwError
from tests.agents.agent_09_video_director.support import (
    EVALS,
    ctx_of,
    make_request,
    make_step,
    sample_script,
    synth_ctx,
    synth_shot,
)

pytestmark = pytest.mark.unit

CASES = [
    json.loads(line) for line in (EVALS / "timeline_engine/cases.jsonl").read_text().splitlines()
]


def base(case_input: dict[str, Any], extra: dict[str, Any] | None = None) -> Agent09Config:
    return base_for_tests().with_overrides(
        {**case_input.get("config_overrides", {}), **(extra or {})}
    )


def grid(inp: dict[str, Any], c: Agent09Config, span: tuple[int, int] | None = None):  # type: ignore[no-untyped-def]
    sc = inp["scene"]
    t0, t1 = span or (inp["span"]["t0_ms"], inp["span"]["t1_ms"])
    return build_slots(
        beat=sc["beat"], explanatory=sc["explanatory"], change_beats=sc["change_beats"], t0=t0,
        t1=t1, target_gap_ms=inp["target_gap_ms"],
        sentence_boundaries_ms=inp["sentence_boundaries_ms"], cfg=c,
    )  # fmt: skip


def summarize(slots) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "slot_count": len(slots),
        "boundaries_ms": [s.start_ms for s in slots[1:]],
        "durations_ms": [s.end_ms - s.start_ms for s in slots],
    }


def te_slot_grid(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    if "variants" in inp:  # TE-32
        for var, want in zip(inp["variants"], exp["variants"], strict=True):
            c = base(var)
            slots = grid(inp, c, (0, var["span_ms"]))
            got = summarize(slots)
            assert got["slot_count"] == want["slot_count"]
            if "boundaries_ms" in want:
                assert got["boundaries_ms"] == want["boundaries_ms"]
            held = slots[0].held if len(slots) == 1 else None
            if want["held"] is None:
                assert all(s.held is None for s in slots)
            else:
                assert held is not None
                assert held.reason.value == want["held"]["reason"]
                assert held.max_ms == want["held"]["max_ms"]
        return
    c = base(inp)
    slots = grid(inp, c)
    got = summarize(slots)
    assert got == {k: exp[k] for k in got}
    assert grid(inp, c) == slots  # T5
    assert all(a.end_ms == b.start_ms for a, b in itertools.pairwise(slots))  # T2
    assert sum(s.end_ms - s.start_ms for s in slots) == slots[-1].end_ms - slots[0].start_ms
    assert all(s.end_ms - s.start_ms <= c.g_max_ms for s in slots if s.held is None)  # T3


def te_10(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    c = base(inp)
    starts, end = inp["scene_starts_ms"], inp["content_end_ms"]
    edges: list[int] = [0]
    for i, t0 in enumerate(starts):
        t1 = starts[i + 1] if i + 1 < len(starts) else end
        for s in build_slots(
            beat="EXPLAIN", explanatory=True, change_beats=1, t0=t0, t1=t1,
            target_gap_ms=inp["target_gap_ms"], sentence_boundaries_ms=[], cfg=c,
        ):  # fmt: skip
            edges.append(s.end_ms)
    assert edges == exp["all_boundaries_ms"]
    assert len(edges) - 1 == exp["slot_count"]
    shots = [synth_shot(i, a, b) for i, (a, b) in enumerate(itertools.pairwise(edges), 1)]
    assert check_tiling(synth_ctx(shots, config=c)).verdict.value == exp["a09.q.tiling"]


def te_hook(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    c = base(inp)
    aspect = AspectRatio(inp.get("aspect_ratio", "16:9"))
    segs = [
        TimedSegment(s["id"], SegmentKind(s["kind"]), s["start_ms"], s["end_ms"])
        for s in inp["segments"]
    ]
    if "error" in exp:
        with pytest.raises(AmwError) as ei:
            analyze_hook(segs, aspect, c.hook_window_ms)
        assert ei.value.code == exp["error"]
        assert ei.value.details["violations"] == exp["violations"]
        return
    h = analyze_hook(segs, aspect, c.hook_window_ms)
    assert (h.end_ms, h.first_payoff_ms) == (exp["hook_end_ms"], exp["first_payoff_ms"])
    ctx = synth_ctx([synth_shot(1, 0, segs[-1].end_ms)], config=c, aspect=aspect,
                    hook=(h.end_ms, h.first_payoff_ms))  # fmt: skip
    assert check_hook_window(ctx).verdict.value == exp["a09.q.hook_window"]


def te_sting(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    c = base(inp)
    brand = BrandKit(
        intro_ref=inp["brand"]["intro_ref"], intro_duration_ms=inp["brand"].get("intro_duration_ms")
    )
    got = plan_brand_sting(inp["hook_end_ms"], brand, c)
    want = [(o["start_ms"], o["end_ms"]) for o in exp["overlays"]]
    assert ([got] if got else []) == want
    overlays = (
        (Overlay(overlay_id="ov01", kind=OverlayKind.BRAND_STING, start_ms=got[0], end_ms=got[1],
                 template_ref=brand.intro_ref),)
        if got else ()
    )  # fmt: skip
    ctx = synth_ctx(
        [synth_shot(1, 0, 60_000)], config=c, hook=(inp["hook_end_ms"], 9800), overlays=overlays
    )
    assert check_hook_no_brand(ctx).verdict.value == exp["a09.q.hook_no_brand"]
    early = Overlay(
        overlay_id="ov02", kind=OverlayKind.BRAND_STING, start_ms=0, end_ms=900, template_ref="t"
    )
    assert (
        check_hook_no_brand(
            synth_ctx(
                [synth_shot(1, 0, 60_000)],
                config=c,
                hook=(inp["hook_end_ms"], 9800),
                overlays=(early,),
            )
        ).verdict
        is CheckVerdict.FAIL
    )


def te_interrupts(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    c = base(inp)
    spans = [SlotSpan(s["slot_id"], s["start_ms"], s["end_ms"]) for s in inp["slots"]]
    got = place_interrupts(spans, inp["content_end_ms"], c, inp["script_interrupt_slot_ids"])
    assert [f.slot_id for f in got.forced] == exp["forced_slot_ids"]
    if "window" in exp:
        assert got.forced[0].window.value == exp["window"]
    if "satisfied_by" in exp:
        assert set(got.satisfied_by.values()) == {exp["satisfied_by"]}


def te_jl(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    c = base(inp)
    shots = [JlShot(s["shot_id"], s["start_ms"], s["end_ms"]) for s in inp["shots"]]
    b = shots[1].start_ms
    info = {
        b: BoundaryInfo(
            next_shot_is_chart=inp.get("next_shot_kind") == "CHART",
            next_first_segment_starts_here=inp.get("next_first_segment_starts_at_boundary", False),
            next_segment_is_disclaimer=inp.get("next_segment_kind") == "DISCLAIMER",
        )
    }
    got = plan_jl(shots, c, inp["hook_end_ms"], info=info)
    assert [
        {k: v for k, v in {"boundary_ms": a.boundary_ms, "kind": a.kind, "cut_ms": a.cut_ms,
                           "cut_offset_ms": a.cut_offset_ms, "note": a.note}.items()
         if k != "note" or a.note is not None}
        for a in got.applied
    ] == exp["applied"]  # fmt: skip
    assert [{"boundary_ms": s.boundary_ms, "reason": s.reason} for s in got.skipped] == exp[
        "skipped"
    ]
    assert plan_jl(shots, c, inp["hook_end_ms"], info=info) == got  # T5


def te_end_screen(case: dict[str, Any]) -> None:
    inp = case["input"]
    for var, want in zip(inp["variants"], case["expected"]["variants"], strict=True):
        c = base(var)
        es, pauses = plan_end_screen(inp["content_end_ms"], c)
        overlays = (
            (Overlay(overlay_id="ov01", kind=OverlayKind.END_SCREEN, start_ms=es.start_ms,
                     end_ms=es.end_ms, template_ref="outro"),)
            if es else ()
        )  # fmt: skip
        ctx = synth_ctx(
            [synth_shot(1, 0, inp["content_end_ms"])], config=c, overlays=overlays, pauses=pauses
        )
        assert ctx.plan.total_duration_ms == want["total_duration_ms"]
        assert check_end_screen(ctx).verdict.value == want["a09.q.end_screen"]
        if want["end_screen"] is not None:
            assert es is not None
            assert (es.start_ms, es.end_ms) == (
                want["end_screen"]["start_ms"],
                want["end_screen"]["end_ms"],
            )
            assert [p.reason for p in pauses] == [p["reason"] for p in want["deliberate_pauses"]]
        else:
            assert es is None


def te_chapters(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    c = base(inp)
    aspect = AspectRatio(inp.get("aspect_ratio", "16:9"))
    sections = [
        Section(section_id=s["section_id"], scene_ids=(f"{s['section_id']}.sc",))
        for s in inp["sections"]
    ]
    starts = {s["section_id"]: s["first_segment_start_ms"] for s in inp["sections"]}
    ch = build_chapters(sections, starts, aspect)
    assert [x.start_ms for x in ch] == exp["chapters_ms"]  # estimates ignored
    segs = tuple(
        Segment(segment_id=f"s{i}", kind=SegmentKind.BODY, scene_id=f"{sec.section_id}.sc")
        for i, sec in enumerate(sections, 1)
    )
    scenes = tuple(
        Scene(scene_id=f"{sec.section_id}.sc", section_id=sec.section_id, segment_ids=(f"s{i}",))
        for i, sec in enumerate(sections, 1)
    )
    script = ScriptDoc(script_id="scr_x", version=1, language="en-IN", aspect_ratio=aspect,
                       sections=tuple(sections), scenes=scenes, segments=segs)  # fmt: skip
    spans = {
        f"s{i}": (starts[sec.section_id], starts[sec.section_id] + 1000)
        for i, sec in enumerate(sections, 1)
    }
    end = max([v[1] for v in spans.values()] or [1000])
    ctx = synth_ctx(
        [synth_shot(1, 0, end)], config=c, aspect=aspect, chapters=ch, script=script, spans=spans
    )
    r = check_chapters(ctx)
    assert r.verdict.value == exp["a09.q.chapters"]
    if "blocking" in exp:
        assert r.blocking is exp["blocking"]


def te_tiers(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    c = base(inp)
    lim = Limits(**inp.get("limits", {}))
    shots = [
        TierShot(s["shot_id"], s["duration_ms"], still_ok=s.get("still_ok", False),
                 needs_ai_video=s.get("needs_ai_video", False))
        for s in inp["shots"]
    ]  # fmt: skip
    plan = plan_tiers(shots, inp["total_ms"], lim, c)
    if "e_allowed_shot_ids" in exp:
        assert list(plan.e_allowed_shot_ids) == exp["e_allowed_shot_ids"]
        assert plan.worst_case_e_share_permille == exp["worst_case_e_share_permille"]
        assert plan.e_limit_permille == exp["e_limit_permille"]
        t = 0
        synth = []
        for i, s in enumerate(inp["shots"], 1):
            synth.append(
                synth_shot(i, t, t + s["duration_ms"], allowed_tiers=plan.allowed[s["shot_id"]])
            )
            t += s["duration_ms"]
        synth.append(synth_shot(len(synth) + 1, t, inp["total_ms"], allowed_tiers=(Tier.C,)))
        assert (
            check_tier_plan(synth_ctx(synth, config=c, limits=lim)).verdict.value
            == exp["a09.q.tier_plan"]
        )
    else:
        assert {k: [t.value for t in v] for k, v in plan.allowed.items()} == exp["allowed_tiers"]
        assert plan.ai_video_allowed_ms == exp["ai_video_allowed_ms"]


def te_gate_hash(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    with pytest.raises(AmwError) as ei:
        script_gate(
            script_sha256=inp["script_sha256"], ref_sha256=inp["script_sha256"],
            verified_script_sha256=inp["verified_script_sha256"], stage_verdict=inp["stage_verdict"],
        )  # fmt: skip
    assert ei.value.code == exp["error"] and ei.value.details["violations"] == exp["violations"]


def te_timemap(case: dict[str, Any]) -> None:
    inp = case["input"]
    ids = inp["script_segment_ids"]
    variants = inp.get("variants")
    if variants is None:
        tl = {
            "source": "PROVIDER_CLIPS",
            "segments": [
                {"segment_id": s, "start_ms": i * 1000, "end_ms": i * 1000 + 1000}
                for i, s in enumerate(inp["timeline_segment_ids"])
            ],
        }
        variants, wants = [{"timeline": tl}], [case["expected"]]
    else:
        wants = case["expected"]["variants"]
    for var, want in zip(variants, wants, strict=True):
        with pytest.raises(AmwError) as ei:
            build_time_map(ids, NarrationTimeline.model_validate(var["timeline"]))
        assert ei.value.code == want["error"]
        assert ei.value.details["violations"] == want["violations"]


def te_rebase(case: dict[str, Any]) -> None:
    inp = case["input"]
    c = base(inp)
    script, durs = sample_script()
    plan = make_step()[0].run(make_request(script, durs)).plan
    proto = plan.shots[0]
    old = {k: tuple(v) for k, v in inp["old_timeline"].items()}
    shots = [
        proto.model_copy(update={
            "shot_id": s["shot_id"], "segment_ids": tuple(s["segment_ids"]),
            "start_ms": old[s["segment_ids"][0]][0], "end_ms": old[s["segment_ids"][-1]][1],
            "duration_ms": old[s["segment_ids"][-1]][1] - old[s["segment_ids"][0]][0],
            "change_events_ms": (), "cut_offset_ms": 0, "jl_kind": None, "held": None,
        })
        for s in inp["plan_shots"]
    ]  # fmt: skip
    for var in inp["variants"]:
        new = {k: tuple(v) for k, v in var["new_timeline"].items()}
        if "error" in var["expect"]:
            with pytest.raises(AmwError) as ei:
                rebase_shots(shots, old, new, c)
            assert ei.value.details["violations"] == var["expect"]["violations"]
        else:
            got = rebase_shots(shots, old, new, c)
            assert [(s.shot_id, s.start_ms, s.end_ms) for s in got] == [
                (e["shot_id"], e["start_ms"], e["end_ms"]) for e in var["expect"]["shots"]
            ]


def te_vertical(case: dict[str, Any]) -> None:
    for var, want in zip(case["input"]["variants"], case["expected"]["variants"], strict=True):
        portrait = var["aspect_ratio"] == "9:16"
        script, durs = sample_script(AspectRatio.PORTRAIT if portrait else AspectRatio.LANDSCAPE)
        req = make_request(script, durs)
        res = make_step()[0].run(req)
        shots = list(res.plan.shots)
        shots[0] = shots[0].model_copy(
            update={"vertical": None if portrait else Vertical(subject_anchor=Anchor.CENTER)}
        )
        bad = res.plan.model_copy(update={"shots": tuple(shots)})
        ctx = ctx_of(res, req)
        r = check_vertical(replace(ctx, plan=bad))
        assert r.verdict is CheckVerdict.FAIL and r.blocking
        assert r.message == want["violations"][0]


def te_chart(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    c = base(inp)
    g = plan_chart(
        change_beats=inp["scene"]["change_beats"],
        t0=inp["span"]["t0_ms"],
        t1=inp["span"]["t1_ms"],
        cfg=c,
    )
    assert (g.start_ms, g.end_ms) == (exp["start_ms"], exp["end_ms"])
    assert list(g.change_events_ms) == exp["change_events_ms"]
    assert g.held is not None and g.held.reason.value == exp["held"]["reason"]


def te_transition(case: dict[str, Any]) -> None:
    inp = case["input"]
    for var, want in zip(inp["variants"], case["expected"]["variants"], strict=True):
        t = plan_transition(
            base(var), boundary=var["boundary"], hint=var["hint"],
            shorter_neighbour_ms=var["shorter_neighbour_ms"],
        )  # fmt: skip
        assert (t.kind.value, t.duration_ms) == (want["kind"], want["duration_ms"])


def te_audio(case: dict[str, Any]) -> None:
    inp = case["input"]
    for var, want in zip(inp["variants"], case["expected"]["variants"], strict=True):
        got = plan_audio(inp["total_duration_ms"], [], Limits(**var["limits"]))
        assert got.music.model_dump(mode="json") == {
            **want["music"],
            "offset_db_range": [-20.0, -15.0],
        }
        assert list(got.sfx_cues) == want["sfx_cues"]


HANDLERS: dict[str, Callable[[dict[str, Any]], None]] = {}
for n in (*range(1, 10), 32):
    HANDLERS[f"TE-{n:02d}"] = te_slot_grid
HANDLERS["TE-10"] = te_10
for n in (11, 12, 35):
    HANDLERS[f"TE-{n}"] = te_hook
HANDLERS["TE-13"] = HANDLERS["TE-14"] = te_sting
HANDLERS["TE-15"] = HANDLERS["TE-16"] = te_interrupts
for n in range(17, 23):
    HANDLERS[f"TE-{n}"] = te_jl
HANDLERS["TE-23"] = te_end_screen
HANDLERS["TE-24"] = HANDLERS["TE-36"] = te_chapters
HANDLERS["TE-25"] = HANDLERS["TE-26"] = te_tiers
HANDLERS["TE-27"] = te_gate_hash
HANDLERS["TE-28"] = HANDLERS["TE-34"] = te_timemap
HANDLERS["TE-29"] = te_rebase
HANDLERS["TE-31"] = te_chart
HANDLERS["TE-33"] = te_transition
HANDLERS["TE-38"] = te_audio


def te_holds(case: dict[str, Any]) -> None:
    inp, exp = case["input"], case["expected"]
    shots = []
    for i, s in enumerate(inp["shots"], 1):
        held = s["held"]
        shots.append(synth_shot(i, s["start_ms"], s["end_ms"],
                                held=None if held is None else Held(reason=HeldReason(held["reason"]), max_ms=held["max_ms"])))  # fmt: skip
    assert [
        {"start_ms": h.start_ms, "end_ms": h.end_ms, "shot_id": h.shot_id, "reason": h.reason.value}
        for h in derive_holds(shots)
    ] == exp["deliberate_hold"]  # derived by the assembler function, not written by the test
    ctx = synth_ctx(shots, config=base(inp))
    assert ctx.plan.deliberate_black == () == tuple(exp["deliberate_black"])
    assert check_transitions(ctx).verdict.value == exp["a09.q.transitions"]


def te_flags(case: dict[str, Any]) -> None:
    wants = case["expected"]["variants"]
    v0, v1, v2 = case["input"]["variants"]
    shots = [synth_shot(1, 0, 4000), synth_shot(2, 4000, 8000)]
    got = [
        check_revision_addressed(synth_ctx(shots, config=base(v0), iteration=v0["iteration"])),
        check_interrupt_first(synth_ctx(shots, config=base(v1))),
        check_interrupt_first(synth_ctx(shots, config=base(v2))),
    ]
    assert v1["interrupts"] == [] and v2["interrupts"] == []
    for r, want in zip(got, wants, strict=True):
        assert (r.verdict.value, r.blocking, r.gate) == (
            want["verdict"],
            want["blocking"],
            want["gate"],
        )


HANDLERS["TE-30"] = te_vertical
HANDLERS["TE-37"] = te_holds
HANDLERS["TE-39"] = te_flags


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_timeline_engine_case(case: dict[str, Any]) -> None:
    HANDLERS[case["case_id"]](case)


def test_every_case_has_a_handler() -> None:
    assert sorted(HANDLERS) == sorted(c["case_id"] for c in CASES)
    assert len(CASES) == 39


_ = check_cadence
