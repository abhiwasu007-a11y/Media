"""The rows the authorisation guards read, as facts (blueprint section 6.5; the shape is the
``agent_16.publication_authorisation.fixture`` 1.0.0 schema of the eval README).

**Where the facts come from.** In production every ``EvidenceFacts`` is computed by
``authorisation.evidence.OwnerEvidenceVerifier`` from the stored ``owner_instruction_evidence``
row, re-checking the keyed MAC through ``amw_evidence_mac_valid`` (``EvidenceDatabase.mac_valid``)
under the ``amw_app`` role; every other fact is computed by
``authorisation.stage.PublicationAuthorisationStage`` from rows it reads itself. No caller,
task input, model output or operator message can supply a fact: the stage has no parameter that
accepts one. The eval harness builds facts from the dataset fixture directly (the README's
"rows the guard functions read"); the security tests build them from real rows of the fake
evidence database.
"""

from typing import Literal

from pydantic import Field

from agent_16_compliance_qa.base import Model
from amw_core.enums import (
    ApprovalChannel,
    ApprovalKind,
    ApprovalState,
    ApprovalStepState,
    ComplianceVerdict,
    DisclosureDecision,
    EditorialContributionType,
    EvidenceState,
    InstructionSourceKind,
    QualityDimension,
    RenderStatus,
)

VerifierTest = Literal[
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A6",
    "A7",
    "A8",
    "A9",
    "DECISION_GRAMMAR",
    "CONTENT_RULES",
    "SCORE_RULES",
    "CONFIRMATION_GRAMMAR",
]
RefusedReason = Literal[
    "NEEDS_CLARIFICATION", "NOT_OWNER_AUTHORED", "EVENT_NOT_FOUND", "CHECK_FAILED"
]
ActorKind = Literal["HUMAN", "AGENT"]
RecorderKind = Literal["OPERATOR", "SELF", "AGENT"]
RequestedAction = Literal["DELIVERY", "UPLOAD_PRIVATE", "PUBLISH"]


class EvidenceFacts(Model):
    """Every check G4 re-runs on one stored evidence row (clauses (a)-(f))."""

    state: EvidenceState
    source_kind: InstructionSourceKind
    same_org: bool
    on_behalf_of_matches: bool
    subject_matches: bool
    review_code_matches: bool
    parsed_decision_matches: bool | None
    message_after_request: bool
    confirmation_after_message: bool
    verifier_all_passed: bool
    failed_tests: tuple[VerifierTest, ...]
    refused_reason: RefusedReason | None
    hash_recomputes: bool
    mac_valid: bool
    replay_free: bool
    backs_only_this_record: bool
    recorded_by_operator: bool = True
    """Record and evidence both ``recorded_by = sys_operator``. The real-row path always sets it;
    the dataset fixture has no such field (its steps carry ``recorded_by_kind`` instead)."""
    evidence_id: str | None = None
    """``oie_`` id (real-row path only; reported in ``evidence_ids``)."""


class StepFacts(Model):
    step_no: int = Field(ge=1)
    state: ApprovalStepState
    decided_by_kind: ActorKind
    membership_active: bool
    holds_required_role: bool
    recorded_by_kind: RecorderKind
    approval_channel: ApprovalChannel | None
    evidence: EvidenceFacts | None


class ApprovalFacts(Model):
    kind: ApprovalKind
    state: ApprovalState
    subject_hash_matches_render: bool
    review_code_present: bool


class ContributionFacts(Model):
    type: EditorialContributionType
    description_chars: int = Field(ge=0)
    contributor_kind: ActorKind
    bound_to_this_approval: bool
    approval_channel: ApprovalChannel | None
    evidence: EvidenceFacts | None


class ReliedApproval(Model):
    kind: Literal["KNOWLEDGE_RELEASE", "SENSITIVE_CLAIM", "COPYRIGHT_DOUBT"]
    state: ApprovalState
    relied_on_by: Literal["FIN_R12", "YTG_R9_QUOTATION", "NHR_RESOLUTION"]
    steps: tuple[StepFacts, ...]


class HumanScoreFacts(Model):
    dimension: QualityDimension
    points: float = Field(ge=0)
    bound_to_render_hash: bool
    approval_channel: ApprovalChannel | None
    evidence: EvidenceFacts | None


class Scores(Model):
    machine: dict[QualityDimension, float]
    human: tuple[HumanScoreFacts, ...]


class NhrResolution(Model):
    verdict_is_final: bool
    decided_by_kind: ActorKind
    same_subject_hash: bool
    approval_channel: ApprovalChannel | None
    evidence: EvidenceFacts | None
    verdict: ComplianceVerdict = ComplianceVerdict.ALLOWED
    """The mapped step decision (``APPROVED -> ALLOWED``; anything else ``BLOCKED``, G6)."""


class GateFacts(Model):
    overall: ComplianceVerdict
    unresolved_nhr: int = Field(ge=0)
    blocked_rows: int = Field(ge=0)
    nhr_resolutions: tuple[NhrResolution, ...]


class RenderFacts(Model):
    status: RenderStatus
    blocking_qc_fail: int = Field(ge=0)


class LicenceFacts(Model):
    all_active: bool
    expiring: int = Field(ge=0)


class PriceLagFacts(Model):
    latest_price_age_days_at_evaluation: int = Field(ge=0)
    lag_days: int = Field(ge=0)


class AuthRows(Model):
    requested_action: RequestedAction
    approval: ApprovalFacts
    steps: tuple[StepFacts, ...]
    contributions: tuple[ContributionFacts, ...]
    other_approvals: tuple[ReliedApproval, ...]
    scores: Scores
    gate: GateFacts
    disclosure_decision: DisclosureDecision
    render: RenderFacts
    licences: LicenceFacts
    fin_r9: PriceLagFacts | None
    """``None`` when the video has no dated price data (G11 passes, nothing to age)."""
    hashes_unchanged: bool
    all_refs_same_org: bool
    threshold: float
    destination: Literal["FILE_DELIVERY", "YOUTUBE"] = "FILE_DELIVERY"
    """The job's destination (3A: FILE_DELIVERY only, D1)."""
