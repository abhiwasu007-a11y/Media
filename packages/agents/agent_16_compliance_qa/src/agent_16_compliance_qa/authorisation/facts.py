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
    recorded_by_operator: bool
    """Record and evidence both ``recorded_by = sys_operator``. Required (no fail-open default):
    the real-row path computes it; the dataset fixture 1.0.0 has no such field, so the eval
    harness states it from the fixture's own recorder facts."""
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


class ResolvingApproval(Model):
    """The approval whose step wrote an NHR resolution row (04 section 5.17, CCR-102). G5
    derives its state from its steps (G2 + G4); ``approvals.state`` is reported only."""

    kind: ApprovalKind
    state: ApprovalState
    subject_matches_item: bool
    """``approvals.subject_sha256`` = the subject hash of the NHR item being resolved."""
    steps: tuple[StepFacts, ...]


class NhrResolution(Model):
    verdict_is_final: bool
    decided_by_kind: ActorKind
    same_subject_hash: bool
    """The row's ``subject_sha256`` = the subject hash of the NHR item it resolves."""
    approval_channel: ApprovalChannel | None
    evidence: EvidenceFacts | None
    verdict: ComplianceVerdict = ComplianceVerdict.ALLOWED
    """The verdict the row stores; G5 requires it to equal the mapped step decision."""
    item_ref: str | None = None
    """The gate's NHR item (``rule_id`` + subject hash) this row resolves; ``None`` = unbound
    (G5 FAIL). The dataset fixture 1.0.0 has no such field (the eval harness derives it)."""
    step_state: ApprovalStepState | None = None
    """State of the step written together with the row; ``None`` = no such step (G5 FAIL)."""
    reuses_step_evidence: bool = False
    """The row cites the same evidence row and record key as that step (one record)."""
    resolving_approval: ResolvingApproval | None = None
    """``None`` = the approval named by the row is not visible (G5 FAIL)."""
    step_key: str | None = None
    """``<approval_id>:<step_no>`` of the step written with the row; one step backs one row."""


class GateFacts(Model):
    overall: ComplianceVerdict
    unresolved_nhr: int = Field(ge=0)
    """Reported only; a non-zero value fails G5, a zero value proves nothing (G5 binds every
    item in ``nhr_items`` to its own resolution)."""
    blocked_rows: int = Field(ge=0)
    nhr_resolutions: tuple[NhrResolution, ...]
    nhr_items: tuple[str, ...] = ()
    """The gate's ``NEEDS_HUMAN_REVIEW`` verdict rows as item refs (``rule_id`` + subject hash);
    an NHR gate with no item row fails G5 (nothing to bind a resolution to)."""


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
