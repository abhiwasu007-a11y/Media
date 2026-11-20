"""Reader of owner evidence for APPROVALS (3A-13; 03 section 11.6 rules 6 and 7; 04 section 5.16).

``ApprovalEvidenceLookup`` implements ``EvidenceStatusLookup`` (``owner_evidence_status``) over
the evidence tables, inside one tenant transaction. It answers for one evidence row only when the
row is really the decision of an approval step:

* the record kind is a step decision, the source is the owner chat, the state is ``CONFIRMED``
  and the database confirms the MAC (``amw_evidence_mac_valid``);
* the row names an approval of this tenant and carries exactly that approval's review code;
* the row's subject kind and ID equal the approval's subject (the approval itself holds the
  subject hash, so the chain evidence -> approval -> ``subject_sha256`` is the subject binding);
* the approval's step ``step_no`` of the row is DECIDED by exactly this evidence
  (``approval_steps.evidence_id``, written only by ``amw_human_record_apply``), with the same
  decision and the owner as ``decided_by``;
* no newer or equal decision record on the same subject and code supersedes it.

Anything else is ``None`` (fail closed; ``explain`` gives the reason for tests and logs). The
source is ``REAL`` only for the production mark in ``verifier_result`` (inside the MAC); a row
verified through the dry-run source reports ``TEST_FIXTURE`` and the consumer refuses it in a real
run. No key is read and no row is written.
"""

from dataclasses import dataclass
from typing import Final

from amw_core.approval_store_pg import ApprovalRecord, PgApprovalStore, StepRecord
from amw_core.enums import EvidenceRecordKind, EvidenceState, InstructionSourceKind
from amw_core.errors import InputInvalidError
from amw_core.ids import APPROVAL, ApprovalId, WireId
from amw_core.interfaces.owner_evidence import DbSession, EvidenceDatabase, EvidenceRecord
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_fake import PRODUCTION_MARK, TEST_MARK
from amw_core.owner_evidence_real import superseded
from amw_core.owner_evidence_review_code import is_valid_review_code
from amw_core.owner_evidence_status import (
    OWNER_CHAT_OPERATOR,
    EvidenceSourceKind,
    EvidenceStatus,
)

APPROVAL_DECISION: Final = "APPROVAL_DECISION"
DECISION_KINDS: Final = frozenset(
    {EvidenceRecordKind.STEP_DECISION, EvidenceRecordKind.KNOWLEDGE_RELEASE_REQUEST}
)


@dataclass(frozen=True, slots=True)
class ApprovalEvidenceStatus(EvidenceStatus):
    """``EvidenceStatus`` plus the approval binding (what PR 107 / CCR-296 asked the port for)."""

    approval_id: str
    step_no: int
    decision: str
    subject_sha256: str
    review_code: str
    parsed_target_stage_id: str | None


class ApprovalEvidenceLookup:
    def __init__(
        self,
        database: EvidenceDatabase,
        store: PgApprovalStore,
        session: DbSession,
        tx: TenantTransaction,
    ) -> None:
        self._db, self._store, self._session, self._tx = database, store, session, tx

    def get(self, evidence_id: str) -> ApprovalEvidenceStatus | None:
        status, _ = self._check(evidence_id, None)
        return status

    def get_for_approval(self, evidence_id: str, approval_id: str) -> ApprovalEvidenceStatus | None:
        """As ``get`` and the row must belong to ``approval_id``."""
        status, _ = self._check(evidence_id, approval_id)
        return status

    def explain(self, evidence_id: str, approval_id: str | None = None) -> str:
        """``bound`` or the first reason the row is refused."""
        status, reason = self._check(evidence_id, approval_id)
        return "bound" if status is not None else reason

    # ---- the checks ---------------------------------------------------------------------
    def _check(
        self, evidence_id: str, approval_id: str | None
    ) -> tuple[ApprovalEvidenceStatus | None, str]:
        try:
            row = self._db.get(self._session, self._tx, WireId(evidence_id))
        except InputInvalidError, ValueError:
            return None, "malformed evidence id"
        if row is None:
            return None, "evidence not found in this tenant"
        e = row.evidence
        if e.record_kind not in DECISION_KINDS:
            return None, "not a step decision"
        if e.source_kind is not InstructionSourceKind.OWNER_CHAT_MESSAGE:
            return None, "not an owner chat message"
        if row.state is not EvidenceState.CONFIRMED:
            return None, "evidence is not CONFIRMED"
        if e.approval_id is None or e.step_no is None or e.parsed_decision is None:
            return None, "evidence names no approval step decision"
        if approval_id is not None and e.approval_id != approval_id:
            return None, "evidence belongs to another approval"
        if not self._db.mac_valid(self._session, self._tx, row.id):
            return None, "evidence MAC is not valid"
        approval = self._store.get(self._tx, ApprovalId(e.approval_id))
        if approval is None or approval.org_id != row.org_id:
            return None, "approval not found in this tenant"
        reason = self._binding(row, approval)
        if reason:
            return None, reason
        step = self._store.step(self._tx, approval.id, e.step_no)
        reason = self._step_binding(row, approval, step)
        if reason or step is None:
            return None, reason or "step not found"
        siblings = self._db.for_subject(self._session, self._tx, e.subject_kind, e.subject_id)
        if superseded(row, siblings):
            return None, "a later decision supersedes this one"
        result = row.verifier_result
        real = result.get(PRODUCTION_MARK) is True and not result.get(TEST_MARK)
        sha = approval.subject_sha256
        if sha is None:  # pragma: no cover - _binding refused a hash-less approval
            return None, "the approval is bound to no subject hash"
        subject = "|".join(
            (APPROVAL_DECISION, approval.id, e.subject_kind, e.subject_id, sha, row.org_id)
        )
        return (
            ApprovalEvidenceStatus(
                evidence_id=row.id,
                evidence_state=row.state.value,
                recorded_from=OWNER_CHAT_OPERATOR,
                org_id=row.org_id,
                kind=APPROVAL_DECISION,
                subject_kind=e.subject_kind,
                subject_id=e.subject_id,
                subject=subject,
                source_kind=EvidenceSourceKind.REAL if real else EvidenceSourceKind.TEST_FIXTURE,
                mac_valid=True,
                approval_id=approval.id,
                step_no=e.step_no,
                decision=e.parsed_decision.value,
                subject_sha256=sha,
                review_code=approval.review_code,
                parsed_target_stage_id=e.parsed_target_stage_id,
            ),
            "bound",
        )

    @staticmethod
    def _binding(row: EvidenceRecord, approval: ApprovalRecord) -> str:
        e = row.evidence
        if approval.subject_sha256 is None:
            return "the approval is bound to no subject hash"
        code = (e.review_code or "").upper()
        if not is_valid_review_code(code, len(approval.review_code)):
            return "evidence carries no valid review code"
        if code != approval.review_code.upper():
            return "evidence carries another review code than the approval"
        if (e.subject_kind, e.subject_id) != (approval.subject_kind, approval.subject_id):
            return "evidence is bound to another subject than the approval"
        return ""

    @staticmethod
    def _step_binding(
        row: EvidenceRecord, approval: ApprovalRecord, step: StepRecord | None
    ) -> str:
        e = row.evidence
        if step is None:
            return "the approval has no such step"
        if step.evidence_id != row.id or not step.decided:
            return "the step is not decided by this evidence"
        if step.approval_channel != OWNER_CHAT_OPERATOR:
            return "the step was not decided through the owner chat"
        if e.parsed_decision is None or step.state.value != e.parsed_decision.value:
            return "the step decision differs from the evidence"
        if step.decided_by != e.on_behalf_of:
            return "the step was decided by another user"
        if e.step_no != approval.current_step:
            return "the evidence is not for the approval's current step"
        return ""


def approval_wire(approval_id: str) -> ApprovalId:
    """``ApprovalId`` from a wire string (``InputInvalidError`` if malformed)."""
    APPROVAL.to_uuid(ApprovalId(approval_id))
    return ApprovalId(approval_id)
