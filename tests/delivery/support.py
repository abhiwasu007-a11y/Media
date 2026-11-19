"""Builders for the delivery tests: real FFmpeg on tiny synthetic media, in-memory storage."""

import shutil
import subprocess
from pathlib import Path

from amw_core import ids
from amw_core.cost.report import CostStageReport, StageRow
from amw_core.enums import ComplianceVerdict
from amw_core.interfaces.tenancy_context import TenantContext
from amw_delivery.models import (
    ArtefactRef,
    BundleInputs,
    BundleLimits,
    ComplianceInfo,
    DisclaimerInfo,
    GateRow,
    QcCheckRow,
    ScoreRow,
    SubtitleFile,
    ThumbnailOption,
)
from amw_delivery.testing import MemoryBlobStorage, sha256_hex

BANNER = "PLUMBING TEST - NOT QUALITY"
SRT = (
    "1\n00:00:00,000 --> 00:00:01,500\nHello world\n\n"
    "2\n00:00:01,500 --> 00:00:03,000\nSecond line\n"
)


OPAQUE_MP4 = bytes(range(256)) * 64
"""16 KiB of fixed bytes standing in for a video file where nothing decodes it."""
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def make_mp4(path: Path, *, seconds: int = 2, size: str = "320x180", audio: bool = True) -> Path:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i"]
    cmd += [f"testsrc=size={size}:rate=25:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "64k", "-ac", "2"]
    cmd += [str(path)]
    subprocess.run(["nice", "-n", "10", *cmd], check=True, capture_output=True, timeout=120)  # noqa: S603, S607
    return path


def cost_report(job_id: str) -> CostStageReport:
    row = StageRow(
        stage="s05_script", task_type="agent_05.script_draft", provider="fake_llm",
        model="fake-model", calls=2, tokens_in=100, tokens_out=50, tokens_cached_in=0,
        units={"CHARACTERS": "400"}, cost_micros=1234, cost_minor=0, currency="USD",
        figure_kind="ESTIMATE", share_of_total="100.0%", revision_loops=0, wasted_cost_micros=0,
    )  # fmt: skip
    return CostStageReport(
        job_id=job_id, production_type_key="CHANNEL_LONG_FORM", production_type_version="2",
        topic_ref=None, query_scope=f"cost_ledger WHERE job_id = {job_id}",
        figure_kind_summary="ESTIMATE", price_refs={}, generated_at="2026-11-19T00:00:00Z",
        run_mode="development", currency="USD", rows=[row], total_micros=1234, total_minor=0,
        terms_micros={"LLM": 1234}, allocated=[], human_review_minutes=0, budgets=[],
        header_budget={"per_video_limit_minor": 500, "pilot_limit_minor": 5000,
                       "pilot_committed_micros": 1234, "pilot_remaining_micros": 4998766},
    )  # fmt: skip


class World:
    """One tenant with stored artefacts; ``inputs()`` builds a valid ``BundleInputs``."""

    def __init__(self, tmp: Path, *, shorts: bool = False) -> None:
        self.org = ids.ORG.new()
        self.job = ids.JOB.new()
        self.context = TenantContext(self.org, ids.ActorRef("sys_operator"))
        self.storage = MemoryBlobStorage(chunk=4096)
        self.tmp = tmp
        self.shorts = shorts
        # The bundle never decodes the videos (it copies bytes and checks SHA-256 and size), so
        # opaque deterministic bytes keep these tests independent of an FFmpeg install; the real
        # FFmpeg path is covered by test_vertical.
        self.video = OPAQUE_MP4 + b"master"
        self.vertical = OPAQUE_MP4 + b"vertical" if shorts else b""

    def put(self, name: str, data: bytes, owner: str | None = None) -> ArtefactRef:
        uri = f"amw-blob://{owner or self.org}/jobs/{self.job}/{name}"
        self.storage.blobs[uri] = data
        self.storage._recorded[uri] = sha256_hex(data)
        return ArtefactRef(uri=uri, sha256=sha256_hex(data), size_bytes=len(data))

    def inputs(self, **over: object) -> BundleInputs:
        video = self.put("renders/master.mp4", self.video)
        data: dict[str, object] = {
            "org_id": self.org,
            "job_id": self.job,
            "production_type_key": "CHANNEL_LONG_FORM",
            "production_type_version": "2",
            "config_version": "cfg-1",
            "metadata_present": True,
            "banner": BANNER,
            "disclaimer": DisclaimerInfo(
                text="This video is general information, not investment advice.",
                version="d-0.1", status_label="DRAFT - not lawyer-approved",
            ),
            "disclosure_note": "Altered or synthetic content: the owner sets the label by hand.",
            "video_16x9": video,
            "video_9x16": self.put("renders/vert.mp4", self.vertical) if self.shorts else None,
            "shorts_wanted": self.shorts,
            "thumbnails": tuple(
                ThumbnailOption(
                    option_id=f"v{i}",
                    ref=self.put(f"renders/thumb-v{i}.png", b"\x89PNG" + bytes([i])),
                    media_type="image/png",
                )
                for i in (1, 2, 3)
            ),
            "chosen_thumbnail_id": "v2",
            "subtitles": (
                SubtitleFile(language="en", ref=self.put("renders/subs-en.srt", SRT.encode())),
                SubtitleFile(language="hi", ref=self.put("renders/subs-hi.srt", SRT.encode())),
            ),
            "primary_language": "en",
            "qc_checks": (
                QcCheckRow(check_id="qc.video.resolution", verdict="PASS", measured="1920x1080",
                           threshold=">=1920x1080"),
                QcCheckRow(check_id="qc.audio.loudness", verdict="SKIPPED"),
            ),
            "score_rows": (
                ScoreRow(dimension="AUDIO_QUALITY", source="MACHINE", max_points=10, points=9),
                ScoreRow(dimension="VISUAL_QUALITY", source="MACHINE", max_points=15, points=12),
                ScoreRow(dimension="VISUAL_QUALITY", source="HUMAN", max_points=15, points=10,
                         evidence="owner review"),
            ),
            "gates": (
                GateRow(gate_id="qc.technical", passed=True),
                GateRow(gate_id="quality.threshold", passed=False, remedy="human scores needed"),
            ),
            "compliance": ComplianceInfo(
                verdict=ComplianceVerdict.ALLOWED, authorised_for_delivery=True,
                authorisation_verdict_id="cvd_1", render_sha256=video.sha256,
            ),
            "cost_report": cost_report(self.job),
            "limits": BundleLimits(max_file_bytes=50_000_000, max_total_bytes=100_000_000,
                                   max_thumbnail_bytes=1_000_000),
        }  # fmt: skip
        data.update(over)
        return BundleInputs.model_validate(data)
