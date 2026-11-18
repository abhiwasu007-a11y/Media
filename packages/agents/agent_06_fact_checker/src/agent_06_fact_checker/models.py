"""Pydantic models of every Agent 06 payload (blueprint 7 and 8; both prompt files).

They are the Pydantic twins of the JSON Schemas: ``agent_06.claim_extraction.input`` 1.1.0,
``agent_06.claim_extraction.output`` 1.0.0, ``agent_06.claim_verification.input`` 1.0.0,
``agent_06.claim_verification.batch.output`` 1.0.0 and ``agent_06.claim_verification.output``
1.0.0. Closed value sets come from ``amw_core.enums`` (GLOSSARY 6.38-6.41) or are the GLOSSARY
6.52 sets of blueprint 8.3 (declared here once; none is payload-local).
"""

from enum import StrEnum
from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from amw_core.contracts.common import AmwModel
from amw_core.enums import (
    ClaimStatus,
    ClaimType,
    ComplianceVerdict,
    RuleSeverity,
    TimeReferenceKind,
)

_UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
ScriptIdStr = Annotated[str, StringConstraints(pattern=rf"^scr_{_UUID7}$")]
ClaimIdStr = Annotated[str, StringConstraints(pattern=rf"^clm_{_UUID7}$")]
LocalIdStr = Annotated[str, StringConstraints(pattern=r"^c[0-9]{1,4}$")]
SegmentIdStr = Annotated[str, StringConstraints(pattern=r"^s[0-9]{1,4}$")]
ChartRefStr = Annotated[str, StringConstraints(pattern=r"^chart_[0-9a-z_]{1,32}$")]
RuleIdStr = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,8}-R[0-9]{1,3}$")]
RulePackKeyStr = Annotated[str, StringConstraints(pattern=r"^rp\.[a-z0-9_]+$")]
LanguageStr = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")]
CategoryStr = Annotated[str, StringConstraints(pattern=r"^[a-z_]{3,32}$")]
Sha256Str = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CitationRefStr = Annotated[str, StringConstraints(max_length=64)]
PosInt = Annotated[int, Field(ge=1)]
NonNegInt = Annotated[int, Field(ge=0)]

# Verdicts are ordered by severity (13 1.1 item 7: doubt never resolves to ALLOWED).
Verdict = ComplianceVerdict
_SEVERITY = {Verdict.ALLOWED: 0, Verdict.NEEDS_HUMAN_REVIEW: 1, Verdict.BLOCKED: 2}


def most_severe(*verdicts: Verdict) -> Verdict:
    """The most severe verdict (``ALLOWED`` < ``NEEDS_HUMAN_REVIEW`` < ``BLOCKED``)."""
    return max(verdicts, key=_SEVERITY.__getitem__, default=Verdict.ALLOWED)


class DataAge(StrEnum):
    OLDER_THAN_LAG = "OLDER_THAN_LAG"
    WITHIN_LAG = "WITHIN_LAG"
    UNKNOWN = "UNKNOWN"


class DataAgeBasis(StrEnum):
    MEASURED = "MEASURED"
    CONSTRAINT = "CONSTRAINT"


class VerifyMode(StrEnum):
    """Stage parameter ``verify_mode`` (two-value subset of ``factcheck_verify_mode``)."""

    EVIDENCE = "EVIDENCE"
    CHART_FACTS = "CHART_FACTS"


class ClaimMode(StrEnum):
    """GLOSSARY 6.52 ``factcheck_verify_mode`` (per claim)."""

    EVIDENCE = "EVIDENCE"
    CHART_FACTS = "CHART_FACTS"
    SKIPPED = "SKIPPED"
    CODE_ONLY = "CODE_ONLY"


class ReasonCode(StrEnum):
    """GLOSSARY 6.52 ``verification_reason_code`` (blueprint 8.3)."""

    NO_EVIDENCE_CANDIDATES = "NO_EVIDENCE_CANDIDATES"
    SKIPPED_BY_POLICY = "SKIPPED_BY_POLICY"
    QUOTE_NOT_ATTRIBUTABLE = "QUOTE_NOT_ATTRIBUTABLE"
    NO_CHART_FACTS = "NO_CHART_FACTS"
    CHART_PENDING = "CHART_PENDING"
    RESTRICTED_NOT_RELEASED = "RESTRICTED_NOT_RELEASED"
    CITATION_UNRESOLVABLE = "CITATION_UNRESOLVABLE"
    LOW_RELIABILITY_ONLY = "LOW_RELIABILITY_ONLY"
    NUMBER_NOT_IN_EVIDENCE = "NUMBER_NOT_IN_EVIDENCE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    NO_SCRIPT_CITATION = "NO_SCRIPT_CITATION"
    OVERREACH = "OVERREACH"
    CONTRADICTED_BY_EVIDENCE = "CONTRADICTED_BY_EVIDENCE"
    NOT_FOUND_IN_EVIDENCE = "NOT_FOUND_IN_EVIDENCE"
    MODEL_UNCERTAIN = "MODEL_UNCERTAIN"
    MODEL_REFUSED = "MODEL_REFUSED"
    INJECTED_EVIDENCE_DISCARDED = "INJECTED_EVIDENCE_DISCARDED"
    SPAN_INVALID = "SPAN_INVALID"
    CLAIM_CONFLICT = "CLAIM_CONFLICT"


class Assessment(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NOT_FOUND = "NOT_FOUND"
    UNCLEAR = "UNCLEAR"


class Certainty(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Relation(StrEnum):
    SUPPORTS = "SUPPORTS"
    PARTIAL = "PARTIAL"
    CONTRADICTS = "CONTRADICTS"


class EvidenceSourceKind(StrEnum):
    KNOWLEDGE_CHUNK = "KNOWLEDGE_CHUNK"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"
    CHART_FACT = "CHART_FACT"


class DiscrepancyKind(StrEnum):
    NUMBER = "NUMBER"
    UNIT = "UNIT"
    ENTITY = "ENTITY"
    DIRECTION = "DIRECTION"
    TIME_SCOPE = "TIME_SCOPE"
    NEGATION = "NEGATION"
    QUANTIFIER = "QUANTIFIER"
    CAUSATION = "CAUSATION"
    SCOPE = "SCOPE"
    DEFINITION = "DEFINITION"


class ConflictKind(StrEnum):
    NUMBER = "NUMBER"
    DIRECTION = "DIRECTION"
    DEFINITION = "DEFINITION"
    ENTITY = "ENTITY"
    TIME_SCOPE = "TIME_SCOPE"
    NEGATION = "NEGATION"


class RevisionAction(StrEnum):
    ADD_CITATION = "ADD_CITATION"
    CORRECT_CLAIM = "CORRECT_CLAIM"
    PROVIDE_EVIDENCE = "PROVIDE_EVIDENCE"
    RESOLVE_CONFLICT = "RESOLVE_CONFLICT"
    REMOVE_OR_REWORD = "REMOVE_OR_REWORD"


class PassageFlagKind(StrEnum):
    INJECTION_SUSPECTED = "INJECTION_SUSPECTED"
    UNREADABLE = "UNREADABLE"


class CitationKind(StrEnum):
    KNOWLEDGE_CHUNK = "KNOWLEDGE_CHUNK"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"


class RefusalReason(StrEnum):
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"
    RULE_WOULD_BE_BROKEN = "RULE_WOULD_BE_BROKEN"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    CONFLICTING_INSTRUCTIONS = "CONFLICTING_INSTRUCTIONS"
    UNSAFE_CONTENT = "UNSAFE_CONTENT"


class Refusal(AmwModel):
    """Refusal object of both prompt schemas (27 4.3, GLOSSARY 6.51)."""

    reason: RefusalReason
    message: Annotated[str, StringConstraints(max_length=1000)]
    missing_inputs: tuple[str, ...]
    violated_rule_ids: tuple[RuleIdStr, ...]


# ---------------------------------------------------------------- extraction input 1.1.0
class Segment(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"citation_refs"})

    segment_id: SegmentIdStr
    text: Annotated[str, StringConstraints(min_length=1, max_length=5000)]
    visual_refs: tuple[ChartRefStr, ...]
    citation_refs: tuple[CitationRefStr, ...] | None = None


class ChartDataRef(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"data_age_basis"})

    ref_id: ChartRefStr
    instrument: Annotated[str, StringConstraints(max_length=100)]
    data_age_vs_lag: DataAge | None
    data_age_basis: DataAgeBasis | None = None

    @property
    def basis(self) -> DataAgeBasis:
        return self.data_age_basis or DataAgeBasis.MEASURED


class AvailableCitation(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"content_sha256"})

    citation_ref: CitationRefStr
    kind: CitationKind
    title: Annotated[str, StringConstraints(max_length=300)]
    content_sha256: Sha256Str | None = None


class ExtractionInput(AmwModel):
    script_id: ScriptIdStr
    script_version: PosInt
    language: LanguageStr
    channel_category: CategoryStr
    owner_sebi_registration: str
    active_rule_packs: Annotated[tuple[RulePackKeyStr, ...], Field(min_length=1)]
    segments: Annotated[tuple[Segment, ...], Field(min_length=1, max_length=400)]
    chart_data_refs: tuple[ChartDataRef, ...]
    available_citations: tuple[AvailableCitation, ...]
    our_method_release_approved: bool

    @model_validator(mode="after")
    def _general_pack(self) -> Self:
        if "rp.youtube_general" not in self.active_rule_packs:
            raise ValueError("active_rule_packs must contain rp.youtube_general")
        return self


# ---------------------------------------------------------------- extraction output 1.0.0
class RuleFlag(AmwModel):
    rule_id: RuleIdStr
    severity: RuleSeverity
    evidence: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class ExtractedClaim(AmwModel):
    local_id: LocalIdStr
    segment_id: SegmentIdStr
    char_start: NonNegInt
    char_end: PosInt
    quote: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    normalized_claim: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    claim_type: ClaimType
    time_reference_kind: TimeReferenceKind
    instrument: Annotated[str, StringConstraints(max_length=100)] | None
    chart_data_ref: ChartRefStr | None
    requires_citation: bool
    citation_refs: tuple[CitationRefStr, ...]
    rule_flags: tuple[RuleFlag, ...]
    proposed_verdict: Verdict
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=600)]


class ExtractionOverall(AmwModel):
    proposed_verdict: Verdict
    blocking_rule_ids: tuple[RuleIdStr, ...]
    needs_human_review_reasons: tuple[Annotated[str, StringConstraints(max_length=300)], ...]


class ExtractionOutput(AmwModel):
    """Both the model's raw object and the final payload (verdict fields overwritten by D7)."""

    claims: Annotated[tuple[ExtractedClaim, ...], Field(max_length=500)]
    overall: ExtractionOverall
    refusal: Refusal | None

    @model_validator(mode="after")
    def _refusal_has_no_claims(self) -> Self:
        if self.refusal is not None and self.claims:
            raise ValueError("a refusal requires an empty claims list")
        return self


# ---------------------------------------------------------------- verification input 1.0.0
class VerificationClaim(AmwModel):
    claim_id: ClaimIdStr
    local_id: LocalIdStr
    segment_id: SegmentIdStr
    quote: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    normalized_claim: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    claim_type: ClaimType
    time_reference_kind: TimeReferenceKind
    instrument: Annotated[str, StringConstraints(max_length=100)] | None
    chart_data_ref: ChartRefStr | None
    requires_citation: bool
    citation_refs: tuple[CitationRefStr, ...]
    extraction_verdict: Verdict


class ChartFact(AmwModel):
    fact_id: Annotated[str, StringConstraints(pattern=r"^f[0-9]{2,3}$")]
    statement: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class ChartFacts(AmwModel):
    ref_id: ChartRefStr
    instrument: Annotated[str, StringConstraints(max_length=100)]
    facts: Annotated[tuple[ChartFact, ...], Field(max_length=200)]


class VerificationInput(AmwModel):
    script_id: ScriptIdStr
    script_version: PosInt
    script_sha256: Sha256Str
    verify_mode: VerifyMode
    iteration: NonNegInt
    language: LanguageStr
    channel_category: CategoryStr
    active_rule_packs: Annotated[tuple[RulePackKeyStr, ...], Field(min_length=1)]
    our_method_release_approved: bool
    extraction_overall_verdict: Verdict
    claims: Annotated[tuple[VerificationClaim, ...], Field(max_length=500)]
    available_citations: tuple[AvailableCitation, ...]
    chart_facts: tuple[ChartFacts, ...]
    claims_sha256: Sha256Str

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if "rp.youtube_general" not in self.active_rule_packs:
            raise ValueError("active_rule_packs must contain rp.youtube_general")
        if any(c.content_sha256 is None for c in self.available_citations):
            raise ValueError("available_citations[].content_sha256 is required for verification")
        return self


# ---------------------------------------------------------------- batch output (model)
class BatchEvidence(AmwModel):
    evidence_id: Annotated[str, StringConstraints(pattern=r"^[pf][0-9]{2,3}$")]
    relation: Relation
    span_start: NonNegInt
    span_end: PosInt


class BatchDiscrepancy(AmwModel):
    kind: DiscrepancyKind
    claim_value: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    evidence_value: Annotated[str, StringConstraints(min_length=1, max_length=80)]


class BatchResult(AmwModel):
    local_id: LocalIdStr
    assessment: Assessment
    evidence: Annotated[tuple[BatchEvidence, ...], Field(max_length=6)]
    discrepancies: Annotated[tuple[BatchDiscrepancy, ...], Field(max_length=6)]
    certainty: Certainty
    suggested_correction: Annotated[str, StringConstraints(max_length=300)] | None
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class BatchConflict(AmwModel):
    claim_a: LocalIdStr
    claim_b: LocalIdStr
    kind: ConflictKind
    explanation: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class PassageFlag(AmwModel):
    evidence_id: Annotated[str, StringConstraints(pattern=r"^p[0-9]{2,3}$")]
    flag: PassageFlagKind


class VerificationBatchOutput(AmwModel):
    results: Annotated[tuple[BatchResult, ...], Field(max_length=200)]
    claim_conflicts: Annotated[tuple[BatchConflict, ...], Field(max_length=50)]
    passage_flags: Annotated[tuple[PassageFlag, ...], Field(max_length=50)]
    refusal: Refusal | None

    @model_validator(mode="after")
    def _refusal_is_empty(self) -> Self:
        if self.refusal is not None and (self.results or self.claim_conflicts):
            raise ValueError("a refusal requires empty results and claim_conflicts")
        return self


# ---------------------------------------------------------------- verification output 1.0.0
class GateVerdict(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class OutputEvidence(AmwModel):
    source_kind: EvidenceSourceKind
    source_ref: CitationRefStr
    relation: Relation
    char_start: NonNegInt
    char_end: PosInt
    content_sha256: Sha256Str


class OutputDiscrepancy(AmwModel):
    kind: DiscrepancyKind
    claim_value: Annotated[str, StringConstraints(max_length=80)]
    evidence_value: Annotated[str, StringConstraints(max_length=80)]


class VerifiedClaim(AmwModel):
    claim_id: ClaimIdStr
    local_id: LocalIdStr
    mode: ClaimMode
    status: ClaimStatus
    reason_codes: tuple[ReasonCode, ...]
    verification_verdict: Verdict | None
    combined_verdict: Verdict
    assessment: Assessment | None
    certainty: Certainty | None
    script_cited: bool
    evidence: Annotated[tuple[OutputEvidence, ...], Field(max_length=6)]
    discrepancies: Annotated[tuple[OutputDiscrepancy, ...], Field(max_length=6)]
    suggested_correction: Annotated[str, StringConstraints(max_length=300)] | None
    suggested_citation_refs: tuple[CitationRefStr, ...]


class OutputConflict(AmwModel):
    claim_ids: Annotated[tuple[ClaimIdStr, ...], Field(min_length=2, max_length=2)]
    local_ids: Annotated[tuple[LocalIdStr, ...], Field(min_length=2, max_length=2)]
    kind: ConflictKind
    explanation: Annotated[str, StringConstraints(max_length=300)]


class RevisionRequest(AmwModel):
    claim_id: ClaimIdStr
    segment_id: SegmentIdStr
    action: RevisionAction
    detail: Annotated[str, StringConstraints(max_length=300)]
    suggested_citation_refs: tuple[CitationRefStr, ...]


class StatusCounts(AmwModel):
    EXTRACTED: NonNegInt
    VERIFIED: NonNegInt
    CONTRADICTED: NonNegInt
    UNVERIFIABLE: NonNegInt
    NEEDS_SUBSTANTIATION: NonNegInt


class VerificationOverall(AmwModel):
    proposed_verdict: Verdict
    verification_verdict: Verdict
    blocking_claim_ids: tuple[ClaimIdStr, ...]
    needs_human_review_reasons: tuple[Annotated[str, StringConstraints(max_length=300)], ...]
    counts: StatusCounts


class AccuracySummary(AmwModel):
    checkable_total: NonNegInt
    with_citation_or_chart: NonNegInt
    verified: NonNegInt
    contradicted: NonNegInt
    unverifiable: NonNegInt
    needs_substantiation: NonNegInt
    chart_pending: NonNegInt


class EvidenceScope(AmwModel):
    channel_scoped: Literal[True]
    restricted_used: bool


class Provenance(AmwModel):
    prompt_id: str
    prompt_sha256: Sha256Str
    llm_calls: NonNegInt
    batches: NonNegInt
    config_version: Annotated[str, StringConstraints(max_length=64)]
    evidence_scope: EvidenceScope


class VerificationOutput(AmwModel):
    script_id: ScriptIdStr
    script_version: PosInt
    script_sha256: Sha256Str
    verify_mode: VerifyMode
    iteration: NonNegInt
    gate_verdict: GateVerdict
    claims: Annotated[tuple[VerifiedClaim, ...], Field(max_length=500)]
    claim_conflicts: tuple[OutputConflict, ...]
    revision_requests: tuple[RevisionRequest, ...]
    overall: VerificationOverall
    accuracy_summary: AccuracySummary
    provenance: Provenance
