"""An approval authorises only what it was given for (SAFETY: a stale approval never authorises a
different render). Used by the builder that consumes an ``svc_s07.request_approval.output``.

CCR-296 (closed by this module with the S7 approval desk, CCR-297). Fail closed: the approval is
accepted only if ALL of these hold, checked against the CURRENT subject of the stage being
authorised (never against the approval itself):

* the output is a well-formed ``ApprovalOutput`` (CCR-283), ``state`` ``APPROVED``, of the
  expected ``approval_kind``, ``subject_sha256`` equal to the SHA-256 of the current subject
  (03 section 11.6 rule 1), naming at least one evidence ID;
* the ``ApprovalEvidencePort`` (``amw_core.owner_evidence_approvals``) answers
  ``approved(approval_id, subject_sha256)`` with an ``ApprovalEvidenceStatus`` (a base
  ``EvidenceStatus`` or ``None`` refuses) of kind ``APPROVAL_DECISION`` (a whitelist) that is
  ``CONFIRMED``, owner-chat, MAC-valid, of the run's org, of THIS approval (``approval_id``), of
  the current subject hash, ``decision`` ``APPROVED``, bound to the same subject kind and ID as the
  approval, and one of the output's ``evidence_ids``;
* its source is ``REAL`` (``TEST_FIXTURE`` only when the run is a dry run: the rule of the run
  preflight);
* no port refuses.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from amw_core.errors import InputInvalidError
from amw_core.owner_evidence_approvals import (
    APPROVAL_DECISION,
    ApprovalEvidencePort,
    ApprovalEvidenceStatus,
)
from amw_core.owner_evidence_status import OWNER_CHAT_OPERATOR, EvidenceSourceKind
from amw_orchestrator.payloads import ApprovalOutput


@dataclass(frozen=True, slots=True)
class ExpectedSubject:
    """What the stage being authorised works on NOW: ``approvals.subject_kind`` / ``subject_id``
    / ``subject_sha256`` (04 section 5.16)."""

    kind: str
    id: str
    sha256: str


def _refuse(stage_id: str, reason: str) -> InputInvalidError:
    return InputInvalidError(
        f"the approval of {stage_id} does not authorise this subject: {reason}",
        details={"stage_id": stage_id[:64], "reason": reason[:120]},
    )


def require_bound_approval(
    data: Mapping[str, Any],
    *,
    stage_id: str,
    approval_kind: str,
    subject: ExpectedSubject,
    org_id: str,
    evidence: ApprovalEvidencePort | None,
    real_run: bool,
) -> ApprovalOutput:
    """The validated approval, or a typed ``INPUT_INVALID`` refusal (fail closed)."""
    try:
        approval = ApprovalOutput.model_validate(dict(data))
    except ValidationError:
        raise _refuse(stage_id, "the approval output is not a valid approval") from None
    if approval.state != "APPROVED":
        raise _refuse(stage_id, f"state is {approval.state}, not APPROVED")
    if approval.approval_kind.value != approval_kind:
        raise _refuse(stage_id, "approval kind differs")
    if approval.subject_sha256 != subject.sha256:
        raise _refuse(stage_id, "subject hash differs from the current subject")
    if not approval.evidence_ids:
        raise _refuse(stage_id, "no owner evidence")
    if evidence is None:
        raise _refuse(stage_id, "no evidence port: the evidence cannot be confirmed")
    row = evidence.approved(approval.approval_id, subject.sha256)
    if row is None:
        raise _refuse(stage_id, "no approved evidence for this approval and subject")
    if not isinstance(row, ApprovalEvidenceStatus):
        raise _refuse(stage_id, "evidence is not an approval-decision status")
    if row.kind != APPROVAL_DECISION:
        raise _refuse(stage_id, "evidence is not an approval decision")
    if not row.mac_valid:
        raise _refuse(stage_id, "evidence MAC is not valid")
    if row.evidence_state != "CONFIRMED" or row.recorded_from != OWNER_CHAT_OPERATOR:
        raise _refuse(stage_id, "evidence is not CONFIRMED from the owner chat")
    if row.source_kind is EvidenceSourceKind.TEST_FIXTURE:
        if real_run:
            raise _refuse(stage_id, "TEST_FIXTURE evidence refused in a real run")
    elif row.source_kind is not EvidenceSourceKind.REAL:
        raise _refuse(stage_id, "evidence source is neither REAL nor TEST_FIXTURE")
    if row.org_id != org_id:
        raise _refuse(stage_id, "evidence belongs to another org")
    if row.approval_id != approval.approval_id:
        raise _refuse(stage_id, "evidence belongs to another approval")
    if row.subject_sha256 != subject.sha256:
        raise _refuse(stage_id, "evidence is bound to another subject hash")
    if row.decision != "APPROVED":
        raise _refuse(stage_id, f"evidence decision is {row.decision}, not APPROVED")
    if row.evidence_id not in approval.evidence_ids:
        raise _refuse(stage_id, "evidence is not one the approval names")
    if row.subject_kind != subject.kind or row.subject_id != subject.id:
        raise _refuse(stage_id, "evidence is bound to another subject")
    return approval
