"""Runs the 120 deterministic cases of ``evals/agent_10_video_editor/deterministic_core`` (R-01).

Every case is run through the real pure function of the package; ``expected`` must match exactly
(T1), error cases make zero FFmpeg calls (T3), running twice gives identical results (T4), and a
missing measurement is never PASS (T6).
"""

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from agent_10_video_editor.config import GuardConfig, MarketWindow, NightWindow, Placement, Weekday
from agent_10_video_editor.errors import MeasurementUnavailable, violations_of
from agent_10_video_editor.frames import FrameQuantiser
from agent_10_video_editor.guard import HeavyWorkGuard, LocalTime, SelfDrainTimer
from agent_10_video_editor.probe import (
    BlackdetectParser,
    Ebur128Parser,
    FreezedetectParser,
    SilencedetectParser,
)
from agent_10_video_editor.qc import checks as C  # noqa: N812
from agent_10_video_editor.qc.gate import GateAggregator
from agent_10_video_editor.qc.result import CheckResult
from agent_10_video_editor.segments import SegmentKey, SegmentPlanner, ShotFrames
from agent_10_video_editor.subtitles import (
    Cue,
    CueBuilder,
    SrtValidator,
    SrtWriter,
    SubtitleStageCore,
)
from agent_10_video_editor.timeline import (
    RevealStepBuilder,
    TimelineHasher,
    UpstreamGate,
)
from amw_core.errors import AmwError
from tests.agents.agent_10_video_editor.support import compile_case

CASES_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs/v4/evals/agent_10_video_editor/deterministic_core/cases.jsonl"
)
CASES = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line]


def _guard_cfg(inp: dict[str, Any]) -> GuardConfig:
    def mins(text: str) -> int:
        hours, minutes = text.split(":")
        return int(hours) * 60 + int(minutes)

    night = inp["night_window"]
    return GuardConfig(
        market_windows=tuple(
            MarketWindow(
                weekday=Weekday(w["weekday"]), start_min=mins(w["start"]), end_min=mins(w["end"])
            )
            for w in inp["market_windows_local"]
        ),
        night_window=NightWindow(end_min=mins(night["end"]), grace_ms=night["grace_min"] * 60_000),
    )


def _spans(items: list[list[int]]) -> list[tuple[int, int]]:
    return [(a, b) for a, b in items]


def _cue_dicts(items: list[dict[str, Any]]) -> list[Cue]:
    return [Cue(c["index"], c["start_ms"], c["end_ms"], c["text"]) for c in items]


def _eval(fn: str, i: dict[str, Any]) -> CheckResult | dict[str, Any]:
    match fn:
        case "qc.video.bitrate.evaluate":
            return C.qc_video_bitrate(**i)
        case "qc.audio.true_peak.evaluate":
            return C.qc_audio_true_peak(
                true_peak_dbtp=i["true_peak_dbtp"], ceiling_dbtp=i["ceiling_dbtp"]
            )
        case "qc.audio.integrated_lufs.evaluate":
            return C.qc_audio_integrated_lufs(**i)
        case "qc.duration.vs_timeline.evaluate":
            return C.qc_duration_vs_timeline(**i)
        case "qc.visual.tier_share_e.evaluate":
            return C.qc_visual_tier_share_e(**i)
        case "qc.video.black_frames.evaluate":
            return C.qc_video_black_frames(
                detections_ms=i["detections_ms"],
                deliberate_black_ms=i["deliberate_black_ms"],
                total_ms=i["total_ms"],
                calibrated=i["calibrated"],
            )
        case "qc.audio.silence_mix.evaluate":
            return C.qc_audio_silence_mix(**i)
        case "qc.licence.completeness.evaluate":
            return C.qc_licence_completeness(**i)
        case "qc.audio.music_bed_offset.evaluate":
            return C.qc_audio_music_bed_offset(**i)
        case "edit.visual.cadence.evaluate":
            return C.edit_visual_cadence(**i)
        case "edit.chapters.evaluate":
            return C.edit_chapters(**i)
        case "edit.hook.no_brand_intro.evaluate":
            return C.edit_hook_no_brand_intro(**i)
        case "CfrAnalyser.evaluate":
            return C.CfrAnalyser.evaluate(**i)
        case "qc.subtitles.sync.evaluate":
            return C.qc_subtitles_sync(**i)
        case "qc.visual.ai_video_budget.evaluate":
            return C.qc_visual_ai_video_budget(**i)
        case "qc.audio.bitrate.evaluate":
            return C.qc_audio_bitrate(**i)
        case "qc.duration.vs_script.evaluate":
            return C.qc_duration_vs_script(**i)
    raise AssertionError(fn)


def _call(case: dict[str, Any]) -> Any:
    fn, i = case["function"], case["input"]
    match fn:
        case "FrameQuantiser.to_frame":
            return {"frame": FrameQuantiser.to_frame(**i)}
        case "FrameQuantiser.frames_to_ms":
            return {"duration_ms": FrameQuantiser.frames_to_ms(**i)}
        case "TimelineCompiler.compile":
            timeline = compile_case(i)
            return {
                "shots_frames": timeline.shots_frames,
                "total_frames": timeline.total_frames,
                "expected_render_duration_ms": timeline.expected_render_duration_ms,
            }
        case "TimelineHasher.sha256":
            return {
                "sha256_equal": TimelineHasher.sha256(i["variant_a"])
                == TimelineHasher.sha256(i["variant_b"])
            }
        case "SegmentPlanner.plan":
            segs = SegmentPlanner.plan(
                [ShotFrames(s["shot_id"], s["start_frame"], s["end_frame"]) for s in i["shots"]],
                i["target_frames"],
            )
            return {
                "segments": [
                    {
                        "start_frame": s.start_frame,
                        "end_frame": s.end_frame,
                        "shot_ids": list(s.shot_ids),
                    }
                    for s in segs
                ]
            }
        case "SegmentKey.compute":
            return {
                "keys_equal": SegmentKey.compute(**i["variant_a"])
                == SegmentKey.compute(**i["variant_b"])
            }
        case "SrtWriter.format_time":
            return {"text": SrtWriter.format_time(i["ms"])}
        case "CueBuilder.build":
            seg = i["segment"]
            built = CueBuilder.build(
                seg["segment_id"],
                seg["start_ms"],
                seg["end_ms"],
                seg["text"],
                i["max_chars_per_cue"],
            )
            out: dict[str, Any] = {
                "cues": [
                    {"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text} for c in built.cues
                ]
            }
            if built.warnings:
                out["warnings"] = list(built.warnings)
            return out
        case "SrtValidator.validate":
            return {"errors": SrtValidator.validate(_cue_dicts(i["cues"]), i["video_duration_ms"])}
        case "Ebur128Parser.parse":
            return Ebur128Parser.parse(i["stderr"])
        case "BlackdetectParser.parse":
            return {
                "detections": [
                    {"start_ms": a, "end_ms": b} for a, b in BlackdetectParser.parse(i["stderr"])
                ]
            }
        case "SilencedetectParser.parse":
            return {
                "runs": [
                    {"start_ms": a, "end_ms": b}
                    for a, b in SilencedetectParser.parse(i["stderr"], i["stream_end_ms"])
                ]
            }
        case "FreezedetectParser.parse":
            return {
                "detections": [
                    {"start_ms": a, "end_ms": b}
                    for a, b in FreezedetectParser.parse(i["stderr"], i.get("stream_end_ms"))
                ]
            }
        case "GateAggregator.decide":
            results = [
                CheckResult(
                    r["check_id"],
                    r["verdict"],
                    r["blocking"],
                    gate=r.get("gate", True),
                    remedy_stage_id=r.get("remedy_stage_id"),
                )
                for r in i["results"]
            ]
            gate = GateAggregator.decide(results, i["profile_check_ids"])
            out = {
                "gate_verdict": str(gate.gate_verdict),
                "failed_checks": [
                    {"check_id": f.check_id, "reason": f.reason} for f in gate.failed_checks
                ],
            }
            if "remedy_stage_ids" in case["expected"]:
                out["remedy_stage_ids"] = list(gate.remedy_stage_ids)
            return out
        case "HeavyWorkGuard.may_start_segment":
            now = LocalTime.parse(i["now_local"]["weekday"], i["now_local"]["time"])
            res = HeavyWorkGuard.may_start_segment(
                now, i["est_segment_ms"], Placement(i["placement"]), i["drain_flag"], _guard_cfg(i)
            )
            return {"allowed": res.allowed, "reason": str(res.reason) if res.reason else None}
        case "SelfDrainTimer.act_by":
            now = LocalTime.parse(i["now_local"]["weekday"], i["now_local"]["time"])
            result = SelfDrainTimer.act_by(now, Placement(i["placement"]), _guard_cfg(i))
            return {"act_by": {"weekday": str(result.weekday), "time": result.hhmm}}
        case "RevealStepBuilder.build":
            steps = RevealStepBuilder.build(
                i["shot"], i["change_events_ms"], i["stills"], i["fps_num"], i["fps_den"]
            )
            return {"steps": [{"k": k, "start_frame": f, "still": s} for k, f, s in steps]}
        case "UpstreamGate.check_render":
            UpstreamGate.check_render(
                timing_basis=i["plan"]["timing_basis"],
                shot_ids=i["plan"]["shot_ids"],
                manifest_entries=i["manifest"]["shots"],
                audio_gate_verdict=i["audio_master"]["gate_verdict"],
                audio_sample_rate_hz=i["audio_master"]["sample_rate_hz"],
                audio_channels=i["audio_master"]["channels"],
                audio_duration_ms=i["audio_master"]["duration_ms"],
                narration_end_ms=i["narration_end_ms"],
                script_sha_equal=i["script_sha_equal"],
                aspect_ratio=i["aspect_ratio"],
            )
            return {}
        case "SubtitleStage.check_timeline_source":
            SubtitleStageCore.check_timeline_source(i["timeline_source"])
            return {}
    return _eval(fn, i)


def _actual_value(actual: Any, key: str) -> Any:
    if isinstance(actual, CheckResult):
        value = actual.value_of(key)
        return str(value) if key == "verdict" else value
    return actual[key]


def _tolerant(expected: Any, actual: Any) -> bool:
    if isinstance(expected, float) or isinstance(actual, float):
        return Fraction(str(expected)) == Fraction(str(actual))
    return bool(expected == actual)


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_deterministic_core_case(case: dict[str, Any]) -> None:
    expected = case["expected"]
    if "error" in expected:
        with pytest.raises((AmwError, MeasurementUnavailable)) as info:
            _call(case)
        exc = info.value
        if expected["error"] == "MEASUREMENT_UNAVAILABLE":
            assert isinstance(exc, MeasurementUnavailable)
            assert list(exc.missing) == expected["missing"]
        else:
            assert isinstance(exc, AmwError)
            assert exc.code == expected["error"]
            assert violations_of(exc) == expected["violations"]
            assert expected["ffmpeg_calls"] == 0
        return
    first = _call(case)
    for key, want in expected.items():
        got = _actual_value(first, key)
        assert _tolerant(want, got), f"{case['case_id']} {key}: expected {want!r}, got {got!r}"
    second = _call(case)  # T4 determinism
    for key in expected:
        assert _actual_value(first, key) == _actual_value(second, key)


@pytest.mark.unit
def test_dataset_has_all_120_cases() -> None:
    assert len(CASES) == 120
    assert {c["case_id"] for c in CASES} == {f"DC-{n:02d}" for n in range(1, 121)}
