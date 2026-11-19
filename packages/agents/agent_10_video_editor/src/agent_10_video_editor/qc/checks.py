"""Pure check evaluators, one per check of blueprint 10 section 20.1 (F-36).

Each evaluator takes measured values and configuration and returns a ``CheckResult``; nothing
reads files, the clock or the database. Verdict mapping (18 section 7.0.4): a sourced threshold
gives PASS or FAIL with ``blocking = True``; an unsourced one gives the measured value,
``threshold = None``, WARN, ``blocking = False``. A missing measurement never reaches an evaluator
as a default: parsers raise ``MeasurementUnavailable`` first.
"""

import itertools
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any

from agent_10_video_editor.qc.result import (
    REMEDY,
    CheckResult,
    failed,
    passed,
    skipped,
    verdict_by,
    warned,
)
from amw_core.enums import CheckVerdict

Span = Sequence[int]


def _inside(span: Span, containers: Sequence[Span]) -> bool:
    return any(c[0] <= span[0] and span[1] <= c[1] for c in containers)


def _spans(items: Sequence[Span]) -> tuple[tuple[int, int], ...]:
    return tuple((int(s[0]), int(s[1])) for s in items)


# ----------------------------------------------------------------------------- video metadata


def qc_video_resolution(
    *, width: int, height: int, min_width: int, min_height: int, blocking: bool = True
) -> CheckResult:
    ok = width >= min_width and height >= min_height
    return verdict_by(
        "qc.video.resolution",
        ok,
        sourced=blocking,
        measured=f"{width}x{height}",
        threshold=f"{min_width}x{min_height}" if blocking else None,
        unit="px",
    )


def qc_video_codec_profile(
    *, codec_name: str, profile: str | None, field_order: str | None
) -> CheckResult:
    ok = codec_name == "h264" and profile == "High" and field_order in ("progressive", None)
    return verdict_by(
        "qc.video.codec_profile",
        ok,
        measured=f"{codec_name}/{profile}/{field_order}",
        threshold="h264/High/progressive",
    )


def qc_video_pix_fmt(*, pix_fmt: str | None) -> CheckResult:
    return verdict_by(
        "qc.video.pix_fmt", pix_fmt == "yuv420p", measured=pix_fmt, threshold="yuv420p"
    )


def x264_expected(
    *,
    gop_frames: int,
    bframes: int,
    cabac: bool,
    target_bps: int,
    maxrate_bps: int | None,
    bufsize_bps: int | None,
) -> dict[str, str]:
    """The x264 SEI options a delivery encode must carry (ADR-014)."""
    want: dict[str, str] = {
        "cabac": str(int(cabac)),
        "bframes": str(bframes),
        "open_gop": "0",
        "interlaced": "0",
        "keyint": str(gop_frames),
        "rc": "abr",
        "bitrate": str(target_bps // 1000),
    }
    if maxrate_bps is not None and bufsize_bps is not None:
        want["vbv_maxrate"] = str(maxrate_bps // 1000)
        want["vbv_bufsize"] = str(bufsize_bps // 1000)
    return want


def sei_mismatches(sei: Mapping[str, str] | None, want: Mapping[str, str]) -> list[str]:
    """Option names of one segment's x264 SEI that differ from ``want`` (no SEI: missing)."""
    if sei is None:
        return ["x264_sei_missing"]
    bad = [f"sei.{k}" for k, v in want.items() if sei.get(k) != v]
    if "vbv_maxrate" not in want and sei.get("vbv_maxrate", "0") != "0":
        bad.append("sei.vbv_maxrate")
    if sei.get("filler", "0") != "0":
        bad.append("sei.filler")
    if sei.get("nal_hrd", "none") != "none":
        bad.append("sei.nal_hrd")
    return bad


def qc_video_encoder_settings(
    *,
    codec_name: str,
    profile: str | None,
    pix_fmt: str | None,
    field_order: str | None,
    r_frame_rate: Fraction | str,
    level: int | None,
    has_b_frames: int | None,
    edit_list: bool | None,
    seis: Sequence[Mapping[str, str] | None],
    expected_segments: int,
    keyframes: Sequence[int] | None,
    segment_starts: Sequence[int],
    total_frames: int,
    settings_sha256_recorded: str | None,
    settings_sha256_measured: str | None,
    fps_num: int,
    fps_den: int,
    gop_frames: int,
    bframes: int,
    cabac: bool,
    target_bps: int,
    maxrate_bps: int | None,
    bufsize_bps: int | None,
) -> CheckResult:
    """ADR-014 (replaces the measured-bitrate floor): the delivered stream carries the settings
    it was encoded with, in EVERY segment.

    Measured facts of the final file (ffprobe): codec, profile, pix_fmt, scan, frame rate,
    ``has_b_frames``, no MP4 edit list (INF-13), and the GOP structure from the packet keyframe
    flags (frame 0 and every segment start are keyframes; no keyframe interval above the GOP).
    Declared settings: one x264 SEI per segment (count = segments of the render), each with the
    expected rate control, B-frames, CABAC, closed GOP, keyint, VBV and no filler, bound to the
    render by the hash the render recorded of each segment's SEI before the concat. The SEI is
    self-declared by the encoder: rate-control values cannot be measured from the stream, which
    is why the measured facts are checked next to it. Any difference = blocking FAIL. The H.264
    level is reported only (no sourced value; REQUIRES REVIEW)."""
    fps = Fraction(r_frame_rate) if isinstance(r_frame_rate, str) else r_frame_rate
    bad: list[str] = []
    if codec_name != "h264":
        bad.append("codec_name")
    if profile != "High":
        bad.append("profile")
    if pix_fmt != "yuv420p":
        bad.append("pix_fmt")
    if field_order != "progressive":
        bad.append("field_order")
    if fps != Fraction(fps_num, fps_den):
        bad.append("fps")
    if bframes > 0 and (has_b_frames is None or has_b_frames < 1):
        bad.append("has_b_frames")
    if edit_list is None:
        bad.append("container.edit_list_unknown")
    elif edit_list:
        bad.append("container.edit_list")
    if keyframes is None:
        bad.append("gop.keyframes_unknown")
    else:
        keys = sorted(set(keyframes))
        if not keys or keys[0] != 0:
            bad.append("gop.first_not_key")
        if any(start not in set(keys) for start in segment_starts):
            bad.append("gop.segment_start_not_key")
        gaps = [b - a for a, b in itertools.pairwise([*keys, total_frames])]
        if any(gap > gop_frames for gap in gaps):
            bad.append("gop.interval")
    want = x264_expected(
        gop_frames=gop_frames,
        bframes=bframes,
        cabac=cabac,
        target_bps=target_bps,
        maxrate_bps=maxrate_bps,
        bufsize_bps=bufsize_bps,
    )
    if len(seis) != expected_segments:
        bad.append("sei.count")
    per_segment = [sei_mismatches(sei, want) for sei in seis]
    for item in dict.fromkeys(m for ms in per_segment for m in ms):
        bad.append(item)
    if settings_sha256_recorded is None or settings_sha256_measured != settings_sha256_recorded:
        bad.append("sei.binding")
    first = seis[0] if seis else None
    measured = f"{codec_name}/{profile}/{pix_fmt}/{fps.numerator}/{fps.denominator}" + (
        f"/rc={first.get('rc')}/bitrate={first.get('bitrate')}/segments={len(seis)}"
        if first
        else "/no_sei"
    )
    return CheckResult(
        "qc.video.encoder_settings",
        CheckVerdict.PASS if not bad else CheckVerdict.FAIL,
        True,
        measured=measured,
        threshold=f"h264/High/yuv420p/{fps_num}/{fps_den}/rc=abr/bitrate={target_bps // 1000}"
        f"/segments={expected_segments}",
        offending=tuple(bad),
        remedy_stage_id=REMEDY["qc.video.encoder_settings"] if bad else None,
        details={
            "level": level,
            "level_threshold": None,
            "has_b_frames": has_b_frames,
            "edit_list": edit_list,
            "sei_core": first.get("_core") if first else None,
            "expected_sei": want,
            "segments_failing": [i for i, ms in enumerate(per_segment) if ms],
        },
    )


def qc_video_quality_metric(
    *,
    ssim_all: str | None,
    frames_measured: int,
    frames_total: int,
    min_ssim: str | None,
    vmaf_status: str,
) -> CheckResult:
    """ADR-014: SSIM of the delivery encode against its lossless reference. REPORT ONLY in 3A:
    the pass threshold ``qc.video.quality_min_ssim`` is unset until 3B, so the verdict is a
    non-blocking WARN carrying the measured value; it never blocks the gate."""
    details: dict[str, Any] = {
        "report_only": True,
        "metric": "SSIM",
        "ssim_all": ssim_all,
        "frames_measured": frames_measured,
        "frames_total": frames_total,
        "vmaf": None,
        "vmaf_status": vmaf_status,
    }
    if ssim_all is None or frames_measured == 0:
        return warned(
            "qc.video.quality_metric",
            threshold=None,
            remedy_stage_id=None,
            message="NOT_MEASURED: no segment has an SSIM value (report only)",
            details=details,
        )
    measured = float(ssim_all)
    if min_ssim is None:
        return warned(
            "qc.video.quality_metric",
            measured=measured,
            threshold=None,
            remedy_stage_id=None,
            message=f"REPORT_ONLY: SSIM {ssim_all}; threshold unset until 3B (ADR-014)",
            details={**details, "threshold_status": "UNSET_UNTIL_3B"},
        )
    ok = Decimal(ssim_all) >= Decimal(min_ssim)
    return CheckResult(
        "qc.video.quality_metric",
        CheckVerdict.PASS if ok else CheckVerdict.WARN,
        False,
        measured=measured,
        threshold=float(min_ssim),
        message=f"SSIM {ssim_all} vs {min_ssim} (non-blocking until 3B decides)",
        details={**details, "threshold_status": "SET_NON_BLOCKING"},
    )


class CfrAnalyser:
    """F-24: every packet interval within the tick tolerance of ``1/fps`` (DC-81, DC-82)."""

    @staticmethod
    def evaluate(
        *,
        interval_histogram_s: Mapping[str, int],
        fps_num: int,
        fps_den: int,
        tolerance_s: str,
        r_frame_rate: Fraction | None = None,
        avg_frame_rate: Fraction | None = None,
    ) -> CheckResult:
        expected = Decimal(fps_den) / Decimal(fps_num)
        tolerance = Decimal(tolerance_s)
        off = [
            k
            for k, count in interval_histogram_s.items()
            if count > 0 and abs(Decimal(k) - expected) > tolerance
        ]
        rates_equal = (
            r_frame_rate is None or avg_frame_rate is None or r_frame_rate == avg_frame_rate
        )
        ok = not off and rates_equal
        details = {"off_interval_values": off}
        if ok:
            return passed("qc.video.cfr", measured="CFR", details=details)
        return failed("qc.video.cfr", measured=",".join(off) or "r!=avg", details=details)


def qc_video_fps_matches_project(
    *, r_frame_rate: Fraction, fps_num: int, fps_den: int
) -> CheckResult:
    ok = r_frame_rate == Fraction(fps_num, fps_den)
    return verdict_by(
        "qc.video.fps_matches_project",
        ok,
        measured=str(r_frame_rate),
        threshold=f"{fps_num}/{fps_den}",
    )


def qc_container_faststart(*, moov_first: bool, method_confirmed: bool = False) -> CheckResult:
    """WARN until the method is confirmed (18 section 7.1, REQUIRES REVIEW)."""
    return verdict_by(
        "qc.container.faststart",
        moov_first,
        sourced=method_confirmed,
        measured=moov_first,
        threshold="moov before mdat" if method_confirmed else None,
    )


# ----------------------------------------------------------------------------- audio


def qc_audio_codec(*, codec_name: str, profile: str | None) -> CheckResult:
    return verdict_by(
        "qc.audio.codec",
        codec_name == "aac" and profile == "LC",
        measured=f"{codec_name}/{profile}",
        threshold="aac/LC",
    )


def qc_audio_sample_rate(*, sample_rate_hz: int, expected_hz: int = 48000) -> CheckResult:
    return verdict_by(
        "qc.audio.sample_rate",
        sample_rate_hz == expected_hz,
        measured=sample_rate_hz,
        threshold=expected_hz,
        unit="Hz",
    )


def qc_audio_channels(*, channels: int, expected: int = 2) -> CheckResult:
    return verdict_by(
        "qc.audio.channels", channels == expected, measured=channels, threshold=expected
    )


def qc_audio_bitrate(*, nominal_bps: int, measured_avg_bps: int, min_bps: int) -> CheckResult:
    """The configured nominal rate is the gate; the measured stream average is only reported."""
    return verdict_by(
        "qc.audio.bitrate",
        nominal_bps >= min_bps,
        measured=nominal_bps,
        threshold=min_bps,
        unit="bps",
        details={"measured_avg_bps": measured_avg_bps},
    )


def qc_audio_true_peak(*, true_peak_dbtp: float, ceiling_dbtp: float) -> CheckResult:
    ok = Decimal(str(true_peak_dbtp)) <= Decimal(str(ceiling_dbtp))
    return verdict_by(
        "qc.audio.true_peak", ok, measured=true_peak_dbtp, threshold=ceiling_dbtp, unit="dBTP"
    )


def qc_audio_integrated_lufs(
    *, integrated_lufs: float, target_lufs: float, tolerance_lu: float | None
) -> CheckResult:
    if tolerance_lu is None:
        return warned(
            "qc.audio.integrated_lufs", measured=integrated_lufs, threshold=None, unit="LUFS"
        )
    deviation = abs(Decimal(str(integrated_lufs)) - Decimal(str(target_lufs)))
    return verdict_by(
        "qc.audio.integrated_lufs",
        deviation <= Decimal(str(tolerance_lu)),
        measured=integrated_lufs,
        threshold=tolerance_lu,
        unit="LUFS",
    )


def qc_audio_lra_report(*, lra_lu: float) -> CheckResult:
    return passed("qc.audio.lra_report", blocking=False, measured=lra_lu, unit="LU")


def qc_audio_clipping(*, clipping_samples: int | None) -> CheckResult:
    """3A: Agent 07's recorded ``clipping_samples`` for the master is cross-checked."""
    if clipping_samples is None:
        return warned("qc.audio.clipping", measured=None, threshold=None)
    return verdict_by(
        "qc.audio.clipping", clipping_samples == 0, measured=clipping_samples, threshold=0
    )


def qc_audio_music_bed_offset(
    *, music_lufs: float | None, narration_lufs: float, min_db: float = -20.0, max_db: float = -15.0
) -> CheckResult:
    if music_lufs is None:
        return skipped("qc.audio.music_bed_offset", "NO_MUSIC_STEM")
    offset = Decimal(str(music_lufs)) - Decimal(str(narration_lufs))
    ok = Decimal(str(min_db)) <= offset <= Decimal(str(max_db))
    return verdict_by(
        "qc.audio.music_bed_offset",
        ok,
        measured=float(offset),
        threshold=f"{min_db}..{max_db}",
        unit="dB",
        details={"offset_db": float(offset)},
    )


def _silence(
    check_id: str,
    runs_ms: Sequence[Span],
    deliberate_pause_ms: Sequence[Span],
    total_ms: int,
    max_ms: int | None,
) -> CheckResult:
    runs = _spans(runs_ms)
    if max_ms is None:
        return warned(check_id, measured=len(runs), threshold=None, unit="runs")
    pauses = _spans(deliberate_pause_ms)
    offending = tuple(
        r
        for r in runs
        if (r[0] <= 0 or r[1] >= total_ms) or (r[1] - r[0] >= max_ms and not _inside(r, pauses))
    )
    return verdict_by(
        check_id,
        not offending,
        measured=len(runs),
        threshold=max_ms,
        unit="ms",
        offending=offending,
    )


def qc_audio_silence_mix(
    *,
    runs_ms: Sequence[Span],
    deliberate_pause_ms: Sequence[Span],
    total_ms: int,
    max_ms: int | None,
) -> CheckResult:
    return _silence("qc.audio.silence_mix", runs_ms, deliberate_pause_ms, total_ms, max_ms)


def edit_dead_air(
    *,
    runs_ms: Sequence[Span],
    deliberate_pause_ms: Sequence[Span],
    total_ms: int,
    max_ms: int | None,
) -> CheckResult:
    return _silence("edit.dead_air", runs_ms, deliberate_pause_ms, total_ms, max_ms)


def qc_audio_speech_spans(*, spans_ms: Sequence[Span] | None) -> CheckResult:
    if spans_ms is None:
        return skipped("qc.audio.speech_spans", "NO_NARRATION_STEM")
    return passed("qc.audio.speech_spans", blocking=False, measured=len(spans_ms))


# ----------------------------------------------------------------------------- detectors


def _detector(
    check_id: str,
    detections_ms: Sequence[Span],
    allowed_ms: Sequence[Span],
    total_ms: int,
    calibrated: bool,
    *,
    edge_rule: bool,
) -> CheckResult:
    allowed = _spans(allowed_ms)
    offending = tuple(
        d
        for d in _spans(detections_ms)
        if not _inside(d, allowed) or (edge_rule and (d[0] <= 0 or d[1] >= total_ms))
    )
    return verdict_by(
        check_id,
        not offending,
        sourced=calibrated,
        measured=len(detections_ms),
        threshold=0 if calibrated else None,
        unit="runs",
        offending=offending,
    )


def qc_video_black_frames(
    *,
    detections_ms: Sequence[Span],
    deliberate_black_ms: Sequence[Span],
    total_ms: int,
    calibrated: bool,
) -> CheckResult:
    """18 section 7.3: any detection at the first or last frame also fails."""
    return _detector(
        "qc.video.black_frames",
        detections_ms,
        deliberate_black_ms,
        total_ms,
        calibrated,
        edge_rule=True,
    )


def qc_video_freeze(
    *,
    detections_ms: Sequence[Span],
    deliberate_hold_ms: Sequence[Span],
    total_ms: int,
    calibrated: bool,
) -> CheckResult:
    return _detector(
        "qc.video.freeze", detections_ms, deliberate_hold_ms, total_ms, calibrated, edge_rule=False
    )


# ----------------------------------------------------------------------------- sync, duration


def qc_sync_av_container(
    *,
    start_video_s: str,
    start_audio_s: str,
    duration_video_s: str,
    duration_audio_s: str,
    frame_ms: int,
    tol_start_ms: int | None,
    tol_dur_ms: int | None,
) -> CheckResult:
    d_start = abs((Decimal(start_video_s) - Decimal(start_audio_s)) * 1000)
    d_dur = abs((Decimal(duration_video_s) - Decimal(duration_audio_s)) * 1000)
    details = {
        "start_offset_ms": float(d_start),
        "duration_offset_ms": float(d_dur),
        "over_one_frame": bool(d_start > frame_ms or d_dur > frame_ms),
    }
    if tol_start_ms is None or tol_dur_ms is None:
        return warned(
            "qc.sync.av_container",
            measured=float(max(d_start, d_dur)),
            threshold=None,
            unit="ms",
            details=details,
        )
    ok = d_start <= tol_start_ms and d_dur <= tol_dur_ms
    return verdict_by(
        "qc.sync.av_container",
        ok,
        measured=float(max(d_start, d_dur)),
        threshold=max(tol_start_ms, tol_dur_ms),
        unit="ms",
        details=details,
    )


def qc_subtitles_format(*, errors: Sequence[str]) -> CheckResult:
    return verdict_by(
        "qc.subtitles.format",
        not errors,
        measured=len(errors),
        threshold=0,
        details={"errors": list(errors)},
    )


def qc_subtitles_languages(*, present: Sequence[str], required: Sequence[str]) -> CheckResult:
    missing = sorted(set(required) - set(present))
    return verdict_by(
        "qc.subtitles.languages",
        not missing,
        measured=len(present),
        threshold=len(required),
        offending=tuple(missing),
    )


def qc_subtitles_sync(
    *,
    segments: Sequence[Mapping[str, Any]],
    cues: Sequence[Mapping[str, Any]],
    tol_sub_ms: int | None,
    calibrated: bool,
) -> CheckResult:
    """18 section 7.6.2: first cue start, last cue end, interior boundaries strictly inside."""
    tol = tol_sub_ms if tol_sub_ms is not None else 0
    violations: list[str] = []
    for seg in segments:
        sid = str(seg["segment_id"])
        s_start, s_end = int(seg["start_ms"]), int(seg["end_ms"])
        own = sorted((c for c in cues if c["segment_id"] == sid), key=lambda c: int(c["start_ms"]))
        if not own:
            violations.append(f"NO_CUES:{sid}")
            continue
        if abs(int(own[0]["start_ms"]) - s_start) > tol:
            violations.append(f"FIRST_CUE_START:{sid}")
        if abs(int(own[-1]["end_ms"]) - s_end) > tol:
            violations.append(f"LAST_CUE_END:{sid}")
        for a, b in itertools.pairwise(own):
            for boundary in (int(a["end_ms"]), int(b["start_ms"])):
                if not s_start < boundary < s_end:
                    violations.append(f"INTERIOR_BOUNDARY_OUTSIDE:{sid}:{boundary}")
    violations = list(dict.fromkeys(violations))
    return verdict_by(
        "qc.subtitles.sync",
        not violations,
        sourced=calibrated,
        measured=len(violations),
        threshold=tol_sub_ms if calibrated else None,
        unit="ms",
        details={"violations": violations},
    )


def qc_subtitles_accuracy(*, overlap_permille: int) -> CheckResult:
    """Deterministic word overlap with the script; not blocking in 3A (18 section 7.6)."""
    if overlap_permille >= 1000:
        return passed(
            "qc.subtitles.accuracy", blocking=False, measured=overlap_permille, unit="permille"
        )
    return warned(
        "qc.subtitles.accuracy", measured=overlap_permille, threshold=1000, unit="permille"
    )


def qc_duration_vs_script(
    *, actual_ms: int, narration_end_ms: int, end_screen_ms: int, tol_dur_ms: int | None
) -> CheckResult:
    expected = narration_end_ms + end_screen_ms
    details = {"expected_ms": expected}
    if actual_ms < narration_end_ms:
        return failed(
            "qc.duration.vs_script",
            measured=actual_ms,
            threshold=narration_end_ms,
            unit="ms",
            details=details,
        )
    if tol_dur_ms is None:
        return warned(
            "qc.duration.vs_script", measured=actual_ms, threshold=None, unit="ms", details=details
        )
    return verdict_by(
        "qc.duration.vs_script",
        abs(actual_ms - expected) <= tol_dur_ms,
        measured=actual_ms,
        threshold=tol_dur_ms,
        unit="ms",
        details=details,
    )


def qc_duration_vs_timeline(
    *, actual_ms: int, timeline_frames: int, fps_num: int, fps_den: int
) -> CheckResult:
    delta = abs(actual_ms * fps_num - timeline_frames * 1000 * fps_den)
    return verdict_by(
        "qc.duration.vs_timeline",
        delta <= 1000 * fps_den,
        measured=actual_ms,
        threshold=1000 * fps_den,
        unit="frame*1000",
        details={"delta": delta},
    )


def qc_duration_in_bounds(*, actual_ms: int, targets_ms: tuple[int, int] | None) -> CheckResult:
    if targets_ms is None:
        return skipped("qc.duration.in_bounds", "BOUNDS_NOT_SET")
    return verdict_by(
        "qc.duration.in_bounds",
        targets_ms[0] <= actual_ms <= targets_ms[1],
        measured=actual_ms,
        threshold=f"{targets_ms[0]}..{targets_ms[1]}",
        unit="ms",
    )


# ----------------------------------------------------------------------------- licence


def _licence_row_ok(
    row: Mapping[str, Any],
    element: Mapping[str, Any],
    *,
    tenant: str,
    render_id: str,
    licences: Mapping[str, Mapping[str, Any]],
    ai_item: bool,
    destination: str,
) -> bool:
    if row["asset_id"] != element["asset_id"] or row.get("render_id") not in (None, render_id):
        return False
    used_from, used_to = row.get("used_from_ms"), row.get("used_to_ms")
    if used_from is not None and used_from > element["start_ms"]:
        return False
    if used_to is not None and used_to < element["end_ms"]:
        return False
    licence = licences.get(str(row["licence_id"]))
    if licence is None or licence.get("state") != "ACTIVE":
        return False
    if destination == "MONETIZED_YOUTUBE" and licence.get("covers_monetized_youtube") is not True:
        return False
    expires = licence.get("expires_in_days")
    if expires is not None and expires <= 0:
        return False
    if licence.get("third_party_permission") == "UNKNOWN" and licence.get("org") != tenant:
        return False
    return not (ai_item and row.get("usage_kind") != "AI_OUTPUT")


def qc_licence_completeness(
    *,
    tenant: str,
    render_id: str,
    elements: Sequence[Mapping[str, Any]],
    ledger: Sequence[Mapping[str, Any]],
    licences: Mapping[str, Mapping[str, Any]],
    assets: Mapping[str, Mapping[str, Any]],
    destination: str = "MONETIZED_YOUTUBE",
) -> CheckResult:
    """18 sections 2.2, 2.3, 7.9 (CCR-030): every element needs a covering ledger row."""
    offending: list[str] = []
    for element in elements:
        asset_id = element.get("asset_id")
        asset = assets.get(str(asset_id)) if asset_id else None
        if asset_id is None or asset is None or asset.get("status") != "ACTIVE":
            offending.append(str(element["element_id"]))
            continue
        ai_item = bool(asset.get("ai_item"))
        if not any(
            _licence_row_ok(
                row,
                element,
                tenant=tenant,
                render_id=render_id,
                licences=licences,
                ai_item=ai_item,
                destination=destination,
            )
            for row in ledger
        ):
            offending.append(str(element["element_id"]))
    return verdict_by(
        "qc.licence.completeness",
        not offending,
        measured=len(offending),
        threshold=0,
        offending=tuple(offending),
        shot_ids=tuple(o for o in offending if o.startswith("sh")),
    )


def qc_licence_expiry_window(
    *, licences: Sequence[Mapping[str, Any]], warning_window_days: int | None
) -> CheckResult:
    """An expired licence FAILs; one expiring inside the warning window is a WARN."""
    expired = tuple(
        str(x["licence_id"])
        for x in licences
        if x.get("expires_in_days") is not None and x["expires_in_days"] <= 0
    )
    if expired:
        return failed(
            "qc.licence.expiry_window", measured=len(expired), threshold=0, offending=expired
        )
    if warning_window_days is not None:
        soon = tuple(
            str(x["licence_id"])
            for x in licences
            if x.get("expires_in_days") is not None and x["expires_in_days"] <= warning_window_days
        )
        if soon:
            return warned(
                "qc.licence.expiry_window",
                measured=len(soon),
                threshold=warning_window_days,
                offending=soon,
            )
    return passed("qc.licence.expiry_window", measured=0, threshold=0)


def qc_watermark_provenance(*, stock_items: Sequence[Mapping[str, Any]]) -> CheckResult:
    bad = tuple(
        str(i["element_id"])
        for i in stock_items
        if not i.get("vendor_item_id") or i.get("licence_state") != "ACTIVE" or i.get("preview")
    )
    return verdict_by(
        "qc.watermark.provenance", not bad, measured=len(bad), threshold=0, offending=bad
    )


def qc_watermark_visual(
    *,
    corner_patch_by_shot: Mapping[str, str] | None,
    overlay_patches: Sequence[str] = (),
    min_shots: int = 3,
) -> CheckResult:
    """Deterministic fallback of 18 section 7.10; the judged part is Agent 16's (SKIPPED)."""
    if not corner_patch_by_shot:
        return skipped("qc.watermark.visual", "JUDGED_BY_AGENT_16")
    counts: dict[str, list[str]] = {}
    for shot, patch in corner_patch_by_shot.items():
        counts.setdefault(patch, []).append(shot)
    hits = tuple(
        shot
        for patch, shots in counts.items()
        if len(shots) >= min_shots and patch not in overlay_patches
        for shot in shots
    )
    if hits:
        return warned(
            "qc.watermark.visual", measured=len(hits), threshold=None, offending=hits, shot_ids=hits
        )
    return skipped("qc.watermark.visual", "JUDGED_BY_AGENT_16")


# ----------------------------------------------------------------------------- visual sourcing


def _tier_total(frames_by_tier: Mapping[str, int]) -> int:
    return sum(frames_by_tier.values())


def qc_visual_tier_share_e(*, frames_by_tier: Mapping[str, int], limit_ratio: str) -> CheckResult:
    total = _tier_total(frames_by_tier)
    e_frames = frames_by_tier.get("E_AI_STILL", 0)
    permille = e_frames * 1000 // total if total else 0
    ok = total == 0 or Fraction(e_frames, total) < Fraction(limit_ratio)
    return verdict_by(
        "qc.visual.tier_share_e",
        ok,
        measured=permille,
        threshold=int(Fraction(limit_ratio) * 1000),
        unit="permille",
        details={"share_permille": permille},
    )


def qc_visual_tier_mix_report(*, frames_by_tier: Mapping[str, int]) -> CheckResult:
    total = _tier_total(frames_by_tier)
    shares = {tier: (n * 1000 // total if total else 0) for tier, n in frames_by_tier.items()}
    return passed(
        "qc.visual.tier_mix_report",
        blocking=False,
        measured=total,
        unit="frames",
        details={"shares_permille": shares},
    )


def qc_visual_ai_video_budget(*, ai_video_ms: int, ai_video_limit_ms: int | None) -> CheckResult:
    if ai_video_limit_ms is None:
        if ai_video_ms > 0:
            return failed(
                "qc.visual.ai_video_budget",
                measured=ai_video_ms,
                threshold=None,
                unit="ms",
                details={"violations": ["LIMIT_UNSET"]},
            )
        return passed("qc.visual.ai_video_budget", measured=0, threshold=None, unit="ms")
    return verdict_by(
        "qc.visual.ai_video_budget",
        ai_video_ms <= ai_video_limit_ms,
        measured=ai_video_ms,
        threshold=ai_video_limit_ms,
        unit="ms",
    )


def qc_visual_ai_disclosure_recorded(*, items: Sequence[Mapping[str, Any]]) -> CheckResult:
    bad = tuple(
        str(i["element_id"])
        for i in items
        if i.get("tier") in ("D_AI_VIDEO", "E_AI_STILL")
        and i.get("is_realistic_synthetic")
        and not i.get("disclosure_recorded")
    )
    return verdict_by(
        "qc.visual.ai_disclosure_recorded",
        not bad,
        measured=len(bad),
        threshold=0,
        offending=bad,
        shot_ids=tuple(b for b in bad if b.startswith("sh")),
    )


def qc_visual_chart_data_age(
    *, charts: Sequence[Mapping[str, Any]], lag_days: int | None, today: date, finance_channel: bool
) -> CheckResult:
    """FIN-R9: each chart's ``data_end_date`` must be older than the configured lag."""
    if lag_days is None:
        if finance_channel and charts:
            # FIN-R9 / IN-02: an unset lag on a finance channel is a blocking FAIL, not a WARN
            return failed(
                "qc.visual.chart_data_age",
                measured=len(charts),
                threshold=None,
                unit="days",
                offending=tuple(str(c["element_id"]) for c in charts),
                shot_ids=tuple(str(c["element_id"]) for c in charts),
                message="PRICE_DATA_LAG_UNSET",
                details={"rule_id": "FIN-R9"},
            )
        if finance_channel:
            return passed(
                "qc.visual.chart_data_age",
                measured=0,
                threshold=None,
                details={"rule_id": "FIN-R9"},
            )
        return warned("qc.visual.chart_data_age", measured=len(charts), threshold=None)
    bad = tuple(
        str(c["element_id"])
        for c in charts
        if c.get("data_end_date") is None
        or (today - date.fromisoformat(str(c["data_end_date"]))).days <= lag_days
    )
    ok = not bad
    if not finance_channel:
        return (
            passed(
                "qc.visual.chart_data_age", blocking=False, measured=len(bad), threshold=lag_days
            )
            if ok
            else warned(
                "qc.visual.chart_data_age", measured=len(bad), threshold=lag_days, offending=bad
            )
        )
    return verdict_by(
        "qc.visual.chart_data_age",
        ok,
        measured=len(bad),
        threshold=lag_days,
        unit="days",
        offending=bad,
        shot_ids=tuple(b for b in bad if b.startswith("sh")),
        details={"rule_id": "FIN-R9"},
    )


def qc_visual_no_synthetic_presenter(
    *, items: Sequence[Mapping[str, Any]], finance_channel: bool
) -> CheckResult:
    bad = tuple(
        str(i["element_id"])
        for i in items
        if i.get("tier") in ("D_AI_VIDEO", "E_AI_STILL") and i.get("depicts_real_person")
    )
    if not finance_channel:
        return passed("qc.visual.no_synthetic_presenter", blocking=False, measured=len(bad))
    return verdict_by(
        "qc.visual.no_synthetic_presenter",
        not bad,
        measured=len(bad),
        threshold=0,
        offending=bad,
        details={"rule_id": "FIN-R11"},
    )


# ----------------------------------------------------------------------------- edit rules


def edit_hook_window(*, hook_end_ms: int, first_payoff_ms: int, window_ms: int) -> CheckResult:
    ok = hook_end_ms <= window_ms and first_payoff_ms <= window_ms
    return verdict_by(
        "edit.hook.window",
        ok,
        measured=max(hook_end_ms, first_payoff_ms),
        threshold=window_ms,
        unit="ms",
    )


def edit_hook_no_brand_intro(
    *, overlays: Sequence[Mapping[str, Any]], hook_end_ms: int
) -> CheckResult:
    bad = tuple(
        str(o["overlay_id"])
        for o in overlays
        if o["kind"] == "BRAND_STING" and int(o["start_ms"]) < hook_end_ms
    )
    return verdict_by(
        "edit.hook.no_brand_intro", not bad, measured=len(bad), threshold=0, offending=bad
    )


def edit_visual_cadence(
    *,
    change_events_ms: Sequence[int],
    explanatory_stretches_ms: Sequence[Span],
    max_gap_ms: int,
    blocking: bool,
) -> CheckResult:
    """The gap between change events in every explanatory stretch (stretch ends count)."""
    violations: list[tuple[int, int]] = []
    for stretch in _spans(explanatory_stretches_ms):
        points = [
            stretch[0],
            *sorted(e for e in change_events_ms if stretch[0] < e < stretch[1]),
            stretch[1],
        ]
        violations.extend((a, b) for a, b in itertools.pairwise(points) if b - a > max_gap_ms)
    details = {"violations": [list(v) for v in violations]}
    if not violations:
        return passed(
            "edit.visual.cadence",
            blocking=blocking,
            measured=0,
            threshold=max_gap_ms,
            unit="ms",
            details=details,
        )
    if blocking:
        return failed(
            "edit.visual.cadence",
            measured=len(violations),
            threshold=max_gap_ms,
            unit="ms",
            details=details,
        )
    return warned(
        "edit.visual.cadence", measured=len(violations), threshold=None, unit="ms", details=details
    )


def edit_visual_cadence_render_crosscheck(
    *, timeline_events: int, scene_events: int, tolerance: str
) -> CheckResult:
    denominator = max(timeline_events, scene_events, 1)
    ratio = Fraction(abs(timeline_events - scene_events), denominator)
    ok = ratio <= Fraction(tolerance)
    base = {"measured": float(ratio), "threshold": float(Fraction(tolerance))}
    if ok:
        return passed("edit.visual.cadence_render_crosscheck", blocking=False, **base)
    return warned("edit.visual.cadence_render_crosscheck", **base)


def _optional_window(
    check_id: str, hits: int, configured: bool, *, unit: str = "events"
) -> CheckResult:
    if not configured:
        return warned(check_id, measured=hits, threshold=None, unit=unit)
    return verdict_by(check_id, hits >= 1, measured=hits, threshold=1, unit=unit)


def edit_interrupt_first_dropoff(
    *, interrupt_times_ms: Sequence[int], window_ms: tuple[int, int] | None
) -> CheckResult:
    hits = (
        0
        if window_ms is None
        else sum(1 for t in interrupt_times_ms if window_ms[0] <= t <= window_ms[1])
    )
    return _optional_window("edit.interrupt.first_dropoff", hits, window_ms is not None)


def edit_interrupt_midpoint(
    *, interrupt_times_ms: Sequence[int], total_ms: int, half_window_ms: int | None
) -> CheckResult:
    centre = total_ms // 2
    hits = (
        0
        if half_window_ms is None
        else sum(1 for t in interrupt_times_ms if abs(t - centre) <= half_window_ms)
    )
    return _optional_window("edit.interrupt.midpoint", hits, half_window_ms is not None)


def edit_cuts_j_l(*, jl_count: int, min_count: int | None) -> CheckResult:
    if min_count is None:
        return warned("edit.cuts.j_l", measured=jl_count, threshold=None, unit="cuts")
    return verdict_by(
        "edit.cuts.j_l", jl_count >= min_count, measured=jl_count, threshold=min_count, unit="cuts"
    )


#: ``section_id`` of the hook scenes (agent_05 section 8.3, CCR-202): reserved, never a section.
HOOK_SECTION_ID = "hook"


def section_starts_ms(shots: Iterable[tuple[str | None, int]]) -> list[int]:
    """Chapter starts the plan implies (18 ``edit.chapters``, CCR-202).

    ``shots`` are ``(section_id, start_ms)`` in plan order. Only real sections count (the reserved
    ``hook`` id and ``None`` do not); the first section starts at 0 by definition (its chapter
    covers the lead-in), every later section starts at its first shot.
    """
    starts: list[int] = []
    seen: set[str] = set()
    for section_id, start_ms in shots:
        if section_id is None or section_id == HOOK_SECTION_ID or section_id in seen:
            continue
        seen.add(section_id)
        starts.append(0 if not starts else start_ms)
    return starts


def edit_chapters(
    *, chapters_ms: Sequence[int], section_starts_ms: Sequence[int], tolerance_ms: int
) -> CheckResult:
    errors: list[str] = []
    if chapters_ms and chapters_ms[0] != 0:
        errors.append("FIRST_NOT_ZERO")
    if any(b <= a for a, b in itertools.pairwise(chapters_ms)):
        errors.append("NOT_INCREASING")
    if len(chapters_ms) != len(section_starts_ms):
        errors.append("COUNT_MISMATCH")
    errors.extend(
        f"START_MISMATCH:{c}"
        for c, s in zip(chapters_ms, section_starts_ms, strict=False)
        if abs(c - s) > tolerance_ms
    )
    return verdict_by(
        "edit.chapters",
        not errors,
        measured=len(errors),
        threshold=tolerance_ms,
        unit="ms",
        details={"errors": errors},
    )


def edit_end_screen(
    *, end_screen_ms: int | None, configured_ms: int | None, other_content: bool = False
) -> CheckResult:
    if configured_ms is None:
        return warned("edit.end_screen", measured=end_screen_ms, threshold=None, unit="ms")
    ok = end_screen_ms == configured_ms and not other_content
    return verdict_by(
        "edit.end_screen", ok, measured=end_screen_ms, threshold=configured_ms, unit="ms"
    )


# ----------------------------------------------------------------------------- process checks


def a10_q_colour_tags(
    *, probed: Mapping[str, str | None], configured: Mapping[str, str]
) -> CheckResult:
    bad = tuple(k for k, v in configured.items() if probed.get(k) != v)
    return CheckResult(
        "a10.q.colour_tags",
        CheckVerdict.PASS if not bad else CheckVerdict.FAIL,
        True,
        gate=False,
        measured=len(bad),
        threshold=0,
        offending=bad,
    )


def a10_q_gop_settings(*, recorded: Mapping[str, Any], configured_gop_frames: int) -> CheckResult:
    ok = (
        recorded.get("closed_gop") is True
        and recorded.get("idr_at_segment_start") is True
        and recorded.get("gop_frames") == configured_gop_frames
    )
    return CheckResult(
        "a10.q.gop_settings",
        CheckVerdict.PASS if ok else CheckVerdict.FAIL,
        True,
        gate=False,
        measured=recorded.get("gop_frames"),
        threshold=configured_gop_frames,
    )
