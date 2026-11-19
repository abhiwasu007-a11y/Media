"""P4-19 (CCR-121, CCR-131): audit verbs of owner-chat evidence, written with the state change."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from amw_core import ids
from amw_core.audit.memory import MemoryAuditLog
from amw_core.enums import ActorKind, EvidenceRecordKind, EvidenceState, InstructionSourceKind
from amw_core.errors import InvalidTransitionError, MissingDependencyError, PermissionDeniedError
from amw_core.interfaces import TenantContext
from amw_core.owner_evidence_audit import (
    AUDIT_FAMILY,
    VERBS,
    AuditedEvidenceFlow,
    audit_action,
)
from amw_core.owner_evidence_fake import MemorySessionEventSource
from amw_core.owner_evidence_verifier import NewEvidence, SessionEvent, VerifierPolicy
from amw_core.testing.memory import MemoryTransaction
from tests.evidence_support import EvidenceHarness

REQUESTED = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
SAID = REQUESTED + timedelta(minutes=5)
NOW = REQUESTED + timedelta(hours=1)
POLICY = VerifierPolicy(
    human_inbound_origins=frozenset({"human"}),
    owner_account_ids=frozenset({"acct-owner"}),
    content_max_age_ms=24 * 3600 * 1000,
)
TEXT = "Use the 2008 crash as the opening example instead of 2020"
OWNER = ids.USER.new()


def event(content: str, uuid: str, at: datetime = SAID) -> SessionEvent:
    return SessionEvent("ses-1", uuid, "user", False, "human", content, at, "acct-owner", None)


def evidence(kind: EvidenceRecordKind, quote: str = TEXT, **change: Any) -> NewEvidence:
    base = NewEvidence(
        record_kind=kind,
        subject_kind="script",
        subject_id=ids.new_id(ids.Prefix.SCRIPT),
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        session_id="ses-1",
        event_uuid="ev-1",
        quote=quote,
        message_at=SAID,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=OWNER,
        job_id=ids.JOB.new(),
        review_code="R7K2",
    )
    return replace(base, **change)


NO_CODE_KINDS = (EvidenceRecordKind.OWNER_TOPIC, EvidenceRecordKind.DATASET_INTAKE)


def first_message(kind: EvidenceRecordKind) -> str:
    """CCR-116: OWNER_TOPIC / DATASET_INTAKE precede the job and carry no code in the first
    message (the store issues it); other kinds carry the code they were asked for."""
    return TEXT if kind in NO_CODE_KINDS else f"For R7K2: {TEXT}."


def new_evidence(kind: EvidenceRecordKind) -> NewEvidence:
    return evidence(kind, review_code=None if kind in NO_CODE_KINDS else "R7K2")


class World:
    def __init__(self, *events: SessionEvent) -> None:
        self.harness = EvidenceHarness(MemorySessionEventSource(events), POLICY)
        self.log = MemoryAuditLog()
        self.org = ids.ORG.new()
        self.tx = MemoryTransaction(TenantContext(self.org, ids.ActorRef("sys_operator")))
        self.flow = AuditedEvidenceFlow(
            self.harness.db, self.harness.operator, self.harness.verifier, self.log
        )

    def actions(self, org: ids.OrgId | None = None) -> list[str]:
        tx = MemoryTransaction(TenantContext(org or self.org, ids.ActorRef("sys_operator")))
        return [r.entry.action for r in self.log.export(tx)]


def test_every_record_kind_has_a_family_and_the_three_verbs() -> None:
    assert set(AUDIT_FAMILY) == set(EvidenceRecordKind)
    assert VERBS == ("recorded_from_owner_chat", "owner_confirmed", "record_refused")
    assert set(AUDIT_FAMILY.values()) == {
        "approval",
        "editorial_contribution",
        "quality_score",
        "owner_topic",
        "asset_intake",
    }
    assert audit_action(EvidenceRecordKind.OWNER_TOPIC, EvidenceState.VERIFIED) == (
        "owner_topic.recorded_from_owner_chat"
    )
    assert audit_action(EvidenceRecordKind.DATASET_INTAKE, EvidenceState.CONFIRMED) == (
        "asset_intake.owner_confirmed"
    )
    assert audit_action(EvidenceRecordKind.OWNER_TOPIC, EvidenceState.REFUSED) == (
        "owner_topic.record_refused"
    )
    with pytest.raises(InvalidTransitionError):
        audit_action(EvidenceRecordKind.OWNER_TOPIC, EvidenceState.PENDING_VERIFICATION)


@pytest.mark.parametrize(
    ("kind", "family"),
    [
        (EvidenceRecordKind.OWNER_TOPIC, "owner_topic"),
        (EvidenceRecordKind.DATASET_INTAKE, "asset_intake"),
        (EvidenceRecordKind.CONTRIBUTION, "editorial_contribution"),
    ],
)
def test_verify_and_confirm_write_verbs_in_order(kind: EvidenceRecordKind, family: str) -> None:
    w = World(event(first_message(kind), "ev-1"))
    row = w.flow.record(w.tx, new_evidence(kind), NOW)
    code = row.evidence.review_code
    assert code is not None
    w.harness.source.add(event(f"{code} confirmed", "ev-2", SAID + timedelta(seconds=1)))
    assert w.actions() == []  # a pending insert is not yet a record
    assert w.flow.verify(w.tx, row.id, REQUESTED, NOW).state is EvidenceState.VERIFIED
    done = w.flow.confirm(w.tx, row.id, "ses-1", "ev-2", "confirmed", NOW)
    assert done.state is EvidenceState.CONFIRMED
    assert w.actions() == [f"{family}.recorded_from_owner_chat", f"{family}.owner_confirmed"]
    first = next(iter(w.log.export(w.tx)))
    assert first.entry.actor_ref == "sys_operator"
    assert first.entry.actor_kind is ActorKind.SYSTEM
    assert first.entry.on_behalf_of == OWNER
    assert first.entry.target_id == row.id
    assert first.entry.details["evidence_sha256"] == row.evidence_sha256
    assert w.log.verify_chain(w.tx).ok


def test_refused_verification_is_audited_without_the_quote() -> None:
    w = World(event("what about " + TEXT + "?", "ev-1"))
    row = w.flow.record(w.tx, new_evidence(EvidenceRecordKind.OWNER_TOPIC), NOW)
    out = w.flow.verify(w.tx, row.id, None, NOW)
    assert out.state is EvidenceState.REFUSED
    assert w.actions() == ["owner_topic.record_refused"]
    entry = next(iter(w.log.export(w.tx))).entry
    assert entry.details["refused_reason"] == out.refused_reason
    assert entry.details["failed_checks"]
    assert TEXT not in str(entry.details)


def test_operator_refused_attempt_is_audited() -> None:
    w = World()
    row = w.flow.record(
        w.tx,
        new_evidence(EvidenceRecordKind.DATASET_INTAKE),
        NOW,
        state=EvidenceState.REFUSED,
        refused_reason="source_owner_chat",
    )
    assert row.state is EvidenceState.REFUSED
    assert w.actions() == ["asset_intake.record_refused"]


def test_unfetchable_event_writes_nothing() -> None:
    w = World()
    pending = w.flow.record(w.tx, new_evidence(EvidenceRecordKind.OWNER_TOPIC), NOW)
    with pytest.raises(MissingDependencyError):
        w.flow.verify(w.tx, pending.id, None, NOW)
    assert w.actions() == []


def test_failed_confirmation_is_audited_as_a_refused_attempt_and_the_row_stays_verified() -> None:
    w = World(event(TEXT, "ev-1"))
    row = w.flow.record(w.tx, new_evidence(EvidenceRecordKind.OWNER_TOPIC), NOW)
    w.flow.verify(w.tx, row.id, None, NOW)
    with pytest.raises(MissingDependencyError):  # the confirmation event is not fetchable
        w.flow.confirm(w.tx, row.id, "ses-1", "ev-missing", "confirmed", NOW)
    assert w.actions() == ["owner_topic.recorded_from_owner_chat"]
    with pytest.raises(PermissionDeniedError):
        # the same event as the evidence is not a distinct confirmation
        w.flow.confirm(w.tx, row.id, "ses-1", "ev-1", "confirmed", NOW)
    assert w.actions() == ["owner_topic.recorded_from_owner_chat", "owner_topic.record_refused"]
    entry = list(w.log.export(w.tx))[-1].entry
    assert entry.details["attempt"] == "confirmation"
    assert entry.details["state"] == "VERIFIED"
    assert entry.details["failed_checks"]
    assert TEXT not in str(entry.details)
    assert w.harness.db.get(w.harness.operator, w.tx, row.id).state is EvidenceState.VERIFIED  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "free_text",
    [TEXT, "owner said: " + TEXT, "sk-live-abcdef0123456789", "Q9Z3 and more", "a" * 300],
)
def test_operator_free_text_reason_never_reaches_the_audit(free_text: str) -> None:
    w = World()
    row = w.flow.record(
        w.tx,
        new_evidence(EvidenceRecordKind.DATASET_INTAKE),
        NOW,
        state=EvidenceState.REFUSED,
        refused_reason=free_text,
    )
    assert row.refused_reason == "operator_refused"
    entry = next(iter(w.log.export(w.tx))).entry
    assert entry.details["refused_reason"] == "operator_refused"
    assert free_text not in str(entry.details)


def test_audit_is_tenant_scoped() -> None:
    w = World(event(TEXT, "ev-1"))
    row = w.flow.record(w.tx, new_evidence(EvidenceRecordKind.OWNER_TOPIC), NOW)
    w.flow.verify(w.tx, row.id, None, NOW)
    assert w.actions() != []
    assert w.actions(ids.ORG.new()) == []
