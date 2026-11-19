"""Readiness probe (blueprint 10 section 24.3, F-46): a worker that fails it does not claim.

Passes when the configuration and calendar are complete, ``ffmpeg`` and ``ffprobe`` run, the build
ID equals the pinned one, every required filter exists, the scratch directory is writable and the
QC self-test record for this build exists and passed. Each check reports an identifier-like detail
only (no paths, no tool text).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_10_video_editor.config import AgentTenConfig, Placement
from agent_10_video_editor.ffmpeg import ArgvBuilder, FfmpegRunner, RunLimits, ffmpeg_build_id
from agent_10_video_editor.guard import AdmissionProbe
from agent_10_video_editor.qc.stage import SelfTestProvider

REQUIRED_FILTERS = (
    "blackdetect", "freezedetect", "silencedetect", "ebur128", "select", "showinfo", "tile",
    "drawtext", "concat", "overlay", "scale", "apad", "split", "ssim",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    checks: tuple[ReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.checks if not c.ok)


def _check(name: str, ok: bool, detail: str = "") -> ReadinessCheck:
    return ReadinessCheck(name, ok, "" if ok else detail)


class ReadinessProbe:
    def __init__(
        self,
        *,
        runner: FfmpegRunner,
        cfg: AgentTenConfig,
        scratch_root: Path,
        selftests: SelfTestProvider,
        admission: AdmissionProbe,
        pinned_build_id: str | None,
        required_filters: Sequence[str] = REQUIRED_FILTERS,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
    ) -> None:
        self._runner, self._cfg, self._scratch = runner, cfg, scratch_root
        self._selftests, self._admission = selftests, admission
        self._pinned, self._filters = pinned_build_id, tuple(required_filters)
        self._argv = ArgvBuilder(cfg.render, ffmpeg_bin, ffprobe_bin)

    def run(self) -> ReadinessReport:
        checks: list[ReadinessCheck] = []
        add = checks.append
        guard = self._cfg.guard
        add(_check("calendar", bool(guard.market_windows), "NO_MARKET_CALENDAR"))
        try:
            placement = self._admission.placement()
            now = self._admission.now_local()
            add(_check("admission_probe", True, now.weekday.value))
        except Exception:
            placement = Placement.DEV
            add(_check("admission_probe", False, "PROBE_FAILED"))
        if placement is Placement.VPS:
            add(_check("vps_eta", self._cfg.render.eta_ms_per_output_s is not None, "ETA_NOT_SET"))
            add(_check("night_window", guard.night_window is not None, "NO_NIGHT_WINDOW"))
        try:
            self._scratch.mkdir(parents=True, exist_ok=True)
            marker = self._scratch / ".ready"
            marker.write_text("x")
            marker.unlink()
            add(_check("scratch_writable", True))
        except OSError:
            add(_check("scratch_writable", False, "SCRATCH_NOT_WRITABLE"))
        work = self._scratch
        build = ""
        try:
            version = self._runner.run(self._argv.version(), cwd=work, limits=RunLimits())
            build = ffmpeg_build_id(version.stdout)
            add(_check("ffmpeg_present", version.exit_code == 0 and bool(build), "FFMPEG_MISSING"))
            probe_version = self._runner.run(
                [self._argv.ffprobe_bin, "-version"], cwd=work, limits=RunLimits()
            )
            add(_check("ffprobe_present", probe_version.exit_code == 0, "FFPROBE_MISSING"))
        except OSError, FileNotFoundError:
            add(_check("ffmpeg_present", False, "FFMPEG_MISSING"))
        add(
            _check(
                "build_pinned",
                self._pinned is not None and build == self._pinned,
                "BUILD_NOT_PINNED",
            )
        )
        try:
            listing = self._runner.run(
                [self._argv.ffmpeg_bin, "-hide_banner", "-filters"], cwd=work, limits=RunLimits()
            )
            present = set(re.findall(r"^\s*[T.][S.][C.]\s+(\S+)\s", listing.stdout, flags=re.M))
            missing = [f for f in self._filters if f not in present]
            add(_check("filters", not missing, ",".join(missing)[:128]))
        except OSError, FileNotFoundError:
            add(_check("filters", False, "FILTERS_UNKNOWN"))
        try:
            record = self._selftests.record_for(build)
            add(_check("selftest", record.passed, "SELFTEST_FAILED"))
        except Exception:
            add(_check("selftest", False, "SELFTEST_UNAVAILABLE"))
        return ReadinessReport(tuple(checks))
