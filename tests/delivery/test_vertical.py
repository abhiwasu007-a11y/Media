"""9:16 cut with REAL FFmpeg on tiny synthetic inputs (no network, no paid call)."""

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


def test_ffmpeg_failure_is_typed(tmp_path: Path) -> None:
    bad = tmp_path / "garbage.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(InputInvalidError):
        make_9x16(bad, tmp_path / "o.mp4", SMALL)
    src = make_mp4(tmp_path / "in.mp4")
    broken = SMALL.model_copy(update={"x264_preset": "no_such_preset"})
    with pytest.raises(RenderCrashError):
        make_9x16(src, tmp_path / "o.mp4", broken)
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
