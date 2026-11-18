"""Test harness for owner evidence: a fake database with the three roles, the verifier
component, and an operator-side view with the method names the evidence tests use."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from amw_core.enums import EvidenceState
from amw_core.ids import WireId
from amw_core.interfaces import DbRole, EvidenceRecord, HumanRecord, NewEvidence, TenantTransaction
from amw_core.owner_evidence_fake import FakeEvidenceDatabase, MemorySessionEventSource
from amw_core.owner_evidence_mac import MacKeyring
from amw_core.owner_evidence_service import EvidenceVerifierService
from amw_core.owner_evidence_verifier import VerifierPolicy

# Test-only secrets, built at runtime (never a real credential).
PASSWORDS = {role: f"test-{role.value}-pw" for role in DbRole}
TEST_KEY = bytes(range(32))


class EvidenceHarness:
    def __init__(
        self, source: MemorySessionEventSource, policy: VerifierPolicy, key: bytes = TEST_KEY
    ) -> None:
        self.source = source
        self.db = FakeEvidenceDatabase(PASSWORDS, MacKeyring({1: key}))
        self.operator = self.db.login(DbRole.OPERATOR, PASSWORDS[DbRole.OPERATOR])
        self.app = self.db.login(DbRole.APP, PASSWORDS[DbRole.APP])
        verifier_session = self.db.login(DbRole.VERIFIER, PASSWORDS[DbRole.VERIFIER])
        self.verifier_session = verifier_session
        self.verifier = EvidenceVerifierService(self.db, verifier_session, source, policy)

    # operator side
    def record(self, tx: TenantTransaction, evidence: NewEvidence, **kw: Any) -> EvidenceRecord:
        return self.db.insert_evidence(self.operator, tx, evidence, **kw)

    def apply(
        self, tx: TenantTransaction, evidence_id: WireId, text: str | None = None
    ) -> HumanRecord:
        return self.db.human_record_apply(self.operator, tx, evidence_id, text)

    # verifier side
    def verify_recorded(
        self, tx: TenantTransaction, evidence_id: WireId, anchor: datetime | None, now: datetime,
        allowed_stages: frozenset[str] | None = None,
    ) -> EvidenceRecord:  # fmt: skip
        return self.verifier.verify_recorded(tx, evidence_id, anchor, now, allowed_stages)

    def confirm(
        self, tx: TenantTransaction, evidence_id: WireId, session_id: str, event_uuid: str,
        quote: str, now: datetime,
    ) -> EvidenceRecord:  # fmt: skip
        return self.verifier.confirm(tx, evidence_id, session_id, event_uuid, quote, now)

    def refuse(self, tx: TenantTransaction, evidence_id: WireId, reason: str) -> EvidenceRecord:
        return self.db.refuse(self.verifier_session, tx, evidence_id, reason, {})

    # reads
    def get(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceRecord | None:
        return self.db.get(self.app, tx, evidence_id)

    def for_subject(
        self, tx: TenantTransaction, subject_kind: str, subject_id: WireId
    ) -> Sequence[EvidenceRecord]:
        return self.db.for_subject(self.app, tx, subject_kind, subject_id)

    def mac_valid(self, tx: TenantTransaction, evidence_id: WireId) -> bool:
        return self.db.mac_valid(self.app, tx, evidence_id)

    def state(self, tx: TenantTransaction, evidence_id: WireId) -> EvidenceState:
        row = self.get(tx, evidence_id)
        assert row is not None
        return row.state
