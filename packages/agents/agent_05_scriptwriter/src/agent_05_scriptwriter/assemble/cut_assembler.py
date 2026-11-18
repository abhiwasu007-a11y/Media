"""Assembly of a Shorts cut into a vertical ``script_document`` (blueprint 8.4, 10.4).

A cut has scenes and no sections; every scene keeps the parent segment IDs it was drawn from.
Charts are reused from the parent (no new chart request exists in a cut).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_05_scriptwriter.assemble.assembler import (
    Assembled,
    canonical_bytes,
    sha256_hex,
)
from agent_05_scriptwriter.assemble.parts import estimate_ms, split_segments
from agent_05_scriptwriter.contracts import (
    CutHook,
    CutScene,
    DocConceptRef,
    DocPromise,
    DocScene,
    DocSegment,
    DocumentProvenance,
    OptionOut,
    ScriptDocument,
)
from agent_05_scriptwriter.text import speech_chars


@dataclass(frozen=True, slots=True)
class CutAssemblyInput:
    script_id: str
    job_id: str
    channel_id: str
    language: str
    version: int
    iteration: int
    promise: DocPromise
    hook: CutHook
    scenes: Sequence[CutScene]
    concept_map: Mapping[str, str]
    hook_options: Sequence[OptionOut]
    rate_cps: float | None
    provenance: DocumentProvenance


def assemble_cut(inp: CutAssemblyInput) -> Assembled:
    segments: list[DocSegment] = []
    scenes: list[DocScene] = []
    splits = 0

    def add(
        texts: Sequence[tuple[str, str, str]],
        kind: str,
        scene_id: str,
        scene: CutScene | None,
        parents: Sequence[str],
    ) -> list[str]:
        nonlocal splits
        ids: list[str] = []
        for text, pace, emotion in texts:
            parts, extra = split_segments(text, pace, emotion)
            splits += extra
            for part in parts:
                seg_id = f"s{len(segments) + 1}"
                ids.append(seg_id)
                segments.append(
                    DocSegment(
                        segment_id=seg_id,
                        kind=kind,  # type: ignore[arg-type]
                        section_id=None,
                        scene_id=scene_id,
                        text=part.text,
                        pace=part.pace,  # type: ignore[arg-type]
                        emotion=part.emotion,  # type: ignore[arg-type]
                        concept_refs=[
                            DocConceptRef(
                                concept_id=r.concept_id,
                                pack_concept_id=inp.concept_map.get(r.concept_id, "c00"),
                                citation_refs=list(r.citation_refs),
                            )
                            for r in (scene.concept_refs if scene else [])
                        ],
                        chart_ref=scene.chart_ref if scene else None,
                        method_label=scene.method_label if scene else False,
                        hypothetical_example=scene.hypothetical_example if scene else False,
                        est_start_ms=None,
                        est_duration_ms=None,
                        parent_segment_ids=list(parents),
                    )
                )
        return ids

    hook_ids = add(
        [(s.text, s.pace, s.emotion) for s in inp.hook.sentences],
        "SHORT_HOOK",
        "hook.sc1",
        None,
        inp.hook.parent_segment_ids,
    )
    scenes.append(_scene("hook.sc1", "SHORT_HOOK", hook_ids, None))
    pauses: dict[str, int] = {}
    for position, sc in enumerate(inp.scenes, start=1):
        scene_id = f"sc{position}"
        ids = add(
            [(s.text, s.pace, s.emotion) for s in sc.sentences],
            sc.beat,
            scene_id,
            sc,
            sc.parent_segment_ids,
        )
        pauses[ids[-1]] = sc.deliberate_pause_ms
        scenes.append(_scene(scene_id, sc.beat, ids, sc))
    if inp.rate_cps is not None:
        clock = 0
        for i, seg in enumerate(segments):
            dur = estimate_ms(speech_chars(seg.text), inp.rate_cps, pauses.get(seg.segment_id, 0))
            assert dur is not None  # noqa: S101 - a rate is set
            segments[i] = seg.model_copy(update={"est_start_ms": clock, "est_duration_ms": dur})
            clock += dur
    options = [
        o.model_copy(update={"segment_ids": hook_ids if o.segment_ids else []})
        for o in inp.hook_options
    ]
    document = ScriptDocument(
        script_id=inp.script_id,
        job_id=inp.job_id,
        channel_id=inp.channel_id,
        language=inp.language,  # type: ignore[arg-type]
        version=inp.version,
        iteration=inp.iteration,
        aspect_ratio="9:16",
        promise=inp.promise,
        sections=[],
        scenes=scenes,
        segments=segments,
        chart_requests=[],
        chapters=[],
        disclaimer_slots=[],
        description_draft=None,
        thumbnail_brief=None,
        hook_options=options,
        omitted_concepts=[],
        provenance=inp.provenance,
    )
    content = canonical_bytes(document.model_dump(mode="json"))
    return Assembled(document, content, sha256_hex(content), splits, {})


def _scene(scene_id: str, beat: str, ids: list[str], sc: CutScene | None) -> DocScene:
    return DocScene(
        scene_id=scene_id,
        section_id=None,
        beat=beat,
        segment_ids=ids,
        on_screen_text=list(sc.on_screen_text) if sc else [],
        visual_intent=sc.visual_intent if sc else None,
        interrupt=sc.interrupt if sc else None,
        deliberate_pause_ms=sc.deliberate_pause_ms if sc else 0,
        explanatory=sc.explanatory if sc else False,
        pronunciation_candidates=list(sc.pronunciation_candidates) if sc else [],
        chart_id=sc.chart_ref if sc else None,
        purpose_concept_id=None,
        method_label=sc.method_label if sc else False,
        hypothetical_example=sc.hypothetical_example if sc else False,
    )
