"""PlanChecks (F-26): the 24 deterministic ``a09.q.*`` checks of blueprint 20 as pure functions.

Every check returns a ``ValidationResult``. ``blocking`` is true only where a PASS/FAIL is
computable; a ``WARN`` or ``SKIPPED`` result is never blocking (CCR-001, 03 section 5.3 rule 5);
no result carries ``gate`` (``s09_plan`` is not a gate stage). Messages carry numbers and IDs,
never narration or on-screen text (27 section 7.3.6).
"""

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from agent_09_video_director.assemble import plan_hash, sha256_text
from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import (
    AspectRatio,
    HeldReason,
    IntentKind,
    InterruptWindow,
    Limits,
    Origin,
    OverlayKind,
    ScriptDoc,
    SegmentKind,
    Shot,
    ShotPlan,
    TextRefDisclaimer,
    TextRefScene,
    Tier,
    TransitionKind,
)
from agent_09_video_director.direction.guard import scan_injection
from agent_09_video_director.direction.runner import Accepted
from agent_09_video_director.mathx import round_half_up
from agent_09_video_director.timeline.timemap import TimeMap
from amw_core.contracts.task_output import MeasuredValue, ValidationResult
from amw_core.enums import CheckKind, CheckVerdict

_ALLOWED_TRANSITIONS = set(TransitionKind)
_TIER_ORDER = {t: i for i, t in enumerate(Tier)}


@dataclass(frozen=True, slots=True)
class CheckContext:
    plan: ShotPlan
    script: ScriptDoc
    tm: TimeMap
    cfg: Agent09Config
    limits: Limits
    channel_category: str
    accepted: Mapping[str, Accepted] = field(default_factory=dict)
    slot_ids: Sequence[str] = ()
    banned_subjects: Sequence[str] = ()
    jl_eligible_count: int = 0
    feedback: Sequence[FeedbackItem] = ()
    previous_plan: ShotPlan | None = None
    cost: tuple[int, int, int, int] | None = None  # spent, max_micros, calls, max_calls
    rerun_hash: Callable[[], str] | None = None


@dataclass(frozen=True, slots=True)
class FeedbackItem:
    check_id: str
    shot_ids: tuple[str, ...]
    measured: float | None = None
    threshold: float | None = None


def _res(
    check_id: str,
    verdict: CheckVerdict,
    message: str,
    *,
    blocking: bool = True,
    measured: MeasuredValue = None,
    threshold: MeasuredValue = None,
    unit: str | None = None,
) -> ValidationResult:
    if verdict in (CheckVerdict.WARN, CheckVerdict.SKIPPED):
        blocking = False
    return ValidationResult(
        check_id=check_id,
        kind=CheckKind.DETERMINISTIC,
        verdict=verdict,
        blocking=blocking,
        measured=measured,
        threshold=threshold,
        unit=unit,
        message=message,
    )


def _pf(ok: bool) -> CheckVerdict:
    return CheckVerdict.PASS if ok else CheckVerdict.FAIL


# 1 ---------------------------------------------------------------------------------------
def check_schema(c: CheckContext) -> ValidationResult:
    try:
        ShotPlan.model_validate(c.plan.model_dump())
        ok = True
    except ValueError:
        ok = False
    return _res("a09.q.schema", _pf(ok), "plan validates against agent_09.shot_plan.output 1.0.0")


# 2 ---------------------------------------------------------------------------------------
def check_refs(c: CheckContext) -> ValidationResult:
    sc = {s.scene_id: s for s in c.script.scenes}
    seg_ids = {s.segment_id for s in c.script.segments}
    sec_ids = {s.section_id for s in c.script.sections}
    charts = {r.chart_id for r in c.script.chart_requests}
    ids = [s.shot_id for s in c.plan.shots]
    bad = len(ids) != len(set(ids))
    for s in c.plan.shots:
        if (
            s.scene_id not in sc
            or any(x not in seg_ids for x in s.segment_ids)
            or (s.section_id is not None and s.section_id not in sec_ids)
            or (s.chart_id is not None and s.chart_id not in charts)
            or not s.allowed_tiers
            or not s.fallback_template_key
        ):
            bad = True
    return _res("a09.q.refs", _pf(not bad), "ids, refs and fallback templates resolve")


# 3 ---------------------------------------------------------------------------------------
def check_tiling(c: CheckContext) -> ValidationResult:
    shots = c.plan.shots
    ok = bool(shots) and shots[0].start_ms == 0 and shots[-1].end_ms == c.plan.content_end_ms
    ok = ok and all(s.duration_ms == s.end_ms - s.start_ms for s in shots)
    ok = ok and all(a.end_ms == b.start_ms for a, b in itertools.pairwise(shots))
    ok = ok and sum(s.duration_ms for s in shots) == c.plan.content_end_ms
    end_len = c.cfg.end_screen_length_ms or 0
    ok = ok and c.plan.total_duration_ms == c.plan.content_end_ms + end_len
    return _res(
        "a09.q.tiling",
        _pf(ok),
        "main track tiles [0, content_end] with no gap or overlap",
        measured=sum(s.duration_ms for s in shots),
        threshold=c.plan.content_end_ms,
        unit="ms",
    )


# 4 ---------------------------------------------------------------------------------------
def _gap_stats(c: CheckContext) -> tuple[int, int, bool]:
    """(max gap, min gap, every gap legal) over change events, with held exemptions."""
    shots = c.plan.shots
    limit = c.cfg.g_max_ms
    events: list[tuple[int, Shot | None]] = []
    for s in shots:
        events.append((s.start_ms, s))
        events.extend((e, s) for e in s.change_events_ms)
    events.append((c.plan.content_end_ms, None))
    gaps: list[int] = []
    legal = True
    for (a, owner), (b, _) in itertools.pairwise(events):
        g = b - a
        gaps.append(g)
        exempt = (
            owner is not None
            and owner.held is not None
            and c.cfg.held_max_ms is not None
            and owner.held.reason is not HeldReason.CHART_REVEAL
            and owner.duration_ms <= max(c.cfg.held_max_ms, owner.held.max_ms)
        )
        if g > limit and not exempt:
            legal = False
    return max(gaps, default=0), min(gaps, default=0), legal


def check_cadence(c: CheckContext) -> ValidationResult:
    mx, mn, legal = _gap_stats(c)
    return _res(
        "a09.q.cadence",
        _pf(legal),
        f"max change gap {mx} ms, min {mn} ms",
        measured=mx,
        threshold=c.cfg.g_max_ms,
        unit="ms",
    )


# 5, 6, 7 ---------------------------------------------------------------------------------
def check_hook_window(c: CheckContext) -> ValidationResult:
    h = c.plan.hook
    ok = h.end_ms <= c.cfg.hook_window_ms and h.first_payoff_ms <= c.cfg.hook_window_ms
    return _res(
        "a09.q.hook_window",
        _pf(ok),
        "hook inside the window",
        measured=h.end_ms,
        threshold=c.cfg.hook_window_ms,
        unit="ms",
    )


def check_hook_no_brand(c: CheckContext) -> ValidationResult:
    hook_end = c.plan.hook.end_ms
    stings = [o for o in c.plan.overlays if o.kind is OverlayKind.BRAND_STING]
    ok = all(o.start_ms >= hook_end for o in stings)
    ok = ok and all(o.start_ms == hook_end for o in stings)
    ok = ok and not any(
        o.kind is OverlayKind.CHAPTER_CARD and o.start_ms < hook_end for o in c.plan.overlays
    )
    return _res(
        "a09.q.hook_no_brand",
        _pf(ok),
        "no brand element before the hook ends",
        measured=len([o for o in stings if o.start_ms < hook_end]),
        threshold=0,
    )


def check_first_shot(c: CheckContext) -> ValidationResult:
    shots = c.plan.shots
    first = shots[0] if shots else None
    ok = (
        first is not None
        and first.start_ms == 0
        and first.origin is not Origin.CODE_DISCLAIMER
        and bool(set(first.segment_ids) & set(c.plan.hook.segment_ids[:1]))
    )
    return _res(
        "a09.q.first_shot", _pf(bool(ok)), "first shot starts at 0 and shows the hook proof beat"
    )


# 8, 9 ------------------------------------------------------------------------------------
def _centre_in(s: Shot, window: tuple[int, int]) -> bool:
    return window[0] * 2 <= s.start_ms + s.end_ms <= window[1] * 2


def _interrupt_check(c: CheckContext, which: InterruptWindow, check_id: str) -> ValidationResult:
    from agent_09_video_director.timeline.interrupts import windows

    win = windows(c.plan.content_end_ms, c.cfg).get(which)
    inter = [s for s in c.plan.shots if s.interrupt is not None]
    if win is None:
        if which is InterruptWindow.FIRST_DROPOFF:
            n = sum(1 for s in inter if s.end_ms * 2 <= c.plan.content_end_ms + s.duration_ms)
        else:
            n = len(inter)
        return _res(
            check_id,
            CheckVerdict.WARN,
            "window not set: script-planned interrupts only",
            measured=n,
        )
    n = sum(1 for s in inter if _centre_in(s, win))
    return _res(check_id, _pf(n >= 1), "interrupt inside the window", measured=n, threshold=1)


def check_interrupt_first(c: CheckContext) -> ValidationResult:
    return _interrupt_check(c, InterruptWindow.FIRST_DROPOFF, "a09.q.interrupt_first")


def check_interrupt_mid(c: CheckContext) -> ValidationResult:
    return _interrupt_check(c, InterruptWindow.MIDPOINT, "a09.q.interrupt_mid")


# 10 --------------------------------------------------------------------------------------
def check_jl(c: CheckContext) -> ValidationResult:
    cfg = c.cfg
    if cfg.jl_offset_ms is None or cfg.jl_every_nth is None:
        return _res("a09.q.jl", CheckVerdict.WARN, "J/L rate not set", measured=0)
    cuts = [s for s in c.plan.shots if s.jl_kind is not None]
    consistent = all(
        s.cut_offset_ms != 0 and ((s.jl_kind == "J") == (s.cut_offset_ms > 0)) for s in cuts
    )
    gap_skips = sum(1 for k in c.plan.jl_cuts if k.skipped_reason == "GAP_LIMIT")
    need = c.jl_eligible_count // cfg.jl_every_nth
    ok = consistent and len(cuts) + gap_skips >= need
    return _res(
        "a09.q.jl", _pf(ok), "J/L cuts at the configured rate", measured=len(cuts), threshold=need
    )


# 11 --------------------------------------------------------------------------------------
def check_end_screen(c: CheckContext) -> ValidationResult:
    length = c.cfg.end_screen_length_ms
    if length is None:
        return _res("a09.q.end_screen", CheckVerdict.WARN, "end-screen length not set")
    last = c.plan.overlays[-1] if c.plan.overlays else None
    pause = any(p.reason == "END_SCREEN" for p in c.plan.audio_plan.deliberate_pauses)
    ok = (
        last is not None
        and last.kind is OverlayKind.END_SCREEN
        and last.start_ms == c.plan.content_end_ms
        and last.end_ms - last.start_ms == length
        and not last.text_refs
        and pause
    )
    return _res(
        "a09.q.end_screen",
        _pf(bool(ok)),
        "end screen reserved after the narration",
        measured=length,
        threshold=length,
        unit="ms",
    )


# 12 --------------------------------------------------------------------------------------
def check_chapters(c: CheckContext) -> ValidationResult:
    if c.plan.aspect_ratio is AspectRatio.PORTRAIT or not c.script.sections:
        return _res("a09.q.chapters", CheckVerdict.SKIPPED, "script has no sections")
    ch = c.plan.chapters
    first_seg = {sc.scene_id: sc.segment_ids[0] for sc in c.script.scenes}
    measured = {
        sec.section_id: (0 if i == 0 else c.tm.start(first_seg[sec.scene_ids[0]]))
        for i, sec in enumerate(c.script.sections)
        if sec.scene_ids
    }
    ok = (
        len(ch) == len(c.script.sections)
        and ch[0].start_ms == 0
        and all(b.start_ms > a.start_ms for a, b in itertools.pairwise(ch))
        and all(abs(x.start_ms - measured.get(x.section_id, -(10**9))) <= 1000 for x in ch)
    )
    return _res(
        "a09.q.chapters",
        _pf(ok),
        "chapters follow measured section starts",
        measured=len(ch),
        threshold=len(c.script.sections),
    )


# 13 --------------------------------------------------------------------------------------
def check_tier_plan(c: CheckContext) -> ValidationResult:
    order_ok = all(
        [_TIER_ORDER[t] for t in s.allowed_tiers] == sorted(_TIER_ORDER[t] for t in s.allowed_tiers)
        and Tier.C in s.allowed_tiers
        for s in c.plan.shots
    )
    e_ms = sum(s.duration_ms for s in c.plan.shots if Tier.E in s.allowed_tiers)
    d_ms = sum(s.duration_ms for s in c.plan.shots if Tier.D in s.allowed_tiers)
    total = max(c.plan.content_end_ms, 1)
    share_ok = e_ms * 1000 < c.cfg.tier_e_max_share_permille * total
    d_ok = d_ms <= c.limits.ai_video_allowed_ms and (c.cfg.tier_d_enabled or d_ms == 0)
    e_ok = c.limits.ai_still_allowed or e_ms == 0
    return _res(
        "a09.q.tier_plan",
        _pf(order_ok and share_ok and d_ok and e_ok),
        "tier plan inside hierarchy, share and budget",
        measured=round_half_up(e_ms * 1000, total),
        threshold=c.cfg.tier_e_max_share_permille,
        unit="permille",
    )


# 14 --------------------------------------------------------------------------------------
def check_charts(c: CheckContext) -> ValidationResult:
    seg_scene = {s.segment_id: s.scene_id for s in c.script.segments}
    chart_shots = [s for s in c.plan.shots if s.intent_kind is IntentKind.CHART]
    ok = len({s.chart_id for s in chart_shots}) == len(chart_shots)
    ok = ok and all(s.intent_text == "" for s in chart_shots)
    requested = {r.chart_id: r for r in c.script.chart_requests}
    ok = ok and {s.chart_id for s in chart_shots} == set(requested)
    for r in c.script.chart_requests:
        match = [s for s in chart_shots if s.chart_id == r.chart_id]
        seg = c.tm.spans.get(r.first_segment_id)
        ok = (
            ok
            and len(match) == 1
            and seg is not None
            and (match[0].start_ms <= seg[0] < match[0].end_ms)
            and seg_scene.get(r.first_segment_id) == match[0].scene_id
        )
    return _res(
        "a09.q.charts",
        _pf(ok),
        "one CHART shot per chart request",
        measured=len(chart_shots),
        threshold=len(requested),
    )


# 15 --------------------------------------------------------------------------------------
def _resolves(c: CheckContext, ref: object) -> bool:
    if isinstance(ref, TextRefScene):
        sc = next((s for s in c.script.scenes if s.scene_id == ref.scene_id), None)
        return (
            sc is not None
            and 0 <= ref.index < len(sc.on_screen_text)
            and sha256_text(sc.on_screen_text[ref.index]) == ref.sha256
        )
    if isinstance(ref, TextRefDisclaimer):
        return any(
            d.slot_id == ref.disclaimer_slot_id and d.text_sha256 == ref.sha256
            for d in c.script.disclaimer_slots
        )
    return False


def check_text_provenance(c: CheckContext) -> ValidationResult:
    refs = [r for s in c.plan.shots for r in s.text_refs] + [
        r for o in c.plan.overlays for r in o.text_refs
    ]
    bad = sum(1 for r in refs if not _resolves(c, r))
    return _res(
        "a09.q.text_provenance",
        _pf(bad == 0),
        "every text ref resolves to script text",
        measured=bad,
        threshold=0,
    )


# 16 --------------------------------------------------------------------------------------
def check_disclaimer(c: CheckContext) -> ValidationResult:
    segs = [s for s in c.script.segments if s.kind is SegmentKind.DISCLAIMER]
    bad = 0
    for seg in segs:
        a, b = c.tm.spans[seg.segment_id]
        cards = [o for o in c.plan.overlays if o.kind is OverlayKind.DISCLAIMER_CARD]
        covered = any(o.start_ms <= a and o.end_ms >= b for o in cards) or any(
            s.intent_kind is IntentKind.TEXT_CARD and s.start_ms <= a and s.end_ms >= b
            for s in c.plan.shots
        )
        moved = any(
            s.cut_offset_ms != 0 and s.origin is Origin.CODE_DISCLAIMER for s in c.plan.shots
        )
        bad += 0 if covered and not moved else 1
    return _res(
        "a09.q.disclaimer",
        _pf(bad == 0),
        "disclaimer segments covered, never shifted",
        measured=bad,
        threshold=0,
    )


# 17 --------------------------------------------------------------------------------------
def check_visual_guard(c: CheckContext) -> ValidationResult:
    finance = c.channel_category == "finance"
    banned = [b.lower() for b in c.banned_subjects]
    bad = 0
    for sid in c.slot_ids:
        acc = c.accepted.get(sid)
        if acc is None:
            continue
        d = acc.direction.depiction
        if (
            d.real_person
            or d.identifiable_person
            or d.brand_or_logo
            or d.ai_presenter
            or d.market_data_screen
            or (finance and d.market_direction_imagery)
        ):
            bad += 1
    for s in c.plan.shots:
        t = s.intent_text
        if any(ch.isdigit() for ch in t) or any(b in t.lower() for b in banned):
            bad += 1
    return _res(
        "a09.q.visual_guard",
        _pf(bad == 0),
        "no forbidden picture in the plan",
        measured=bad,
        threshold=0,
    )


# 18 --------------------------------------------------------------------------------------
def check_vertical(c: CheckContext) -> ValidationResult:
    if c.plan.aspect_ratio is AspectRatio.PORTRAIT:
        ok = all(s.vertical is not None for s in c.plan.shots) and all(
            o.vertical_variant for o in c.plan.overlays
        )
        return _res(
            "a09.q.vertical", _pf(ok), "VERTICAL_ANCHOR_MISSING" if not ok else "9:16 plan complete"
        )
    ok = all(s.vertical is None for s in c.plan.shots)
    return _res(
        "a09.q.vertical",
        _pf(ok),
        "VERTICAL_ON_LANDSCAPE" if not ok else "16:9 plan has no vertical data",
    )


def check_vertical_safe_zone(c: CheckContext) -> ValidationResult:
    return _res(
        "a09.q.vertical.safe_zone",
        CheckVerdict.SKIPPED,
        "official Shorts overlay zones are not logged yet",
    )


# 19 --------------------------------------------------------------------------------------
def check_transitions(c: CheckContext) -> ValidationResult:
    shots = c.plan.shots
    ok = not c.plan.deliberate_black
    for prev, s in itertools.pairwise(shots):
        t = s.transition_in
        if t.kind not in _ALLOWED_TRANSITIONS:
            ok = False
        if t.kind is not TransitionKind.CUT:
            cap = c.cfg.transition_max_ms
            if (
                cap is None
                or t.duration_ms > cap
                or t.duration_ms * 5 > min(prev.duration_ms, s.duration_ms)
            ):
                ok = False
    expected = [(s.start_ms, s.end_ms, s.shot_id) for s in shots if s.held is not None]
    ok = ok and [(h.start_ms, h.end_ms, h.shot_id) for h in c.plan.deliberate_hold] == expected
    return _res("a09.q.transitions", _pf(ok), "no dip to black; holds listed")


# 20 --------------------------------------------------------------------------------------
def check_audio_plan(c: CheckContext) -> ValidationResult:
    a = c.plan.audio_plan
    ok = a.music.offset_db_range == (-20.0, -15.0)
    if a.music.bed == "REQUESTED":
        ok = ok and c.limits.music_library_enabled
    else:
        ok = ok and a.music.start_ms is None and a.music.end_ms is None
    ok = ok and (not a.sfx_cues or c.limits.sfx_library_enabled)
    return _res("a09.q.audio_plan", _pf(ok), "audio cues only from enabled licensed libraries")


# 21 --------------------------------------------------------------------------------------
def check_injection_scan(c: CheckContext) -> ValidationResult:
    n = sum(1 for s in c.plan.shots if scan_injection(s.intent_text))
    return _res(
        "a09.q.injection_scan",
        _pf(n == 0),
        "no scanner hit in output strings",
        measured=n,
        threshold=0,
    )


# 22 --------------------------------------------------------------------------------------
def check_cost(c: CheckContext) -> ValidationResult:
    if c.cost is None:
        return _res("a09.q.cost", CheckVerdict.SKIPPED, "no ledger data")
    spent, cap, calls, max_calls = c.cost
    return _res(
        "a09.q.cost",
        _pf(spent <= cap and calls <= max_calls),
        "ledger inside resource_budget",
        measured=spent,
        threshold=cap,
        unit="micros",
    )


# 23 --------------------------------------------------------------------------------------
def check_determinism(c: CheckContext) -> ValidationResult:
    if c.rerun_hash is None:
        return _res("a09.q.determinism", CheckVerdict.SKIPPED, "no rerun available")
    return _res(
        "a09.q.determinism",
        _pf(c.rerun_hash() == plan_hash(c.plan)),
        "engine rerun reproduces the plan hash",
    )


# 24 --------------------------------------------------------------------------------------
_REVISABLE: dict[str, Callable[[CheckContext], ValidationResult]] = {}


def check_revision_addressed(c: CheckContext) -> ValidationResult:
    if c.plan.iteration == 0 or not c.feedback:
        return _res("a09.q.revision_addressed", CheckVerdict.SKIPPED, "iteration 0")
    prev = {s.shot_id: s for s in c.previous_plan.shots} if c.previous_plan else {}
    new = {s.shot_id: s for s in c.plan.shots}
    named = {sid for f in c.feedback for sid in f.shot_ids}
    unresolved = 0
    for f in c.feedback:
        fn = _REVISABLE.get(f.check_id)
        if fn is not None:
            if fn(c).verdict is CheckVerdict.FAIL:
                unresolved += 1
        elif f.shot_ids and not all(
            sid not in new or sid not in prev or new[sid].content_key != prev[sid].content_key
            for sid in f.shot_ids
        ):
            unresolved += 1
    stable = (
        all(
            sid in new and new[sid].content_key == p.content_key
            for sid, p in prev.items()
            if sid not in named
            and c.plan.narration_timeline_sha256
            == (c.previous_plan.narration_timeline_sha256 if c.previous_plan else "")
        )
        if prev
        else True
    )
    return _res(
        "a09.q.revision_addressed",
        _pf(unresolved == 0 and stable),
        "every feedback item resolved; untouched shots keep id and content key",
        measured=unresolved,
        threshold=0,
    )


ALL_CHECKS: tuple[Callable[[CheckContext], ValidationResult], ...] = (
    check_schema,
    check_refs,
    check_tiling,
    check_cadence,
    check_hook_window,
    check_hook_no_brand,
    check_first_shot,
    check_interrupt_first,
    check_interrupt_mid,
    check_jl,
    check_end_screen,
    check_chapters,
    check_tier_plan,
    check_charts,
    check_text_provenance,
    check_disclaimer,
    check_visual_guard,
    check_vertical,
    check_transitions,
    check_audio_plan,
    check_injection_scan,
    check_cost,
    check_determinism,
    check_revision_addressed,
)
_REVISABLE.update(
    {
        "a09.q.cadence": check_cadence,
        "a09.q.tiling": check_tiling,
        "a09.q.tier_plan": check_tier_plan,
        "a09.q.interrupt_first": check_interrupt_first,
        "a09.q.interrupt_mid": check_interrupt_mid,
        "a09.q.jl": check_jl,
        "a09.q.hook_no_brand": check_hook_no_brand,
        "a09.q.charts": check_charts,
        "a09.q.visual_guard": check_visual_guard,
        "a09.q.transitions": check_transitions,
        "a09.q.first_shot": check_first_shot,
        "a09.q.refs": check_refs,
    }
)


def run_all(c: CheckContext) -> list[ValidationResult]:
    """The 24 checks in blueprint order plus the sub-result ``a09.q.vertical.safe_zone``."""
    results = [fn(c) for fn in ALL_CHECKS]
    results.insert(18, check_vertical_safe_zone(c))
    return results
