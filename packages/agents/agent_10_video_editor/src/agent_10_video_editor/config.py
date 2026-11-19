"""Typed view of the ``agent_10.*`` and ``qc.*`` configuration keys (blueprint 10 section 24.2).

``amw_core.config`` does not exist yet (core_need): this model is the single place the package
reads configuration from; a required key that is unset is ``PERMANENT.CONFIG_INVALID`` and the
worker does not claim. No value here is a literal of the method: values come from the caller.
"""

from enum import StrEnum
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from agent_10_video_editor.encode import EncodeSettings, resolve
from agent_10_video_editor.errors import config_invalid

PresetKey = Literal["yt_master_1080p", "yt_master_1440p", "shorts_9x16"]

_PRESET_GEOMETRY: dict[str, tuple[int, int]] = {
    "yt_master_1080p": (1920, 1080),
    "yt_master_1440p": (2560, 1440),
    "shorts_9x16": (1080, 1920),
}


class Placement(StrEnum):
    """``AMW_PLACEMENT`` (operational values owned by 06_NIGHT_SCHEDULING.md and ADR-012)."""

    DEV = "DEV"
    VPS = "VPS"


class Weekday(StrEnum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class _Cfg(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ColourTags(_Cfg):
    """``agent_10.render.color_*`` (PROPOSAL values; REQUIRES REVIEW, section 6.2 item 9)."""

    primaries: str = "bt709"
    transfer: str = "bt709"
    matrix: str = "bt709"
    range: str = "tv"


class RenderConfig(_Cfg):
    fps_num: Annotated[int, Field(ge=1, strict=True)]
    fps_den: Annotated[int, Field(ge=1, strict=True)]
    preset_key: PresetKey
    video_encoder: Literal["libx264"]
    video_bitrate_bps: Annotated[int, Field(ge=1, strict=True)] | None = None
    """Only for a size / frame rate without a row in ``data/encode_targets.json`` (REQUIRES
    REVIEW); where a row exists the row is the target and a different value is refused."""
    video_maxrate_bps: Annotated[int, Field(ge=1, strict=True)] | None = None
    """VBV cap override; unset = the row's measured PROPOSAL cap (REQUIRES REVIEW, ADR-014
    section 3.4); must be above the target, else x264 runs CBR."""
    video_bufsize_bps: Annotated[int, Field(ge=1, strict=True)] | None = None
    gop_frames: Annotated[int, Field(ge=1, strict=True)] | None = None
    """Derived as half the frame rate (INF-13); a set value must equal it."""
    segment_target_ms: Annotated[int, Field(ge=1, strict=True)]
    threads: Annotated[int, Field(ge=1, strict=True)]
    eta_ms_per_output_s: int | None = None
    drain_finish_max_ms: Annotated[int, Field(ge=0, strict=True)]
    colour: ColourTags = ColourTags()
    aac_priming_samples: Annotated[int, Field(ge=0, strict=True)] = 1024
    """``agent_10.render.aac_priming_samples``: encoder delay of the native AAC encoder, dropped
    from the master because the MP4 has no edit list (INF-13). 1024 = MEASURED on FFmpeg 6.1.1
    (click test, ADR-014 section 3.5); REQUIRES REVIEW (Phase 1): re-measure on the pinned build."""
    quality_sample_every: Annotated[int, Field(ge=1, strict=True)] = 1
    """``agent_10.render.quality_sample_every``: the lossless reference (and the SSIM) keep every
    n-th frame; 1 = every frame (default, exact). Raise it to bound the FFV1 scratch size of long
    noisy segments (ADR-014 section 4; REQUIRES REVIEW: value from the 3B pilot)."""
    x264_preset: str = "medium"
    """One of ``encode.X264_PRESETS_ALLOWED`` (never ``ultrafast``: Constrained Baseline)."""
    effect_lock_ms: Annotated[int, Field(ge=1, strict=True)] = 900_000
    width_px: int | None = None
    height_px: int | None = None

    @property
    def geometry(self) -> tuple[int, int]:
        default = _PRESET_GEOMETRY[self.preset_key]
        return (self.width_px or default[0], self.height_px or default[1])

    @property
    def encode(self) -> EncodeSettings:
        """Resolved encoder settings (ADR-014); validated when the configuration loads."""
        width, height = self.geometry
        return resolve(
            width_px=width,
            height_px=height,
            fps=Fraction(self.fps_num, self.fps_den),
            video_bitrate_bps=self.video_bitrate_bps,
            video_maxrate_bps=self.video_maxrate_bps,
            video_bufsize_bps=self.video_bufsize_bps,
            gop_frames=self.gop_frames,
            x264_preset=self.x264_preset,
        )

    @property
    def effective_gop_frames(self) -> int:
        return self.encode.gop_frames

    @model_validator(mode="after")
    def _encode_resolves(self) -> RenderConfig:
        self.encode  # noqa: B018 - raises ValueError (CONFIG_INVALID) when unresolvable
        return self


class SubConfig(_Cfg):
    max_chars_per_cue: Annotated[int, Field(ge=1, strict=True)]
    min_cue_ms: int | None = None


class MarketWindow(_Cfg):
    """Half-open ``[start_min, end_min)`` market window of one weekday (minute of day)."""

    weekday: Weekday
    start_min: Annotated[int, Field(ge=0, lt=1440, strict=True)]
    end_min: Annotated[int, Field(gt=0, le=1440, strict=True)]


class NightWindow(_Cfg):
    """VPS night window ``[start_min, end_min)`` (00:00-07:00) and ``drain.grace_ms``."""

    start_min: Annotated[int, Field(ge=0, lt=1440, strict=True)] = 0
    end_min: Annotated[int, Field(gt=0, le=1440, strict=True)]
    grace_ms: Annotated[int, Field(ge=0, strict=True)]


class GuardConfig(_Cfg):
    """``ops.market_windows``, ``ops.night_window``, ``drain.grace_ms`` (06_NIGHT_SCHEDULING.md).

    ``market_windows = None`` or empty means no calendar is configured: the guard fails closed
    (``PERMANENT.CONFIG_INVALID``), it never defaults to "allowed".
    """

    market_windows: tuple[MarketWindow, ...] | None = None
    night_window: NightWindow | None = None


class QcConfig(_Cfg):
    """``qc.*`` of 18 section 13 plus the ``agent_10.qc.*`` keys. ``None`` = unsourced/unset."""

    profile: Literal["qc.long_form", "qc.shorts"] = "qc.long_form"
    min_width_px: int = 1920
    min_height_px: int = 1080
    quality_min_ssim: str | None = None
    """``qc.video.quality_min_ssim``: UNSET in 3A (report only, ADR-014); set in 3B."""
    audio_bitrate_min_bps: int = 384_000
    sample_rate_hz: int = 48_000
    channels: int = 2
    true_peak_ceiling_dbtp: str = "-1.0"
    target_lufs: str = "-14.0"
    lufs_tolerance_lu: str | None = None
    music_offset_min_db: str = "-20.0"
    music_offset_max_db: str = "-15.0"
    silence_max_ms: int | None = None
    silence_n_db: int = -50
    silence_d_s: str = "1"
    black_d_s: str = "2"
    black_pic_th: str = "0.98"
    black_pix_th: str = "0.10"
    black_calibrated: bool = False
    freeze_n_db: int = -60
    freeze_d_s: str = "2"
    freeze_calibrated: bool = False
    scene_threshold: str = "0.3"
    cfr_tolerance_s: str = "0.000010"
    cadence_max_gap_ms: int = 5000
    cadence_blocking: bool = False
    hook_window_ms: int = 30_000
    sync_tol_start_ms: int | None = None
    sync_tol_dur_ms: int | None = None
    sub_tol_ms: int | None = None
    duration_tol_ms: int | None = None
    duration_targets_ms: tuple[int, int] | None = None
    licence_expiry_warning_days: int | None = None
    e_share_limit_ratio: str = "0.50"
    price_data_lag_days: int | None = None
    finance_channel: bool | None = None
    """``None`` (default) = derive: a channel is a finance channel unless it is listed in
    ``non_finance_channel_ids`` (the 3A channel carries ``rp.finance_sebi_in``); a bool forces."""
    non_finance_channel_ids: tuple[str, ...] = ()
    sample_frames_per_min: Annotated[int, Field(ge=1, strict=True)] = 6
    single_pass: bool = False
    music_enabled: bool = False
    first_dropoff_window_ms: tuple[int, int] | None = None
    midpoint_window_ms: int | None = None
    min_jl_cuts: int | None = None
    end_screen_ms: int | None = None
    cadence_crosscheck_tolerance: str = "0.3"
    destination: Literal["MONETIZED_YOUTUBE", "NON_MONETIZED"] = "MONETIZED_YOUTUBE"


class AgentTenConfig(_Cfg):
    render: RenderConfig
    sub: SubConfig
    guard: GuardConfig = GuardConfig()
    qc: QcConfig = QcConfig()
    max_atomic_write_ms: StrictInt | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, object]) -> AgentTenConfig:
        """Validate a configuration mapping; any problem is ``PERMANENT.CONFIG_INVALID``."""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            keys = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})
            reasons = sorted(
                {
                    str(err["ctx"]["error"])
                    for err in exc.errors()
                    if err["type"] == "value_error" and "ctx" in err
                }
            )
            raise config_invalid(
                *(f"CONFIG_KEY:{key}" for key in keys), *(f"REASON:{r}" for r in reasons)
            ) from exc
