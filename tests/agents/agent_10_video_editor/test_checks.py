# ruff: noqa: E501
"""One pass and one fail fixture per check of section 20.1 (rows 11-60, A-09) and parser extras."""

from datetime import date
from fractions import Fraction
from typing import Any

import pytest

from agent_10_video_editor.errors import MeasurementUnavailable
from agent_10_video_editor.probe import (
    AtomOrderChecker,
    Ebur128Parser,
    PacketParser,
    ProbeParser,
    SceneParser,
    parse_stream_times,
    seconds_to_ms,
)
from agent_10_video_editor.qc import checks as C  # noqa: N812
from agent_10_video_editor.qc.result import CheckResult
from amw_core.enums import CheckVerdict

R = Fraction(30, 1)
LIC_OK = {"L": {"state": "ACTIVE", "covers_monetized_youtube": True, "expires_in_days": None,
                "third_party_permission": "PERMITTED", "org": "T"}}  # fmt: skip
ELEMENT = {"element_id": "sh01", "asset_id": "a", "start_ms": 0, "end_ms": 1000}
ROW = {
    "asset_id": "a",
    "licence_id": "L",
    "render_id": None,
    "used_from_ms": 0,
    "used_to_ms": 1000,
    "usage_kind": "SHOT",
}
ASSET = {"a": {"status": "ACTIVE", "ai_item": False}}

SEI = {
    "cabac": "1",
    "interlaced": "0",
    "bframes": "2",
    "open_gop": "0",
    "keyint": "15",
    "rc": "abr",
    "bitrate": "8000",
    "_core": "164",
}
SETTINGS: dict[str, Any] = {
    "codec_name": "h264", "profile": "High", "pix_fmt": "yuv420p", "field_order": "progressive",
    "r_frame_rate": R, "level": 40, "has_b_frames": 2, "edit_list": False, "seis": [SEI, SEI],
    "expected_segments": 2, "keyframes": [0, 15, 30, 45], "segment_starts": [0, 30],
    "total_frames": 60, "settings_sha256_recorded": "a" * 64, "settings_sha256_measured": "a" * 64,
    "fps_num": 30, "fps_den": 1, "gop_frames": 15,
    "bframes": 2, "cabac": True, "target_bps": 8_000_000, "maxrate_bps": None, "bufsize_bps": None,
}  # fmt: skip

# (check_id, pass result, fail result, expected fail verdict)
ROWS: list[tuple[str, CheckResult, CheckResult]] = [
    ("qc.video.resolution", C.qc_video_resolution(width=1920, height=1080, min_width=1920, min_height=1080),
     C.qc_video_resolution(width=1280, height=720, min_width=1920, min_height=1080)),
    ("qc.video.codec_profile", C.qc_video_codec_profile(codec_name="h264", profile="High", field_order="progressive"),
     C.qc_video_codec_profile(codec_name="h264", profile="Main", field_order="progressive")),
    ("qc.video.pix_fmt", C.qc_video_pix_fmt(pix_fmt="yuv420p"), C.qc_video_pix_fmt(pix_fmt="yuv444p")),
    ("qc.video.encoder_settings", C.qc_video_encoder_settings(**{**SETTINGS}),
     C.qc_video_encoder_settings(**{**SETTINGS, "profile": "Constrained Baseline"})),
    ("qc.video.cfr", C.CfrAnalyser.evaluate(interval_histogram_s={"0.033333": 10}, fps_num=30, fps_den=1, tolerance_s="0.00001", r_frame_rate=R, avg_frame_rate=R),
     C.CfrAnalyser.evaluate(interval_histogram_s={"0.033333": 10}, fps_num=30, fps_den=1, tolerance_s="0.00001", r_frame_rate=R, avg_frame_rate=Fraction(2997, 100))),
    ("qc.video.fps_matches_project", C.qc_video_fps_matches_project(r_frame_rate=R, fps_num=30, fps_den=1),
     C.qc_video_fps_matches_project(r_frame_rate=Fraction(25), fps_num=30, fps_den=1)),
    ("qc.container.faststart", C.qc_container_faststart(moov_first=True, method_confirmed=True),
     C.qc_container_faststart(moov_first=False, method_confirmed=True)),
    ("qc.audio.codec", C.qc_audio_codec(codec_name="aac", profile="LC"), C.qc_audio_codec(codec_name="mp3", profile=None)),
    ("qc.audio.sample_rate", C.qc_audio_sample_rate(sample_rate_hz=48000), C.qc_audio_sample_rate(sample_rate_hz=44100)),
    ("qc.audio.channels", C.qc_audio_channels(channels=2), C.qc_audio_channels(channels=1)),
    ("qc.audio.bitrate", C.qc_audio_bitrate(nominal_bps=384000, measured_avg_bps=200000, min_bps=384000),
     C.qc_audio_bitrate(nominal_bps=192000, measured_avg_bps=200000, min_bps=384000)),
    ("qc.audio.true_peak", C.qc_audio_true_peak(true_peak_dbtp=-1.2, ceiling_dbtp=-1.0), C.qc_audio_true_peak(true_peak_dbtp=-0.5, ceiling_dbtp=-1.0)),
    ("qc.audio.integrated_lufs", C.qc_audio_integrated_lufs(integrated_lufs=-14.2, target_lufs=-14.0, tolerance_lu=0.5),
     C.qc_audio_integrated_lufs(integrated_lufs=-17.0, target_lufs=-14.0, tolerance_lu=0.5)),
    ("qc.audio.clipping", C.qc_audio_clipping(clipping_samples=0), C.qc_audio_clipping(clipping_samples=3)),
    ("qc.audio.music_bed_offset", C.qc_audio_music_bed_offset(music_lufs=-31.0, narration_lufs=-14.0),
     C.qc_audio_music_bed_offset(music_lufs=-20.0, narration_lufs=-14.0)),
    ("qc.audio.silence_mix", C.qc_audio_silence_mix(runs_ms=[], deliberate_pause_ms=[], total_ms=10_000, max_ms=1000),
     C.qc_audio_silence_mix(runs_ms=[(2000, 4000)], deliberate_pause_ms=[], total_ms=10_000, max_ms=1000)),
    ("qc.video.black_frames", C.qc_video_black_frames(detections_ms=[], deliberate_black_ms=[], total_ms=10_000, calibrated=True),
     C.qc_video_black_frames(detections_ms=[(0, 3000)], deliberate_black_ms=[(0, 3000)], total_ms=10_000, calibrated=True)),
    ("qc.video.freeze", C.qc_video_freeze(detections_ms=[(1000, 4000)], deliberate_hold_ms=[(0, 5000)], total_ms=10_000, calibrated=True),
     C.qc_video_freeze(detections_ms=[(1000, 4000)], deliberate_hold_ms=[], total_ms=10_000, calibrated=True)),
    ("qc.sync.av_container", C.qc_sync_av_container(start_video_s="0", start_audio_s="0.01", duration_video_s="10", duration_audio_s="10", frame_ms=33, tol_start_ms=40, tol_dur_ms=40),
     C.qc_sync_av_container(start_video_s="0", start_audio_s="0.2", duration_video_s="10", duration_audio_s="10", frame_ms=33, tol_start_ms=40, tol_dur_ms=40)),
    ("qc.subtitles.format", C.qc_subtitles_format(errors=[]), C.qc_subtitles_format(errors=["OVERLAP:2"])),
    ("qc.subtitles.languages", C.qc_subtitles_languages(present=["mr"], required=["mr"]), C.qc_subtitles_languages(present=[], required=["mr"])),
    ("qc.subtitles.sync", C.qc_subtitles_sync(segments=[{"segment_id": "s", "start_ms": 0, "end_ms": 1000}], cues=[{"segment_id": "s", "start_ms": 0, "end_ms": 1000}], tol_sub_ms=50, calibrated=True),
     C.qc_subtitles_sync(segments=[{"segment_id": "s", "start_ms": 0, "end_ms": 1000}], cues=[], tol_sub_ms=50, calibrated=True)),
    ("qc.duration.vs_script", C.qc_duration_vs_script(actual_ms=10_000, narration_end_ms=9000, end_screen_ms=1000, tol_dur_ms=100),
     C.qc_duration_vs_script(actual_ms=8000, narration_end_ms=9000, end_screen_ms=1000, tol_dur_ms=100)),
    ("qc.duration.vs_timeline", C.qc_duration_vs_timeline(actual_ms=1000, timeline_frames=30, fps_num=30, fps_den=1),
     C.qc_duration_vs_timeline(actual_ms=2000, timeline_frames=30, fps_num=30, fps_den=1)),
    ("qc.duration.in_bounds", C.qc_duration_in_bounds(actual_ms=5000, targets_ms=(1000, 9000)), C.qc_duration_in_bounds(actual_ms=50, targets_ms=(1000, 9000))),
    ("qc.licence.completeness", C.qc_licence_completeness(tenant="T", render_id="R", elements=[ELEMENT], ledger=[ROW], licences=LIC_OK, assets=ASSET),
     C.qc_licence_completeness(tenant="T", render_id="R", elements=[ELEMENT], ledger=[], licences=LIC_OK, assets=ASSET)),
    ("qc.licence.expiry_window", C.qc_licence_expiry_window(licences=[{"licence_id": "L", "expires_in_days": 400}], warning_window_days=30),
     C.qc_licence_expiry_window(licences=[{"licence_id": "L", "expires_in_days": 0}], warning_window_days=30)),
    ("qc.watermark.provenance", C.qc_watermark_provenance(stock_items=[{"element_id": "sh01", "vendor_item_id": "v1", "licence_state": "ACTIVE", "preview": False}]),
     C.qc_watermark_provenance(stock_items=[{"element_id": "sh01", "vendor_item_id": None, "licence_state": "ACTIVE", "preview": False}])),
    ("qc.visual.tier_share_e", C.qc_visual_tier_share_e(frames_by_tier={"E_AI_STILL": 1, "C_CODE_MOTION": 9}, limit_ratio="0.5"),
     C.qc_visual_tier_share_e(frames_by_tier={"E_AI_STILL": 5, "C_CODE_MOTION": 5}, limit_ratio="0.5")),
    ("qc.visual.ai_video_budget", C.qc_visual_ai_video_budget(ai_video_ms=0, ai_video_limit_ms=None),
     C.qc_visual_ai_video_budget(ai_video_ms=5, ai_video_limit_ms=None)),
    ("qc.visual.ai_disclosure_recorded", C.qc_visual_ai_disclosure_recorded(items=[{"element_id": "sh01", "tier": "D_AI_VIDEO", "is_realistic_synthetic": True, "disclosure_recorded": True}]),
     C.qc_visual_ai_disclosure_recorded(items=[{"element_id": "sh01", "tier": "D_AI_VIDEO", "is_realistic_synthetic": True, "disclosure_recorded": False}])),
    ("qc.visual.chart_data_age", C.qc_visual_chart_data_age(charts=[{"element_id": "sh01", "data_end_date": "2020-01-01"}], lag_days=30, today=date(2020, 6, 1), finance_channel=True),
     C.qc_visual_chart_data_age(charts=[{"element_id": "sh01", "data_end_date": "2020-05-25"}], lag_days=30, today=date(2020, 6, 1), finance_channel=True)),
    ("qc.visual.no_synthetic_presenter", C.qc_visual_no_synthetic_presenter(items=[{"element_id": "sh01", "tier": "C_CODE_MOTION", "depicts_real_person": True}], finance_channel=True),
     C.qc_visual_no_synthetic_presenter(items=[{"element_id": "sh01", "tier": "E_AI_STILL", "depicts_real_person": True}], finance_channel=True)),
    ("edit.hook.window", C.edit_hook_window(hook_end_ms=25_000, first_payoff_ms=20_000, window_ms=30_000),
     C.edit_hook_window(hook_end_ms=35_000, first_payoff_ms=20_000, window_ms=30_000)),
    ("edit.hook.no_brand_intro", C.edit_hook_no_brand_intro(overlays=[], hook_end_ms=1000),
     C.edit_hook_no_brand_intro(overlays=[{"overlay_id": "ov01", "kind": "BRAND_STING", "start_ms": 0}], hook_end_ms=1000)),
    ("edit.visual.cadence", C.edit_visual_cadence(change_events_ms=[2000], explanatory_stretches_ms=[(0, 4000)], max_gap_ms=5000, blocking=True),
     C.edit_visual_cadence(change_events_ms=[], explanatory_stretches_ms=[(0, 9000)], max_gap_ms=5000, blocking=True)),
    ("edit.interrupt.first_dropoff", C.edit_interrupt_first_dropoff(interrupt_times_ms=[40_000], window_ms=(30_000, 60_000)),
     C.edit_interrupt_first_dropoff(interrupt_times_ms=[], window_ms=(30_000, 60_000))),
    ("edit.interrupt.midpoint", C.edit_interrupt_midpoint(interrupt_times_ms=[50_000], total_ms=100_000, half_window_ms=5000),
     C.edit_interrupt_midpoint(interrupt_times_ms=[10_000], total_ms=100_000, half_window_ms=5000)),
    ("edit.cuts.j_l", C.edit_cuts_j_l(jl_count=3, min_count=2), C.edit_cuts_j_l(jl_count=1, min_count=2)),
    ("edit.chapters", C.edit_chapters(chapters_ms=[0, 5000], section_starts_ms=[0, 5200], tolerance_ms=1000),
     C.edit_chapters(chapters_ms=[0, 5000], section_starts_ms=[0], tolerance_ms=1000)),
    ("edit.end_screen", C.edit_end_screen(end_screen_ms=5000, configured_ms=5000), C.edit_end_screen(end_screen_ms=1000, configured_ms=5000)),
    ("edit.dead_air", C.edit_dead_air(runs_ms=[], deliberate_pause_ms=[], total_ms=10_000, max_ms=1000),
     C.edit_dead_air(runs_ms=[(3000, 5000)], deliberate_pause_ms=[], total_ms=10_000, max_ms=1000)),
]  # fmt: skip


@pytest.mark.unit
@pytest.mark.parametrize(("check_id", "ok", "bad"), ROWS, ids=[r[0] for r in ROWS])
def test_each_check_passes_on_its_pass_fixture_and_fails_on_its_fail_fixture(
    check_id: str, ok: CheckResult, bad: CheckResult
) -> None:
    assert ok.check_id == bad.check_id == check_id
    assert ok.verdict is CheckVerdict.PASS, ok
    assert ok.gate
    assert bad.verdict is CheckVerdict.FAIL, bad
    assert bad.blocking
    assert bad.gate
    if check_id not in ("edit.visual.cadence",):
        assert bad.remedy_stage_id is not None


@pytest.mark.unit
def test_unsourced_checks_warn_with_null_threshold_and_never_block() -> None:
    cases: list[CheckResult] = [
        C.qc_container_faststart(moov_first=False),
        C.qc_audio_integrated_lufs(integrated_lufs=-20.0, target_lufs=-14.0, tolerance_lu=None),
        C.qc_audio_silence_mix(runs_ms=[(1, 5000)], deliberate_pause_ms=[], total_ms=9000, max_ms=None),
        C.qc_video_black_frames(detections_ms=[(2000, 5000)], deliberate_black_ms=[], total_ms=9000, calibrated=False),
        C.qc_video_freeze(detections_ms=[(2000, 5000)], deliberate_hold_ms=[], total_ms=9000, calibrated=False),
        C.qc_sync_av_container(start_video_s="0", start_audio_s="1", duration_video_s="9", duration_audio_s="9", frame_ms=33, tol_start_ms=None, tol_dur_ms=None),
        C.qc_subtitles_sync(segments=[{"segment_id": "s", "start_ms": 0, "end_ms": 10}], cues=[], tol_sub_ms=None, calibrated=False),
        C.qc_duration_vs_script(actual_ms=10_000, narration_end_ms=9000, end_screen_ms=0, tol_dur_ms=None),
        C.qc_visual_chart_data_age(charts=[], lag_days=None, today=date(2020, 1, 1), finance_channel=False),
        C.edit_interrupt_first_dropoff(interrupt_times_ms=[], window_ms=None),
        C.edit_cuts_j_l(jl_count=0, min_count=None),
        C.edit_end_screen(end_screen_ms=1, configured_ms=None),
        C.edit_visual_cadence(change_events_ms=[], explanatory_stretches_ms=[(0, 9000)], max_gap_ms=5000, blocking=False),
    ]  # fmt: skip
    for result in cases:
        assert result.verdict is CheckVerdict.WARN, result.check_id
        assert not result.blocking
        assert result.threshold is None


@pytest.mark.unit
def test_skipped_results_never_block_and_judged_parts_are_not_pass() -> None:
    for result in (
        C.qc_audio_music_bed_offset(music_lufs=None, narration_lufs=-14.0),
        C.qc_audio_speech_spans(spans_ms=None),
        C.qc_duration_in_bounds(actual_ms=1, targets_ms=None),
        C.qc_watermark_visual(corner_patch_by_shot=None),
    ):
        assert result.verdict is CheckVerdict.SKIPPED
        assert not result.blocking
    assert C.qc_watermark_visual(corner_patch_by_shot=None).message == "JUDGED_BY_AGENT_16"
    hit = C.qc_watermark_visual(
        corner_patch_by_shot={"sh01": "x", "sh02": "x", "sh03": "x", "sh04": "y"}
    )
    assert hit.verdict is CheckVerdict.WARN
    assert set(hit.offending) == {"sh01", "sh02", "sh03"}
    assert C.qc_watermark_visual(
        corner_patch_by_shot={"sh01": "x", "sh02": "x", "sh03": "x"}, overlay_patches=["x"]
    ).verdict is CheckVerdict.SKIPPED  # fmt: skip


@pytest.mark.unit
def test_process_integrity_checks_have_gate_false() -> None:
    ok = C.a10_q_colour_tags(probed={"primaries": "bt709"}, configured={"primaries": "bt709"})
    bad = C.a10_q_colour_tags(probed={"primaries": None}, configured={"primaries": "bt709"})
    assert (ok.verdict, bad.verdict) == (CheckVerdict.PASS, CheckVerdict.FAIL)
    assert not ok.gate
    assert not bad.gate
    gop_ok = C.a10_q_gop_settings(
        recorded={"closed_gop": True, "idr_at_segment_start": True, "gop_frames": 60},
        configured_gop_frames=60,
    )
    gop_bad = C.a10_q_gop_settings(
        recorded={"closed_gop": False, "idr_at_segment_start": True, "gop_frames": 60},
        configured_gop_frames=60,
    )
    assert (gop_ok.verdict, gop_bad.verdict) == (CheckVerdict.PASS, CheckVerdict.FAIL)


@pytest.mark.unit
def test_licence_edge_cases_non_monetised_unexpired_and_tenant_platform() -> None:
    licences: dict[str, dict[str, Any]] = {"L": {**LIC_OK["L"], "covers_monetized_youtube": None}}
    nm = C.qc_licence_completeness(
        tenant="T",
        render_id="R",
        elements=[ELEMENT],
        ledger=[ROW],
        licences=licences,
        assets=ASSET,
        destination="NON_MONETIZED",
    )
    assert (
        nm.verdict is CheckVerdict.PASS
    )  # unknown monetisation only blocks a monetised destination
    whole = C.qc_licence_completeness(
        tenant="T",
        render_id="R",
        elements=[ELEMENT],
        ledger=[{**ROW, "used_from_ms": None, "used_to_ms": None}],
        licences=LIC_OK,
        assets=ASSET,
    )
    assert (
        whole.verdict is CheckVerdict.PASS
    )  # a whole-render row (fonts, voice) covers the element
    ai = C.qc_licence_completeness(
        tenant="T",
        render_id="R",
        elements=[ELEMENT],
        ledger=[{**ROW, "usage_kind": "AI_OUTPUT"}],
        licences=LIC_OK,
        assets={"a": {"status": "ACTIVE", "ai_item": True}},
    )
    assert ai.verdict is CheckVerdict.PASS


@pytest.mark.unit
def test_probe_parser_reads_ffprobe_json_and_never_defaults() -> None:
    doc: dict[str, Any] = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "profile": "High", "pix_fmt": "yuv420p", "width": 1920, "height": 1080,
             "field_order": "progressive", "r_frame_rate": "30/1", "avg_frame_rate": "30/1", "start_time": "0.0", "duration": "8.0",
             "color_primaries": "bt709", "color_transfer": "bt709", "color_space": "bt709", "color_range": "tv"},
            {"codec_type": "audio", "codec_name": "aac", "profile": "LC", "sample_rate": "48000", "channels": 2, "bit_rate": "240000"},
        ],
        "format": {"duration": "8.000", "size": "20000000", "format_name": "mov,mp4"},
    }  # fmt: skip
    import json

    probe = ProbeParser.parse(json.dumps(doc))
    assert probe.duration_ms == 8000
    assert probe.video.r_frame_rate == Fraction(30)
    assert (
        probe.video_bitrate_bps == 20_000_000 * 8 * 1000 // 8000 - 240000
    )  # size*8/duration minus audio
    assert probe.video.colour["primaries"] == "bt709"
    for broken in (
        "not json",
        json.dumps({"streams": [], "format": {}}),
        json.dumps({"streams": [{"codec_type": "audio"}], "format": {"duration": "1"}}),
    ):
        with pytest.raises(MeasurementUnavailable):
            ProbeParser.parse(broken)
    del doc["format"]["size"]
    with pytest.raises(MeasurementUnavailable):
        ProbeParser.parse(json.dumps(doc)).video_bitrate_bps  # noqa: B018 - no bit_rate, no size
    with pytest.raises(MeasurementUnavailable):
        ProbeParser.parse_frame_count("{}")
    with pytest.raises(MeasurementUnavailable):
        ProbeParser.parse_first_frame_idr("{}")
    assert ProbeParser.parse_first_frame_idr(
        json.dumps({"frames": [{"key_frame": 1, "pict_type": "I"}]})
    )
    assert not ProbeParser.parse_first_frame_idr(
        json.dumps({"frames": [{"key_frame": 0, "pict_type": "P"}]})
    )


@pytest.mark.unit
def test_misc_parsers() -> None:
    assert seconds_to_ms("0.0005") == 1
    assert seconds_to_ms("1.2345") == 1235
    with pytest.raises(MeasurementUnavailable):
        seconds_to_ms("abc")
    assert Ebur128Parser.parse_series(
        "t: 0.1 M: -20 S: -19 I: -14.1 LUFS\nt: 1.2 M: -20 S: -19 I: -14.0 LUFS\nt: 1.3 M: -1 S: -1 I: -9.0 LUFS"
    ) == [(0, -14.1), (1, -14.0)]
    assert SceneParser.parse(
        "[Parsed_showinfo_1 @ 0x1] n: 0 pts: 1 pts_time:2.5 duration: 1\n"
    ) == [2500]
    assert PacketParser.count("0.0\n0.033\nN/A\n") == 2
    with pytest.raises(MeasurementUnavailable):
        PacketParser.histogram("0.0\n")
    with pytest.raises(MeasurementUnavailable):
        PacketParser.histogram("x\ny\n")
    with pytest.raises(MeasurementUnavailable):
        parse_stream_times("video,0,1\n")
    assert parse_stream_times("video,0.0,1.0\naudio,0.0,1.0\n")["audio"] == ("0.0", "1.0")


@pytest.mark.unit
def test_atom_order_checker() -> None:
    def box(kind: bytes, size: int) -> bytes:
        return size.to_bytes(4, "big") + kind + b"\0" * (size - 8)

    assert AtomOrderChecker.moov_first(box(b"ftyp", 16) + box(b"moov", 16) + box(b"mdat", 32))
    assert not AtomOrderChecker.moov_first(box(b"ftyp", 16) + box(b"mdat", 32) + box(b"moov", 16))
    with pytest.raises(MeasurementUnavailable):
        AtomOrderChecker.moov_first(b"\0" * 4)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("change", "offending"),
    [
        ({"sei": None}, "x264_sei_missing"),
        ({"sei": {**SEI, "rc": "cbr"}}, "sei.rc"),
        ({"sei": {**SEI, "bitrate": "20000"}}, "sei.bitrate"),
        ({"sei": {**SEI, "bframes": "0"}}, "sei.bframes"),
        ({"sei": {**SEI, "cabac": "0"}}, "sei.cabac"),
        ({"sei": {**SEI, "open_gop": "1"}}, "sei.open_gop"),
        ({"sei": {**SEI, "keyint": "60"}}, "sei.keyint"),
        (
            {
                "sei": {
                    **SEI,
                    "vbv_maxrate": "12000",
                    "vbv_bufsize": "16000",
                    "nal_hrd": "cbr",
                    "filler": "1",
                }
            },
            "sei.filler",
        ),
        ({"sei": {**SEI, "nal_hrd": "cbr"}}, "sei.nal_hrd"),
        ({"sei": {**SEI, "vbv_maxrate": "12000"}}, "sei.vbv_maxrate"),
        ({"r_frame_rate": Fraction(25)}, "fps"),
        ({"pix_fmt": "yuv444p"}, "pix_fmt"),
        ({"seis": [SEI]}, "sei.count"),
        ({"settings_sha256_measured": "b" * 64}, "sei.binding"),
        ({"settings_sha256_recorded": None}, "sei.binding"),
        ({"edit_list": True}, "container.edit_list"),
        ({"edit_list": None}, "container.edit_list_unknown"),
        ({"has_b_frames": 0}, "has_b_frames"),
        ({"keyframes": [0, 30]}, "gop.interval"),
        ({"keyframes": [0, 15, 29, 44]}, "gop.segment_start_not_key"),
        ({"keyframes": [1, 15, 30, 45]}, "gop.first_not_key"),
        ({"keyframes": None}, "gop.keyframes_unknown"),
    ],
)
def test_encoder_settings_fails_on_every_wrong_setting(
    change: dict[str, Any], offending: str
) -> None:
    change = dict(change)
    if "sei" in change:  # the FIRST segment is right, the second one is wrong
        change["seis"] = [SEI, change.pop("sei")]
    result = C.qc_video_encoder_settings(**{**SETTINGS, **change})
    assert result.verdict is CheckVerdict.FAIL
    assert result.blocking
    assert offending in result.offending
    assert result.remedy_stage_id == "s10_render"


@pytest.mark.unit
def test_encoder_settings_with_a_vbv_cap_and_level_reported_only() -> None:
    sei = {**SEI, "vbv_maxrate": "12000", "vbv_bufsize": "16000", "nal_hrd": "none", "filler": "0"}
    result = C.qc_video_encoder_settings(
        **{
            **SETTINGS,
            "seis": [sei, sei],
            "maxrate_bps": 12_000_000,
            "bufsize_bps": 16_000_000,
            "level": 52,
        }
    )
    assert result.verdict is CheckVerdict.PASS
    assert result.details["level"] == 52
    assert result.details["level_threshold"] is None


@pytest.mark.unit
def test_quality_metric_is_report_only_and_never_blocks() -> None:
    kw: dict[str, Any] = {
        "frames_measured": 30,
        "frames_total": 30,
        "vmaf_status": "LIBVMAF_NOT_IN_BUILD",
    }
    unset = C.qc_video_quality_metric(ssim_all="0.971708", min_ssim=None, **kw)
    assert unset.verdict is CheckVerdict.WARN
    assert not unset.blocking
    assert unset.measured == 0.971708
    assert unset.threshold is None
    assert unset.remedy_stage_id is None
    assert unset.details["report_only"] is True
    assert unset.details["threshold_status"] == "UNSET_UNTIL_3B"
    none = C.qc_video_quality_metric(ssim_all=None, min_ssim=None, **{**kw, "frames_measured": 0})
    assert none.verdict is CheckVerdict.WARN
    assert not none.blocking
    assert none.measured is None
    low = C.qc_video_quality_metric(ssim_all="0.900000", min_ssim="0.950000", **kw)
    high = C.qc_video_quality_metric(ssim_all="0.990000", min_ssim="0.950000", **kw)
    assert (low.verdict, low.blocking) == (CheckVerdict.WARN, False)
    assert (high.verdict, high.blocking) == (CheckVerdict.PASS, False)
