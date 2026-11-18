"""Evidence pack: sampled frames, contact sheet, loudness series, report, and the single evidence
manifest ``agent_10.evidence_manifest`` for Agent 16 (blueprint 10 section 8.3a; F-39).

Agent 10 writes data and sample images only. The manifest is written LAST, after every frame blob,
so that its hashes exist; it carries IDs, hashes, numbers and enums only (no text).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_10_video_editor.canonical import canonical_json
from agent_10_video_editor.config import AgentTenConfig
from agent_10_video_editor.contracts import (
    BlobRef,
    EvidenceFrame,
    EvidenceManifest,
    EvidenceOverlay,
)
from agent_10_video_editor.errors import config_invalid
from agent_10_video_editor.ffmpeg import ArgvBuilder, FfmpegRunner, RunLimits
from agent_10_video_editor.frames import FrameQuantiser
from agent_10_video_editor.media import run_checked
from agent_10_video_editor.probe import Ebur128Parser
from agent_10_video_editor.qc.result import CheckResult
from agent_10_video_editor.scope import TenantScope
from agent_10_video_editor.timeline import END_SCREEN_SHOT_ID, Timeline

MAX_FRAMES = 999


def sample_frame_indices(total_frames: int, duration_ms: int, per_min: int) -> list[int]:
    """``floor(k * total_frames / n)`` for ``k`` in ``0..n-1``; ``n = ceil(per_min * minutes)``."""
    n = max(1, -(-per_min * duration_ms // 60_000))
    if n > MAX_FRAMES:
        raise config_invalid("CONFIG_KEY:agent_10.qc.sample_frames_per_min")
    n = min(n, total_frames)
    return [k * total_frames // n for k in range(n)]


def shot_at_frame(timeline: Timeline, frame_index: int) -> str | None:
    """The shot of ``$T`` containing the frame; ``None`` in a hold or the end screen."""
    for shot in timeline.shots:
        if shot.start_frame <= frame_index < shot.end_frame:
            return None if shot.shot_id == END_SCREEN_SHOT_ID else shot.shot_id
    return None


@dataclass(frozen=True, slots=True)
class EvidenceRefs:
    manifest: BlobRef
    contact_sheet: BlobRef
    frames: tuple[BlobRef, ...]
    loudness_series: BlobRef
    report: BlobRef
    manifest_model: EvidenceManifest


def _seek_ms(frame_index: int, timeline: Timeline) -> int:
    """Mid-frame time: seeks land on the frame itself, not its neighbour."""
    return FrameQuantiser.frames_to_ms(2 * frame_index + 1, 2 * timeline.fps.num, timeline.fps.den)


class EvidenceWriter:
    def __init__(
        self, runner: FfmpegRunner, argv: ArgvBuilder, scope: TenantScope, cfg: AgentTenConfig
    ) -> None:
        self._runner = runner
        self._argv = argv
        self._scope = scope
        self._cfg = cfg

    def extract_frames(
        self, final_name: str, timeline: Timeline, duration_ms: int, work: Path, stop: object = None
    ) -> list[tuple[int, str]]:
        """Sample frames into ``work`` as ``s001.png``...; returns ``(frame_index, file name)``."""
        indices = sample_frame_indices(
            timeline.total_frames, duration_ms, self._cfg.qc.sample_frames_per_min
        )
        out: list[tuple[int, str]] = []
        for number, index in enumerate(indices, start=1):
            name = f"s{number:03d}.png"
            run_checked(
                self._runner,
                self._argv.sample_frame(final_name, _seek_ms(index, timeline), name),
                cwd=work,
                limits=RunLimits(),
            )
            out.append((index, name))
        return out

    def contact_sheet(self, count: int, work: Path) -> str:
        columns = min(count, 6)
        rows = -(-count // columns)
        run_checked(
            self._runner,
            self._argv.contact_sheet("s%03d.png", columns, rows, 320, "sheet.png"),
            cwd=work,
            limits=RunLimits(),
        )
        return "sheet.png"

    def loudness_series(self, final_name: str, work: Path) -> list[tuple[int, float]]:
        result = run_checked(
            self._runner,
            self._argv.ebur128(final_name, framelog="verbose"),
            cwd=work,
            limits=RunLimits(),
        )
        return Ebur128Parser.parse_series(result.stderr)

    def write(
        self,
        *,
        base: str,
        render_id: str,
        render_sha256: str,
        timeline: Timeline,
        timeline_sha256: str,
        frames: Sequence[tuple[int, str]],
        sheet_name: str,
        series: Sequence[tuple[int, float]],
        results: Sequence[CheckResult],
        work: Path,
    ) -> EvidenceRefs:
        """``base`` = ``<job>/tasks/<task>/attempts/<att>/artifacts`` (03 section 8)."""
        entries: list[EvidenceFrame] = []
        frame_refs: list[BlobRef] = []
        for number, (index, name) in enumerate(frames, start=1):
            info = self._scope.put_file(
                self._scope.uri("jobs", f"{base}/frames/f{number:03d}.png"), work / name
            )
            ref = BlobRef(uri=info.uri, sha256=info.sha256)
            frame_refs.append(ref)
            entries.append(
                EvidenceFrame(
                    frame_id=f"f{number:02d}" if number < 100 else f"f{number:03d}",
                    frame_index=index,
                    t_ms=FrameQuantiser.frames_to_ms(index, timeline.fps.num, timeline.fps.den),
                    shot_id=shot_at_frame(timeline, index),
                    uri=info.uri,
                    sha256=info.sha256,
                )
            )
        sheet = self._scope.put_file(
            self._scope.uri("jobs", f"{base}/contact_sheet.png"), work / sheet_name
        )
        series_blob = self._scope.put_bytes(
            self._scope.uri("jobs", f"{base}/loudness_series.json"),
            canonical_json(
                {
                    "unit": "centi_LUFS",
                    "hz": 1,
                    "series": [[s, round(v * 100)] for s, v in series],
                }
            ),
        )
        report = self._scope.put_bytes(
            self._scope.uri("jobs", f"{base}/qc_report.json"),
            json.dumps(
                [
                    {
                        "check_id": r.check_id,
                        "verdict": str(r.verdict),
                        "blocking": r.blocking,
                        "measured": r.measured,
                        "threshold": r.threshold,
                        "unit": r.unit,
                        "offending": [str(o) for o in r.offending],
                        "remedy_stage_id": r.remedy_stage_id,
                    }
                    for r in results
                ],
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode(),
        )
        manifest = EvidenceManifest(
            render_id=render_id,
            render_sha256=render_sha256,
            timeline_sha256=timeline_sha256,
            fps_num=timeline.fps.num,
            fps_den=timeline.fps.den,
            total_frames=timeline.total_frames,
            frames=tuple(entries),
            contact_sheet=BlobRef(uri=sheet.uri, sha256=sheet.sha256),
            overlays=tuple(
                EvidenceOverlay(
                    overlay_id=o.overlay_id,
                    kind=o.kind[:32],
                    start_ms=o.plan_start_ms,
                    end_ms=o.plan_end_ms,
                )
                for o in timeline.overlays
            ),
        )
        manifest_blob = self._scope.put_bytes(
            self._scope.uri("jobs", f"{base}/evidence_manifest.json"),
            canonical_json(manifest.model_dump(mode="json")),
        )
        return EvidenceRefs(
            manifest=BlobRef(uri=manifest_blob.uri, sha256=manifest_blob.sha256),
            contact_sheet=BlobRef(uri=sheet.uri, sha256=sheet.sha256),
            frames=tuple(frame_refs),
            loudness_series=BlobRef(uri=series_blob.uri, sha256=series_blob.sha256),
            report=BlobRef(uri=report.uri, sha256=report.sha256),
            manifest_model=manifest,
        )


__all__ = ["EvidenceRefs", "EvidenceWriter", "sample_frame_indices", "shot_at_frame"]
