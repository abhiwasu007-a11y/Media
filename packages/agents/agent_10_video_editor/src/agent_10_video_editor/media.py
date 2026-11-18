"""Runner helpers: checked runs and the probe service (blueprint 10 sections 4.4, 10)."""

from collections.abc import Callable
from pathlib import Path

from agent_10_video_editor.errors import MeasurementUnavailable
from agent_10_video_editor.ffmpeg import (
    ArgvBuilder,
    FfmpegRunner,
    ProcessResult,
    RunLimits,
    error_for_result,
)
from agent_10_video_editor.probe import PacketParser, ProbeParser, ProbeResult


class StopRequested(Exception):  # noqa: N818 - control flow, not an error
    """The process was terminated on request (drain / self-drain); the caller checkpoints."""

    def __init__(self, result: ProcessResult) -> None:
        super().__init__("process stopped on request")
        self.result = result


def run_checked(
    runner: FfmpegRunner,
    argv: list[str] | tuple[str, ...],
    *,
    cwd: Path,
    limits: RunLimits,
    stop: Callable[[], bool] | None = None,
) -> ProcessResult:
    """Run one process; map an abnormal end to its 07 error; a requested stop raises
    ``StopRequested`` (never an error)."""
    result = runner.run(argv, cwd=cwd, limits=limits, stop=stop)
    if result.killed_by == "SIGTERM":
        raise StopRequested(result)
    error = error_for_result(result)
    if error is not None:
        raise error
    return result


class ProbeService:
    """Runs ffprobe and parses; any failure to measure is ``MeasurementUnavailable``."""

    def __init__(self, runner: FfmpegRunner, argv: ArgvBuilder, cwd: Path) -> None:
        self._runner = runner
        self._argv = argv
        self._cwd = cwd

    def _run(self, argv: list[str]) -> str:
        result = self._runner.run(argv, cwd=self._cwd, limits=RunLimits())
        if result.exit_code != 0:
            raise MeasurementUnavailable(["ffprobe_exit"], f"ffprobe exited {result.exit_code}")
        return result.stdout

    def full(self, name: str) -> ProbeResult:
        return ProbeParser.parse(self._run(self._argv.probe_full(name)))

    def frame_count(self, name: str) -> int:
        return ProbeParser.parse_frame_count(self._run(self._argv.probe_frame_count(name)))

    def first_frame_is_idr(self, name: str) -> bool:
        return ProbeParser.parse_first_frame_idr(self._run(self._argv.probe_first_frame(name)))

    def packets_csv(self, name: str) -> str:
        return self._run(self._argv.probe_packets(name))

    def packet_count(self, name: str) -> int:
        return PacketParser.count(self.packets_csv(name))

    def stream_times_csv(self, name: str) -> str:
        return self._run(self._argv.probe_stream_times(name))

    def readable(self, name: str) -> bool:
        try:
            self._run(self._argv.probe_full(name))
        except MeasurementUnavailable:
            return False
        return True
