# mypy: disable-error-code="arg-type,attr-defined,misc,has-type,no-untyped-def,no-any-return"
# mypy: disable-error-code="assignment,union-attr,index,call-arg"
# (test helpers feed dataset dicts and fakes into typed APIs; the package is strict clean)
"""Synthetic fixtures: OHLC data generated at test time (never private market data)."""

import json
import random
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from agent_08_visual_assets.charts.render import BrandPalette
from agent_08_visual_assets.persistence.records import LicenceRecord, NewAsset
from agent_08_visual_assets.settings import AssetSettings, CanvasSize
from agent_08_visual_assets.testing.memory import (
    MemoryAssetRepository,
    MemoryAuditLog,
    MemoryBlobStorage,
    MemoryFingerprintRepository,
    MemoryLedgerRepository,
    MemoryLicenceRepository,
    MemoryReleaseApprovals,
)
from amw_core.enums import AssetKind, LicenceSourceType, LicenceState, ThirdPartyPermission
from amw_core.ids import ORG, Prefix, new_id
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.testing.memory import MemoryTransaction

NOW = datetime(2026, 6, 1, tzinfo=UTC)
PALETTE = BrandPalette("#101820", "#f2f2f2", "#2a3540", "#2ecc71", "#e74c3c", "#f1c40f", "#3498db")


def synthetic_csv(n: int = 120, start: date = date(2025, 1, 1), seed: int = 7) -> bytes:
    rnd = random.Random(seed)  # noqa: S311
    price = 100.0
    rows = ["date,open,high,low,close"]
    for i in range(n):
        o, c = price, price + rnd.uniform(-2, 2)
        h, low = max(o, c) + rnd.uniform(0, 1), min(o, c) - rnd.uniform(0, 1)
        price = c
        rows.append(f"{start + timedelta(days=i)},{o:.2f},{h:.2f},{low:.2f},{c:.2f}")
    return ("\n".join(rows) + "\n").encode()


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def monotonic_ms(self) -> int:
        return 0


class FakeTenancy:
    @contextmanager
    def transaction(self, context: TenantContext):
        yield MemoryTransaction(context)


def settings(**over: object) -> AssetSettings:
    base: dict[str, object] = {
        "price_data_lag_days": 30,
        "price_data_lag_platform_min_days": 30,
        "tier_e_max_share": Decimal("0.5"),
        "licence_expiry_warning_days": 14,
        "min_resolution": {
            "16:9": CanvasSize(width_px=1280, height_px=720),
            "9:16": CanvasSize(width_px=720, height_px=1280),
        },
        "canvas": {
            "16:9": CanvasSize(width_px=1280, height_px=720),
            "9:16": CanvasSize(width_px=720, height_px=1280),
        },
        "max_shots_per_task": 50,
        "max_candidates_per_shot": 12,
        "max_search_requests_per_shot": 3,
        "min_head_tail_ms": 500,
        "max_dataset_bars": 5000,
        "fingerprint_frames_per_clip": 3,
    }
    return AssetSettings(**{**base, **over})


def lic(org: str, source: LicenceSourceType, key: str | None = None) -> LicenceRecord:
    return LicenceRecord(
        str(new_id(Prefix.LICENCE)),
        org,
        key or f"self_grant.{source.value}",
        source,
        LicenceState.ACTIVE,
        None,
        ThirdPartyPermission.PERMITTED,
        True,
        None,
    )


class World:
    """One tenant with repos, standing licences, a dataset, a chart case and brand assets."""

    def __init__(self) -> None:
        self.org = str(ORG.new())
        self.ctx = TenantContext(self.org, "usr_" + str(new_id(Prefix.USER))[4:], None)
        self.blobs, self.assets = MemoryBlobStorage(), MemoryAssetRepository()
        self.licences, self.ledger = MemoryLicenceRepository(), MemoryLedgerRepository()
        self.fps, self.approvals, self.audit = (
            MemoryFingerprintRepository(),
            MemoryReleaseApprovals(),
            MemoryAuditLog(),
        )
        self.tx = MemoryTransaction(self.ctx)
        for st in (
            LicenceSourceType.CODE_GENERATED,
            LicenceSourceType.OWNER_MADE,
            LicenceSourceType.FONT,
        ):
            self.licences.add(lic(self.org, st))

    def add_asset(self, kind: AssetKind, sha: str, title: str, st: LicenceSourceType) -> str:
        return self.assets.insert(
            self.tx,
            NewAsset(
                kind=kind,
                source_type=st,
                content_sha256=sha,
                uri=f"amw-blob://{self.org}/assets/{sha}",
                size_bytes=1,
                title=title,
            ),
        ).asset_id


def case_json(dataset_asset_id: str, **over: object) -> bytes:
    doc: dict[str, object] = {
        "case_id": "case_a",
        "data_kind": "REAL_HISTORICAL",
        "instrument": "EXAMPLE_X",
        "timeframe": "1D",
        "dataset_asset_id": dataset_asset_id,
        "window": {"first_bar_index": 10, "last_bar_index": 100},
        "indicators": ["SMA_10"],
        "pattern_concept_ids": ["k1"],
        "outcome": "WORKED",
        "annotations": [
            {"kind": "MARK_BAR", "bar": 60},
            {"kind": "LABEL", "bar": 60, "text": "Historical example"},
        ],
        "method_content": False,
        "template_id": "chart_base",
    }
    return json.dumps({**doc, **over}).encode()


__all__ = ["Decimal"]
