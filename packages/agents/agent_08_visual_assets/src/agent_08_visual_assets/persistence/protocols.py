"""Repository Protocols. Every method takes the ``TenantTransaction`` first (04 section 3.2) and
must scope by ``tx.context.org_id`` explicitly (RLS is the second line, blueprint 19.1).

``amw_core`` does not yet ship licence/asset repository interfaces; these are Agent 08's needs
(listed under ``core_needs``). Only ``AssetRepository``, ``LedgerRepository`` and
``FingerprintRepository`` write; ``LicenceRepository`` is read only (``amw_app`` has no write
grant on ``licences``, S-15).
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from agent_08_visual_assets.persistence.records import (
    AssetRecord,
    FingerprintRow,
    LedgerEntry,
    LicenceRecord,
    NewAsset,
    NewLedgerEntry,
)
from amw_core.enums import AssetKind, LicenceSourceType
from amw_core.interfaces.tenancy_context import TenantTransaction


@runtime_checkable
class AssetRepository(Protocol):
    def insert(self, tx: TenantTransaction, asset: NewAsset) -> AssetRecord:
        """Idempotent on ``(org_id, content_sha256)``: a conflict returns the existing row."""
        ...

    def get(self, tx: TenantTransaction, asset_id: str) -> AssetRecord | None:
        """``None`` for a missing id and for an id of another tenant alike."""
        ...

    def find_by_sha(self, tx: TenantTransaction, content_sha256: str) -> AssetRecord | None: ...

    def list_assets(
        self,
        tx: TenantTransaction,
        *,
        kinds: Sequence[AssetKind],
        source_types: Sequence[LicenceSourceType] | None = None,
    ) -> Sequence[AssetRecord]: ...

    def uses_in_window(self, tx: TenantTransaction, asset_id: str, channel_id: str) -> int: ...


@runtime_checkable
class LicenceRepository(Protocol):
    def get(self, tx: TenantTransaction, licence_id: str) -> LicenceRecord | None: ...

    def self_grant(
        self, tx: TenantTransaction, source_type: LicenceSourceType
    ) -> LicenceRecord | None:
        """The tenant's standing row (``licence_key = self_grant.<source_type>``)."""
        ...

    def active_for_source(
        self, tx: TenantTransaction, source_type: LicenceSourceType
    ) -> LicenceRecord | None: ...


@runtime_checkable
class LedgerRepository(Protocol):
    def write(self, tx: TenantTransaction, entry: NewLedgerEntry) -> LedgerEntry:
        """Append-only and idempotent on ``(org, task, asset, usage_kind, shot_id, from_ms)``
        (CCR-030): a replay returns the stored row."""
        ...

    def for_job(self, tx: TenantTransaction, job_id: str) -> Sequence[LedgerEntry]: ...


@runtime_checkable
class FingerprintRepository(Protocol):
    def add(self, tx: TenantTransaction, rows: Sequence[FingerprintRow]) -> None: ...

    def for_asset(self, tx: TenantTransaction, asset_id: str) -> Sequence[FingerprintRow]: ...

    def perceptual_library(self, tx: TenantTransaction) -> Sequence[tuple[str, str]]:
        """``(asset_id, hash_hex)`` of the first perceptual frame of every tenant asset."""
        ...


@runtime_checkable
class ReleaseApprovals(Protocol):
    def is_released(self, tx: TenantTransaction, asset_id: str, subject_sha256: str) -> bool:
        """An ``APPROVED`` ``KNOWLEDGE_RELEASE`` approval of the same org for this asset and
        document hash (04 section 5.16, CCR-012); read only."""
        ...
