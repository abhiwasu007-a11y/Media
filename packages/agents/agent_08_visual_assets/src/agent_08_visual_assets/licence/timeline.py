"""``TimelineLedgerPlanner``: ledger rows of the overlay track and the brand fonts (CCR-031).

Plans one ``TEMPLATE`` row per overlay interval (``shot_id`` = overlay id) in plan order, then one
whole-timeline ``FONT`` row per brand-kit font in brand-kit order (``shot_id`` NULL). All inputs
are validated first: a missing template asset or font is ``MISSING_DEPENDENCY`` and an overlay
beyond the timeline is ``INPUT_INVALID``; never a partial list (``OV-01`` to ``OV-05``).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from amw_core.enums import LicenceUsageKind
from amw_core.errors import InputInvalidError, MissingDependencyError


@dataclass(frozen=True, slots=True)
class OverlayInput:
    overlay_id: str
    kind: str
    start_ms: int
    end_ms: int
    template_asset: str | None


@dataclass(frozen=True, slots=True)
class PlannedRow:
    element_id: str
    asset: str
    usage_kind: LicenceUsageKind
    used_from_ms: int
    used_to_ms: int
    shot_id: str | None


class TimelineLedgerPlanner:
    @staticmethod
    def plan(
        overlays: Sequence[OverlayInput], brand_fonts: Sequence[str], timeline_end_ms: int
    ) -> list[PlannedRow]:
        if timeline_end_ms <= 0:
            raise InputInvalidError("timeline end must be positive")
        if not brand_fonts:
            raise MissingDependencyError(
                "brand kit lists no font", details={"class": "brand_kit_font"}
            )
        for ov in overlays:
            if ov.template_asset is None:
                raise MissingDependencyError(
                    "overlay has no registered template asset",
                    details={"class": "overlay_template", "overlay_id": ov.overlay_id},
                )
            if ov.start_ms < 0 or ov.end_ms <= ov.start_ms or ov.end_ms > timeline_end_ms:
                raise InputInvalidError(
                    "overlay interval is outside the timeline",
                    details={"overlay_id": ov.overlay_id},
                )
        rows = [
            PlannedRow(
                ov.overlay_id,
                ov.template_asset,
                LicenceUsageKind.TEMPLATE,
                ov.start_ms,
                ov.end_ms,
                ov.overlay_id,
            )
            for ov in overlays
            if ov.template_asset is not None
        ]
        rows.extend(
            PlannedRow(f"font:{font}", font, LicenceUsageKind.FONT, 0, timeline_end_ms, None)
            for font in brand_fonts
        )
        return rows
