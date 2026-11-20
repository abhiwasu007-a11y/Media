"""In-memory ``ApprovalEvidencePort`` (``amw_core.owner_evidence_approvals``) for tests: a
TEST_FIXTURE desk records the evidence it invents, so the dry-run chain keeps working in DRY_RUN
and is refused in a real run. Like the real port it is keyed by the approval ID asked for; unlike
it, it does not filter by decision or hash, so a test can make it return a row the consumer must
refuse (the consumer compares everything again)."""

from dataclasses import replace

from amw_core.ids import OWNER_EVIDENCE
from amw_core.owner_evidence_approvals import APPROVAL_DECISION, ApprovalEvidenceStatus
from amw_core.owner_evidence_status import OWNER_CHAT_OPERATOR, EvidenceSourceKind


class FakeEvidenceStatuses:
    def __init__(self) -> None:
        self.rows: dict[str, ApprovalEvidenceStatus] = {}
        self.by_approval: dict[str, str] = {}
        self.asked: list[tuple[str, str]] = []

    def record(
        self,
        org_id: str,
        subject_kind: str,
        subject_id: str,
        *,
        approval_id: str,
        subject_sha256: str,
        decision: str = "APPROVED",
        state: str = "CONFIRMED",
        source: EvidenceSourceKind = EvidenceSourceKind.TEST_FIXTURE,
        mac_valid: bool = True,
        recorded_from: str = OWNER_CHAT_OPERATOR,
    ) -> str:
        evidence_id = str(OWNER_EVIDENCE.new())
        self.rows[evidence_id] = ApprovalEvidenceStatus(
            evidence_id=evidence_id,
            evidence_state=state,
            recorded_from=recorded_from,
            org_id=org_id,
            kind=APPROVAL_DECISION,
            subject_kind=subject_kind,
            subject_id=subject_id,
            subject=None,
            source_kind=source,
            mac_valid=mac_valid,
            approval_id=approval_id,
            step_no=1,
            decision=decision,
            subject_sha256=subject_sha256,
            review_code="ABCD",
            parsed_target_stage_id=None,
        )
        self.by_approval[approval_id] = evidence_id
        return evidence_id

    def change(self, evidence_id: str, **fields: object) -> None:
        self.rows[evidence_id] = replace(self.rows[evidence_id], **fields)  # type: ignore[arg-type]

    def approved(self, approval_id: str, subject_sha256: str) -> ApprovalEvidenceStatus | None:
        self.asked.append((approval_id, subject_sha256))
        evidence_id = self.by_approval.get(approval_id)
        return self.rows.get(evidence_id) if evidence_id is not None else None
