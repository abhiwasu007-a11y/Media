"""The in-package result of one check and the remedy mapping (blueprint 10 section 6.5)."""

from dataclasses import dataclass, field
from typing import Any

from agent_10_video_editor.errors import config_invalid
from amw_core.enums import CheckVerdict

MeasuredValue = bool | int | float | str | None

_VOICE = "s07_voice"
_ASSETS = "s08_assets"
_PLAN = "s09_plan"
_RENDER = "s10_render"

# 6.5.4: one entry per gate check_id of 20.1 (qc.* and edit.*); a10.* has no remedy.
REMEDY: dict[str, str] = {
    "qc.video.resolution": _RENDER,
    "qc.video.codec_profile": _RENDER,
    "qc.video.pix_fmt": _RENDER,
    "qc.video.bitrate": _RENDER,
    "qc.video.cfr": _RENDER,
    "qc.video.fps_matches_project": _RENDER,
    "qc.container.faststart": _RENDER,
    "qc.audio.codec": _RENDER,
    "qc.audio.sample_rate": _RENDER,
    "qc.audio.channels": _RENDER,
    "qc.audio.bitrate": _RENDER,
    "qc.audio.true_peak": _VOICE,
    "qc.audio.integrated_lufs": _VOICE,
    "qc.audio.lra_report": _VOICE,
    "qc.audio.clipping": _VOICE,
    "qc.audio.music_bed_offset": _VOICE,
    "qc.audio.silence_mix": _VOICE,
    "qc.audio.speech_spans": _VOICE,
    "qc.video.black_frames": _ASSETS,
    "qc.video.freeze": _PLAN,
    "qc.sync.av_container": _RENDER,
    "qc.subtitles.format": _RENDER,
    "qc.subtitles.languages": _RENDER,
    "qc.subtitles.sync": _RENDER,
    "qc.subtitles.accuracy": _RENDER,
    "qc.duration.vs_script": _VOICE,
    "qc.duration.vs_timeline": _RENDER,
    "qc.duration.in_bounds": _PLAN,
    "qc.licence.completeness": _ASSETS,
    "qc.licence.expiry_window": _ASSETS,
    "qc.watermark.provenance": _ASSETS,
    "qc.watermark.visual": _ASSETS,
    "qc.visual.tier_share_e": _PLAN,
    "qc.visual.tier_mix_report": _PLAN,
    "qc.visual.ai_video_budget": _PLAN,
    "qc.visual.ai_disclosure_recorded": _ASSETS,
    "qc.visual.chart_data_age": _ASSETS,
    "qc.visual.no_synthetic_presenter": _ASSETS,
    "edit.hook.window": _PLAN,
    "edit.hook.no_brand_intro": _PLAN,
    "edit.visual.cadence": _PLAN,
    "edit.visual.cadence_render_crosscheck": _PLAN,
    "edit.interrupt.first_dropoff": _PLAN,
    "edit.interrupt.midpoint": _PLAN,
    "edit.cuts.j_l": _PLAN,
    "edit.chapters": _PLAN,
    "edit.end_screen": _PLAN,
    "edit.dead_air": _VOICE,
}

REMEDY_TARGETS = frozenset({_VOICE, _ASSETS, _PLAN, _RENDER})


class RemedyMapper:
    """F-38: ``check_id`` to the stage that can fix it; an unmapped ID is ``ConfigInvalid``."""

    @staticmethod
    def map(check_id: str) -> str:
        try:
            return REMEDY[check_id]
        except KeyError as exc:
            raise config_invalid(f"UNMAPPED_CHECK:{check_id}") from exc


@dataclass(frozen=True, slots=True)
class CheckResult:
    check_id: str
    verdict: CheckVerdict
    blocking: bool
    gate: bool = True
    measured: MeasuredValue = None
    threshold: MeasuredValue = None
    unit: str | None = None
    offending: tuple[Any, ...] = ()
    remedy_stage_id: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    shot_ids: tuple[str, ...] = ()

    def value_of(self, key: str) -> Any:
        """Look a named expected field up (used by the golden dataset runner)."""
        if key in self.details:
            return self.details[key]
        value = getattr(self, key)
        return (
            [list(x) if isinstance(x, tuple) else x for x in value] if key == "offending" else value
        )


def passed(check_id: str, *, blocking: bool = True, **kw: Any) -> CheckResult:
    return CheckResult(check_id, CheckVerdict.PASS, blocking, **kw)


def failed(check_id: str, **kw: Any) -> CheckResult:
    """A sourced blocking FAIL with the remedy stage of the family."""
    return CheckResult(
        check_id,
        CheckVerdict.FAIL,
        True,
        remedy_stage_id=kw.pop("remedy_stage_id", REMEDY.get(check_id)),
        **kw,
    )


def warned(check_id: str, **kw: Any) -> CheckResult:
    """Unsourced / uncalibrated: measured value recorded, threshold ``None``, never blocking."""
    return CheckResult(
        check_id,
        CheckVerdict.WARN,
        False,
        remedy_stage_id=kw.pop("remedy_stage_id", REMEDY.get(check_id)),
        **kw,
    )


def skipped(check_id: str, message: str = "", **kw: Any) -> CheckResult:
    return CheckResult(check_id, CheckVerdict.SKIPPED, False, message=message, **kw)


def verdict_by(check_id: str, ok: bool, *, sourced: bool = True, **kw: Any) -> CheckResult:
    """18 section 7.0.4: sourced -> PASS/FAIL blocking; unsourced -> PASS or WARN, not blocking."""
    if ok:
        return passed(check_id, blocking=sourced, **kw)
    return failed(check_id, **kw) if sourced else warned(check_id, **kw)
