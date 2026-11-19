"""Pydantic models of the four Agent 16 / S2 output payload schemas (blueprint section 8.2-8.5).

Each model is written by hand to match, field for field, the JSON Schema block that defines it in
``docs/v4/agents/agent_16_compliance_qa.md`` (the contract lives in the document, 03 section 2.1);
``tests/agents/agent_16_compliance_qa/test_payload_models.py`` compares every model with the
document block (shape, required set, enums, patterns, bounds) and fails when they differ. The
producers (``gate_payload``, ``score_payload``, ``auth_payload``, ``uniqueness_payload``) build
their dictionaries through these models, so a payload that does not match its schema is never
emitted (``AGENT.INCOMPLETE_OUTPUT``) and the registered model validates it again on the way out.
"""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import MISSING, BeforeValidator, Field, StringConstraints, ValidationError

from agent_16_compliance_qa.base import Model
from amw_core.contracts.common import Sha256Hex, StorageUri
from amw_core.enums import (
    AuthorisedAction,
    CheckVerdict,
    ComplianceVerdict,
    CrossVideoStatus,
    DisclosureDecision,
    FrameFinding,
    GateVerdict,
    QualityDimension,
)
from amw_core.errors import IncompleteOutputError

_UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


def _pattern(prefix: str) -> StringConstraints:
    return StringConstraints(pattern=f"^{prefix}_{_UUID7}$")


RenderId = Annotated[str, _pattern("rnd")]
ScriptId = Annotated[str, _pattern("scr")]
RulePackId = Annotated[str, _pattern("rpk")]
VerdictId = Annotated[str, _pattern("cvd")]
QualityScoreId = Annotated[str, _pattern("qsc")]
EvidenceId = Annotated[str, _pattern("oie")]
StageId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,32}$")]
Number = Annotated[float, Field(strict=True)]
Unit = Annotated[float, Field(strict=True, ge=0, le=1)]
NonNegInt = Annotated[int, Field(strict=True, ge=0)]


def _iso_date_text(value: object) -> object:
    if not isinstance(value, (str, date)):
        raise ValueError("a date is an ISO 8601 text")
    return value


IsoDate = Annotated[date, BeforeValidator(_iso_date_text)]
"""JSON Schema ``format: date``: accepts the ISO text (or a date) and nothing else."""


class RevisionFinding(Model):
    rule_id: str
    item_ref: str
    finding: str = Field(max_length=500)
    remedy_stage_id: StageId | None


# --- 8.2 agent_16.compliance_gate.output --------------------------------------------------
class GateSubject(Model):
    render_id: RenderId
    render_sha256: Sha256Hex
    script_id: ScriptId
    script_sha256: Sha256Hex


class PackRow(Model):
    key: str
    version: int = Field(strict=True, ge=1)
    rule_pack_id: RulePackId
    verdict: ComplianceVerdict


class RuleRow(Model):
    rule_id: str = Field(pattern=r"^[A-Z]{2,8}-R[0-9]{1,3}$")
    check_verdict: CheckVerdict
    compliance_verdict: ComplianceVerdict | None
    kind: Literal["DETERMINISTIC", "LLM_JUDGE"]
    rationale: str = Field(max_length=1000)
    evidence: dict[str, Any]
    precondition: str | None = None
    remedy_stage_id: StageId | None = None


class FrameCheck(Model):
    check_id: Literal["qc.watermark.visual", "qc.visual.no_synthetic_presenter"]
    finding: FrameFinding
    frame_ids: tuple[Annotated[str, StringConstraints(pattern=r"^f[0-9]{2,3}$")], ...]
    verdict: CheckVerdict
    rationale: str = Field(max_length=500)


class Disclosure(Model):
    decision: DisclosureDecision
    rationale: str
    report_text_key: str


class ReviewRequest(Model):
    rule_id: str
    approval_kind: Literal["SENSITIVE_CLAIM", "COPYRIGHT_DOUBT"]
    evidence_ref: str


class ComplianceGateOutput(Model):
    """``agent_16.compliance_gate.output`` 1.0.0 (section 8.2)."""

    verdict: ComplianceVerdict
    subject: GateSubject
    packs: tuple[PackRow, ...]
    rules: tuple[RuleRow, ...]
    frame_checks: tuple[FrameCheck, ...]
    disclosure: Disclosure
    earliest_compliant_publish_date: IsoDate | None = None
    review_requests: tuple[ReviewRequest, ...]
    revision_findings: tuple[RevisionFinding, ...]
    verdict_ids: tuple[VerdictId, ...]
    gate_verdict: GateVerdict | MISSING = MISSING
    provenance: dict[str, Any]


# --- 8.3 svc_s02.uniqueness_check.output --------------------------------------------------
class CrossVideo(Model):
    status: CrossVideoStatus
    prior_videos_compared: NonNegInt
    max_similarity: Unit | None


class UniquenessMeasures(Model):
    masked_structure_identical_to_template: bool
    template_text_share: Unit
    section_role_sequence_equal_to_template: bool
    shot_type_sequence_identity: Unit
    cross_video: CrossVideo


class UniquenessCheckOutput(Model):
    """``svc_s02.uniqueness_check.output`` 1.0.0 (section 8.3)."""

    verdict: ComplianceVerdict
    measures: UniquenessMeasures
    thresholds: dict[str, Number | None]
    precondition: str | None
    revision_findings: tuple[RevisionFinding, ...]
    report_ref: StorageUri


# --- 8.4 agent_16.quality_score.output ----------------------------------------------------
class Criterion(Model):
    criterion_id: str
    kind: Literal["DETERMINISTIC", "LLM_JUDGE"]
    max: Annotated[float, Field(strict=True, ge=0)]
    earned: Annotated[float, Field(strict=True, ge=0)]
    status: Literal["SCORED", "SKIPPED"]
    precondition: str | None
    evidence_refs: tuple[str, ...]


class DimensionScore(Model):
    dimension: QualityDimension
    max_points: int = Field(strict=True, ge=1)
    points: Annotated[float, Field(strict=True, ge=0)]
    scorer_kind: Literal["DETERMINISTIC", "LLM_JUDGE"]
    criteria: tuple[Criterion, ...]


class JudgedElement(Model):
    element_id: str
    score: int = Field(strict=True, ge=0, le=2)


class JudgedCheck(Model):
    check_id: Literal["edit.promise_alignment", "edit.hook.beat_content"]
    verdict: Literal["PASS", "WARN", "SKIPPED"]
    elements: tuple[JudgedElement, ...]
    rationale: str = Field(max_length=500)


class ScoreFinding(Model):
    rule_id: str | None
    item_ref: str
    finding: str = Field(max_length=500)
    remedy_stage_id: StageId | None


class QualityScoreOutput(Model):
    """``agent_16.quality_score.output`` 1.0.0 (section 8.4)."""

    gate: Literal["PASS", "FAIL", "NOT_GATING"]
    machine_total: Annotated[float, Field(strict=True, ge=0, le=100)]
    threshold: Number
    rubric_version: str
    dimensions: Annotated[tuple[DimensionScore, ...], Field(min_length=8, max_length=8)]
    judged_checks: tuple[JudgedCheck, ...]
    quality_score_ids: tuple[QualityScoreId, ...]
    judge_calls: int = Field(strict=True, ge=0, le=3)
    revision_findings: tuple[ScoreFinding, ...]
    gate_verdict: GateVerdict | MISSING = MISSING
    provenance: dict[str, Any]


# --- 8.5 agent_16.publication_authorisation.output ----------------------------------------
class AuthSubject(Model):
    render_id: RenderId
    render_sha256: Sha256Hex
    script_id: ScriptId
    script_sha256: Sha256Hex
    thumbnail_set_sha256: tuple[Sha256Hex, ...]


class GuardRow(Model):
    guard_id: Literal[
        "G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G9a", "G10", "G11", "G12",
        "G13", "G14",
    ]  # fmt: skip
    result: Literal["PASS", "FAIL", "SKIPPED"]
    detail: str = Field(max_length=500)


class DimensionUsed(Model):
    dimension: QualityDimension
    machine: Number
    human: Number | None
    used: Number


class PublicationAuthorisationOutput(Model):
    """``agent_16.publication_authorisation.output`` 1.0.0 (section 8.5)."""

    verdict: Literal["ALLOWED", "BLOCKED"]
    is_final: Literal[True]
    authorised_action: AuthorisedAction | None
    subject: AuthSubject
    guards: tuple[GuardRow, ...]
    human_wins_total: Annotated[float, Field(strict=True, ge=0, le=100)]
    per_dimension_used: tuple[DimensionUsed, ...]
    evaluation_date: IsoDate
    earliest_compliant_publish_date: IsoDate | None
    evaluated_publish_date: IsoDate | None
    authorisation_verdict_id: VerdictId
    disclosure_verdict_id: VerdictId
    evidence_ids: tuple[EvidenceId, ...]
    report_ref: StorageUri


def emit[M: Model](model: type[M], data: dict[str, Any]) -> dict[str, Any]:
    """Validate a producer's payload dictionary and return its JSON form; a payload that does not
    match its schema is ``AGENT.INCOMPLETE_OUTPUT`` (03 section 5.3 rule 2), never emitted. The
    error names field locations only, never values."""
    try:
        return model.model_validate(data).model_dump(mode="json")
    except ValidationError as exc:
        where = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        raise IncompleteOutputError(
            "the payload does not match its schema",
            details={"model": model.__name__, "fields": where[:20]},
        ) from exc
