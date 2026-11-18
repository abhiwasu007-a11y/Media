"""``AssetSettings``: the config keys of blueprint 24.2 as one validated, frozen model.

Values are never literals in code (27 section 7.3.1): the stage receives an ``AssetSettings`` built
from the configuration source. Keys the blueprint leaves without a value (owner-set or REQUIRES
REVIEW (Phase 1)) have **no default**; ``0`` or unset disables the feature they bound. ``amw_core``
does not yet ship a config loader, so ``from_mapping`` takes the flat dotted keys of the registry
(18 section 13) and is the only place that knows their names.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from amw_core.errors import ConfigInvalidError

NonNeg = Annotated[int, Field(ge=0, strict=True)]
Pos = Annotated[int, Field(ge=1, strict=True)]


class CanvasSize(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    width_px: Pos
    height_px: Pos


class AssetSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # compliance.finance_sebi_in.price_data_lag_days and the platform minimum (13 section 4)
    price_data_lag_days: NonNeg
    price_data_lag_platform_min_days: NonNeg
    # qc.visual.tier_e_max_share (18 section 13), qc.licence.expiry_warning_window in days
    tier_e_max_share: Annotated[Decimal, Field(gt=0, le=1)]
    licence_expiry_warning_days: NonNeg
    # qc.video.min_width_px / min_height_px per aspect (16:9 floor and the 9:16 proposal)
    min_resolution: Mapping[str, CanvasSize]
    # chart and graphic canvas (pixels) per aspect
    canvas: Mapping[str, CanvasSize]
    # assets.*
    stock_enabled: bool = False
    max_shots_per_task: Pos
    max_candidates_per_shot: Pos
    max_search_requests_per_shot: Pos
    min_head_tail_ms: NonNeg
    max_dataset_bars: Pos
    fingerprint_frames_per_clip: Pos
    near_duplicate_max_distance: NonNeg | None = None
    stock_max_uses_per_channel: NonNeg | None = None
    min_gap_shots: NonNeg = 0
    ai_video_max_ms_per_video: NonNeg = 0
    ai_video_max_cost_micros_per_video: NonNeg = 0
    ai_video_max_clips_per_video: NonNeg = 0
    ai_video_max_clip_ms: NonNeg = 0
    ai_video_model: str | None = None
    ai_video_estimate_micros_per_clip: NonNeg = 0
    ai_still_model: str | None = None
    ai_still_estimate_micros: NonNeg = 0
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "USD"

    @model_validator(mode="after")
    def _lag_not_below_platform(self) -> Self:
        if self.price_data_lag_days < self.price_data_lag_platform_min_days:
            # 13 section 4: the platform may raise the lag, never lower it (CL-10)
            raise ConfigInvalidError("price data lag is below the platform minimum")
        return self

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Self:
        """Build from the flat dotted registry keys; a missing required key is
        ``PERMANENT.CONFIG_INVALID`` (never a silent default)."""
        try:
            return cls.model_validate(
                {
                    "price_data_lag_days": raw["compliance.finance_sebi_in.price_data_lag_days"],
                    "price_data_lag_platform_min_days": raw[
                        "compliance.finance_sebi_in.price_data_lag_platform_min_days"
                    ],
                    "tier_e_max_share": Decimal(str(raw["qc.visual.tier_e_max_share"])),
                    "licence_expiry_warning_days": raw["qc.licence.expiry_warning_window"],
                    "min_resolution": raw["qc.video.min_resolution"],
                    "canvas": raw["assets.canvas"],
                    "stock_enabled": raw.get("assets.stock.enabled", False),
                    "max_shots_per_task": raw["assets.max_shots_per_task"],
                    "max_candidates_per_shot": raw["assets.max_candidates_per_shot"],
                    "max_search_requests_per_shot": raw["assets.max_search_requests_per_shot"],
                    "min_head_tail_ms": raw["assets.min_head_tail_ms"],
                    "max_dataset_bars": raw["assets.chart.max_dataset_bars"],
                    "fingerprint_frames_per_clip": raw["assets.fingerprint.frames_per_clip"],
                    "near_duplicate_max_distance": raw.get(
                        "assets.reuse.near_duplicate_max_distance"
                    ),
                    "stock_max_uses_per_channel": raw.get(
                        "assets.reuse.stock_max_uses_per_channel"
                    ),
                    "min_gap_shots": raw.get("assets.reuse.min_gap_shots", 0),
                    "ai_video_max_ms_per_video": raw.get("assets.ai_video.max_ms_per_video", 0),
                    "ai_video_max_cost_micros_per_video": raw.get(
                        "assets.ai_video.max_cost_micros_per_video", 0
                    ),
                    "ai_video_max_clips_per_video": raw.get(
                        "assets.ai_video.max_clips_per_video", 0
                    ),
                    "ai_video_max_clip_ms": raw.get("assets.ai_video.max_clip_ms", 0),
                    "ai_video_model": raw.get("assets.ai_video.model"),
                    "ai_video_estimate_micros_per_clip": raw.get(
                        "assets.ai_video.estimate_micros_per_clip", 0
                    ),
                    "ai_still_model": raw.get("assets.ai_still.model"),
                    "ai_still_estimate_micros": raw.get("assets.ai_still.estimate_micros", 0),
                    "currency": raw.get("assets.currency", "USD"),
                }
            )
        except KeyError as exc:
            raise ConfigInvalidError(f"missing config key {exc.args[0]!r}") from None
