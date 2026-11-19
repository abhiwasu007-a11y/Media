"""The CI guard that turns an FFmpeg-related skip into a failure (tests/conftest.py)."""

from __future__ import annotations

import pytest

from tests.conftest import ffmpeg_skip_is_failure

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("ci", ["true", "1", "True"])
def test_ffmpeg_skip_fails_in_ci(ci: str) -> None:
    assert ffmpeg_skip_is_failure("ffmpeg/ffprobe not installed", ci)
    assert ffmpeg_skip_is_failure("real FFmpeg and ffprobe are not installed", ci)


def test_ffmpeg_skip_allowed_outside_ci() -> None:
    assert not ffmpeg_skip_is_failure("ffmpeg not installed", "")
    assert not ffmpeg_skip_is_failure("ffmpeg not installed", "false")


def test_other_skips_untouched_in_ci() -> None:
    assert not ffmpeg_skip_is_failure("needs PostgreSQL", "true")
