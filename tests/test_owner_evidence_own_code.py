"""CCR-116 (ticket P4-01): evidence without an approval gets its own review code from the store,
unique per org across approval and evidence codes; the confirmation names exactly that code.
PostgreSQL side: migration 0052, ``tests/tenancy/test_evidence_review_code_db.py``."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from amw_core import ids
from amw_core.enums import EvidenceRecordKind, EvidenceState, InstructionSourceKind
from amw_core.errors import IdempotencyConflictError, PermissionDeniedError
from amw_core.interfaces import TenantContext
from amw_core.owner_evidence_fake import MemorySessionEventSource, needs_own_review_code
from amw_core.owner_evidence_review_code import is_valid_review_code
from amw_core.owner_evidence_verifier import NewEvidence, SessionEvent, VerifierPolicy
from amw_core.owner_evidence_verifier import evidence_sha256 as sha_of
from amw_core.testing.memory import MemoryTransaction
from tests.evidence_support import EvidenceHarness

SAID = datetime(2026, 1, 1, 9, 5, tzinfo=UTC)
LATER = SAID + timedelta(minutes=1)
NOW = SAID + timedelta(minutes=30)
POLICY = VerifierPolicy(
    human_inbound_origins=frozenset({"human"}),
    owner_account_ids=frozenset({"acct-owner"}),
    content_max_age_ms=2 * 3600 * 1000,
)
TOPIC = "RSI divergence on a weekly chart"


def event(content: str, uuid: str = "ev-1", at: datetime = SAID) -> SessionEvent:
    return SessionEvent("ses-1", uuid, "user", False, "human", content, at, "acct-owner", None)


def topic(**change: Any) -> NewEvidence:
    base = NewEvidence(
        record_kind=EvidenceRecordKind.OWNER_TOPIC,
        subject_kind="script",
        subject_id=ids.new_id(ids.Prefix.SCRIPT),
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        session_id="ses-1",
        event_uuid="ev-1",
        quote=TOPIC,
        message_at=SAID,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=ids.USER.new(),
    )
    return replace(base, **change)


def tx() -> MemoryTransaction:
    return MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef("sys_operator")))


def harness(*events: SessionEvent) -> EvidenceHarness:
    return EvidenceHarness(MemorySessionEventSource(events), POLICY)


def test_kinds_that_need_an_own_code() -> None:
    own = {k for k in EvidenceRecordKind if needs_own_review_code(k)}
    assert own == {
        EvidenceRecordKind.CONTRIBUTION,
        EvidenceRecordKind.REVISION_NOTE,
        EvidenceRecordKind.OWNER_TOPIC,
        EvidenceRecordKind.DATASET_INTAKE,
        EvidenceRecordKind.HUMAN_SCORE,
    }


def test_store_issues_an_own_code_bound_into_the_hash() -> None:
    h, t = harness(event(TOPIC)), tx()
    row = h.record(t, topic())
    code = row.evidence.review_code
    assert code is not None
    assert is_valid_review_code(code)
    assert code == code.upper()
    assert row.evidence_sha256 == sha_of(row.evidence)
    assert row.evidence_sha256 != sha_of(replace(row.evidence, review_code=None))


def test_confirmation_names_exactly_the_own_code() -> None:
    h, t = harness(event(TOPIC)), tx()
    row = h.record(t, topic())
    code = row.evidence.review_code
    assert code is not None
    assert h.verify_recorded(t, row.id, None, NOW).state is EvidenceState.VERIFIED
    other = "R7K2" if code != "R7K2" else "Q9Z3"
    h.source.add(event(f"confirm {other}", "ev-2", LATER))
    h.source.add(event("confirm", "ev-3", LATER))
    h.source.add(event(f"confirm {code.lower()}", "ev-4", LATER))
    for wrong in ("ev-2", "ev-3"):
        with pytest.raises(PermissionDeniedError):
            h.confirm(t, row.id, "ses-1", wrong, "confirm", NOW)
        assert h.state(t, row.id) is EvidenceState.VERIFIED
    confirmed = h.confirm(t, row.id, "ses-1", "ev-4", "confirm", NOW)
    assert confirmed.state is EvidenceState.CONFIRMED
    assert h.mac_valid(t, row.id)


def test_own_code_is_unique_against_approval_codes() -> None:
    h, t = harness(), tx()
    h.db.register_approval_code(t, "r7k2")
    with pytest.raises(IdempotencyConflictError):
        h.record(t, topic(review_code="R7K2"))
    issued = h.record(t, topic(event_uuid="ev-5")).evidence.review_code
    assert issued is not None
    with pytest.raises(IdempotencyConflictError):
        h.db.register_approval_code(t, issued.lower())


def test_own_code_is_unique_against_other_evidence_and_per_org() -> None:
    h, t = harness(), tx()
    h.record(t, topic(review_code="Q9Z3"))
    with pytest.raises(IdempotencyConflictError):
        h.record(t, topic(review_code="Q9Z3", event_uuid="ev-6"))
    refused = topic(review_code="Q9Z3", event_uuid="ev-7")
    with pytest.raises(IdempotencyConflictError):  # a refused row cannot take a used code either
        h.record(t, refused, state=EvidenceState.REFUSED, refused_reason="x")
    assert h.record(tx(), topic(review_code="Q9Z3")).evidence.review_code == "Q9Z3"


@pytest.mark.parametrize("code", ["q9z3", "ABCD", "2345", "Q0Z3", "Q-Z3"])
def test_malformed_own_code_is_refused(code: str) -> None:
    with pytest.raises(PermissionDeniedError):
        harness().record(tx(), topic(review_code=code))


def test_refused_row_needs_no_code_and_approval_rows_keep_the_approval_code() -> None:
    h, t = harness(), tx()
    row = h.record(t, topic(), state=EvidenceState.REFUSED, refused_reason="x")
    assert row.evidence.review_code is None
    h.db.register_approval_code(t, "R7K2")
    bound = topic(
        record_kind=EvidenceRecordKind.CONTRIBUTION,
        approval_id=ids.APPROVAL.new(),
        review_code="R7K2",
        event_uuid="ev-8",
    )
    assert h.record(t, bound).evidence.review_code == "R7K2"
    decision = topic(record_kind=EvidenceRecordKind.STEP_DECISION, event_uuid="ev-9")
    assert h.record(t, decision).evidence.review_code is None
