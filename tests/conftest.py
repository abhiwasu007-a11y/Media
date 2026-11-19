"""Suite-wide guard: in CI an FFmpeg-related skip is a FAILURE, not a skip.

The real-FFmpeg tests (9:16 encode policy ADR-014, voice master, video editor) carry skipif marks
that are convenient on a laptop. On the GitHub runner (CI=true) the gates job installs FFmpeg, so
a missing binary there is an environment defect that must not hide untested code.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest


def ffmpeg_skip_is_failure(reason: str, ci_value: str) -> bool:
    """True when a skip with this reason must become a failure under this CI env value."""
    in_ci = ci_value.strip().lower() in {"1", "true", "yes"}
    return in_ci and any(word in reason.lower() for word in ("ffmpeg", "ffprobe"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, Any]:
    outcome = yield
    report = outcome.get_result()
    if not report.skipped:
        return
    lr = report.longrepr
    reason = lr[2] if isinstance(lr, tuple) else str(lr)
    if ffmpeg_skip_is_failure(reason, os.environ.get("CI", "")):
        report.outcome = "failed"
        report.longrepr = f"FFmpeg/ffprobe skip is not allowed in CI (install FFmpeg): {reason}"
