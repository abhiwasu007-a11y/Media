"""Ports of agent 11: the read/write access to tenant rows behind one repository Protocol.

Every method takes the tenant transaction (``SET LOCAL app.org_id``, explicit org predicates in the
implementation). The concrete SQL repository is a core / worker concern (core_need): the
``amw_core`` interfaces carry no scripts, brand kits, assets or licence ledger yet.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agent_11_thumbnail_design.models import Brief, Promise, SubjectHint
from agent_11_thumbnail_design.subject_options import AssetFacts
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class ScriptView:
    script_id: str
    content_sha256: str
    verified_sha256: str | None
    verdict: str | None
    open_blocked_claims: int
    promise: Promise | None
    brief: Brief | None


@dataclass(frozen=True, slots=True)
class FontRef:
    asset_id: str
    uri: str
    sha256: str
    scripts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BrandKitView:
    colours: dict[str, str]
    fonts: tuple[FontRef, ...]
    banned_words: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnerAsset:
    """A tenant picture asset: eligibility facts plus the blob to draw."""

    asset_id: str
    facts: AssetFacts
    uri: str
    content_sha256: str
    asset_kind: str
    data_end_date_present: bool = False


@dataclass(frozen=True, slots=True)
class RegisteredAsset:
    """A tenant ``TEMPLATE`` / ``FONT`` asset registered once by the shared registry (CCR-031)."""

    asset_id: str
    kind: str
    key: str
    licence_state: str
    covers_monetized: bool
    source_type: str
    expired: bool = False


@dataclass(frozen=True, slots=True)
class NewImageAsset:
    content_sha256: str
    uri: str
    size_bytes: int
    width_px: int
    height_px: int
    visual_source_tier: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NewLedgerRow:
    asset_id: str
    usage_kind: str
    job_id: str
    task_id: str


@dataclass(frozen=True, slots=True)
class LedgerRow:
    asset_id: str
    usage_kind: str
    job_id: str
    has_interval: bool


@runtime_checkable
class ThumbnailRepository(Protocol):
    def script_view(self, tx: TenantTransaction, uri: str, sha256: str) -> ScriptView: ...

    def channel_category(self, tx: TenantTransaction, channel_id: str) -> str: ...

    def brand_kit(self, tx: TenantTransaction, uri: str, sha256: str) -> BrandKitView | None: ...

    def default_font(self, tx: TenantTransaction) -> FontRef | None:
        """The tenant's registered default OFL font (R21), when it has one."""
        ...

    def owner_assets(self, tx: TenantTransaction, uris: Sequence[str]) -> list[OwnerAsset]: ...

    def subject_hints(self, tx: TenantTransaction, uri: str, sha256: str) -> list[SubjectHint]: ...

    def previous_manifest(
        self, tx: TenantTransaction, uri: str, sha256: str
    ) -> dict[str, Any] | None: ...

    def registered_assets(
        self, tx: TenantTransaction, keys: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], RegisteredAsset]:
        """Look up registered ``(kind, key)`` rows; a missing one is simply absent."""
        ...

    def licence_id_code_generated(self, tx: TenantTransaction) -> str: ...

    def insert_image_asset(self, tx: TenantTransaction, row: NewImageAsset) -> str:
        """Insert one composed picture file; ``UNIQUE (org_id, content_sha256)`` makes a repeat
        return the existing asset id."""
        ...

    def insert_ledger_row(self, tx: TenantTransaction, row: NewLedgerRow) -> None:
        """Idempotent per (asset, usage kind, job)."""
        ...

    def ledger_rows(self, tx: TenantTransaction, job_id: str) -> list[LedgerRow]: ...
