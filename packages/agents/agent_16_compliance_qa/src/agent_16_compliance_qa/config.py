"""Agent16Config: every model, threshold, lexicon and limit of Agent 16 is configuration
(blueprint section 24.2, CCR-019; rule 5). No module of this package holds such a value as a
literal.

``amw_core.config`` does not exist yet (core_need): this model is the typed view the worker
fills from it. It is built from the dotted keys of the blueprint (``from_mapping``); a missing
or malformed required key is ``PERMANENT.CONFIG_INVALID``. Values that are REQUIRES REVIEW
(Phase 1) in the blueprint (uniqueness, near-copy and paraphrase thresholds, frame counts) are
``None`` until the owner sets them, and the code treats ``None`` as "not decided" (WARN / human
review, never PASS).

Startup rules (section 6.6.4, section 18, U-83): ``quality.score_gate_mode = BLOCKING`` with
``quality.machine_scaling = NONE`` can never pass (the machine total is at most 79) and is
refused; so is any accepted approval channel other than ``OWNER_CHAT_OPERATOR`` in 3A
(``WEB_DASHBOARD`` is refused until its apply function exists, 04 section 5.16).
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, ValidationError, model_validator

from agent_16_compliance_qa.base import Model
from amw_core.enums import ApprovalChannel
from amw_core.errors import ConfigInvalidError


class MachineScaling(StrEnum):
    NONE = "NONE"
    PRO_RATA = "PRO_RATA"


class ScoreGateMode(StrEnum):
    REPORT_ONLY = "REPORT_ONLY"
    BLOCKING = "BLOCKING"


class LlmStepConfig(Model):
    """``llm.agent_16.<task>.<step>.*`` (27 section 4.2 keys; the model id comes from config)."""

    model: str = Field(min_length=1)
    max_output_tokens: int = Field(ge=1)
    temperature: float = Field(ge=0, le=2)
    timeout_ms: int = Field(ge=1)
    cache_system_prompt: bool
    max_calls: int = Field(ge=0)
    worst_case_call_micros: int = Field(ge=0)
    max_cost_micros: int = Field(ge=0)
    accepts_images: bool = False


class Lexicon(Model):
    """``compliance.prefilter.lexicon.<lang>`` (blueprint section 6.2; versioned config)."""

    version: str = Field(min_length=1)
    future_markers: tuple[str, ...]
    imperative_verbs: tuple[str, ...]
    level_words: tuple[str, ...]
    promotion_words: tuple[str, ...]
    group_words: tuple[str, ...]
    identity_markers: tuple[str, ...]
    child_markers: tuple[str, ...]
    person_markers: tuple[str, ...]
    live_format_terms: tuple[str, ...]


_REQUIRED: Mapping[str, str] = {
    "quality.publish_min_score": "publish_min_score",
    "quality.machine_scaling": "machine_scaling",
    "quality.score_gate_mode": "score_gate_mode",
    "editorial.min_description_chars": "min_description_chars",
    "approvals.accepted_channels": "accepted_channels",
    "approvals.review_code.length": "review_code_length",
    "compliance.finance_sebi_in.price_data_lag_days": "price_data_lag_days",
    "compliance.watermark_visual.calibrated": "watermark_visual_calibrated",
    "compliance.gate.max_items_per_judge_call": "max_items_per_judge_call",
    "compliance.gate.max_llm_calls": "gate_max_llm_calls",
    "uniqueness.cross_video.skip_below_prior_count": "cross_video_skip_below_prior_count",
    "agent_16.llm.fallback_on_unavailable": "llm_fallback_on_unavailable",
}
_OPTIONAL: Mapping[str, str] = {
    "uniqueness.template_text_share.max": "uniq_template_text_share_max",
    "uniqueness.shot_type_sequence_identity.max": "uniq_shot_sequence_identity_max",
    "uniqueness.cross_video.max_similarity": "uniq_cross_video_max_similarity",
    "compliance.paraphrase.ngram_n": "paraphrase_ngram_n",
    "compliance.paraphrase.max_overlap_ratio": "paraphrase_max_overlap_ratio",
    "compliance.paraphrase.lcs_max_chars": "paraphrase_lcs_max_chars",
    "compliance.frames.max_frames": "compliance_max_frames",
    "quality.judge.max_frames": "quality_max_frames",
    "quality.judge.default_audience_level": "default_audience_level",
}
_LLM_STEPS: Mapping[str, str] = {
    "llm.agent_16.compliance_gate.policy": "llm_policy",
    "llm.agent_16.compliance_gate.paraphrase": "llm_paraphrase",
    "llm.agent_16.compliance_gate.frames": "llm_frames",
    "llm.agent_16.quality_score.judge": "llm_quality",
}
_LEXICON_PREFIX = "compliance.prefilter.lexicon."


class Agent16Config(Model):
    publish_min_score: float = Field(ge=0, le=100)
    machine_scaling: MachineScaling
    score_gate_mode: ScoreGateMode
    min_description_chars: int = Field(ge=1)
    accepted_channels: frozenset[ApprovalChannel] = Field(min_length=1)
    review_code_length: int = Field(ge=2)
    price_data_lag_days: int = Field(ge=0)
    watermark_visual_calibrated: bool
    max_items_per_judge_call: int = Field(ge=1)
    gate_max_llm_calls: int = Field(ge=0)
    cross_video_skip_below_prior_count: int = Field(ge=0)
    llm_fallback_on_unavailable: bool
    uniq_template_text_share_max: float | None = Field(default=None, ge=0, le=1)
    uniq_shot_sequence_identity_max: float | None = Field(default=None, ge=0, le=1)
    uniq_cross_video_max_similarity: float | None = Field(default=None, ge=0, le=1)
    paraphrase_ngram_n: int | None = Field(default=None, ge=2)
    paraphrase_max_overlap_ratio: float | None = Field(default=None, ge=0, le=1)
    paraphrase_lcs_max_chars: int | None = Field(default=None, ge=1)
    compliance_max_frames: int | None = Field(default=None, ge=1)
    quality_max_frames: int | None = Field(default=None, ge=1)
    default_audience_level: str | None = None
    llm_policy: LlmStepConfig | None = None
    llm_paraphrase: LlmStepConfig | None = None
    llm_frames: LlmStepConfig | None = None
    llm_quality: LlmStepConfig | None = None
    lexicons: Mapping[str, Lexicon] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _startup_rules(self) -> Self:
        if (
            self.score_gate_mode is ScoreGateMode.BLOCKING
            and self.machine_scaling is MachineScaling.NONE
        ):
            raise ValueError(
                "quality.score_gate_mode BLOCKING with quality.machine_scaling NONE can never "
                "pass (machine total <= 79 < threshold); refused at startup (blueprint 6.6.4)"
            )
        if self.accepted_channels - {ApprovalChannel.OWNER_CHAT_OPERATOR}:
            raise ValueError("3A accepts only OWNER_CHAT_OPERATOR records (blueprint 6.5 G4)")
        if self.llm_fallback_on_unavailable:
            raise ValueError("agent_16.llm.fallback_on_unavailable must stay false (Q-O4)")
        if self.llm_frames is not None and not self.llm_frames.accepts_images:
            raise ValueError("the frames judge tier must accept image input (section 11)")
        return self

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> Self:
        """Build from dotted keys; unknown keys and missing required keys are refused."""
        data: dict[str, Any] = {}
        lexicons: dict[str, Any] = {}
        steps: dict[str, dict[str, Any]] = {}
        for key, value in values.items():
            if key in _REQUIRED:
                data[_REQUIRED[key]] = value
            elif key in _OPTIONAL:
                data[_OPTIONAL[key]] = value
            elif key.startswith(_LEXICON_PREFIX):
                lexicons[key.removeprefix(_LEXICON_PREFIX)] = value
            else:
                prefix, _, leaf = key.rpartition(".")
                if prefix not in _LLM_STEPS:
                    raise ConfigInvalidError(f"unknown Agent 16 config key {key!r}")
                steps.setdefault(_LLM_STEPS[prefix], {})[leaf] = value
        missing = sorted(k for k in _REQUIRED if _REQUIRED[k] not in data)
        if missing:
            raise ConfigInvalidError("missing Agent 16 config keys", details={"keys": missing})
        data |= steps
        data["lexicons"] = lexicons
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ConfigInvalidError(
                "invalid Agent 16 config", details={"errors": str(exc)[:1500]}
            ) from exc

    def lexicon(self, language: str) -> Lexicon:
        """The lexicon for a BCP 47 tag (exact, then primary language); missing = refused."""
        lex = self.lexicons.get(language) or self.lexicons.get(language.split("-")[0])
        if lex is None:
            raise ConfigInvalidError(f"no pre-filter lexicon configured for {language!r}")
        return lex

    def step(self, name: str) -> LlmStepConfig:
        cfg: LlmStepConfig | None = getattr(self, name)
        if cfg is None:
            raise ConfigInvalidError(f"LLM step {name} is not configured")
        return cfg
