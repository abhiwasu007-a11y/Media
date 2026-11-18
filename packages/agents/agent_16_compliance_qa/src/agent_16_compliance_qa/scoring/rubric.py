"""Rubric ``rubric.v1`` (18 section 9.2; CCR-058; blueprint section 6.6.1).

Dimension points are GLOSSARY section 6.45 (``QualityDimension.max_points``). Per dimension:
D + J + H = the dimension's points; the machine owns D + J (79 in all), the owner's HUMAN rows
complete the total. The **sub-weights of the D criteria inside a dimension are PROPOSAL**
(recalibrated in 3B) and are recorded in each row's breakdown. THUMBNAIL_METADATA keeps D 4 in
3A, earned from the thumbnail and working-title checks only (chapters are 3C, Agent 12).
"""

from typing import Final, Literal

from agent_16_compliance_qa.base import Model
from amw_core.enums import QualityDimension as Q

RUBRIC_VERSION: Final = "rubric.v1"
Kind = Literal["DETERMINISTIC", "LLM_JUDGE", "HUMAN"]
Group = Literal["G1", "G2", "G3"]


class Criterion(Model):
    criterion_id: str
    dimension: Q
    kind: Kind
    max_points: int
    group: Group | None = None
    check_prefixes: tuple[str, ...] = ()
    """D criteria scored from ``qc_results``: every row whose ``check_id`` starts with one of
    these must be ``PASS`` (a missing row earns 0 with a finding, never full points)."""
    precondition_3a: str | None = None
    """Set when the criterion cannot be evaluated in 3A (``SKIPPED``, earns 0)."""


def _d(cid: str, dim: Q, pts: int, *prefixes: str, skip: str | None = None) -> Criterion:
    return Criterion(
        criterion_id=cid,
        dimension=dim,
        kind="DETERMINISTIC",
        max_points=pts,
        check_prefixes=prefixes,
        precondition_3a=skip,
    )


def _j(cid: str, dim: Q, pts: int, group: Group) -> Criterion:
    return Criterion(criterion_id=cid, dimension=dim, kind="LLM_JUDGE", max_points=pts, group=group)


def _h(dim: Q, pts: int) -> Criterion:
    return Criterion(
        criterion_id=f"{_ABBR[dim]}.h.owner", dimension=dim, kind="HUMAN", max_points=pts
    )


_ABBR: Final = {
    Q.RESEARCH_ACCURACY: "ra",
    Q.STORYTELLING: "st",
    Q.AUDIENCE_VALUE: "av",
    Q.VISUAL_QUALITY: "vq",
    Q.AUDIO_QUALITY: "au",
    Q.EDITING_QUALITY: "eq",
    Q.THUMBNAIL_METADATA: "tm",
    Q.COMPLIANCE: "co",
}
ABBREVIATION: Final = _ABBR

RUBRIC_V1: Final[tuple[Criterion, ...]] = (
    # RESEARCH_ACCURACY 20 = D 12 + J 5 + H 3
    _d("ra.d.citations", Q.RESEARCH_ACCURACY, 6),
    _d("ra.d.no_contradicted", Q.RESEARCH_ACCURACY, 3),
    _d("ra.d.no_unverified", Q.RESEARCH_ACCURACY, 3),
    _j("ra.j.evidence_use", Q.RESEARCH_ACCURACY, 5, "G1"),
    _h(Q.RESEARCH_ACCURACY, 3),
    # STORYTELLING 15 = D 5 + J 7 + H 3
    _d(
        "st.d.hook",
        Q.STORYTELLING,
        2,
        "edit.hook.window",
        "edit.hook.beats",
        "edit.hook.no_brand_intro",
        "edit.hook.selection_valid",
    ),
    _d("st.d.chapters", Q.STORYTELLING, 1, "edit.chapters"),
    _d("st.d.hook_options", Q.STORYTELLING, 1, "edit.hook.options"),
    _d("st.d.promise_fields", Q.STORYTELLING, 1),
    _j("st.j.narrative", Q.STORYTELLING, 7, "G2"),
    _h(Q.STORYTELLING, 3),
    # AUDIENCE_VALUE 15 = D 3 + J 7 + H 5
    _d("av.d.takeaways", Q.AUDIENCE_VALUE, 1),
    _d("av.d.examples", Q.AUDIENCE_VALUE, 1),
    _d("av.d.problem", Q.AUDIENCE_VALUE, 1),
    _j("av.j.usefulness", Q.AUDIENCE_VALUE, 7, "G1"),
    _h(Q.AUDIENCE_VALUE, 5),
    # VISUAL_QUALITY 15 = D 9 + J 3 + H 3
    _d(
        "vq.d.tier_mix",
        Q.VISUAL_QUALITY,
        3,
        "qc.visual.tier_share_e",
        "qc.visual.ai_video_budget",
        "qc.visual.chart_data_age",
    ),
    _d("vq.d.cadence", Q.VISUAL_QUALITY, 2, "edit.visual.cadence", "qc.visual.max_change_gap_ms"),
    _d(
        "vq.d.format",
        Q.VISUAL_QUALITY,
        2,
        "qc.video.resolution",
        "qc.video.codec_profile",
        "qc.video.pix_fmt",
        "qc.video.cfr",
    ),
    _d("vq.d.no_black_freeze", Q.VISUAL_QUALITY, 1, "qc.video.black_frames", "qc.video.freeze"),
    _d("vq.d.no_watermark", Q.VISUAL_QUALITY, 1, "qc.watermark.provenance"),
    _j("vq.j.frame_relevance", Q.VISUAL_QUALITY, 3, "G3"),
    _h(Q.VISUAL_QUALITY, 3),
    # AUDIO_QUALITY 10 = D 7 + H 3
    _d("au.d.loudness", Q.AUDIO_QUALITY, 2, "qc.audio.integrated_lufs", "qc.audio.true_peak"),
    _d(
        "au.d.codec",
        Q.AUDIO_QUALITY,
        2,
        "qc.audio.codec",
        "qc.audio.sample_rate",
        "qc.audio.bitrate",
    ),
    _d("au.d.clean", Q.AUDIO_QUALITY, 2, "qc.audio.clipping", "qc.audio.silence_mix"),
    _d(
        "au.d.music_bed",
        Q.AUDIO_QUALITY,
        1,
        "qc.audio.music_bed_offset",
        skip="no music bed in 3A technical runs (CCR-007, D6)",
    ),
    _h(Q.AUDIO_QUALITY, 3),
    # EDITING_QUALITY 10 = D 6 + J 2 + H 2
    _d("eq.d.interrupts", Q.EDITING_QUALITY, 1, "edit.interrupt."),
    _d("eq.d.jl_cuts", Q.EDITING_QUALITY, 1, "edit.cuts.j_l"),
    _d("eq.d.dead_air", Q.EDITING_QUALITY, 1, "edit.dead_air"),
    _d("eq.d.end_screen", Q.EDITING_QUALITY, 1, "edit.end_screen"),
    _d("eq.d.sync", Q.EDITING_QUALITY, 1, "qc.sync.av_container", "qc.subtitles.sync"),
    _d("eq.d.duration", Q.EDITING_QUALITY, 1, "qc.duration.vs_script"),
    _j("eq.j.rhythm", Q.EDITING_QUALITY, 2, "G3"),
    _h(Q.EDITING_QUALITY, 2),
    # THUMBNAIL_METADATA 10 = D 4 + J 4 + H 2
    _d("tm.d.variants", Q.THUMBNAIL_METADATA, 1),
    _d("tm.d.spec", Q.THUMBNAIL_METADATA, 1),
    _d("tm.d.legibility", Q.THUMBNAIL_METADATA, 1),
    _d("tm.d.title_length", Q.THUMBNAIL_METADATA, 1),
    _j("tm.j.promise_alignment", Q.THUMBNAIL_METADATA, 4, "G2"),
    _h(Q.THUMBNAIL_METADATA, 2),
    # COMPLIANCE 5 = D 5
    _d("co.d.gate", Q.COMPLIANCE, 2),
    _d("co.d.licence", Q.COMPLIANCE, 1),
    _d("co.d.disclosure", Q.COMPLIANCE, 1),
    _d("co.d.disclaimer", Q.COMPLIANCE, 1),
)


def machine_criteria() -> tuple[Criterion, ...]:
    return tuple(c for c in RUBRIC_V1 if c.kind != "HUMAN")


def group_criteria(group: Group) -> tuple[Criterion, ...]:
    return tuple(c for c in RUBRIC_V1 if c.group == group)


def validate_rubric(rubric: tuple[Criterion, ...] = RUBRIC_V1) -> None:
    """Readiness check: sum of max = 100 and per dimension D + J + H = its points."""
    if sum(c.max_points for c in rubric) != 100:
        raise ValueError("rubric does not sum to 100")
    for dim in Q:
        if sum(c.max_points for c in rubric if c.dimension is dim) != dim.max_points:
            raise ValueError(f"rubric points of {dim.value} differ from GLOSSARY 6.45")
