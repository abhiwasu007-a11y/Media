"""Payload schemas of ``svc_s07.request_approval`` for the registry (03 section 5.3 rule 2a).

PROVISIONAL (CCR-283, PROPOSED; namespace ownership CCR-282): the shapes below are the ones the
CCR-283 row proposes, each input field being one column the gate task writes to the ``approvals``
row (04 section 5.16), each output field a datum of 03 section 11.6. Nothing else is invented:
every model is ``extra = forbid`` and a document that does not match is refused fail closed
(``PERMANENT.SCHEMA_INVALID``). Loaded through the allow-list entry ``amw_orchestrator ->
svc_s07`` (CCR-282 clause 1: the namespace is owned by the package that implements the worker,
here ``ApprovalWorker``)."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from amw_core.contracts.payloads import PayloadRegistrar
from amw_core.enums import ApprovalKind

SCHEMA_VERSION = "1.0.0"
INPUT_SCHEMA = "svc_s07.request_approval.input"
OUTPUT_SCHEMA = "svc_s07.request_approval.output"

_UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ApprovalIdStr = Annotated[str, StringConstraints(pattern=rf"^apr_{_UUID7}$")]
EvidenceIdStr = Annotated[str, StringConstraints(pattern=rf"^oie_{_UUID7}$")]
SubjectIdStr = Annotated[str, StringConstraints(pattern=rf"^[a-z]{{3}}_{_UUID7}$")]
WorkflowKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
StageWord = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,39}$")]
Uri = Annotated[str, StringConstraints(min_length=1, max_length=1024)]

SubjectKind = Literal[
    "script", "render", "thumbnail", "metadata", "concept", "brief", "budget", "dead_letter",
    "experiment", "comment_reply", "knowledge_source", "knowledge_release", "asset", "voice",
    "channel",
]  # fmt: skip
"""The values 04 section 5.16 lists for ``approvals.subject_kind`` (the list ends with an open
``...``: a new kind is a CCR, so an unlisted kind is refused here)."""

ApprovalState = Literal[
    "PENDING", "APPROVED", "REJECTED", "CHANGES_REQUESTED", "EXPIRED", "WITHDRAWN"
]  # GLOSSARY 6.13
_DECIDED_BY_OWNER = frozenset({"APPROVED", "REJECTED", "CHANGES_REQUESTED"})
_ID_PREFIX_OF_KIND = {"script": "scr", "render": "rnd"}
"""Subjects whose entity has a GLOSSARY 2.2 prefix of its own (the two the graph approves)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApprovalSubject(_Strict):
    kind: SubjectKind  # approvals.subject_kind
    id: SubjectIdStr  # approvals.subject_id (wire form)
    sha256: Sha256  # approvals.subject_sha256
    ref: Uri | None = None  # approvals.subject_ref (CCR-070): only for a set subject

    @model_validator(mode="after")
    def _prefix_matches_the_kind(self) -> Self:
        want = _ID_PREFIX_OF_KIND.get(self.kind)
        if want is not None and not self.id.startswith(f"{want}_"):
            raise ValueError("subject id does not belong to the subject kind")
        return self


class ApprovalRequestInput(_Strict):
    """``svc_s07.request_approval.input`` 1.0.0 (CCR-283 PROVISIONAL)."""

    subject: ApprovalSubject
    approval_kind: ApprovalKind  # approvals.kind
    workflow_key: WorkflowKey  # approvals.workflow_key (24 ``gate / approval``)


class ApprovalOutput(_Strict):
    """``svc_s07.request_approval.output`` 1.0.0 (CCR-283 PROVISIONAL). ``PENDING`` while the
    task is suspended, a final state once decided (GLOSSARY 6.13)."""

    approval_id: ApprovalIdStr
    approval_kind: ApprovalKind
    state: ApprovalState
    subject_sha256: Sha256  # the hash the approval is bound to (03 section 11.6 rule 1)
    evidence_ids: tuple[EvidenceIdStr, ...]  # CONFIRMED owner evidence (03 section 11.6 rule 6)
    parsed_target_stage_id: StageWord | None  # stage word of a CHANGES_REQUESTED decision (rule 7)

    @model_validator(mode="after")
    def _decision_is_backed_by_evidence(self) -> Self:
        if self.state in _DECIDED_BY_OWNER and not self.evidence_ids:
            raise ValueError("an owner decision carries its confirmed evidence")
        if self.state == "CHANGES_REQUESTED":
            if self.parsed_target_stage_id is None:
                raise ValueError("a change request names its target stage")
        elif self.parsed_target_stage_id is not None:
            raise ValueError("only a change request carries a target stage")
        return self


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(INPUT_SCHEMA, SCHEMA_VERSION, ApprovalRequestInput)
    registrar.register(OUTPUT_SCHEMA, SCHEMA_VERSION, ApprovalOutput)
