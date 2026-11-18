"""``agent_04.research_pack.plan.input`` / ``.output`` 1.0.0 (prompt research_pack_plan.v1)."""

from typing import Annotated

from pydantic import Field, StringConstraints

from agent_04_research_knowledge.models.common import (
    ChannelCategory,
    CollectionKey,
    ConceptId,
    GapId,
    LanguageTag,
    Refusal,
    RulePackKeyStr,
)
from agent_04_research_knowledge.models.enums import (
    ConceptKind,
    ConceptTimeReference,
    InputGapReason,
    QueryPurpose,
    StatementKind,
)
from amw_core.contracts.common import AmwModel
from amw_core.enums import KnowledgeSourceKind, VideoKind

PLAN_INPUT_SCHEMA = "agent_04.research_pack.plan.input"
PLAN_OUTPUT_SCHEMA = "agent_04.research_pack.plan.output"


class PlanCollection(AmwModel):
    collection_key: CollectionKey
    kind: KnowledgeSourceKind
    languages: tuple[str, ...]


class GlossaryTerm(AmwModel):
    term: Annotated[str, StringConstraints(max_length=120)]
    term_en: Annotated[str, StringConstraints(max_length=120)]


class PlanGap(AmwModel):
    gap_id: GapId
    gap_text: Annotated[str, StringConstraints(max_length=500)]
    reason: InputGapReason


class ResearchPlanInput(AmwModel):
    topic_title: Annotated[str, StringConstraints(min_length=3, max_length=400)]
    topic_brief: Annotated[str, StringConstraints(max_length=2000)] | None
    topic_angle: Annotated[str, StringConstraints(max_length=500)] | None
    video_language: LanguageTag
    channel_category: ChannelCategory
    active_rule_packs: Annotated[tuple[RulePackKeyStr, ...], Field(min_length=1)]
    video_kind: VideoKind
    collections: Annotated[tuple[PlanCollection, ...], Field(max_length=32)]
    library_languages: tuple[str, ...]
    glossary_terms: Annotated[tuple[GlossaryTerm, ...], Field(max_length=200)]
    revision_gaps: Annotated[tuple[PlanGap, ...], Field(max_length=50)]
    max_concepts: Annotated[int, Field(ge=1, le=40)]
    max_queries_per_concept: Annotated[int, Field(ge=1, le=8)]


class PlanQuery(AmwModel):
    text: Annotated[str, StringConstraints(min_length=2, max_length=120)]
    language: LanguageTag
    purpose: QueryPurpose


class PlannedConcept(AmwModel):
    concept_id: ConceptId
    label: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    label_en: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    kind: ConceptKind
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    evidence_needs: Annotated[tuple[StatementKind, ...], Field(min_length=1, max_length=8)]
    time_reference: ConceptTimeReference
    queries: Annotated[tuple[PlanQuery, ...], Field(min_length=1, max_length=8)]
    wants_method_material: bool
    closes_gap_ids: tuple[GapId, ...]
    target_collection_keys: tuple[CollectionKey, ...]


class ResearchPlan(AmwModel):
    concepts: Annotated[tuple[PlannedConcept, ...], Field(max_length=40)]
    out_of_scope_notes: Annotated[
        tuple[Annotated[str, StringConstraints(max_length=300)], ...], Field(max_length=20)
    ]
    refusal: Refusal | None
