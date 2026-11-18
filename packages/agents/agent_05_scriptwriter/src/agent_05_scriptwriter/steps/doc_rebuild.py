"""Rebuild model-shaped blocks from a stored script document (partial revision, blueprint 6.6).

Unchanged sections of a revision are copied from the prior script: the document is turned back
into ``Scene`` / ``HookBeat`` blocks that assemble to the same section hash (one sentence is one
segment, so re-splitting is the identity).
"""

from agent_05_scriptwriter.contracts import (
    ChartRequest,
    ConceptRefIn,
    DocChartRequest,
    DocSection,
    DocSegment,
    HookBeat,
    PlanSection,
    Scene,
    ScriptDocument,
    Sentence,
)


def _chart(doc: ScriptDocument, chart_id: str | None) -> ChartRequest | None:
    found: DocChartRequest | None = next(
        (c for c in doc.chart_requests if c.chart_id == chart_id), None
    )
    if found is None:
        return None
    return ChartRequest(
        chart_id=found.chart_id,
        chart_kind=found.chart_kind,
        instrument=found.instrument,
        timeframe=found.timeframe,
        indicators=list(found.indicators),
        pattern_concept_id=found.pattern_concept_id,
        outcome_shown=found.outcome_shown,
        must_be_historical=True,
    )


def _sentences(segs: list[DocSegment]) -> list[Sentence]:
    return [
        Sentence(text=s.text, pace=s.pace or "NORMAL", emotion=s.emotion or "NEUTRAL") for s in segs
    ]


def _refs(segs: list[DocSegment]) -> list[ConceptRefIn]:
    return (
        [
            ConceptRefIn(concept_id=r.concept_id, citation_refs=list(r.citation_refs))
            for r in segs[0].concept_refs
        ]
        if segs
        else []
    )


def hook_beats(doc: ScriptDocument) -> list[HookBeat]:
    beats: list[HookBeat] = []
    for scene in doc.scenes:
        if scene.section_id != "hook":
            continue
        segs = [s for s in doc.segments if s.scene_id == scene.scene_id]
        beats.append(
            HookBeat(
                beat=scene.beat,  # type: ignore[arg-type]
                sentences=_sentences(segs),
                concrete_example=None,
                chart_request=_chart(doc, scene.chart_id),
                concept_refs=_refs(segs),
            )
        )
    return beats


def plan_section(sec: DocSection) -> PlanSection:
    return PlanSection(
        section_id=sec.section_id,
        section_kind=sec.section_kind,
        heading_local=sec.heading_local,
        heading_en=sec.heading_en,
        purpose=sec.purpose[:240],
        concept_ids=list(sec.concept_ids),
        share_permille=sec.share_permille,
        needs_interrupt=sec.needs_interrupt,
    )


def section_scenes(doc: ScriptDocument, section_id: str) -> list[Scene]:
    section = next(s for s in doc.sections if s.section_id == section_id)
    by_id = {s.scene_id: s for s in doc.scenes}
    scenes: list[Scene] = []
    for position, scene_id in enumerate(section.scene_ids, start=1):
        scene = by_id[scene_id]
        segs = [s for s in doc.segments if s.scene_id == scene_id]
        assert scene.visual_intent is not None  # noqa: S101 - section scenes always carry one
        scenes.append(
            Scene(
                scene_local_id=f"sc{position}",
                beat=scene.beat,  # type: ignore[arg-type]
                sentences=_sentences(segs),
                on_screen_text=list(scene.on_screen_text),
                visual_intent=scene.visual_intent,
                concept_refs=_refs(segs),
                hypothetical_example=scene.hypothetical_example,
                method_label=scene.method_label,
                interrupt=scene.interrupt,
                deliberate_pause_ms=scene.deliberate_pause_ms,
                explanatory=scene.explanatory,
                pronunciation_candidates=list(scene.pronunciation_candidates),
                chart_request=_chart(doc, scene.chart_id),
                purpose_concept_id=scene.purpose_concept_id,
            )
        )
    return scenes


def section_text(doc: ScriptDocument, section_id: str) -> str:
    return " ".join(s.text for s in doc.segments if s.section_id == section_id)[:6000]


def routing_map(doc: ScriptDocument) -> dict[str, list[str]]:
    """``hook`` (hook and disclaimer segments) and each section id to their segment IDs."""
    out: dict[str, list[str]] = {"hook": []}
    for sec in doc.sections:
        out[sec.section_id] = []
    for seg in doc.segments:
        key = seg.section_id if seg.section_id in out else "hook"
        out[key].append(seg.segment_id)
    return out
