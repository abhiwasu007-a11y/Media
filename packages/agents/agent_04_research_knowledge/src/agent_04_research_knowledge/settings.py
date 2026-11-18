"""``ResearchSettings``: the ``research.*`` and ``llm.agent_04.research_pack.*`` config keys.

Every value is configuration (27 section 7.3 rule 1). No product default is written here: values
that blueprint section 6 marks REQUIRES REVIEW (tier scores, domain classes, copy-guard
thresholds) must be supplied, so the build holds no hidden number. ``from_flat`` reads the dotted
keys of the registry (``amw_core.config`` does not exist yet; core_needs) and fails with
``PERMANENT.CONFIG_INVALID`` on a missing or invalid key.
"""

from collections.abc import Mapping
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_04_research_knowledge.errors import ConfigInvalid
from agent_04_research_knowledge.guards.copy_guard import CopyThresholds
from agent_04_research_knowledge.models.enums import DomainClass, ReliabilityTier
from agent_04_research_knowledge.scoring.reliability import DomainClassRegistry, TierScores
from amw_core.enums import LlmModelTier

Pos = Annotated[int, Field(ge=1, strict=True)]
NonNeg = Annotated[int, Field(ge=0, strict=True)]
Ratio = Annotated[float, Field(gt=0.0, le=1.0)]


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanSettings(_Cfg):
    max_concepts: Annotated[int, Field(ge=1, le=40, strict=True)]
    max_queries_per_concept: Annotated[int, Field(ge=1, le=8, strict=True)]


class RetrievalSettings(_Cfg):
    top_k_per_concept: Pos
    candidate_pool_per_query: Pos
    max_chunks_per_source_per_concept: Pos
    statement_timeout_ms: Pos
    text_search_configs: dict[str, str]
    """language primary subtag to PostgreSQL text-search configuration name (REQUIRES REVIEW)."""
    default_text_search_config: str


class NotesSettings(_Cfg):
    max_note_chars: Annotated[int, Field(ge=50, le=600, strict=True)]
    max_notes_per_passage: Annotated[int, Field(ge=1, le=10, strict=True)]
    max_passages_per_call: Annotated[int, Field(ge=1, le=64, strict=True)]
    max_repair_rounds: Annotated[int, Field(ge=0, le=1, strict=True)]


class CopyGuardSettings(_Cfg):
    """Copy-guard thresholds (blueprint 10.6, YTG-R9, 13 section 8, IN-08).

    REQUIRES REVIEW (owner and counsel, H-6): every field below is a legal-risk threshold. There
    is no default in code; the values used in tests are PROPOSALS only (see the package README) and
    must be set on measured samples of the owner's real sources before any real library run.
    """

    max_verbatim_words: Annotated[int, Field(ge=3, le=20, strict=True)]
    """REQUIRES REVIEW (owner/counsel): a run of this many consecutive copied words fails."""
    ngram_n: Annotated[int, Field(ge=3, le=8, strict=True)]
    """REQUIRES REVIEW (owner/counsel): shingle size of the containment measure."""
    max_containment_ratio: Ratio
    """REQUIRES REVIEW (owner/counsel): share of the note's n-grams found in the passage."""
    max_lcs_ratio: Ratio
    """REQUIRES REVIEW (owner/counsel): windowed longest-common-subsequence share of the note."""
    fuzzy_edits: Annotated[int, Field(ge=0, le=3, strict=True)]
    """REQUIRES REVIEW (owner/counsel): edits tolerated inside one fuzzy aligned segment."""
    max_fuzzy_words: Annotated[int, Field(ge=3, le=60, strict=True)]
    """REQUIRES REVIEW (owner/counsel): matched words in one fuzzy segment that fail the note."""
    max_pack_source_coverage: Ratio
    """REQUIRES REVIEW (owner/counsel): share of a source passage all notes together may rebuild."""

    def thresholds(self) -> CopyThresholds:
        return CopyThresholds(
            self.max_verbatim_words, self.ngram_n, self.max_containment_ratio,
            self.max_lcs_ratio, self.fuzzy_edits, self.max_fuzzy_words,
        )  # fmt: skip


class ReliabilitySettings(_Cfg):
    tier_scores: dict[ReliabilityTier, float]
    domain_classes: dict[str, DomainClass]


class ExternalSettings(_Cfg):
    allowlist: tuple[str, ...]
    max_bytes: Pos
    timeout_ms: Pos
    max_redirects: Annotated[int, Field(ge=0, le=10, strict=True)]
    passage_target_chars: Pos


class StepLlm(_Cfg):
    """``llm.agent_04.research_pack.<step>.*`` plus the resolved model of the tier."""

    model_tier: LlmModelTier
    model: Annotated[str, Field(min_length=1)]
    temperature: Annotated[float, Field(ge=0.0, le=2.0)]
    max_output_tokens: Pos
    timeout_ms: Pos
    cost_budget_micros: NonNeg
    cache_system_prompt: bool


class LlmSettings(_Cfg):
    plan: StepLlm
    notes: StepLlm
    default_max_llm_calls: Pos
    """cap used when the Task Input ``resource_budget.max_llm_calls`` is absent."""


class IngestSettings(_Cfg):
    chunk_target_chars: Pos
    chunk_overlap_chars: NonNeg
    min_page_chars: NonNeg
    max_nonprintable_ratio: Annotated[float, Field(ge=0.0, le=1.0)]
    qa_sample_size: NonNeg
    qa_seed: NonNeg


class MemorySettings(_Cfg):
    project_ttl_ms: Pos


class ResearchSettings(_Cfg):
    plan: PlanSettings
    retrieval: RetrievalSettings
    notes: NotesSettings
    copy_guard: CopyGuardSettings
    reliability: ReliabilitySettings
    external: ExternalSettings
    llm: LlmSettings
    ingest: IngestSettings
    memory: MemorySettings
    min_tier_for_factual: ReliabilityTier
    inline_payload_max_bytes: Pos
    """``contracts.inline_payload_max_bytes``: larger payloads go to ``data_ref``."""

    def tier_scores(self) -> TierScores:
        return TierScores.from_mapping(
            {k.value: v for k, v in self.reliability.tier_scores.items()}
        )

    def domain_registry(self) -> DomainClassRegistry:
        return DomainClassRegistry(self.reliability.domain_classes)

    @classmethod
    def from_nested(cls, data: Mapping[str, Any]) -> Self:
        try:
            settings = cls.model_validate(data)
            settings.tier_scores()  # strictly decreasing A to D, else CONFIG_INVALID
        except ValidationError as exc:
            keys = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
            raise ConfigInvalid("research configuration invalid", details={"keys": keys}) from None
        return settings

    @classmethod
    def from_flat(cls, flat: Mapping[str, Any]) -> Self:
        """Dotted registry keys (``research.plan.max_concepts``) to the nested model.

        ``llm.agent_04.research_pack.<step>.<key>`` fills ``llm.<step>``;
        ``agent_04.llm.fallback_on_unavailable`` is not read (no fallback in 3A, blueprint 11).
        """
        nested: dict[str, Any] = {}

        def put(path: list[str], value: Any) -> None:
            node = nested
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = value

        for key, value in flat.items():
            parts = key.split(".")
            if parts[0] == "research":
                put(parts[1:], value)
            elif parts[:3] == ["llm", "agent_04", "research_pack"] and len(parts) == 5:
                put(["llm", parts[3], parts[4]], value)
            elif parts[:3] == ["llm", "agent_04", "caps"] and len(parts) == 4:
                put(["llm", parts[3]], value)
        return cls.from_nested(nested)
