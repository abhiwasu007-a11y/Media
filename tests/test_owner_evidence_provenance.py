"""Contract pass 3 (CCR-087..103): review codes, stage words, confirmation whitelist,
freshness window, and database-level provenance (roles, initial state, keyed MAC) with every
forgery path the fake must refuse (lane L1a implements the PostgreSQL side)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from amw_core import ids
from amw_core.enums import (
    ApprovalStepState,
    EvidenceRecordKind,
    EvidenceState,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.errors import (
    ConfigInvalidError,
    IdempotencyConflictError,
    InputInvalidError,
    InvalidTransitionError,
    PermissionDeniedError,
)
from amw_core.interfaces import DbRole, EvidenceDatabase, TenantContext
from amw_core.owner_evidence_fake import (
    FakeDbSession,
    FakeEvidenceDatabase,
    MemorySessionEventSource,
)
from amw_core.owner_evidence_mac import MacKeyring
from amw_core.owner_evidence_review_code import (
    ALPHABET,
    canonical_review_code,
    generate_review_code,
    is_valid_review_code,
)
from amw_core.owner_evidence_service import EvidenceVerifierService
from amw_core.owner_evidence_verifier import (
    NEEDS_CLARIFICATION,
    NewEvidence,
    SessionEvent,
    VerifierPolicy,
    evidence_sha256,
    is_confirmation,
    read_decision_message,
)
from amw_core.testing.memory import MemoryTransaction
from tests.evidence_support import PASSWORDS, TEST_KEY, EvidenceHarness

REQUESTED = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
SAID = REQUESTED + timedelta(minutes=5)
LATER = SAID + timedelta(minutes=1)
NOW = REQUESTED + timedelta(hours=1)
POLICY = VerifierPolicy(
    human_inbound_origins=frozenset({"human"}),
    owner_account_ids=frozenset({"acct-owner"}),
    content_max_age_ms=2 * 3600 * 1000,
)
SUBJECT = ids.new_id(ids.Prefix.RENDER)
CR = ApprovalStepState.CHANGES_REQUESTED
LF_STAGES = frozenset({"s05_script", "s09_plan", "s11_thumbs"})


def event(content: str = "approve R7K2", uuid: str = "ev-1", **change: Any) -> SessionEvent:
    base = SessionEvent("ses-1", uuid, "user", False, "human", content, SAID, "acct-owner", None)
    return replace(base, **change)


def evidence(**change: Any) -> NewEvidence:
    base = NewEvidence(
        record_kind=EvidenceRecordKind.STEP_DECISION,
        subject_kind="render",
        subject_id=SUBJECT,
        source_kind=InstructionSourceKind.OWNER_CHAT_MESSAGE,
        session_id="ses-1",
        event_uuid="ev-1",
        quote="approve R7K2",
        message_at=SAID,
        recorded_by=ids.ActorRef("sys_operator"),
        on_behalf_of=ids.USER.new(),
        job_id=ids.JOB.new(),
        review_code="R7K2",
        parsed_decision=ApprovalStepState.APPROVED,
    )
    return replace(base, **change)


def tx(actor: str = "sys_operator") -> MemoryTransaction:
    return MemoryTransaction(TenantContext(ids.ORG.new(), ids.ActorRef(actor)))


def harness(*events: SessionEvent) -> EvidenceHarness:
    return EvidenceHarness(MemorySessionEventSource(events), POLICY)


def confirmed_row(h: EvidenceHarness, t: MemoryTransaction, ne: NewEvidence | None = None) -> Any:
    row = h.record(t, ne or evidence())
    assert h.verify_recorded(t, row.id, REQUESTED, NOW).state is EvidenceState.VERIFIED
    assert h.confirm(t, row.id, "ses-1", "ev-2", "confirm", NOW).state is EvidenceState.CONFIRMED
    return row


# --- CCR-090 review codes ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "ok"),
    [
        ("R7K2", True), ("r7k2", True), ("2AB9", True), ("ZZZ2", True),
        ("ABCD", False), ("2345", False), ("R7K", False), ("R7K22", False),
        ("R0K2", False), ("R1K2", False), ("RIK2", False), ("RLK2", False), ("ROK2", False),
        ("R7-2", False), ("", False),
    ],
)  # fmt: skip
def test_review_code_validator(code: str, ok: bool) -> None:
    assert is_valid_review_code(code) is ok
    if ok:
        assert canonical_review_code(code) == code.upper()
    else:
        with pytest.raises(InputInvalidError):
            canonical_review_code(code)


def test_review_code_generator_regenerates_on_collision() -> None:
    picks = iter("AAAA" + "R7K2" + "R7K3")
    taken = {"R7K2"}
    code = generate_review_code(taken.__contains__, choice=lambda _a: next(picks))
    assert code == "R7K3"  # AAAA (no digit) and R7K2 (taken) were regenerated
    for _ in range(200):
        fresh = generate_review_code(lambda _c: False)
        assert is_valid_review_code(fresh)
        assert set(fresh) <= set(ALPHABET)
    with pytest.raises(InputInvalidError):
        generate_review_code(lambda _c: True)
    assert len(generate_review_code(lambda _c: False, length=6)) == 6


def test_verifier_code_shape_matches_the_format() -> None:
    import re

    shape = re.compile(POLICY.review_code_pattern)
    for _ in range(100):
        assert shape.fullmatch(generate_review_code(lambda _c: False).casefold())
    assert not shape.fullmatch("r1k2")


# --- CCR-089 stage words --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "allowed", "expected"),
    [
        ("changes R7K2 thumbnail", LF_STAGES, (CR, "s11_thumbs")),
        ("R7K2 changes visuals please", LF_STAGES, (CR, "s09_plan")),
        ("changes R7K2 script", LF_STAGES, (CR, "s05_script")),
        ("changes R7K2 script", frozenset({"s05_shorts"}), (CR, "s05_shorts")),
        ("R7K2 बदल थंबनेल", LF_STAGES, (CR, "s11_thumbs")),
        ("changes R7K2", LF_STAGES, None),
        ("changes R7K2 thumbnail script", LF_STAGES, None),
        ("changes R7K2 visuals", frozenset({"s05_script"}), None),
        ("approve R7K2 thumbnail", LF_STAGES, None),
        ("changes R7K2 intro", LF_STAGES, None),
    ],
)
def test_stage_words(content: str, allowed: frozenset[str], expected: Any) -> None:
    assert read_decision_message(content, "R7K2", POLICY, allowed) == expected


def test_changes_requested_records_the_stage() -> None:
    ne = evidence(quote="changes R7K2", parsed_decision=CR, parsed_target_stage_id="s11_thumbs")
    confirm = event("confirm R7K2", "ev-2", timestamp=LATER)
    h, t = harness(event("changes R7K2 thumbnail"), confirm), tx()
    row = h.record(t, ne)
    assert h.verify_recorded(t, row.id, REQUESTED, NOW, LF_STAGES).state is EvidenceState.VERIFIED
    h.confirm(t, row.id, "ses-1", "ev-2", "confirm", NOW)
    assert h.apply(t, row.id).target_stage_id == "s11_thumbs"
    assert evidence_sha256(ne) != evidence_sha256(replace(ne, parsed_target_stage_id="s09_plan"))


@pytest.mark.parametrize(
    ("stage", "reason"), [("s09_plan", "target_stage_matches"), (None, "target_stage_matches")]
)
def test_stage_must_match_the_message(stage: str | None, reason: str) -> None:
    ne = evidence(quote="changes R7K2", parsed_decision=CR, parsed_target_stage_id=stage)
    h, t = harness(event("changes R7K2 thumbnail")), tx()
    row = h.record(t, ne)
    refused = h.verify_recorded(t, row.id, REQUESTED, NOW, LF_STAGES)
    assert (refused.state, refused.refused_reason) == (EvidenceState.REFUSED, reason)


def test_revision_note_is_a_content_kind() -> None:
    text = "make the thumbnail headline larger and red"
    ne = evidence(record_kind=EvidenceRecordKind.REVISION_NOTE, quote=text, parsed_decision=None)
    h, t = harness(event(f"R7K2 {text}")), tx()
    assert h.verify_recorded(t, h.record(t, ne).id, REQUESTED, NOW).state is EvidenceState.VERIFIED


# --- CCR-101 confirmation whitelist ---------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "ok"),
    [
        ("confirm R7K2", True),
        ("R7K2 confirmed please", True),
        ("R7K2 पक्के", True),
        ("R7K2 reject", False),  # a dispute is never a confirmation
        ("confirm R7K2 but change the intro", False),
        ("confirm R7K2 Q9Z3", False),
        ("confirm R7K2 R7K2", False),
        ("confirm", False),
        ("approve R7K2", False),  # a new decision is not a confirmation
        ("confirm R7K2?", False),
        ("confirm confirm R7K2", False),
        ("not confirm R7K2", False),
    ],
)
def test_confirmation_whitelist(content: str, ok: bool) -> None:
    assert is_confirmation(content, "R7K2", POLICY) is ok
    h, t = harness(event(), event(content, "ev-2", timestamp=LATER)), tx()
    row = h.record(t, evidence())
    h.verify_recorded(t, row.id, REQUESTED, NOW)
    quote = content.split()[0]
    if ok:
        assert h.confirm(t, row.id, "ses-1", "ev-2", quote, NOW).state is EvidenceState.CONFIRMED
    else:
        with pytest.raises(PermissionDeniedError):
            h.confirm(t, row.id, "ses-1", "ev-2", quote, NOW)
        assert h.state(t, row.id) is EvidenceState.VERIFIED


def test_confirmation_needs_the_records_review_code() -> None:
    assert not is_confirmation("confirm R7K2", None, POLICY)


def test_one_message_is_one_step() -> None:
    h, t = harness(event(), event("confirm R7K2", "ev-2", timestamp=LATER)), tx()
    confirmed_row(h, t)
    # the confirming message can never create another record ...
    with pytest.raises(IdempotencyConflictError):
        h.record(
            t,
            evidence(event_uuid="ev-2", quote="confirm", subject_id=ids.new_id(ids.Prefix.RENDER)),
        )
    # ... and another row's event can never confirm a record
    h2, t2 = harness(event(), event("confirm R7K2", "ev-3", timestamp=LATER)), tx()
    first = h2.record(t2, evidence())
    other = ids.new_id(ids.Prefix.RENDER)
    h2.record(t2, evidence(event_uuid="ev-3", quote="confirm R7K2", subject_id=other))
    h2.verify_recorded(t2, first.id, REQUESTED, NOW)
    with pytest.raises(IdempotencyConflictError):  # grammar passes; the database key refuses
        h2.confirm(t2, first.id, "ses-1", "ev-3", "confirm", NOW)
    assert h2.state(t2, first.id) is EvidenceState.VERIFIED


def test_confirmation_event_confirms_only_once() -> None:
    confirm = event("confirm R7K2", "ev-2", timestamp=LATER)
    h, t = harness(event(), event("approve R7K2", "ev-9"), confirm), tx()
    confirmed_row(h, t)
    second = h.record(t, evidence(event_uuid="ev-9"))
    h.verify_recorded(t, second.id, REQUESTED, NOW)
    with pytest.raises(IdempotencyConflictError):
        h.confirm(t, second.id, "ses-1", "ev-2", "confirm", NOW)


# --- CCR-091 freshness window for kinds without a request anchor -----------------------------


@pytest.mark.parametrize(
    "kind", [EvidenceRecordKind.OWNER_TOPIC, EvidenceRecordKind.DATASET_INTAKE]
)
def test_freshness_window(kind: EvidenceRecordKind) -> None:
    text = "RSI divergence on a weekly chart"
    ne = evidence(record_kind=kind, quote=text, parsed_decision=None, review_code=None)
    message = text  # CCR-116: no subject reference before the job
    fresh = harness(event(message)), tx()
    assert (
        fresh[0].verify_recorded(fresh[1], fresh[0].record(fresh[1], ne).id, None, NOW).state
        is EvidenceState.VERIFIED
    )
    old_now = SAID + timedelta(hours=3)
    h, t = harness(event(message)), tx()
    refused = h.verify_recorded(t, h.record(t, ne).id, None, old_now)
    assert refused.refused_reason == "message_order"
    unset = EvidenceHarness(
        MemorySessionEventSource([event(message)]), replace(POLICY, content_max_age_ms=None)
    )
    t3 = tx()
    assert (
        unset.verify_recorded(t3, unset.record(t3, ne).id, None, NOW).refused_reason
        == "message_order"
    )


def test_anchored_kinds_need_an_anchor() -> None:
    h, t = harness(event()), tx()
    assert (
        h.verify_recorded(t, h.record(t, evidence()).id, None, NOW).refused_reason
        == "message_order"
    )


# --- CCR-100 provenance: roles, initial state, MAC, forgery paths ---------------------------


@pytest.mark.parametrize(
    "columns",
    [
        {"state": EvidenceState.VERIFIED},
        {"state": EvidenceState.CONFIRMED},
        {"evidence_mac": b"\x00" * 32, "mac_key_version": 1},
        {"verifier_result": {"role_user": True}},
        {"event_verified_at": SAID},
        {"confirmation_event_uuid": "ev-2"},
        {"state": EvidenceState.REFUSED},  # refused without a reason
        {"refused_reason": "x"},  # a reason without REFUSED
    ],
)
def test_insert_only_pending_or_refused_and_empty(columns: dict[str, Any]) -> None:
    h, t = harness(), tx()
    with pytest.raises(PermissionDeniedError):
        h.record(t, evidence(), **columns)
    assert (
        h.record(t, evidence(), state=EvidenceState.REFUSED, refused_reason="ambiguous").state
        is EvidenceState.REFUSED
    )


@pytest.mark.parametrize("role", [DbRole.APP, DbRole.VERIFIER])
def test_only_the_operator_inserts(role: DbRole) -> None:
    h, t = harness(), tx()
    session = h.db.login(role, PASSWORDS[role])
    with pytest.raises(PermissionDeniedError):
        h.db.insert_evidence(session, t, evidence())


@pytest.mark.parametrize("actor", ["sys_operator", "sys_verifier", "agent_16", "usr_x"])
def test_only_the_verifier_role_moves_state_whatever_the_actor(actor: str) -> None:
    h, t = harness(event()), tx(actor)
    row = h.record(t, evidence())
    for session in (h.operator, h.app):
        with pytest.raises(PermissionDeniedError):
            h.db.mark_verified(session, t, row.id, {"role_user": True}, NOW)
        with pytest.raises(PermissionDeniedError):
            h.db.refuse(session, t, row.id, "x", {})
        with pytest.raises(PermissionDeniedError):
            h.db.mark_confirmed(session, t, row.id, "ev-2", "confirm", LATER, {})
    assert h.state(t, row.id) is EvidenceState.PENDING_VERIFICATION


def test_forged_sessions_are_refused() -> None:
    h, t = harness(event()), tx()
    row = h.record(t, evidence())
    with pytest.raises(PermissionDeniedError):
        h.db.login(DbRole.VERIFIER, "guess")
    forged = FakeDbSession(DbRole.VERIFIER, 0)  # not issued by this database
    with pytest.raises(PermissionDeniedError):
        h.db.mark_verified(forged, t, row.id, {}, NOW)
    other_db = FakeEvidenceDatabase(PASSWORDS, MacKeyring({1: TEST_KEY}))
    foreign = other_db.login(DbRole.VERIFIER, PASSWORDS[DbRole.VERIFIER])
    with pytest.raises(PermissionDeniedError):
        h.db.mark_verified(foreign, t, row.id, {}, NOW)
    with pytest.raises(PermissionDeniedError):
        EvidenceVerifierService(h.db, h.operator, h.source, POLICY)


def test_operator_cannot_apply_before_confirmation_or_apply_twice() -> None:
    h, t = harness(event(), event("confirm R7K2", "ev-2", timestamp=LATER)), tx()
    row = h.record(t, evidence())
    with pytest.raises(PermissionDeniedError):
        h.apply(t, row.id)
    h.verify_recorded(t, row.id, REQUESTED, NOW)
    with pytest.raises(PermissionDeniedError):
        h.apply(t, row.id)
    h.confirm(t, row.id, "ses-1", "ev-2", "confirm", NOW)
    with pytest.raises(PermissionDeniedError):
        h.db.human_record_apply(h.app, t, row.id)  # wrong role
    assert h.apply(t, row.id).decision is ApprovalStepState.APPROVED
    with pytest.raises(IdempotencyConflictError):
        h.apply(t, row.id)


@pytest.mark.parametrize(
    "tamper",
    [
        {"evidence_mac": None},
        {"evidence_mac": b"\x00" * 32},
        {"mac_key_version": None},
        {"mac_key_version": 2},
        {"state": EvidenceState.CONFIRMED, "confirmation_event_uuid": "ev-x"},
    ],
)
def test_wrong_or_missing_mac_is_detected(tamper: dict[str, Any]) -> None:
    h, t = harness(event(), event("confirm R7K2", "ev-2", timestamp=LATER)), tx()
    row = h.record(t, evidence())
    h.verify_recorded(t, row.id, REQUESTED, NOW)
    assert h.mac_valid(t, row.id)
    h.db.superuser_tamper(t, row.id, **tamper)
    assert not h.mac_valid(t, row.id)
    with pytest.raises((PermissionDeniedError, InvalidTransitionError)):
        h.confirm(t, row.id, "ses-1", "ev-2", "confirm", NOW)
    with pytest.raises(PermissionDeniedError):
        h.apply(t, row.id)


def test_superuser_insert_in_confirmed_without_mac_backs_nothing() -> None:
    h, t = harness(), tx()
    row = h.record(t, evidence())
    h.db.superuser_tamper(t, row.id, state=EvidenceState.CONFIRMED)
    with pytest.raises(PermissionDeniedError):
        h.apply(t, row.id)


def test_mac_copied_from_another_row_is_invalid() -> None:
    h, t = harness(event(), event("approve Q9Z3", "ev-5")), tx()
    a = h.record(t, evidence())
    b = h.record(t, evidence(event_uuid="ev-5", review_code="Q9Z3", quote="approve Q9Z3"))
    h.verify_recorded(t, b.id, REQUESTED, NOW)
    b_row = h.get(t, b.id)
    assert b_row is not None
    h.db.superuser_tamper(
        t, a.id, state=EvidenceState.VERIFIED, evidence_mac=b_row.evidence_mac,
        mac_key_version=b_row.mac_key_version, verifier_result=b_row.verifier_result,
        event_verified_at=b_row.event_verified_at,
    )  # fmt: skip
    assert not h.mac_valid(t, a.id)


def test_content_edit_after_confirmation_is_detected() -> None:
    h, t = (
        harness(event("R7K2 research_accuracy 18"), event("confirm R7K2", "ev-2", timestamp=LATER)),
        tx(),
    )
    ne = evidence(
        record_kind=EvidenceRecordKind.HUMAN_SCORE, quote="R7K2", parsed_decision=None,
        claimed_scores=((QualityDimension.RESEARCH_ACCURACY, 18),),
    )  # fmt: skip
    row = confirmed_row(h, t, ne)
    raised = replace(ne, claimed_scores=((QualityDimension.RESEARCH_ACCURACY, 20),))
    h.db.superuser_tamper(t, row.id, evidence=raised, evidence_sha256=evidence_sha256(raised))
    assert not h.mac_valid(t, row.id)
    with pytest.raises(PermissionDeniedError):
        h.apply(t, row.id)


def test_replay_of_an_event() -> None:
    h, t = harness(event()), tx()
    h.record(t, evidence())
    with pytest.raises(IdempotencyConflictError):
        h.record(t, evidence(subject_id=ids.new_id(ids.Prefix.RENDER)))


def test_key_rotation_and_keyring_rules() -> None:
    h, t = harness(event()), tx()
    row = h.record(t, evidence())
    signed = h.verify_recorded(t, row.id, REQUESTED, NOW)
    assert signed.mac_key_version == 1
    rotated = MacKeyring({1: TEST_KEY, 2: bytes(range(1, 33))})
    assert rotated.current_version == 2
    from amw_core.owner_evidence_fake import _mac_fields

    assert rotated.verify(1, _mac_fields(signed), signed.evidence_mac)
    assert not MacKeyring({2: bytes(range(1, 33))}).verify(
        1, _mac_fields(signed), signed.evidence_mac
    )
    with pytest.raises(ConfigInvalidError):
        MacKeyring({1: b"short"})
    with pytest.raises(ConfigInvalidError):
        MacKeyring({})
    assert "versions=[1, 2]" in repr(rotated)
    assert TEST_KEY.hex() not in repr(rotated)


def test_fake_satisfies_the_protocol() -> None:
    assert isinstance(FakeEvidenceDatabase(PASSWORDS, MacKeyring({1: TEST_KEY})), EvidenceDatabase)


def test_refused_reason_for_clarification() -> None:
    h, t = harness(event("approve R7K2 maybe")), tx()
    refused = h.verify_recorded(t, h.record(t, evidence(quote="approve R7K2")).id, REQUESTED, NOW)
    assert refused.refused_reason == NEEDS_CLARIFICATION
