"""Fact-checker settings (config keys ``factcheck.*``, ``llm.agent_06.*``; blueprint 6, 9).

Numeric limits, models and thresholds are configuration, never literals in the logic. Only the
two tables the blueprint publishes as provisional defaults (verification policy 6.3, verdict map
6.4) and the tier order carry defaults here; every number has none and must be supplied. The
object is built by the worker from ``amw_core.config`` (core_need: that module is not yet part
of Step 0), so the step code never reads the environment.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from agent_06_fact_checker.models import Verdict
from agent_06_fact_checker.pattern_safety import validate_pattern
from agent_06_fact_checker.quote_marks import QuoteMarkConfig
from amw_core.contracts.common import AmwModel
from amw_core.enums import ClaimStatus, ClaimType
from amw_core.errors import ConfigInvalidError


class VerifyPolicy(StrEnum):
    """What the policy table (blueprint 6.3) says for a claim type."""

    EVIDENCE = "EVIDENCE"
    SKIPPED = "SKIPPED"
    CHART_FACTS_OR_PENDING = "CHART_FACTS_OR_PENDING"
    """``HISTORICAL_MARKET``: chart claim = chart facts / pending, no chart = evidence."""
    EVIDENCE_IF_CITATION_REQUIRED = "EVIDENCE_IF_CITATION_REQUIRED"
    EVIDENCE_IF_CITED = "EVIDENCE_IF_CITED"
    """``QUOTED_THIRD_PARTY``: evidence if cited, else code-only ``QUOTE_NOT_ATTRIBUTABLE``."""


def default_policy() -> dict[ClaimType, VerifyPolicy]:
    """Provisional policy table of blueprint 6.3 (Q-F1); ``factcheck.verify.policy``."""
    table: dict[ClaimType, VerifyPolicy] = {
        ClaimType.FACTUAL: VerifyPolicy.EVIDENCE,
        ClaimType.STATISTICAL: VerifyPolicy.EVIDENCE,
        ClaimType.DEFINITION: VerifyPolicy.EVIDENCE,
        ClaimType.COMPARATIVE: VerifyPolicy.EVIDENCE,
        ClaimType.PRODUCT_CLAIM: VerifyPolicy.EVIDENCE,
        ClaimType.HISTORICAL_MARKET: VerifyPolicy.CHART_FACTS_OR_PENDING,
        ClaimType.OPINION: VerifyPolicy.EVIDENCE_IF_CITATION_REQUIRED,
        ClaimType.PERFORMANCE_CLAIM: VerifyPolicy.EVIDENCE,
        ClaimType.TESTIMONIAL: VerifyPolicy.EVIDENCE,
        ClaimType.QUOTED_THIRD_PARTY: VerifyPolicy.EVIDENCE_IF_CITED,
        ClaimType.RECOMMENDATION: VerifyPolicy.SKIPPED,
        ClaimType.FORWARD_VIEW: VerifyPolicy.SKIPPED,
        ClaimType.PRICE_LEVEL: VerifyPolicy.SKIPPED,
        ClaimType.HYPOTHETICAL_EXAMPLE: VerifyPolicy.SKIPPED,
        ClaimType.PROMOTION: VerifyPolicy.SKIPPED,
    }
    return table


def default_verdict_map() -> dict[ClaimStatus, Verdict]:
    """Provisional ``factcheck.verdict_map`` of blueprint 6.4 step 4 (question Q-F2)."""
    return {
        ClaimStatus.VERIFIED: Verdict.ALLOWED,
        ClaimStatus.CONTRADICTED: Verdict.BLOCKED,
        ClaimStatus.NEEDS_SUBSTANTIATION: Verdict.NEEDS_HUMAN_REVIEW,
        ClaimStatus.UNVERIFIABLE: Verdict.NEEDS_HUMAN_REVIEW,
    }


class LlmStepSettings(AmwModel):
    """``llm.agent_06.<task>.*`` (27 4.2, CCR-019). Model ids are config, never literals."""

    model: Annotated[str, StringConstraints(min_length=1)]
    temperature: Annotated[float, Field(ge=0, le=2)]
    max_output_tokens: Annotated[int, Field(ge=1)]
    timeout_ms: Annotated[int, Field(ge=1)]
    cost_budget_micros: Annotated[int, Field(ge=0)]
    """Worst-case cost of one call, checked by the budget guard before the call (E2)."""
    cache_system_prompt: bool
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    price_ref: str | None = None


class FactCheckSettings(AmwModel):
    config_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    extraction_llm: LlmStepSettings
    verification_llm: LlmStepSettings
    # extraction
    extract_max_chars_per_call: Annotated[int, Field(ge=1)]
    price_data_lag_days: Annotated[int, Field(ge=0)]
    """``compliance.finance_sebi_in.price_data_lag_days`` (IN-02)."""
    price_data_lag_unit: str = "CALENDAR_DAYS"
    """Unit of the lag; only ``CALENDAR_DAYS`` is implemented (13 5.5 is open, REQUIRES REVIEW)."""
    referral_patterns: tuple[str, ...]
    """``factcheck.detect.referral_patterns`` (regular expressions, referral / coupon codes)."""
    # verification
    policy: Mapping[ClaimType, VerifyPolicy] = Field(default_factory=default_policy)
    verdict_map: Mapping[ClaimStatus, Verdict] = Field(default_factory=default_verdict_map)
    min_tier_for_verified: str
    tier_order: Annotated[tuple[str, ...], Field(min_length=2)]
    """Best first, e.g. A_PRIMARY ... D_UNVERIFIED (Agent 04, GLOSSARY)."""
    unranked_tier: str
    """Tier of a source that has none in the Agent 04 pack (CCR-053: ``D_UNVERIFIED``)."""
    max_window_chars: Annotated[int, Field(ge=1)]
    max_passages_per_claim: Annotated[int, Field(ge=1)]
    search_top_k_per_claim: Annotated[int, Field(ge=0)]
    max_span_chars: Annotated[int, Field(ge=1)]
    max_claims_per_call: Annotated[int, Field(ge=1)]
    max_digest_claims: Annotated[int, Field(ge=0)]
    rounding_match: bool
    conflict_min_shared_tokens: Annotated[int, Field(ge=1)]
    conflict_max_pairs: Annotated[int, Field(ge=0)]
    conflict_stop_words: Mapping[str, tuple[str, ...]]
    conflict_opposites: Mapping[str, tuple[tuple[str, str], ...]]
    conflict_negations: Mapping[str, tuple[str, ...]]
    advice_words: Mapping[str, tuple[str, ...]]
    """``factcheck.detect.advice_words`` per language (P10 recommendation wording)."""
    advice_suffixes: tuple[str, ...] = ()
    """Inflection suffixes tried after an advice word (config, e.g. ``ing``, ``ed``)."""
    quote_guard_min_words: Annotated[int, Field(ge=1)]
    """``factcheck.quote_guard.min_words``: a quoted span of this many words in a claim that is not
    typed as a quote makes it a guarded claim (never a model verdict; CCR-303)."""
    quote_attribution_patterns: Annotated[tuple[str, ...], Field(min_length=1)]
    """``factcheck.quote_guard.attribution_patterns`` (regular expressions, case-insensitive):
    wording that attributes words to a person without quotation marks, per language (English
    ``said``, ``wrote``; Marathi equivalents). Required and non-empty: an empty list would switch
    the guard off silently (fail closed, D16: data, not literals). Seeded production list:
    ``data/quote_guard.seed.json`` (provisional, needs editor review)."""
    quote_reported_speech_patterns: Annotated[tuple[str, ...], Field(min_length=1)]
    """``factcheck.quote_guard.reported_speech_patterns``: a person's view in reported speech
    (``believed``, ``argued``; Marathi ``मानत``). A claim that matches goes to HUMAN REVIEW (the
    library cannot prove it, the model must not judge it)."""
    quote_marks: QuoteMarkConfig
    """``factcheck.quote_guard.marks``: quotation mark pairs, categories, invisible separators."""
    quote_pattern_max_length: Annotated[int, Field(ge=1)]
    """``factcheck.quote_guard.pattern_max_length``: longest accepted pattern (characters)."""
    quote_pattern_max_repeat: Annotated[int, Field(ge=1)]
    """``factcheck.quote_guard.pattern_max_repeat``: largest finite repeat bound accepted."""
    max_repairs: Annotated[int, Field(ge=0, le=1)] = 1

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        missing = [t.value for t in ClaimType if t not in self.policy]
        if missing:
            raise ConfigInvalidError(
                "factcheck.verify.policy has no entry for a claim type",
                details={"missing": missing},
            )
        self._check_verdict_map()
        for pattern in (*self.quote_attribution_patterns, *self.quote_reported_speech_patterns):
            validate_pattern(
                pattern,
                max_length=self.quote_pattern_max_length,
                max_repeat=self.quote_pattern_max_repeat,
            )
        if len(set(self.tier_order)) != len(self.tier_order):
            raise ConfigInvalidError("tier_order has duplicates")
        for tier in (self.min_tier_for_verified, self.unranked_tier):
            if tier not in self.tier_order:
                raise ConfigInvalidError("tier is not in tier_order", details={"tier": tier})
        return self

    def _check_verdict_map(self) -> None:
        """Safety invariants of ``factcheck.verdict_map`` (13 1.1 item 7, NFR-12): complete over
        the four verifiable statuses; a contradicted claim is BLOCKED; doubt is never ALLOWED."""
        need = (
            ClaimStatus.VERIFIED,
            ClaimStatus.CONTRADICTED,
            ClaimStatus.NEEDS_SUBSTANTIATION,
            ClaimStatus.UNVERIFIABLE,
        )
        missing = [s.value for s in need if s not in self.verdict_map]
        if missing:
            raise ConfigInvalidError(
                "factcheck.verdict_map is incomplete", details={"missing": missing}
            )
        vm = self.verdict_map
        if vm[ClaimStatus.CONTRADICTED] is not Verdict.BLOCKED:
            raise ConfigInvalidError("verdict_map: CONTRADICTED must map to BLOCKED")
        for status in (ClaimStatus.NEEDS_SUBSTANTIATION, ClaimStatus.UNVERIFIABLE):
            if vm[status] is Verdict.ALLOWED:
                raise ConfigInvalidError(
                    "verdict_map: doubt never resolves to ALLOWED", details={"status": status.value}
                )

    def tier_rank(self, tier: str | None) -> int:
        """0 = best. A missing tier is the unranked tier (CCR-053)."""
        name = tier if tier is not None else self.unranked_tier
        if name not in self.tier_order:
            raise ConfigInvalidError("tier is not in tier_order", details={"tier": name})
        return self.tier_order.index(name)

    def meets_tier_floor(self, tier: str | None) -> bool:
        return self.tier_rank(tier) <= self.tier_rank(self.min_tier_for_verified)
