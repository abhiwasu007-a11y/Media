"""Agent 05 configuration (blueprint section 11.2).

Every value comes from ``amw_core.config`` in the worker (the registry of ``agent_05.*``,
``llm.agent_05.*`` and ``qc.*`` keys is a shared change, listed as ``core_needs`` of this lane);
this package only declares the typed shape and the defaults the blueprint itself states. A value the
blueprint marks ``REQUIRES REVIEW`` has **no default**: it is ``None`` (unset) or a required field,
and the dependent check is ``SKIPPED``/``WARN`` or the readiness check fails, never a guess.
"""

from pydantic import BaseModel, ConfigDict, Field

from agent_05_scriptwriter.errors import ConfigInvalid


class LlmStepSettings(BaseModel):
    """The 27 section 4.2 family ``llm.<task_type>.<step>.*`` for one step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1, description="resolved from llm.tiers.<model_tier>.model")
    model_tier: str = "MID"
    temperature: float = Field(ge=0, le=2)
    max_output_tokens: int = Field(ge=1)
    timeout_ms: int = Field(ge=1)
    cost_budget_micros: int = Field(ge=0)
    cache_system_prompt: bool = False
    batch_eligible: bool = False
    fallback_tier: str | None = None
    config_key_family: str = Field(min_length=1)


class NearCopySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ngram_n: int = Field(ge=1)
    max_overlap_ratio: float = Field(ge=0, le=1)
    max_common_run_chars: int = Field(ge=1)


class Agent05Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: LlmStepSettings
    section: LlmStepSettings
    cut: LlmStepSettings | None = None
    near_copy: NearCopySettings
    languages_enabled: tuple[str, ...] = ("mr-IN", "en-IN")
    hooks_min_options: int = Field(default=3, ge=1, le=5)
    hooks_max_options: int = Field(default=5, ge=1, le=5)
    hook_beat_tolerance: float | None = None
    hook_min_fill_ratio: float | None = None
    hook_history_similarity: float | None = None
    hook_history_size: int = Field(default=10, ge=1)
    max_sections: int = Field(default=12, ge=1, le=12)
    speech_rate_cps: dict[str, float] = Field(default_factory=dict)
    size_tolerance: float | None = None
    duration_tolerance: float | None = None
    latin_allow_list_default: tuple[str, ...] = ()
    disclaimer_placements: tuple[str, ...] = ("AFTER_HOOK", "END")
    disclaimer_categories: frozenset[str] = frozenset({"finance"})
    charts_per_section: int = Field(default=2, ge=0, le=12)
    shorts_max_duration_ms: int | None = None
    hook_window_ms: int = Field(default=30_000, ge=1)
    max_change_gap_ms: int = Field(default=5_000, ge=1)
    max_scenes_per_section: int = Field(default=20, ge=1, le=20)
    prompts_root: str | None = None

    def rate_for(self, language: str) -> float | None:
        """Characters per second of the voice in use, or ``None`` while unmeasured."""
        rate = self.speech_rate_cps.get(language)
        return rate if rate is not None and rate > 0 else None

    def require_cut(self) -> LlmStepSettings:
        if self.cut is None:
            raise ConfigInvalid("llm.agent_05.shorts_adaptation.cut.* is not configured")
        return self.cut

    def require_shorts_limit(self) -> int:
        if self.shorts_max_duration_ms is None:
            raise ConfigInvalid("agent_05.shorts.max_duration_ms is not set")
        return self.shorts_max_duration_ms
