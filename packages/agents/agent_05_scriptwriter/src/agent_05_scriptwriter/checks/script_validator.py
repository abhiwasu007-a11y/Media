"""``ScriptValidator`` (blueprint 10.5, 8.1): whole-script checks on the assembled document."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from agent_05_scriptwriter.checks.results import (
    CheckResult,
    failed,
    passed,
    skipped,
    warned,
)
from agent_05_scriptwriter.contracts import ConceptBrief, ScriptDocument
from agent_05_scriptwriter.hooks import HookScore, select_hook
from agent_05_scriptwriter.text import normalise, speech_chars

HOOK_KINDS = ("HOOK_PROOF", "HOOK_WHY", "HOOK_COVERS")


# ---- single checks over plain values (also used directly by the deterministic dataset) ----
def check_hook_window(
    hook_segment_chars: Sequence[int], rate_cps: float | None, window_ms: int
) -> CheckResult:
    if rate_cps is None:
        return skipped("edit.hook.window", "no speech rate measured yet")
    measured = round(sum(hook_segment_chars) / rate_cps * 1000)
    if measured > window_ms:
        return CheckResult(
            "edit.hook.window", "FAIL", True, "hook ends after the window", measured=measured
        )
    return CheckResult(
        "edit.hook.window", "PASS", True, "hook inside the window", measured=measured
    )


def check_coverage(
    concept_plan: Sequence[str],
    segment_concepts: Sequence[Sequence[str]],
    omitted: Sequence[str],
    pack_concepts: Sequence[str] | None = None,
) -> CheckResult:
    covered = {c for refs in segment_concepts for c in refs}
    missing = [c for c in concept_plan if c not in covered]
    problems: list[str] = []
    if pack_concepts is not None and set(pack_concepts) != covered | set(omitted):
        problems.append("a pack concept is neither covered nor omitted")
    if covered & set(omitted):
        problems.append("a concept is both covered and omitted")
    if missing or problems:
        return CheckResult(
            "a05.script.coverage",
            "FAIL",
            True,
            "; ".join(["planned concept not taught"] * bool(missing) + problems),
            details={"missing": missing},
        )
    return passed("a05.script.coverage", "coverage complete")


def check_citations(
    briefs: Mapping[str, Sequence[str]], segments: Sequence[Mapping[str, object]]
) -> CheckResult:
    for seg in segments:
        concept = seg.get("concept")
        cites = seg.get("citations")
        allowed = set(briefs.get(str(concept), ()))
        if not isinstance(cites, Sequence) or not cites or not set(map(str, cites)) <= allowed:
            return failed("a05.script.citations", "a segment cites outside its concept's brief")
    return passed("a05.script.citations", "citations resolve to the brief")


def check_promise_delivery(
    key_terms: Sequence[str], covered_terms: Sequence[str], headings: Sequence[str]
) -> CheckResult:
    haystack = [normalise(t) for t in covered_terms]
    heads = [normalise(h) for h in headings]
    for term in key_terms:
        n = normalise(term)
        if n not in haystack and not any(n in h for h in heads):
            return failed("a05.script.promise_delivery", "a promise key term is never delivered")
    return passed("a05.script.promise_delivery", "promise delivered")


def check_tags(tags: Sequence[Sequence[str | None]]) -> CheckResult:
    if any(p is None or e is None for p, e in tags):
        return failed("a05.script.tags", "a segment lacks pace or emotion")
    paces = {p for p, _ in tags}
    emotions = {e for _, e in tags}
    if len(paces) < 2 and len(emotions) < 2:
        return warned("a05.script.tags", "no variation in pace or emotion")
    return passed("a05.script.tags", "tags complete")


def check_hook_options(hook_count: int, min_options: int, selected: str | None) -> CheckResult:
    if hook_count < min_options or selected is None:
        return failed("edit.hook.options", "too few hook options or none selected")
    return passed("edit.hook.options", f"{hook_count} hook options")


def check_chapters(starts: Sequence[int | None]) -> CheckResult:
    if not starts or starts[0] != 0:
        return failed("edit.chapters", "the first chapter does not start at 0 ms")
    known = [s for s in starts if s is not None]
    if any(b <= a for a, b in pairwise(known)):
        return failed("edit.chapters", "chapter starts are not strictly increasing")
    return passed("edit.chapters", f"{len(starts)} chapters")


def check_duration_fit(
    est_ms: int | None, target_ms: int, tolerance: float | None, rate_cps: float | None
) -> CheckResult:
    if est_ms is None or rate_cps is None or tolerance is None:
        return skipped("a05.script.duration_fit", "no speech rate or tolerance configured")
    if abs(est_ms - target_ms) > tolerance * target_ms:
        return warned("a05.script.duration_fit", "estimated duration outside tolerance", est_ms)
    return CheckResult(
        "a05.script.duration_fit", "PASS", False, "duration within tolerance", measured=est_ms
    )


def check_disclaimer(
    *, required: bool, expected_slots: int, slot_hashes_ok: Sequence[bool]
) -> CheckResult:
    if not required:
        return skipped("a05.script.disclaimer_slots", "no disclaimer needed for the category")
    if len(slot_hashes_ok) != expected_slots or not all(slot_hashes_ok):
        return failed("a05.script.disclaimer_slots", "configured slots do not hold the template")
    return passed("a05.script.disclaimer_slots", f"{expected_slots} disclaimer slots")


# ---- composition over a document ----
@dataclass(frozen=True, slots=True)
class ValidationContext:
    min_hook_options: int
    rate_cps: float | None
    window_ms: int
    briefs: Mapping[str, ConceptBrief]
    concept_plan_ids: Sequence[str]
    pack_concept_ids: Sequence[str]
    target_duration_ms: int
    duration_tolerance: float | None
    disclaimer_required: bool
    disclaimer_text_sha256: str | None
    expected_disclaimer_slots: int
    beat_tolerance: float | None = None


def validate_document(doc: ScriptDocument, ctx: ValidationContext) -> list[CheckResult]:
    results: list[CheckResult] = [_assembly(doc)]
    segments = doc.segments
    covered_by_segment = [[r.concept_id for r in s.concept_refs] for s in segments]
    results.append(
        check_coverage(
            list(ctx.concept_plan_ids),
            covered_by_segment,
            [o.concept_id for o in doc.omitted_concepts],
            [f"k{int(c[1:])}" if c.startswith("c") else c for c in ctx.pack_concept_ids],
        )
    )
    flat = [
        {"concept": r.concept_id, "citations": r.citation_refs}
        for s in segments
        for r in s.concept_refs
    ]
    results.append(check_citations({k: b.citation_refs for k, b in ctx.briefs.items()}, flat))
    covered_terms = [
        t
        for cid in {c for refs in covered_by_segment for c in refs}
        if cid in ctx.briefs
        for t in (ctx.briefs[cid].term_local, ctx.briefs[cid].term_en)
    ]
    results.append(
        check_promise_delivery(
            doc.promise.promise_key_terms, covered_terms, [s.heading_local for s in doc.sections]
        )
    )
    selected = _selected(doc)
    results.append(check_hook_options(len(doc.hook_options), ctx.min_hook_options, selected))
    results.append(_selection_valid(doc, selected, ctx.min_hook_options))
    results.append(_beats(doc, ctx.beat_tolerance))
    hook_chars = [speech_chars(s.text) for s in segments if s.kind in HOOK_KINDS]
    results.append(check_hook_window(hook_chars, ctx.rate_cps, ctx.window_ms))
    results.append(_interrupts(doc))
    results.append(check_tags([(s.pace, s.emotion) for s in segments]))
    results.append(check_chapters([c.est_start_ms for c in doc.chapters]))
    slots_ok = [
        ctx.disclaimer_text_sha256 is not None and slot.text_sha256 == ctx.disclaimer_text_sha256
        for slot in doc.disclaimer_slots
    ]
    results.append(
        check_disclaimer(
            required=ctx.disclaimer_required,
            expected_slots=ctx.expected_disclaimer_slots,
            slot_hashes_ok=slots_ok,
        )
    )
    results.append(_tier_mix(doc))
    estimate = (
        None
        if any(s.est_duration_ms is None for s in segments)
        else sum(s.est_duration_ms or 0 for s in segments)
    )
    results.append(
        check_duration_fit(estimate, ctx.target_duration_ms, ctx.duration_tolerance, ctx.rate_cps)
    )
    return results


def _selected(doc: ScriptDocument) -> str | None:
    chosen = [o.hook_id for o in doc.hook_options if o.segment_ids]
    return chosen[0] if len(chosen) == 1 else None


def _selection_valid(doc: ScriptDocument, selected: str | None, min_options: int) -> CheckResult:
    scores = [
        HookScore(
            o.hook_id,
            o.rubric.viewer_relevance,
            o.rubric.curiosity_without_clickbait,
            o.qualified,
        )
        for o in doc.hook_options
    ]
    selection = select_hook(scores, selected, min_options)
    if selection.status != "OK" or selection.selected != selected:
        return failed("edit.hook.selection_valid", "selected option is not the highest total")
    if any(
        o.total != o.rubric.viewer_relevance + o.rubric.curiosity_without_clickbait
        for o in doc.hook_options
    ):
        return failed("edit.hook.selection_valid", "an option total differs from its rubric")
    return passed("edit.hook.selection_valid", "selection reproduces")


def _beats(doc: ScriptDocument, tolerance: float | None) -> CheckResult:
    kinds: list[str] = []
    sizes: dict[str, int] = {}
    for s in doc.segments:
        if s.kind in HOOK_KINDS:
            if not kinds or kinds[-1] != s.kind:
                kinds.append(s.kind)
            sizes[s.kind] = sizes.get(s.kind, 0) + speech_chars(s.text)
    if tuple(kinds) != HOOK_KINDS:
        return warned("edit.hook.beats", "hook beats missing or out of order")
    if tolerance is not None and sizes:
        mean = sum(sizes.values()) / len(sizes)
        if any(abs(v - mean) > tolerance * mean for v in sizes.values()):
            return warned("edit.hook.beats", "hook beats are uneven")
    return passed("edit.hook.beats", "three beats in order", blocking=False)


def _interrupts(doc: ScriptDocument) -> CheckResult:
    chars: list[tuple[str, int]] = [(s.segment_id, speech_chars(s.text)) for s in doc.segments]
    total = sum(c for _, c in chars)
    if total == 0:
        return warned("a05.script.interrupts", "no narration")
    position: dict[str, int] = {}
    running = 0
    for segment_id, c in chars:
        position[segment_id] = running
        running += c
    first_half = False
    midpoint = False
    section_of_mid = None
    for s in doc.segments:
        if (
            position[s.segment_id] <= total / 2
            and position[s.segment_id] + speech_chars(s.text) > total / 2
        ):
            section_of_mid = s.section_id
    for scene in doc.scenes:
        if scene.interrupt is None or not scene.segment_ids:
            continue
        if position[scene.segment_ids[0]] < total / 2:
            first_half = True
        if scene.section_id == section_of_mid and section_of_mid is not None:
            midpoint = True
    if first_half and midpoint:
        return passed("a05.script.interrupts", "interrupts planned", blocking=False)
    return warned(
        "a05.script.interrupts", "no planned interrupt in the first half or at the midpoint"
    )


def _tier_mix(doc: ScriptDocument) -> CheckResult:
    counts: dict[str, int] = {}
    for scene in doc.scenes:
        if scene.visual_intent is not None:
            counts[scene.visual_intent.tier_hint] = counts.get(scene.visual_intent.tier_hint, 0) + 1
    total = sum(counts.values())
    share = {k: round(1000 * v / total) for k, v in sorted(counts.items())} if total else {}
    return CheckResult(
        "a05.script.tier_mix",
        "PASS",
        False,
        "planned scene share per tier (permille): "
        + ",".join(f"{k}={v}" for k, v in share.items()),
    )


def _assembly(doc: ScriptDocument) -> CheckResult:
    ids = [s.segment_id for s in doc.segments]
    if ids != [f"s{i}" for i in range(1, len(ids) + 1)]:
        return failed("a05.script.assembly", "segment ids are not sequential from s1")
    scenes = {s.scene_id: s for s in doc.scenes}
    sections = {s.section_id for s in doc.sections} | {"hook"}
    for seg in doc.segments:
        scene = scenes.get(seg.scene_id)
        if scene is None or seg.segment_id not in scene.segment_ids:
            return failed("a05.script.assembly", "a segment has no matching scene")
        if scene.section_id is not None and scene.section_id not in sections:
            return failed("a05.script.assembly", "a scene belongs to no planned section")
        if seg.section_id != scene.section_id:
            return failed("a05.script.assembly", "segment and scene disagree on the section")
    if {sid for sc in doc.scenes for sid in sc.segment_ids} != set(ids):
        return failed("a05.script.assembly", "a scene lists a segment that does not exist")
    return passed("a05.script.assembly", f"{len(ids)} segments")
