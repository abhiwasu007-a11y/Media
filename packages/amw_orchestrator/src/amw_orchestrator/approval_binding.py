"""An approval authorises only what it was given for (SAFETY: a stale approval never authorises a
different render). Used by the builder that consumes an ``svc_s07.request_approval.output``.

PROVISIONAL (CCR-296, PROPOSED). Fail closed: the approval is accepted only if ALL of these hold,
checked against the CURRENT subject of the stage being authorised (never against the approval
itself):

* the output is a well-formed ``ApprovalOutput`` (CCR-283), ``state`` ``APPROVED``, of the
  expected ``approval_kind``;
* ``subject_sha256`` equals the SHA-256 of the current subject (03 section 11.6 rule 1);
* it names at least one evidence ID, and EVERY one is read through the ``EvidenceStatusLookup``
  port (``amw_core.owner_evidence_status``) and is ``CONFIRMED``, owner-chat, MAC-valid, of the
  run's org, bound to the same subject kind and ID as the approval, and ``REAL`` (a
  ``TEST_FIXTURE`` row only when the run is a dry run: the rule of the run preflight);
* no port, or an ID the port does not know, refuses.

What the port cannot say today (``EvidenceStatus`` carries neither the approval ID nor the
subject hash of the evidence row) is listed in CCR-296; the subject kind and ID of the row are
the binding available now.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from amw_core.errors import InputInvalidError
from amw_core.owner_evidence_real import FIN_R10, PROVIDER_LIMIT
from amw_core.owner_evidence_status import (
    OWNER_CHAT_OPERATOR,
    EvidenceSourceKind,
    EvidenceStatusLookup,
)
from amw_orchestrator.payloads import ApprovalOutput

_CONFIRMATION_KINDS: frozenset[str] = frozenset({PROVIDER_LIMIT, FIN_R10})
"""``EvidenceStatus.kind`` values of the confirmation bindings (provider limit, FIN R10). Such a
row backs a different claim and is never the evidence of an approval decision. ``EvidenceStatus``
has no record kind, so "is an approval-decision row" is not decidable yet (CCR-296)."""


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
    evidence: EvidenceStatusLookup | None,
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
        raise _refuse(stage_id, "no evidence reader: the evidence cannot be confirmed")
    for evidence_id in approval.evidence_ids:
        row = evidence.get(evidence_id)
        if row is None:
            raise _refuse(stage_id, "evidence row not found")
        if not row.mac_valid:
            raise _refuse(stage_id, "evidence MAC is not valid")
        if row.evidence_state != "CONFIRMED" or row.recorded_from != OWNER_CHAT_OPERATOR:
            raise _refuse(stage_id, "evidence is not CONFIRMED from the owner chat")
        if row.source_kind is EvidenceSourceKind.TEST_FIXTURE:
            if real_run:
                raise _refuse(stage_id, "TEST_FIXTURE evidence refused in a real run")
        elif row.source_kind is not EvidenceSourceKind.REAL:
            raise _refuse(stage_id, "evidence source is neither REAL nor TEST_FIXTURE")
        if row.evidence_id != evidence_id or row.org_id != org_id:
            raise _refuse(stage_id, "evidence belongs to another org")
        if row.kind in _CONFIRMATION_KINDS:
            raise _refuse(stage_id, "evidence is a confirmation binding, not an owner decision")
        if row.subject_kind != subject.kind or row.subject_id != subject.id:
            raise _refuse(stage_id, "evidence is bound to another subject")
    return approval
