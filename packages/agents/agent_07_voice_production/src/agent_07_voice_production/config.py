"""Typed view of the ``agent_07.*`` and ``qc.*`` config keys (blueprint 6.5).

No module reads the environment (27 section 7.3 rule 1): the worker builds this model from the
config registry and injects it. A required key that is unset is ``PERMANENT.CONFIG_INVALID``; the
spec values (-14 LUFS, -1 dBTP, 48 kHz, AAC-LC >= 384 kbps) can be tightened but never loosened
(a config cannot weaken the delivery spec, 18 section 5).
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from amw_core.errors import ConfigInvalidError

SPEC_SAMPLE_RATE_HZ = 48_000
SPEC_TARGET_LUFS = -14.0
SPEC_TRUE_PEAK_MAX_DBTP = -1.0
SPEC_MIN_BITRATE_BPS = 384_000
SPEC_MUSIC_BAND_DB = (-20.0, -15.0)
"""The owner's rule of 18 section 5: music 15 to 20 dB under the narration."""


class DenoiseMode(StrEnum):
    OFF = "OFF"
    LIGHT = "LIGHT"


class AgentSevenConfig(BaseModel):
    """One immutable snapshot of the Agent 07 configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config_version: Annotated[str, Field(min_length=1, max_length=64)]

    # --- voice synthesis -------------------------------------------------------------------
    provider: str | None = None
    model_ref: str | None = None
    gap_ms: Annotated[int, Field(ge=0)] | None = None
    trim_keep_ms: Annotated[int, Field(ge=0)] | None = None
    price_micros_per_1k_chars: Annotated[int, Field(ge=0)] | None = None
    price_ref: str | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "USD"
    sample_max_segments: Annotated[int, Field(ge=1)] | None = None
    checkpoint_every_n: Annotated[int, Field(ge=1)] = 10
    max_segments: Annotated[int, Field(ge=1)] = 500
    max_chars_per_request: Annotated[int, Field(ge=1)] | None = None
    clip_min_ms_per_char: Annotated[int, Field(ge=0)] | None = None
    clip_max_ms_per_char: Annotated[int, Field(ge=1)] | None = None
    max_attempt_retries: Annotated[int, Field(ge=0, le=5)] = 2
    """In-attempt retries of a temporary provider failure (07 section 3); then the task is
    retried by the orchestrator from its checkpoint."""
    max_retry_after_ms: Annotated[int, Field(ge=0)] = 30_000
    """A provider ``retry_after`` beyond this ends the attempt (``RETRY_WAIT``)."""
    noise_floor_max_dbfs: float | None = None
    max_mark_gap_ms: Annotated[int, Field(ge=0)] | None = None
    """Largest gap between an owner recording's segment marks (F-13); unset = not checked."""

    # --- audio master ---------------------------------------------------------------------
    target_lufs: float = SPEC_TARGET_LUFS
    true_peak_max_dbtp: float = SPEC_TRUE_PEAK_MAX_DBTP
    tolerance_lu: Annotated[float, Field(gt=0)] | None = None
    """``qc.loudness.tolerance_lu``: unset until calibrated in 3B (verdict WARN until then)."""
    sample_rate_hz: int = SPEC_SAMPLE_RATE_HZ
    min_bitrate_bps: int = SPEC_MIN_BITRATE_BPS
    max_passes: Annotated[int, Field(ge=1, le=10)] = 3
    limiter_ceiling_dbtp: float = -1.5
    codec_headroom_step_db: Annotated[float, Field(gt=0)] = 0.5
    max_limiter_reduction_db: Annotated[float, Field(gt=0)] | None = None
    max_silence_ms: Annotated[int, Field(ge=1)] | None = None
    denoise_mode: DenoiseMode = DenoiseMode.OFF
    music_enabled: StrictBool = False
    music_band_min_db: float = SPEC_MUSIC_BAND_DB[0]
    music_band_max_db: float = SPEC_MUSIC_BAND_DB[1]
    silence_noise_db: float = -50.0
    """``silencedetect`` noise threshold (18 section 7.5 proposal, calibrate in 3B)."""
    silence_detect_min_s: Annotated[float, Field(gt=0)] = 0.3
    """``silencedetect`` minimum duration for the voice stem (18 section 7.5 proposal)."""

    @model_validator(mode="after")
    def _spec_cannot_be_loosened(self) -> Self:
        problems: list[str] = []
        if self.sample_rate_hz != SPEC_SAMPLE_RATE_HZ:
            problems.append("sample_rate_hz must be 48000 (18 section 5)")
        if self.min_bitrate_bps < SPEC_MIN_BITRATE_BPS:
            problems.append("min_bitrate_bps must be at least 384000 (18 section 5)")
        if self.true_peak_max_dbtp > SPEC_TRUE_PEAK_MAX_DBTP:
            problems.append("true_peak_max_dbtp must be at most -1.0 (18 section 5)")
        if self.limiter_ceiling_dbtp > self.true_peak_max_dbtp:
            problems.append("limiter_ceiling_dbtp must not exceed true_peak_max_dbtp")
        if self.music_band_min_db > self.music_band_max_db:
            problems.append("music band is empty")
        if (
            self.music_band_min_db < SPEC_MUSIC_BAND_DB[0]
            or self.music_band_max_db > SPEC_MUSIC_BAND_DB[1]
        ):
            problems.append("music band must stay inside -20..-15 dB (18 section 5)")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @classmethod
    def checked(cls, **values: object) -> Self:
        """Build the config; a spec violation is ``PERMANENT.CONFIG_INVALID`` (not a schema error)."""
        try:
            return cls.model_validate(values)
        except ValueError as exc:
            raise ConfigInvalidError(
                "agent_07 configuration is invalid", details={"reason": str(exc)[:500]}
            ) from exc

    def require_voice(self) -> None:
        """Keys the voice step cannot run without (blueprint 6.5: unset => CONFIG_INVALID)."""
        missing = [
            name
            for name in ("gap_ms", "trim_keep_ms", "price_micros_per_1k_chars", "price_ref")
            if getattr(self, name) is None
        ]
        if missing:
            raise ConfigInvalidError(
                "required agent_07 voice config keys are unset", details={"missing": missing}
            )
