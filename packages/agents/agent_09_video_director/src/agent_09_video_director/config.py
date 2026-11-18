"""Agent09Config: every number of the engine is config, never a literal (blueprint 24.2, rule 5).

``amw_core.config`` does not exist yet (core_need): this model is the typed view the worker fills
from it. Required keys have no default in ``base_for_tests`` only; production code builds the
config from the registry and a missing required key is ``PERMANENT.CONFIG_INVALID``.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ConfigDict, Field, ValidationError

from agent_09_video_director.contracts import Model
from amw_core.errors import ConfigInvalidError

# dotted keys of the blueprint / eval datasets -> field names
_ALIASES: dict[str, str] = {
    "cadence.min_gap_ms": "cadence_min_gap_ms",
    "cadence.safety_margin_ms": "cadence_safety_margin_ms",
    "qc.visual.max_change_gap_ms": "max_change_gap_ms",
    "qc.hook.window_ms": "hook_window_ms",
    "snap.tolerance_ms": "snap_tolerance_ms",
    "snap.min_slot_ms": "snap_min_slot_ms",
    "held.max_ms": "held_max_ms",
    "interrupt.first_dropoff.start_ms": "first_dropoff_start_ms",
    "interrupt.first_dropoff.end_ms": "first_dropoff_end_ms",
    "interrupt.midpoint.half_width_ms": "midpoint_half_width_ms",
    "jl.offset_ms": "jl_offset_ms",
    "jl.every_nth": "jl_every_nth",
    "transition.max_ms": "transition_max_ms",
    "sting.max_ms": "sting_max_ms",
    "end_screen.length_ms": "end_screen_length_ms",
    "pacing.hook_gap_ms": "pacing_hook_gap_ms",
    "tier.d_enabled": "tier_d_enabled",
    "tier.d_max_ms": "tier_d_max_ms",
    "tier.e_plan_fraction": "tier_e_plan_permille",
    "qc.visual.tier_e_max_share": "tier_e_max_share_permille",
    "chapter_cards.enabled": "chapter_cards_enabled",
    "fallback.max_share_permille": "fallback_max_share_permille",
    "llm.max_repairs_per_batch": "llm_max_repairs_per_batch",
    "llm.batch_slots": "llm_batch_slots",
    "max_slots": "max_slots",
}
_FRACTION_KEYS = {"tier.e_plan_fraction", "qc.visual.tier_e_max_share"}


class Agent09Config(Model):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # required
    cadence_min_gap_ms: int = Field(ge=1)
    max_change_gap_ms: int = Field(ge=1)
    hook_window_ms: int = Field(ge=1)
    tier_e_max_share_permille: int = Field(ge=0, le=1000)
    snap_tolerance_ms: int = Field(ge=0)
    snap_min_slot_ms: int = Field(ge=1)
    max_slots: int = Field(ge=1)
    llm_batch_slots: int = Field(ge=1, le=40)
    llm_max_repairs_per_batch: int = Field(ge=0)
    llm_max_intent_chars: int = Field(ge=1, le=240)
    llm_max_rationale_chars: int = Field(ge=1, le=160)
    # optional (feature off when unset)
    cadence_safety_margin_ms: int = Field(default=0, ge=0)
    held_max_ms: int | None = None
    first_dropoff_start_ms: int | None = None
    first_dropoff_end_ms: int | None = None
    midpoint_half_width_ms: int | None = None
    jl_offset_ms: int | None = None
    jl_every_nth: int | None = Field(default=None, ge=1)
    transition_max_ms: int | None = None
    sting_max_ms: int | None = None
    end_screen_length_ms: int | None = None
    pacing_hook_gap_ms: int | None = None
    tier_d_enabled: bool = False
    tier_d_max_ms: int | None = None
    tier_e_plan_permille: int | None = Field(default=None, ge=0, le=1000)
    chapter_cards_enabled: bool = False
    fallback_max_share_permille: int | None = Field(default=None, ge=0, le=1000)
    llm_fallback_on_unavailable: bool = False
    # model keys llm.agent_09.shot_plan.direction.*
    llm_model: str = Field(min_length=1)
    llm_temperature: float = Field(default=0.0, ge=0, le=2)
    llm_max_output_tokens: int = Field(default=8000, ge=1)
    llm_timeout_ms: int = Field(default=120_000, ge=1)
    llm_cache_system_prompt: bool = True
    # tenant-supplied limits of the call (S4 reservation lives in resource_budget)
    pacing_beat_gap_ms: tuple[tuple[str, int], ...] = ()

    @property
    def g_max_ms(self) -> int:
        """Hard cadence limit used by the grid: limit minus the safety margin (6.2 step 2)."""
        return self.max_change_gap_ms - self.cadence_safety_margin_ms

    def with_overrides(self, overrides: Mapping[str, Any]) -> Agent09Config:
        """Apply dotted-key overrides (used by the eval dataset ``config_overrides``)."""
        updates: dict[str, Any] = {}
        for key, value in overrides.items():
            name = _ALIASES.get(key)
            if name is None:
                raise ConfigInvalidError(f"unknown config key {key!r}")
            updates[name] = round(float(value) * 1000) if key in _FRACTION_KEYS else value
        try:
            return type(self).model_validate({**self.model_dump(), **updates})
        except ValidationError as exc:
            raise ConfigInvalidError("config override invalid") from exc

    def pacing_gap(self, beat: str, role: str) -> int:
        """PacingProfile.target_gap (F-07): table, then the directive window midpoint (6.3)."""
        table = dict(self.pacing_beat_gap_ms)
        if role == "HOOK" and self.pacing_hook_gap_ms is not None:
            return self.pacing_hook_gap_ms
        if beat in table:
            return table[beat]
        if role == "HOOK":
            return self.cadence_min_gap_ms  # hook default = g_min (6.3)
        return (self.cadence_min_gap_ms + self.max_change_gap_ms) // 2  # explain = window midpoint


def base_for_tests() -> Agent09Config:
    """The ``base`` configuration of the timeline_engine dataset (README section 2)."""
    return Agent09Config(
        cadence_min_gap_ms=3000,
        max_change_gap_ms=5000,
        hook_window_ms=30_000,
        tier_e_max_share_permille=500,
        snap_tolerance_ms=0,
        snap_min_slot_ms=2000,
        max_slots=5000,
        llm_batch_slots=12,
        llm_max_repairs_per_batch=1,
        llm_max_intent_chars=240,
        llm_max_rationale_chars=160,
        llm_model="model-ref-from-config",
    )
