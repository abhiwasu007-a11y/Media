"""Agent11Settings (F-04): the ``agent_11.*`` and ``llm.agent_11...`` config keys of 24.2.

``amw_core.config`` (the registry) does not exist yet (core_need): until it does, the keys are read
from a flat mapping ``{"agent_11.canvas.width_px": 1920, ...}`` and validated here. No value has a
default except the ones the blueprint fixes (faces off, chart stills off, AI still off, fallback
flag false, one re-ask, concurrency 1, three variants).
"""

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from amw_core.errors import ConfigInvalidError

PREFIX = "agent_11."
LLM_PREFIX = "llm.agent_11.thumbnail_variants.concepts."


class Agent11Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_variants: Annotated[int, Field(ge=1, le=3)] = 3
    canvas_width_px: Annotated[int, Field(ge=1)]
    canvas_height_px: Annotated[int, Field(ge=1)]
    output_format: Annotated[str, Field(pattern=r"^png$")]
    output_max_bytes: Annotated[int, Field(ge=1)]
    text_max_words: Annotated[int, Field(ge=1, le=12)]
    text_max_chars: Annotated[int, Field(ge=1, le=80)]
    text_max_options: Annotated[int, Field(ge=1, le=12)]
    text_min_font_px: Annotated[int, Field(ge=1)]
    text_max_font_px: Annotated[int, Field(ge=1)]
    text_font_step_px: Annotated[int, Field(ge=1)]
    layout_safe_margin_permille: Annotated[int, Field(ge=0, le=300)]
    layout_reserved_corner: Annotated[
        str, Field(pattern=r"^(bottom_right|bottom_left|top_right|top_left)$")
    ]
    legibility_min_contrast_ratio: Annotated[float, Field(ge=1.0, le=21.0)]
    legibility_min_text_height_px_at_preview: int | None = None
    legibility_preview_width_px: int | None = None
    distinct_min_hash_distance_bits: Annotated[int, Field(ge=0, le=64)]
    asset_min_width_px: Annotated[int, Field(ge=1)]
    asset_min_height_px: Annotated[int, Field(ge=1)]
    fonts_policy: Annotated[str, Field(pattern=r"^(TENANT_ALLOWED|MANIFEST_ONLY)$")] = (
        "TENANT_ALLOWED"
    )
    """``agent_11.fonts.policy``: MANIFEST_ONLY (the owner channel) refuses any font that is not a
    repo-manifest font; TENANT_ALLOWED keeps the tenant brand-kit mechanism (FR-09)."""
    faces_allowed: bool = False
    chart_still_allowed: bool = False
    ai_still_enabled: bool = False
    llm_enabled: bool
    llm_max_reasks: Annotated[int, Field(ge=0, le=1)] = 1
    llm_max_rationale_chars: Annotated[int, Field(ge=40, le=200)]
    llm_fallback_on_unavailable: bool = False
    compose_concurrency: Annotated[int, Field(ge=1, le=1)] = 1
    model_tier: Annotated[str, Field(pattern=r"^(SMALL|MID|TOP)$")]
    model_id: Annotated[str, Field(min_length=1)]
    temperature: Annotated[float, Field(ge=0, le=2)]
    max_output_tokens: Annotated[int, Field(ge=1)]
    timeout_ms: Annotated[int, Field(ge=1)]
    cost_budget_micros: Annotated[int, Field(ge=0)]
    cache_system_prompt: bool
    batch_eligible: bool = False
    price_in_micros_per_token: Annotated[int, Field(ge=0)]
    price_out_micros_per_token: Annotated[int, Field(ge=0)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]

    @classmethod
    def load(cls, flat: Mapping[str, Any]) -> Agent11Settings:
        """Read the flat dotted keys; any missing required key or bad range is CONFIG_INVALID."""
        tier = flat.get(LLM_PREFIX + "model_tier")
        pairs: dict[str, Any] = {}
        for key, value in flat.items():
            if key.startswith(PREFIX):
                pairs[key[len(PREFIX) :].replace(".", "_")] = value
            elif key.startswith(LLM_PREFIX):
                pairs[key[len(LLM_PREFIX) :]] = value
        if tier is not None:
            pairs["model_id"] = flat.get(f"llm.tiers.{tier}.model")
            pairs["price_in_micros_per_token"] = flat.get(
                f"llm.tiers.{tier}.price_in_micros_per_token"
            )
            pairs["price_out_micros_per_token"] = flat.get(
                f"llm.tiers.{tier}.price_out_micros_per_token"
            )
            pairs["currency"] = flat.get(f"llm.tiers.{tier}.currency")
        try:
            return cls.model_validate(pairs)
        except ValidationError as exc:
            fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
            raise ConfigInvalidError(
                "agent_11 configuration is invalid", details={"keys": fields}
            ) from exc
