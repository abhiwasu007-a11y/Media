"""``agent_04.research_pack.output`` 1.0.0 (blueprint section 8): the research pack.

The pack carries no source passage text, only notes in original words and citation metadata.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from agent_04_research_knowledge.models.common import ConceptId, LanguageTag, RuleId
from agent_04_research_knowledge.models.enums import (
    ConceptKind,
    ConceptTimeReference,
    CopyGuardStatus,
    Coverage,
    ExclusionReason,
    FetchStatus,
    GapReason,
    ReliabilityTier,
    StatementKind,
)
from amw_core.contracts.common import AmwModel, Sha256Hex, StorageUri, UtcTimestamp
from amw_core.enums import (
    ComplianceVerdict,
    EvidenceSourceKind,
    KnowledgeSourceKind,
    SourceOwnership,
    TimeReferenceKind,
    VideoKind,
)

PACK_OUTPUT_SCHEMA = "agent_04.research_pack.output"
PACK_OUTPUT_SCHEMA_VERSION = "1.0.0"

EvidenceId = Annotated[str, StringConstraints(pattern=r"^ev_[0-9]{3,4}$")]
CitationRef = Annotated[str, StringConstraints(max_length=64)]
NonNeg = Annotated[int, Field(ge=0, strict=True)]
ApprovalIdStr = Annotated[str, StringConstraints(pattern=r"^apr_[0-9a-f-]{36}$")]


class TopicVerdict(AmwModel):
    verdict: ComplianceVerdict
    violated_rule_ids: tuple[RuleId, ...]


class PackTopic(AmwModel):
    title: str
    language: LanguageTag
    video_kind: VideoKind


class PackConcept(AmwModel):
    concept_id: ConceptId
    label: str
    label_en: str
    kind: ConceptKind
    evidence_needs: tuple[str, ...]
    time_reference: ConceptTimeReference
    coverage: Coverage
    evidence_ids: tuple[EvidenceId, ...]
    has_example: bool
    closes_gap_ids: tuple[str, ...]


class Locator(AmwModel):
    chapter: str | None
    page_from: int | None
    page_to: int | None


class EvidenceItem(AmwModel):
    evidence_id: EvidenceId
    concept_id: ConceptId
    statement_kind: StatementKind
    note: Annotated[str, StringConstraints(max_length=600)]
    time_reference_kind: TimeReferenceKind
    instruments: tuple[str, ...]
    citation_ref: CitationRef
    source_ref: CitationRef
    reliability_tier: ReliabilityTier
    owner_authored: bool
    method_labelled: bool
    usable_for_script: bool
    exclusion_reason: ExclusionReason | None
    copy_guard: CopyGuardStatus
    locator: Locator


class Citation(AmwModel):
    """Same shape as ``available_citations`` of ``agent_06.claim_extraction.input`` (CCR-053)."""

    citation_ref: CitationRef
    kind: Literal[EvidenceSourceKind.KNOWLEDGE_CHUNK, EvidenceSourceKind.EXTERNAL_REFERENCE]
    title: Annotated[str, StringConstraints(max_length=300)]
    content_sha256: Sha256Hex


class PackSource(AmwModel):
    source_ref: CitationRef
    kind: KnowledgeSourceKind
    title: str
    author: str | None
    edition: str | None
    ownership: SourceOwnership | None
    reliability_tier: ReliabilityTier
    reliability_score: float | None
    collection_key: str | None
    external_url: str | None
    accessed_at: UtcTimestamp | None
    fetch_status: FetchStatus
    content_sha256: Sha256Hex | None
    snapshot_ref: StorageUri | None

    @model_validator(mode="after")
    def _conditionals(self) -> Self:
        # Schema allOf: ext_ references have kind WEB_REFERENCE and null ownership; library rows
        # carry ownership, fetch_status OK, a hash and no snapshot; UNREACHABLE has no hash.
        if self.source_ref.startswith("ext_"):
            if self.ownership is not None or self.kind is not KnowledgeSourceKind.WEB_REFERENCE:
                raise ValueError("an external reference has null ownership and kind WEB_REFERENCE")
        elif (
            self.ownership is None
            or self.fetch_status is not FetchStatus.OK
            or self.snapshot_ref is not None
            or self.content_sha256 is None
        ):
            raise ValueError("a library source needs ownership, status OK, a hash, no snapshot")
        if self.fetch_status is FetchStatus.UNREACHABLE:
            if self.content_sha256 is not None or self.snapshot_ref is not None:
                raise ValueError("an UNREACHABLE source has no hash and no snapshot")
        elif self.content_sha256 is None:
            raise ValueError("a reachable source needs content_sha256")
        return self


class PackGap(AmwModel):
    concept_id: str
    reason: GapReason


class RestrictedPending(AmwModel):
    collection_key: str
    concept_ids: tuple[str, ...]


class MethodInfo(AmwModel):
    used: bool
    release_approval_ids: tuple[ApprovalIdStr, ...]
    restricted_pending: tuple[RestrictedPending, ...]


class FurtherReading(AmwModel):
    source_ref: str
    title: str
    author: str | None
    edition: str | None


class TerminologyHit(AmwModel):
    term: Annotated[str, StringConstraints(max_length=120)]
    term_en: Annotated[str, StringConstraints(max_length=120)]
    glossary_term_id: Annotated[str, StringConstraints(max_length=64)]


class CoverageSummary(AmwModel):
    concepts_total: int
    sourced: int
    partial: int
    unsourced: int
    evidence_total: int
    evidence_usable: int
    excluded_forward_looking: int
    excluded_copy_guard: int


class Provenance(AmwModel):
    plan_prompt_id: str
    notes_prompt_id: str
    rule_pack_versions: dict[str, str]
    llm_calls: int


class ResearchPack(AmwModel):
    pack_version: Literal[1]
    iteration: Annotated[int, Field(ge=0, strict=True)]
    topic_verdict: TopicVerdict
    topic: PackTopic
    concepts: Annotated[tuple[PackConcept, ...], Field(max_length=40)]
    evidence: Annotated[tuple[EvidenceItem, ...], Field(max_length=600)]
    citations_available: tuple[Citation, ...]
    sources: tuple[PackSource, ...]
    gaps: tuple[PackGap, ...]
    method: MethodInfo
    further_reading: tuple[FurtherReading, ...]
    terminology: tuple[TerminologyHit, ...]
    coverage_summary: CoverageSummary
    provenance: Provenance


__all__ = [
    "Citation",
    "CoverageSummary",
    "EvidenceItem",
    "FurtherReading",
    "Locator",
    "MethodInfo",
    "PackConcept",
    "PackGap",
    "PackSource",
    "PackTopic",
    "Provenance",
    "ResearchPack",
    "RestrictedPending",
    "TerminologyHit",
    "TopicVerdict",
]
