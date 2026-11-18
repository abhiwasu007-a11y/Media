"""Injected dependencies of the three stages (wired by the worker; blueprint 10 s4.4)."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent_10_video_editor.config import AgentTenConfig
from agent_10_video_editor.ffmpeg import FfmpegRunner
from agent_10_video_editor.guard import AdmissionProbe, TimerFactory
from agent_10_video_editor.ports import (
    AssetCatalog,
    LicenceReader,
    QcResultRepository,
    RenderRepository,
)
from amw_core.interfaces.audit_log import AuditLog
from amw_core.interfaces.checkpoint_store import CheckpointStore
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostLedger
from amw_core.interfaces.storage import BlobStorage
from amw_core.interfaces.tenancy_context import TenancyContext


@dataclass(frozen=True, slots=True)
class StageDeps:
    cfg: AgentTenConfig
    storage: BlobStorage
    tenancy: TenancyContext
    checkpoints: CheckpointStore
    cost_ledger: CostLedger
    runner: FfmpegRunner
    admission: AdmissionProbe
    timers: TimerFactory
    clock: Clock
    scratch_root: Path
    renders: RenderRepository
    assets: AssetCatalog
    qc_results: QcResultRepository
    licences: LicenceReader
    audit: AuditLog | None = None
    font_reader: Callable[[bytes], frozenset[int]] | None = None
    worker_id: str = "render-worker"
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
