"""``LedgerRowBuilder`` and ``CoverageVerifier`` (blueprint 10.6; 18 section 7.9, CCR-030/031).

Rows are written at sourcing time with ``render_id`` NULL. One row per shot (interval = the shot's
interval), one ``TEMPLATE`` row per overlay interval, one whole-timeline ``FONT`` row per brand
font and, in 3B, the ``MUSIC_BED`` row. A single row must cover an element (adjacent rows do not).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from amw_core.enums import AssetKind, LicenceSourceType, LicenceUsageKind, VisualSourceTier
from amw_core.errors import InputInvalidError, MissingDependencyError

_AI_TIERS = frozenset({VisualSourceTier.D_AI_VIDEO, VisualSourceTier.E_AI_STILL})


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """Fields of a ``licence_ledger`` row Agent 08 decides (the repository adds ids/timestamps)."""

    usage_kind: LicenceUsageKind
    licence_ref: str
    used_from_ms: int
    used_to_ms: int
    render_id: str | None
    source_url: str | None
    vendor_item_id: str | None
    shot_id: str | None


def usage_kind_of(
    kind: AssetKind, tier: VisualSourceTier | None, source_type: LicenceSourceType
) -> LicenceUsageKind:
    if tier in _AI_TIERS or source_type is LicenceSourceType.AI_GENERATED:
        return LicenceUsageKind.AI_OUTPUT
    mapping = {
        AssetKind.FONT: LicenceUsageKind.FONT,
        AssetKind.TEMPLATE: LicenceUsageKind.TEMPLATE,
        AssetKind.AUDIO_MUSIC: LicenceUsageKind.MUSIC_BED,
        AssetKind.VIDEO: LicenceUsageKind.SHOT,
        AssetKind.IMAGE: LicenceUsageKind.IMAGE,
        AssetKind.CHART: LicenceUsageKind.IMAGE,
    }
    try:
        return mapping[kind]
    except KeyError:
        raise InputInvalidError(f"asset kind {kind} has no ledger usage kind") from None


class LedgerRowBuilder:
    @staticmethod
    def build(
        *,
        tier: VisualSourceTier | None,
        kind: AssetKind,
        source_type: LicenceSourceType,
        start_ms: int,
        end_ms: int,
        licence_ref: str | None,
        element_id: str | None,
        vendor_item_id: str | None = None,
        source_url: str | None = None,
    ) -> LedgerRow:
        if licence_ref is None:
            raise MissingDependencyError(
                "no licence row for the asset", details={"class": "licence"}
            )
        if start_ms < 0 or end_ms <= start_ms:
            raise InputInvalidError("ledger interval must satisfy 0 <= start < end")
        return LedgerRow(
            usage_kind=usage_kind_of(kind, tier, source_type),
            licence_ref=licence_ref,
            used_from_ms=start_ms,
            used_to_ms=end_ms,
            render_id=None,
            source_url=source_url,
            vendor_item_id=vendor_item_id,
            shot_id=element_id,
        )


@dataclass(frozen=True, slots=True)
class CoverElement:
    element: str
    asset: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class CoverRow:
    asset: str
    from_ms: int
    to_ms: int
    job: str | None = None
    render: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageResult:
    gaps: tuple[str, ...]
    duplicates: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.gaps and not self.duplicates


class CoverageVerifier:
    """Same rule as the reference query of 18 section 7.9: exactly one row covers an element."""

    @staticmethod
    def verify(
        elements: Sequence[CoverElement],
        rows: Sequence[CoverRow],
        *,
        job_id: str | None = None,
        render_id: str | None = None,
    ) -> CoverageResult:
        def in_scope(row: CoverRow) -> bool:
            if job_id is None and render_id is None:
                return True
            return (render_id is not None and row.render == render_id) or (
                row.render is None and job_id is not None and row.job == job_id
            )

        gaps: list[str] = []
        duplicates: list[str] = []
        for el in elements:
            covering = [
                r
                for r in rows
                if r.asset == el.asset
                and r.from_ms <= el.start_ms
                and r.to_ms >= el.end_ms
                and in_scope(r)
            ]
            if not covering:
                gaps.append(el.element)
            elif len(covering) > 1:
                duplicates.append(el.element)
        return CoverageResult(tuple(gaps), tuple(duplicates))
