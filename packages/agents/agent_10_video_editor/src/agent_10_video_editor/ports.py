"""Narrow ports for the tables Agent 10 reads and writes (blueprint 10 section 13).

``amw_core`` has no store interface for ``renders``, ``qc_results``, ``assets`` or the licence
ledger yet (core_need); these Protocols are the package's side of that boundary. Every method takes
the tenant transaction, so every DB access goes through ``amw_core.tenancy``; implementations must
also filter by ``tx.context.org_id`` (layer 1 of section 19.1; RLS is layer 2).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agent_10_video_editor.inputs import AssetRecord
from amw_core.enums import CheckVerdict, RenderStatus
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class RenderRow:
    """Columns of ``renders`` (04 section 5.18) that Agent 10 writes."""

    render_id: str
    job_id: str
    kind: str
    preset_key: str
    version: int
    timeline_sha256: str
    width_px: int
    height_px: int
    fps_num: int
    fps_den: int
    video_codec: str
    audio_codec: str
    video_bitrate_bps: int
    audio_bitrate_bps: int
    audio_sample_rate_hz: int
    duration_ms: int
    size_bytes: int
    storage_ref: str
    content_sha256: str
    status: RenderStatus
    worker_id: str | None = None
    script_id: str | None = None
    integrated_lufs: float | None = None
    true_peak_dbtp: float | None = None


@dataclass(frozen=True, slots=True)
class QcRow:
    """One ``qc_results`` row (04 section 5.17)."""

    render_id: str
    task_id: str
    check_id: str
    verdict: CheckVerdict
    blocking: bool
    measured_num: float | None
    measured_text: str | None
    threshold_num: float | None
    threshold_text: str | None
    rule_id: str | None
    evidence_ref: str | None
    message: str


@runtime_checkable
class RenderRepository(Protocol):
    def find_by_content(self, tx: TenantTransaction, content_sha256: str) -> RenderRow | None: ...

    def find_master(
        self, tx: TenantTransaction, job_id: str, timeline_sha256: str, preset_key: str
    ) -> RenderRow | None: ...

    def get(self, tx: TenantTransaction, render_id: str) -> RenderRow | None: ...

    def insert(self, tx: TenantTransaction, row: RenderRow) -> RenderRow:
        """Insert as ``COMPLETE`` and mark earlier renders of the same job/kind/preset
        ``SUPERSEDED``; ``UNIQUE (org_id, content_sha256)``: the existing row is returned."""
        ...

    def set_qc(
        self,
        tx: TenantTransaction,
        render_id: str,
        status: RenderStatus,
        integrated_lufs: float | None,
        true_peak_dbtp: float | None,
    ) -> RenderRow: ...


@runtime_checkable
class QcResultRepository(Protocol):
    def insert_many(self, tx: TenantTransaction, rows: Sequence[QcRow]) -> int:
        """Idempotent on ``(task_id, check_id)``; returns the number of new rows."""
        ...

    def for_render(self, tx: TenantTransaction, render_id: str) -> Sequence[QcRow]: ...


@dataclass(frozen=True, slots=True)
class SubtitleAsset:
    asset_id: str
    uri: str
    content_sha256: str
    size_bytes: int
    language: str


@runtime_checkable
class AssetCatalog(Protocol):
    def lookup(self, tx: TenantTransaction, asset_ids: Sequence[str]) -> Mapping[str, AssetRecord]:
        """Rows of ``assets`` of the tenant by ID (a missing ID is simply absent)."""
        ...

    def find_subtitle(self, tx: TenantTransaction, content_sha256: str) -> SubtitleAsset | None: ...

    def insert_subtitle(self, tx: TenantTransaction, asset: SubtitleAsset) -> SubtitleAsset:
        """``kind = SUBTITLE``, ``CODE_GENERATED``, both realism flags false,
        ``attributes.language`` (CCR-032); ``UNIQUE (org_id, content_sha256)``: an existing row
        is returned."""
        ...


@dataclass(frozen=True, slots=True)
class LicenceSnapshot:
    """What ``qc.licence.*`` reads: ledger rows, licences and asset facts (read only, CCR-030)."""

    ledger: Sequence[Mapping[str, Any]] = ()
    licences: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    assets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    stock_items: Sequence[Mapping[str, Any]] = ()


@runtime_checkable
class LicenceReader(Protocol):
    def snapshot(
        self, tx: TenantTransaction, job_id: str, render_id: str, asset_ids: Sequence[str]
    ) -> LicenceSnapshot:
        """Rows with ``render_id = R OR (render_id IS NULL AND job_id = J)`` (CCR-030)."""
        ...
