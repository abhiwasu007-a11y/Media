"""Real-row R14 harness: the fake evidence database with its three login roles, the verifier
component, a fake session event store, and Agent 16's read side (``amw_app`` only)."""

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_16_compliance_qa.authorisation.evidence import (
    ApprovalAnchor,
    HumanRecordRef,
    OwnerEvidenceVerifier,
    StoreMacValidator,
)
from amw_core import ids
from amw_core.enums import (
    ApprovalChannel,
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.errors import MissingDependencyError, PermissionDeniedError
from amw_core.ids import WireId
from amw_core.interfaces import DbRole, EvidenceRecord, NewEvidence, TenantContext
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_fake import FakeEvidenceDatabase, MemorySessionEventSource
from amw_core.owner_evidence_mac import MacKeyring
from amw_core.owner_evidence_service import EvidenceVerifierService
from amw_core.owner_evidence_verifier import SessionEvent, VerifierPolicy
from amw_core.testing.memory import MemoryTransaction

PASSWORDS = {role: f"test-{role.value}-pw" for role in DbRole}  # test-only, built at runtime
KEY = bytes(range(32))
REQUESTED = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
SAID = REQUESTED + timedelta(minutes=5)
CONFIRM_AT = SAID + timedelta(minutes=1)
NOW = REQUESTED + timedelta(hours=1)
OWNER_ACCOUNT = "acct-owner"
POLICY = VerifierPolicy(
    human_inbound_origins=frozenset({"human"}),
    owner_account_ids=frozenset({OWNER_ACCOUNT}),
)
CODE = "R7K2"


class FakeIndex:
    """Test implementation of ``EvidenceUseIndex`` over the fake database (the L1 PostgreSQL
    version is an RLS query; core_need)."""

    def __init__(self, db: FakeEvidenceDatabase) -> None:
        self._db = db
        self.citations: dict[WireId, set[str]] = {}

    def live_rows_using_events(
        self, tx: TenantTransaction, event_uuids: frozenset[str]
    ) -> Sequence[EvidenceRecord]:
        org = tx.context.org_id
        return [
            r
            for (o, _), r in self._db._rows.items()
            if o == org
            and r.state is not EvidenceState.REFUSED
            and ({r.evidence.event_uuid, r.confirmation_event_uuid} & event_uuids)
        ]

    def record_keys_citing(self, tx: TenantTransaction, evidence_id: WireId) -> frozenset[str]:
        return frozenset(self.citations.get(evidence_id, set()))


@dataclass
class R14:
    org: ids.OrgId = field(default_factory=ids.ORG.new)
    owner: ids.UserId = field(default_factory=ids.USER.new)
    render: WireId = field(default_factory=lambda: ids.new_id(ids.Prefix.RENDER))
    approval: ids.ApprovalId = field(default_factory=ids.APPROVAL.new)
    job: ids.JobId = field(default_factory=ids.JOB.new)
    source: MemorySessionEventSource = field(default_factory=MemorySessionEventSource)

    def __post_init__(self) -> None:
        self.db = FakeEvidenceDatabase(PASSWORDS, MacKeyring({1: KEY}))
        self.operator = self.db.login(DbRole.OPERATOR, PASSWORDS[DbRole.OPERATOR])
        self.app = self.db.login(DbRole.APP, PASSWORDS[DbRole.APP])
        self.verifier_session = self.db.login(DbRole.VERIFIER, PASSWORDS[DbRole.VERIFIER])
        self.verifier = EvidenceVerifierService(self.db, self.verifier_session, self.source, POLICY)
        self.index = FakeIndex(self.db)
        self.reader = StoreMacValidator(self.db, self.app)
        self.a16 = OwnerEvidenceVerifier(self.reader, self.index)
        self._n = 0

    def tx(self, actor: str = "sys_operator", org: ids.OrgId | None = None) -> MemoryTransaction:
        return MemoryTransaction(TenantContext(org or self.org, ids.ActorRef(actor)))

    def anchor(self, created_at: datetime = REQUESTED, code: str = CODE) -> ApprovalAnchor:
        return ApprovalAnchor(self.approval, self.org, code, created_at)

    def event(self, content: str, at: datetime = SAID, **change: Any) -> SessionEvent:
        self._n += 1
        ev = SessionEvent(
            "ses-1", f"ev-{self._n}", "user", False, "human", content, at, OWNER_ACCOUNT, None
        )
        ev = replace(ev, **change)
        self.source.add(ev)
        return ev

    def new_evidence(
        self, ev: SessionEvent, kind: EvidenceRecordKind, **change: Any
    ) -> NewEvidence:
        base = NewEvidence(
            record_kind=kind,
            subject_kind="render",
            subject_id=self.render,
            source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
            session_id=ev.session_id,
            event_uuid=ev.event_uuid,
            quote=ev.content,
            message_at=ev.timestamp,
            recorded_by=ids.ActorRef("sys_operator"),
            on_behalf_of=self.owner,
            job_id=self.job,
            approval_id=self.approval,
            review_code=CODE,
            step_no=1 if kind is EvidenceRecordKind.STEP_DECISION else None,
            parsed_decision=ApprovalStepState.APPROVED
            if kind is EvidenceRecordKind.STEP_DECISION
            else None,
        )
        return replace(base, **change)

    def record(
        self,
        content: str,
        kind: EvidenceRecordKind = EvidenceRecordKind.STEP_DECISION,
        confirm: str | None = f"confirm {CODE}",
        anchor: datetime = REQUESTED,
        event_change: dict[str, Any] | None = None,
        confirm_change: dict[str, Any] | None = None,
        **change: Any,
    ) -> EvidenceRecord:
        """The operator records, the verifier verifies, the owner confirms (if ``confirm``)."""
        t = self.tx()
        ev = self.event(content, **(event_change or {}))
        row = self.db.insert_evidence(self.operator, t, self.new_evidence(ev, kind, **change))
        with contextlib.suppress(MissingDependencyError):  # unfetchable: stays pending
            row = self.verifier.verify_recorded(t, row.id, anchor, NOW)
        if confirm is not None and row.state is EvidenceState.VERIFIED:
            cev = self.event(confirm, at=CONFIRM_AT, **(confirm_change or {}))
            with contextlib.suppress(PermissionDeniedError, MissingDependencyError):
                row = self.verifier.confirm(
                    t, row.id, cev.session_id, cev.event_uuid, cev.content, NOW
                )  # a failed confirmation: VERIFIED
        got = self.db.get(self.app, t, row.id)
        assert got is not None
        return got

    def step_ref(self, evidence_id: WireId | None, **change: Any) -> HumanRecordRef:
        base = HumanRecordRef(
            record_kind=EvidenceRecordKind.STEP_DECISION,
            record_key=f"step:{self.approval}:1",
            org_id=self.org,
            subject_kind="render",
            subject_id=self.render,
            approval_id=self.approval,
            step_no=1,
            human=self.owner,
            approval_channel=ApprovalChannel.OWNER_CHAT_OPERATOR,
            recorded_by="sys_operator",
            evidence_id=evidence_id,
            step_state=ApprovalStepState.APPROVED,
        )
        return replace(base, **change)

    def score_ref(
        self,
        evidence_id: WireId | None,
        scores: tuple[tuple[QualityDimension, float], ...],
        **change: Any,
    ) -> HumanRecordRef:
        return self.step_ref(
            evidence_id,
            record_kind=EvidenceRecordKind.HUMAN_SCORE,
            record_key=f"score:{evidence_id}",
            step_no=None,
            step_state=None,
            scores=scores,
            **change,
        )

    def contribution_ref(
        self, evidence_id: WireId | None, text: str, **change: Any
    ) -> HumanRecordRef:
        return self.step_ref(
            evidence_id,
            record_kind=EvidenceRecordKind.CONTRIBUTION,
            record_key=f"contribution:{evidence_id}",
            step_no=None,
            step_state=None,
            description=text,
            **change,
        )
