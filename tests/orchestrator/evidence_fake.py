"""In-memory ``EvidenceStatusLookup`` (the port of ``amw_orchestrator.approval_binding``) for
tests: a TEST_FIXTURE desk records the evidence it invents, so the dry-run chain keeps working in
DRY_RUN and is refused in a real run."""

from dataclasses import replace

from amw_core.ids import OWNER_EVIDENCE
from amw_core.owner_evidence_status import (
    OWNER_CHAT_OPERATOR,
    EvidenceSourceKind,
    EvidenceStatus,
)


class FakeEvidenceStatuses:
    def __init__(self) -> None:
        self.rows: dict[str, EvidenceStatus] = {}

    def record(
        self,
        org_id: str,
        subject_kind: str,
        subject_id: str,
        *,
        state: str = "CONFIRMED",
        source: EvidenceSourceKind = EvidenceSourceKind.TEST_FIXTURE,
        mac_valid: bool = True,
        recorded_from: str = OWNER_CHAT_OPERATOR,
    ) -> str:
        evidence_id = str(OWNER_EVIDENCE.new())
        self.rows[evidence_id] = EvidenceStatus(
            evidence_id=evidence_id,
            evidence_state=state,
            recorded_from=recorded_from,
            org_id=org_id,
            kind=None,
            subject_kind=subject_kind,
            subject_id=subject_id,
            subject=None,
            source_kind=source,
            mac_valid=mac_valid,
        )
        return evidence_id

    def change(self, evidence_id: str, **fields: object) -> None:
        self.rows[evidence_id] = replace(self.rows[evidence_id], **fields)  # type: ignore[arg-type]

    def get(self, evidence_id: str) -> EvidenceStatus | None:
        return self.rows.get(evidence_id)
