"""9:16 cut with REAL FFmpeg on tiny synthetic inputs (no network, no paid call)."""

import json
import subprocess
from pathlib import Path

import pytest

from amw_core.errors import (
    CorruptedOutputError,
    InputInvalidError,
    MissingDependencyError,
    RenderCrashError,
)
from amw_delivery import vertical
from amw_delivery.testing import PLUMBING_VERTICAL_SPEC
from amw_delivery.vertical import (
    SafeArea,
    VerticalSpec,
    build_filter,
    integrated_lufs,
    make_9x16,
    probe_media,
)
from tests.delivery.support import SRT, make_mp4

pytestmark = pytest.mark.integration

SMALL = PLUMBING_VERTICAL_SPEC.model_copy(
    update={
        "width_px": 216,
        "height_px": 384,
        "safe_area": SafeArea(top_px=20, bottom_px=60, left_px=10, right_px=20),
    }
)


def test_blur_pad_with_subtitles_probes_correctly(tmp_path: Path) -> None:
    src = make_mp4(tmp_path / "in.mp4")
    srt = tmp_path / "s.srt"
    srt.write_text(SRT, encoding="utf-8")
    spec = SMALL.model_copy(update={"loudness_tolerance_lu": 0.5})
    out = make_9x16(src, tmp_path / "o" / "out.mp4", spec, subtitles_srt=srt)
    assert (out.width, out.height) == (216, 384)
    assert out.fps == 25
    assert out.video_codec == "h264"
    assert (out.video_profile or "").lower() == "high"
    assert out.audio_codec == probe_media(src).audio_codec
    assert abs(out.duration_ms - probe_media(src).duration_ms) <= 200
    assert (
        abs(
            integrated_lufs(src, timeout_s=60, nice=10)
            - integrated_lufs(tmp_path / "o" / "out.mp4", timeout_s=60, nice=10)
        )
        < 0.5
    )
    assert not list((tmp_path / "o").glob("*.partial.mp4"))


def test_crop_mode_without_subtitles(tmp_path: Path) -> None:
    src = make_mp4(tmp_path / "in.mp4")
    spec = SMALL.model_copy(update={"mode": "crop", "focus_x": 0.25})
    out = make_9x16(src, tmp_path / "out.mp4", spec)
    assert (out.width, out.height) == (216, 384)


def test_filter_string_uses_safe_area_for_subtitles() -> None:
    f = build_filter(SMALL, subtitles_name="sub.srt")
    assert "MarginV=60" in f
    assert "MarginL=10" in f
    assert "original_size=216x384" in f
    assert "subtitles" not in build_filter(SMALL, subtitles_name=None)
    spec = SMALL.model_copy(
        update={"safe_area": SafeArea(top_px=0, bottom_px=0, left_px=200, right_px=100)}
    )
    with pytest.raises(InputInvalidError):
        build_filter(spec, subtitles_name=None)


def test_missing_input_and_missing_subtitles(tmp_path: Path) -> None:
    with pytest.raises(MissingDependencyError):
        make_9x16(tmp_path / "nope.mp4", tmp_path / "o.mp4", SMALL)
    src = make_mp4(tmp_path / "in.mp4")
    with pytest.raises(MissingDependencyError):
        make_9x16(src, tmp_path / "o.mp4", SMALL, subtitles_srt=tmp_path / "none.srt")


def test_input_without_audio_is_refused(tmp_path: Path) -> None:
    src = make_mp4(tmp_path / "in.mp4", audio=False)
    with pytest.raises(InputInvalidError):
        make_9x16(src, tmp_path / "o.mp4", SMALL)


def test_ffmpeg_failure_is_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "garbage.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(InputInvalidError):
        make_9x16(bad, tmp_path / "o.mp4", SMALL)
    src = make_mp4(tmp_path / "in.mp4")
    real_tool = vertical._tool
    # ffmpeg itself exits non-zero (the former "no_such_preset" case is now refused earlier by the
    # ADR-014 preset allow-list, see test_encode_settings_refusals)
    monkeypatch.setattr(
        vertical, "_tool", lambda name: "false" if name == "ffmpeg" else real_tool(name)
    )
    with pytest.raises(RenderCrashError):
        make_9x16(src, tmp_path / "o.mp4", SMALL)
    assert not (tmp_path / "o.mp4").exists()


def test_verification_failure_removes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = make_mp4(tmp_path / "in.mp4")
    # force a failing check through the loudness tolerance (measurements are faked)
    quiet = SMALL.model_copy(update={"duration_tolerance_ms": 1000, "loudness_tolerance_lu": 0.0})
    calls: list[int] = []

    def fake(path: Path, *, timeout_s: int, nice: int | None) -> float:
        calls.append(1)
        return -20.0 if len(calls) == 1 else -14.0

    monkeypatch.setattr(vertical, "integrated_lufs", fake)
    with pytest.raises(CorruptedOutputError, match="loudness"):
        make_9x16(src, tmp_path / "o.mp4", quiet)
    assert not (tmp_path / "o.mp4").exists()
    assert not list(tmp_path.glob("*.partial.mp4"))


def test_probe_mismatch_is_reported(tmp_path: Path) -> None:
    src = make_mp4(tmp_path / "in.mp4")
    # output of the wrong size relative to the spec: use the source itself as the "output"
    with pytest.raises(CorruptedOutputError) as err:
        vertical._verify(probe_media(src), src, src, SMALL)
    problems = err.value.details["problems"]
    assert any(p.startswith("size") for p in problems)


def test_spec_requires_every_policy_value() -> None:
    with pytest.raises(ValueError, match="Field required"):
        VerticalSpec.model_validate({"width_px": 1080})


@pytest.mark.parametrize(
    ("update", "reason"),
    [
        ({"video_bitrate_bps": None}, "ENCODE_TARGET_REQUIRES_REVIEW"),
        ({"gop_frames": None}, "GOP_REQUIRES_REVIEW"),
        ({"x264_preset": "ultrafast"}, "X264_PRESET_NOT_ALLOWED"),
        ({"x264_preset": "no_such_preset"}, "X264_PRESET_NOT_ALLOWED"),
        ({"video_maxrate_bps": 4_000_000_000}, "VBV_MAXRATE_WITHOUT_BUFSIZE"),
        ({"video_maxrate_bps": 1_000, "video_bufsize_bps": 2_000}, "VBR_MAXRATE_NOT_ABOVE_TARGET"),
    ],
)
def test_encode_settings_refusals(tmp_path: Path, update: dict[str, object], reason: str) -> None:
    """ADR-014 through Agent 10's resolve: no silent default for a missing or odd policy value."""
    src = make_mp4(tmp_path / "in.mp4")
    with pytest.raises(InputInvalidError) as err:
        make_9x16(src, tmp_path / "o.mp4", SMALL.model_copy(update=update))
    assert err.value.details["reason"] == reason
    assert not (tmp_path / "o.mp4").exists()


def test_derived_gop_needs_no_operator_value() -> None:
    thirty = SMALL.model_copy(update={"fps": 30, "gop_frames": None})
    assert vertical.resolve_encode(thirty).gop_frames == 15
    with pytest.raises(InputInvalidError):  # an operator GOP that contradicts "half the rate"
        vertical.resolve_encode(thirty.model_copy(update={"gop_frames": 10}))


def test_output_follows_the_encode_policy(tmp_path: Path) -> None:
    """x264 High, 2 B-frames, CABAC, GOP of half the rate (12 at 25 fps, operator value), VBV."""
    src = make_mp4(tmp_path / "in.mp4", seconds=3)
    spec = SMALL.model_copy(update={"video_maxrate_bps": 12_000_000, "video_bufsize_bps": 16_000_000})
    out = tmp_path / "o.mp4"
    make_9x16(src, out, spec)
    res = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_frames",
         "-select_streams", "v:0", "-show_entries",
         "stream=profile,has_b_frames:frame=pict_type,key_frame", str(out)],  # noqa: S607
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    data = json.loads(res.stdout)
    assert data["streams"][0]["profile"] == "High"
    assert data["streams"][0]["has_b_frames"] >= 1
    types = [f["pict_type"] for f in data["frames"]]
    assert "B" in types
    keys = [i for i, f in enumerate(data["frames"]) if f["key_frame"] == 1]
    assert len(keys) > 1
    assert max(b - a for a, b in zip(keys, keys[1:], strict=False)) <= 12
    assert b"elst" not in out.read_bytes()  # no edit lists (INF-13)
