"""Row shapes of the four repositories (04 section 5.15: ``licences``, ``licence_ledger``,
``assets``, ``asset_fingerprints``). Plain frozen dataclasses; ids are wire ids (``ast_...``).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from amw_core.enums import (
    AssetKind,
    AssetStatus,
    LicenceSourceType,
    LicenceState,
    LicenceUsageKind,
    ThirdPartyPermission,
    VisualSourceTier,
)


@dataclass(frozen=True, slots=True)
class NewAsset:
    kind: AssetKind
    source_type: LicenceSourceType
    content_sha256: str
    uri: str
    size_bytes: int
    title: str
    visual_source_tier: VisualSourceTier | None = None
    licence_id: str | None = None
    expires_at: datetime | None = None
    allowed_channel_ids: tuple[str, ...] | None = None
    is_realistic_synthetic: bool = False
    depicts_real_person: bool = False
    release_ref: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    duration_ms: int | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AssetRecord:
    asset_id: str
    org_id: str
    status: AssetStatus
    created_at: datetime
    asset: NewAsset


@dataclass(frozen=True, slots=True)
class LicenceRecord:
    licence_id: str
    org_id: str | None
    """``None`` = platform-held."""
    licence_key: str
    source_type: LicenceSourceType
    state: LicenceState
    expires_at: datetime | None
    third_party_permission: ThirdPartyPermission | None
    covers_monetized_youtube: bool | None
    indemnification: bool | None
    vendor: str | None = None


@dataclass(frozen=True, slots=True)
class NewLedgerEntry:
    job_id: str
    task_id: str
    asset_id: str
    licence_id: str
    usage_kind: LicenceUsageKind
    used_from_ms: int
    used_to_ms: int
    shot_id: str | None
    render_id: str | None
    source_url: str | None
    vendor_item_id: str | None


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    ledger_entry_id: str
    org_id: str
    entry: NewLedgerEntry


@dataclass(frozen=True, slots=True)
class FingerprintRow:
    asset_id: str
    algo: str
    algo_version: int
    value_hex: str
    frame_ms: int | None
