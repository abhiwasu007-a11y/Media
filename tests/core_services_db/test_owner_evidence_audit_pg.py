"""P4-19 on real PostgreSQL: the audit row of a refused confirmation survives the caller's tenant
transaction (the flow returns the refusal; raising would have rolled the row back)."""

from datetime import UTC, datetime, timedelta

import pytest

from amw_core import ids
from amw_core.audit.pg import PgAuditLog
from amw_core.enums import EvidenceRecordKind, InstructionSourceKind
from amw_core.errors import PermissionDeniedError
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.owner_evidence_audit import AuditedEvidenceFlow
from amw_core.owner_evidence_fake import MemorySessionEventSource
from amw_core.owner_evidence_verifier import NewEvidence, SessionEvent, VerifierPolicy
from amw_core.tenancy import PgTenancy
from tests.core_services_db.conftest import Work
from tests.evidence_support import EvidenceHarness
from tests.pg_fixtures import Tenant

pytestmark = pytest.mark.integration
SAID = datetime(2026, 1, 1, 9, 5, tzinfo=UTC)
NOW = SAID + timedelta(minutes=30)
TEXT = "RSI divergence on a weekly chart"
POLICY = VerifierPolicy(
    human_inbound_origins=frozenset({"human"}),
    owner_account_ids=frozenset({"acct-owner"}),
    content_max_age_ms=2 * 3600 * 1000,
)


def test_refused_confirmation_audit_survives_the_transaction(
    tenancy: PgTenancy, readonly: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    source = MemorySessionEventSource(
        [SessionEvent("ses-1", "ev-1", "user", False, "human", TEXT, SAID, "acct-owner", None)]
    )
    harness = EvidenceHarness(source, POLICY)
    log = PgAuditLog()
    flow = AuditedEvidenceFlow(harness.db, harness.operator, harness.verifier, log)
    ctx = TenantContext(tenant_a.org_id, ids.ActorRef("sys_operator"))
    evidence = NewEvidence(
        record_kind=EvidenceRecordKind.OWNER_TOPIC,
        subject_kind="script",
        subject_id=ids.new_id(ids.Prefix.SCRIPT),
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        session_id="ses-1",
        event_uuid="ev-1",
        quote=TEXT,
        message_at=SAID,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=ids.USER.new(),
    )
    with tenancy.transaction(ctx) as tx:
        row = flow.record(tx, evidence, NOW)
        flow.verify(tx, row.id, None, NOW)
    # the normal call pattern: no try / except around the transaction
    with tenancy.transaction(ctx) as tx:
        result = flow.confirm(tx, row.id, "ses-1", "ev-1", "confirmed", NOW)
    assert not result.confirmed
    with pytest.raises(PermissionDeniedError):
        result.require_confirmed()
    with readonly.transaction(ctx) as tx:
        actions = [e.entry.action for e in log.export(tx)]
        last = list(log.export(tx))[-1].entry
        assert log.verify_chain(tx).ok
    assert actions == ["owner_topic.recorded_from_owner_chat", "owner_topic.record_refused"]
    assert last.details["attempt"] == "confirmation"
    assert last.details["state"] == "VERIFIED"


def test_raising_inside_the_transaction_loses_the_audit_row(
    tenancy: PgTenancy, readonly: PgTenancy, tenant_a: Tenant, work_a: Work
) -> None:
    """Why the flow returns the refusal: calling ``require_confirmed`` inside the tenant
    transaction rolls the refusal's audit row back with it. Call it after the commit."""
    source = MemorySessionEventSource(
        [SessionEvent("ses-1", "ev-1", "user", False, "human", TEXT, SAID, "acct-owner", None)]
    )
    harness = EvidenceHarness(source, POLICY)
    log = PgAuditLog()
    flow = AuditedEvidenceFlow(harness.db, harness.operator, harness.verifier, log)
    ctx = TenantContext(tenant_a.org_id, ids.ActorRef("sys_operator"))
    evidence = NewEvidence(
        record_kind=EvidenceRecordKind.OWNER_TOPIC,
        subject_kind="script",
        subject_id=ids.new_id(ids.Prefix.SCRIPT),
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        session_id="ses-1",
        event_uuid="ev-1",
        quote=TEXT,
        message_at=SAID,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=ids.USER.new(),
    )
    with tenancy.transaction(ctx) as tx:
        row = flow.record(tx, evidence, NOW)
        flow.verify(tx, row.id, None, NOW)
    with pytest.raises(PermissionDeniedError), tenancy.transaction(ctx) as tx:
        flow.confirm(tx, row.id, "ses-1", "ev-1", "confirmed", NOW).require_confirmed()
    with readonly.transaction(ctx) as tx:
        assert [e.entry.action for e in log.export(tx)] == ["owner_topic.recorded_from_owner_chat"]
