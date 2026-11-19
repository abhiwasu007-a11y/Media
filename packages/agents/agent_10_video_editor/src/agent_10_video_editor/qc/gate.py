"""Gate aggregation and the QC plan (blueprint 10 sections 6.5.3, F-34, F-37)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from agent_10_video_editor.errors import config_invalid
from agent_10_video_editor.qc.result import REMEDY, CheckResult
from amw_core.enums import CheckVerdict, GateVerdict

# 20.1 rows 11-58, profile order (cheap checks first is the run order of QcPlan, not this order).
PROFILE_CHECKS: tuple[str, ...] = (
    "qc.video.resolution",
    "qc.video.codec_profile",
    "qc.video.pix_fmt",
    "qc.video.encoder_settings",
    "qc.video.quality_metric",
    "qc.video.cfr",
    "qc.video.fps_matches_project",
    "qc.container.faststart",
    "qc.audio.codec",
    "qc.audio.sample_rate",
    "qc.audio.channels",
    "qc.audio.bitrate",
    "qc.audio.true_peak",
    "qc.audio.integrated_lufs",
    "qc.audio.lra_report",
    "qc.audio.clipping",
    "qc.audio.music_bed_offset",
    "qc.audio.silence_mix",
    "qc.audio.speech_spans",
    "qc.video.black_frames",
    "qc.video.freeze",
    "qc.sync.av_container",
    "qc.subtitles.format",
    "qc.subtitles.languages",
    "qc.subtitles.sync",
    "qc.subtitles.accuracy",
    "qc.duration.vs_script",
    "qc.duration.vs_timeline",
    "qc.duration.in_bounds",
    "qc.licence.completeness",
    "qc.licence.expiry_window",
    "qc.watermark.provenance",
    "qc.watermark.visual",
    "qc.visual.tier_share_e",
    "qc.visual.tier_mix_report",
    "qc.visual.ai_video_budget",
    "qc.visual.ai_disclosure_recorded",
    "qc.visual.chart_data_age",
    "qc.visual.no_synthetic_presenter",
    "edit.hook.window",
    "edit.hook.no_brand_intro",
    "edit.visual.cadence",
    "edit.visual.cadence_render_crosscheck",
    "edit.interrupt.first_dropoff",
    "edit.interrupt.midpoint",
    "edit.cuts.j_l",
    "edit.chapters",
    "edit.end_screen",
    "edit.dead_air",
)

# qc.shorts: section-based items are emitted SKIPPED, blocking false (24 section 7.2a).
SHORTS_SKIPPED: frozenset[str] = frozenset(
    {"edit.chapters", "edit.interrupt.first_dropoff", "edit.interrupt.midpoint"}
)

# QC groups of section 4.2 / 16.2, in run order (cheap checks first).
GROUPS: tuple[str, ...] = ("qc.probe", "qc.audio", "qc.video", "qc.db")


def profile_check_ids(profile: Literal["qc.long_form", "qc.shorts"]) -> tuple[str, ...]:
    if profile not in ("qc.long_form", "qc.shorts"):
        raise config_invalid("UNKNOWN_PROFILE")
    return PROFILE_CHECKS


@dataclass(frozen=True, slots=True)
class FailedCheck:
    check_id: str
    reason: Literal["NO_RESULT", "FAIL"]


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_verdict: GateVerdict
    failed_checks: tuple[FailedCheck, ...]
    remedy_stage_ids: tuple[str, ...]


class GateAggregator:
    """F-37: FAILED if any profile check has no result or a gate result that is blocking FAIL."""

    @staticmethod
    def decide(results: Sequence[CheckResult], profile_check_ids: Sequence[str]) -> GateResult:
        by_id = {r.check_id: r for r in results}
        failed: list[FailedCheck] = []
        remedies: list[str] = []
        for check_id in profile_check_ids:
            result = by_id.get(check_id)
            if result is None:
                failed.append(FailedCheck(check_id, "NO_RESULT"))
                remedy = REMEDY.get(check_id)
            elif result.gate and result.blocking and result.verdict == CheckVerdict.FAIL:
                failed.append(FailedCheck(check_id, "FAIL"))
                remedy = result.remedy_stage_id or REMEDY.get(check_id)
            else:
                continue
            if remedy is not None and remedy not in remedies:
                remedies.append(remedy)
        return GateResult(
            GateVerdict.FAILED if failed else GateVerdict.PASSED,
            tuple(failed),
            tuple(remedies),
        )


@dataclass(frozen=True, slots=True)
class CheckSpec:
    check_id: str
    group: str


# Which group measures which check (QcPlan order: cheap first, full-decode passes last).
_GROUP_OF: dict[str, str] = {
    **dict.fromkeys(
        (
            "qc.video.resolution",
            "qc.video.codec_profile",
            "qc.video.pix_fmt",
            "qc.video.encoder_settings",
            "qc.video.quality_metric",
            "qc.video.cfr",
            "qc.video.fps_matches_project",
            "qc.container.faststart",
            "qc.audio.codec",
            "qc.audio.sample_rate",
            "qc.audio.channels",
            "qc.audio.bitrate",
            "qc.sync.av_container",
            "qc.duration.vs_script",
            "qc.duration.vs_timeline",
            "qc.duration.in_bounds",
        ),
        "qc.probe",
    ),
    **dict.fromkeys(
        (
            "qc.audio.true_peak",
            "qc.audio.integrated_lufs",
            "qc.audio.lra_report",
            "qc.audio.clipping",
            "qc.audio.music_bed_offset",
            "qc.audio.silence_mix",
            "qc.audio.speech_spans",
            "edit.dead_air",
        ),
        "qc.audio",
    ),
    **dict.fromkeys(
        (
            "qc.video.black_frames",
            "qc.video.freeze",
            "edit.visual.cadence_render_crosscheck",
            "qc.watermark.visual",
        ),
        "qc.video",
    ),
}


class QcPlan:
    @staticmethod
    def build(profile: Literal["qc.long_form", "qc.shorts"]) -> list[CheckSpec]:
        ids = profile_check_ids(profile)
        order = {g: i for i, g in enumerate(GROUPS)}
        specs = [CheckSpec(cid, _GROUP_OF.get(cid, "qc.db")) for cid in ids]
        return sorted(specs, key=lambda s: order[s.group])  # stable: profile order inside a group
