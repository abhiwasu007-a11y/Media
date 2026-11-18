"""``ScriptAssembler`` (blueprint 10.6): validated plan and sections to the script document.

Deterministic: the same inputs give the same bytes (canonical JSON, UTF-8, sorted keys, no
insignificant whitespace, 03 section 9.1). Segment IDs are ``s1..sN`` in document order; one
segment is one narration sentence. A section hash covers the section's kinds, headings, scene fields
and sentence text and tags but not absolute segment or scene IDs, so an unchanged section keeps its
hash when an earlier section changes length.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agent_05_scriptwriter.assemble.parts import (
    DisclaimerTemplate,
    chapter_starts,
    estimate_ms,
    split_segments,
)
from agent_05_scriptwriter.contracts import (
    Chapter,
    ChartRequest,
    DisclaimerSlot,
    DocChartRequest,
    DocConceptRef,
    DocPromise,
    DocScene,
    DocSection,
    DocSegment,
    DocumentProvenance,
    HookBeat,
    OptionOut,
    PlanSection,
    Scene,
    ScriptDocument,
    ThumbnailBrief,
)
from agent_05_scriptwriter.text import speech_chars

HOOK_SECTION = "hook"
HOOK_KINDS = {"HOOK_PROOF", "HOOK_WHY", "HOOK_COVERS"}


def canonical_bytes(model_dump: Any) -> bytes:
    return json.dumps(model_dump, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class AssemblyInput:
    script_id: str
    job_id: str
    channel_id: str
    language: str
    version: int
    iteration: int
    promise: DocPromise
    hook_beats: Sequence[HookBeat]
    hook_chart_id: str | None
    sections: Sequence[PlanSection]
    section_scenes: Mapping[str, Sequence[Scene]]
    concept_map: Mapping[str, str]
    hook_options: Sequence[OptionOut]
    description_draft: str | None
    thumbnail_brief: ThumbnailBrief | None
    rate_cps: float | None
    disclaimer_template: DisclaimerTemplate | None = None
    disclaimer_placements: Sequence[str] = ()
    provenance: DocumentProvenance | None = None


@dataclass(frozen=True, slots=True)
class Assembled:
    document: ScriptDocument
    content: bytes
    sha256: str
    split_count: int
    section_sha256: dict[str, str] = field(default_factory=dict)


def _concept_refs(refs: Sequence[Any], concept_map: Mapping[str, str]) -> list[DocConceptRef]:
    return [
        DocConceptRef(
            concept_id=r.concept_id,
            pack_concept_id=concept_map[r.concept_id],
            citation_refs=list(r.citation_refs),
        )
        for r in refs
    ]


def section_hash(plan: PlanSection, scenes: Sequence[Scene]) -> str:
    """Hash of the section content without absolute IDs (scene order and sentence text/tags)."""
    body = {
        "kind": plan.section_kind,
        "heading_local": plan.heading_local,
        "heading_en": plan.heading_en,
        "purpose": plan.purpose,
        "concept_ids": list(plan.concept_ids),
        "needs_interrupt": plan.needs_interrupt,
        "share_permille": plan.share_permille,
        "scenes": [
            {
                **s.model_dump(mode="json", exclude={"scene_local_id"}),
                "sentences": [
                    {"text": p.text, "pace": p.pace, "emotion": p.emotion}
                    for sent in s.sentences
                    for p in split_segments(sent.text, sent.pace, sent.emotion)[0]
                ],
            }
            for s in scenes
        ],
    }
    return sha256_hex(canonical_bytes(body))


def assemble(inp: AssemblyInput) -> Assembled:
    segments: list[DocSegment] = []
    scenes: list[DocScene] = []
    charts: list[DocChartRequest] = []
    splits = 0
    pending_pause: dict[str, int] = {}

    def add_segments(
        texts: Sequence[tuple[str, str, str]],
        *,
        kind: str,
        section_id: str | None,
        scene_id: str,
        refs: list[DocConceptRef],
        chart_ref: str | None,
        method_label: bool,
        hypothetical: bool,
    ) -> list[str]:
        nonlocal splits
        ids: list[str] = []
        for text, pace, emotion in texts:
            parts, extra = split_segments(text, pace, emotion)
            splits += extra
            for part in parts:
                segment_id = f"s{len(segments) + 1}"
                ids.append(segment_id)
                segments.append(
                    DocSegment(
                        segment_id=segment_id,
                        kind=kind,  # type: ignore[arg-type]  # str narrowed to a Literal; value comes from a validated model
                        section_id=section_id,
                        scene_id=scene_id,
                        text=part.text,
                        pace=part.pace,  # type: ignore[arg-type]  # str narrowed to a Literal; value comes from a validated model
                        emotion=part.emotion,  # type: ignore[arg-type]  # str narrowed to a Literal; value comes from a validated model
                        concept_refs=refs,
                        chart_ref=chart_ref,
                        method_label=method_label,
                        hypothetical_example=hypothetical,
                        est_start_ms=None,
                        est_duration_ms=None,
                        parent_segment_ids=[],
                    )
                )
        return ids

    def add_disclaimer(slot_index: int, placement: str) -> DisclaimerSlot:
        template = inp.disclaimer_template
        assert template is not None  # noqa: S101 - placements are only given with a template
        scene_id = f"disc.sc{slot_index}"
        ids = add_segments(
            [(template.text, "NORMAL", "NEUTRAL")],
            kind="DISCLAIMER",
            section_id=None,
            scene_id=scene_id,
            refs=[],
            chart_ref=None,
            method_label=False,
            hypothetical=False,
        )
        scenes.append(
            DocScene(
                scene_id=scene_id,
                section_id=None,
                beat="DISCLAIMER",
                segment_ids=ids,
                on_screen_text=[],
                visual_intent=None,
                interrupt=None,
                deliberate_pause_ms=0,
                explanatory=False,
                pronunciation_candidates=[],
                chart_id=None,
                purpose_concept_id=None,
                method_label=False,
                hypothetical_example=False,
            )
        )
        return DisclaimerSlot(
            slot_id=f"slot{slot_index}",
            placement=placement,
            template_ref=template.ref,
            template_version=template.version,
            text_sha256=sha256_hex(template.text.encode("utf-8")),
            segment_id=ids[0],
        )

    slots: list[DisclaimerSlot] = []
    after_hook = [p for p in inp.disclaimer_placements if p == "AFTER_HOOK"]
    at_end = [p for p in inp.disclaimer_placements if p == "END"]

    # hook: one scene per beat, in order
    for number, beat in enumerate(inp.hook_beats, start=1):
        scene_id = f"{HOOK_SECTION}.sc{number}"
        chart_id = inp.hook_chart_id if beat.chart_request is not None else None
        ids = add_segments(
            [(s.text, s.pace, s.emotion) for s in beat.sentences],
            kind=beat.beat,
            section_id=HOOK_SECTION,
            scene_id=scene_id,
            refs=_concept_refs(beat.concept_refs, inp.concept_map),
            chart_ref=chart_id,
            method_label=False,
            hypothetical=False,
        )
        scenes.append(
            DocScene(
                scene_id=scene_id,
                section_id=HOOK_SECTION,
                beat=beat.beat,
                segment_ids=ids,
                on_screen_text=[],
                visual_intent=None,
                interrupt=None,
                deliberate_pause_ms=0,
                explanatory=False,
                pronunciation_candidates=[],
                chart_id=chart_id,
                purpose_concept_id=None,
                method_label=False,
                hypothetical_example=False,
            )
        )
        if beat.chart_request is not None and chart_id is not None:
            charts.append(_chart(beat.chart_request, chart_id, ids[0]))
    for index, placement in enumerate(after_hook, start=1):
        slots.append(add_disclaimer(index, placement))

    doc_sections: list[DocSection] = []
    section_hashes: dict[str, str] = {}
    for plan in inp.sections:
        scene_ids: list[str] = []
        for position, scene in enumerate(inp.section_scenes[plan.section_id], start=1):
            scene_id = f"{plan.section_id}.sc{position}"
            scene_ids.append(scene_id)
            chart_id = scene.chart_request.chart_id if scene.chart_request else None
            ids = add_segments(
                [(s.text, s.pace, s.emotion) for s in scene.sentences],
                kind=scene.beat,
                section_id=plan.section_id,
                scene_id=scene_id,
                refs=_concept_refs(scene.concept_refs, inp.concept_map),
                chart_ref=chart_id,
                method_label=scene.method_label,
                hypothetical=scene.hypothetical_example,
            )
            pending_pause[ids[-1]] = scene.deliberate_pause_ms
            scenes.append(
                DocScene(
                    scene_id=scene_id,
                    section_id=plan.section_id,
                    beat=scene.beat,
                    segment_ids=ids,
                    on_screen_text=list(scene.on_screen_text),
                    visual_intent=scene.visual_intent,
                    interrupt=scene.interrupt,
                    deliberate_pause_ms=scene.deliberate_pause_ms,
                    explanatory=scene.explanatory,
                    pronunciation_candidates=list(scene.pronunciation_candidates),
                    chart_id=chart_id,
                    purpose_concept_id=scene.purpose_concept_id,
                    method_label=scene.method_label,
                    hypothetical_example=scene.hypothetical_example,
                )
            )
            if scene.chart_request is not None:
                charts.append(_chart(scene.chart_request, scene.chart_request.chart_id, ids[0]))
        doc_sections.append(
            DocSection(
                section_id=plan.section_id,
                section_kind=plan.section_kind,
                heading_local=plan.heading_local,
                heading_en=plan.heading_en,
                purpose=plan.purpose,
                concept_ids=list(plan.concept_ids),
                needs_interrupt=plan.needs_interrupt,
                scene_ids=scene_ids,
                share_permille=plan.share_permille,
            )
        )
        section_hashes[plan.section_id] = section_hash(plan, inp.section_scenes[plan.section_id])
    for index, placement in enumerate(at_end, start=len(after_hook) + 1):
        slots.append(add_disclaimer(index, placement))

    _estimate(segments, pending_pause, inp.rate_cps)
    starts = _section_starts(doc_sections, segments)
    chapters = [
        Chapter(section_id=s.section_id, title_local=s.heading_local, est_start_ms=starts[i])
        for i, s in enumerate(doc_sections)
    ]
    provenance = inp.provenance or DocumentProvenance(
        prompt_ids={},
        prompt_sha256={},
        rule_pack_versions={},
        config_key_families=[],
        section_sha256={},
    )
    provenance = provenance.model_copy(update={"section_sha256": section_hashes})
    document = ScriptDocument(
        script_id=inp.script_id,
        job_id=inp.job_id,
        channel_id=inp.channel_id,
        language=inp.language,  # type: ignore[arg-type]  # str narrowed to a Literal; value comes from a validated model
        version=inp.version,
        iteration=inp.iteration,
        aspect_ratio="16:9",
        promise=inp.promise,
        sections=doc_sections,
        scenes=scenes,
        segments=segments,
        chart_requests=charts,
        chapters=chapters,
        disclaimer_slots=slots,
        description_draft=inp.description_draft,
        thumbnail_brief=inp.thumbnail_brief,
        hook_options=_with_selected_ids(inp.hook_options, segments),
        provenance=provenance,
    )
    content = canonical_bytes(document.model_dump(mode="json"))
    return Assembled(document, content, sha256_hex(content), splits, section_hashes)


def _chart(req: ChartRequest, chart_id: str, first_segment_id: str) -> DocChartRequest:
    return DocChartRequest(
        chart_id=chart_id,
        chart_kind=req.chart_kind,
        instrument=req.instrument,
        timeframe=req.timeframe,
        indicators=list(req.indicators),
        pattern_concept_id=req.pattern_concept_id,
        outcome_shown=req.outcome_shown,
        must_be_historical=True,
        first_segment_id=first_segment_id,
    )


def _with_selected_ids(
    options: Sequence[OptionOut], segments: Sequence[DocSegment]
) -> list[OptionOut]:
    hook_ids = [s.segment_id for s in segments if s.kind in HOOK_KINDS]
    return [
        o.model_copy(update={"segment_ids": hook_ids if o.segment_ids else []}) for o in options
    ]


def _estimate(segments: list[DocSegment], pauses: Mapping[str, int], rate: float | None) -> None:
    if rate is None:
        return
    clock = 0
    for index, seg in enumerate(segments):
        duration = estimate_ms(speech_chars(seg.text), rate, pauses.get(seg.segment_id, 0))
        assert duration is not None  # noqa: S101 - a rate is set
        segments[index] = seg.model_copy(
            update={"est_start_ms": clock, "est_duration_ms": duration}
        )
        clock += duration


def _section_starts(
    sections: Sequence[DocSection], segments: Sequence[DocSegment]
) -> list[int | None]:
    durations: list[int | None] = []
    for section in sections:
        own = [s for s in segments if s.section_id == section.section_id]
        durations.append(
            None
            if any(s.est_duration_ms is None for s in own)
            else sum(s.est_duration_ms or 0 for s in own)
        )
    if sections and segments:
        # the hook (and any slot after it) belongs to the first chapter, which starts at 0 ms
        first = next(
            (i for i, s in enumerate(segments) if s.section_id == sections[0].section_id), 0
        )
        lead = segments[:first]
        if durations[0] is not None:
            durations[0] = (
                None
                if any(s.est_duration_ms is None for s in lead)
                else durations[0] + sum(s.est_duration_ms or 0 for s in lead)
            )
    return chapter_starts(durations)
