# ruff: noqa: PT018
"""SEC-R14 (blueprint section 21) against **real rows**: the fake evidence database with its
login roles and definer functions, the verifier component with a fake session event store, and
Agent 16's G4 (``OwnerEvidenceVerifier`` -> ``evidence_problems``). Every forged, wrong-MAC,
sub-agent / tool-result / notification, replayed, unconfirmed or unevidenced record fails G4.

The operator assistant (the AI recording the owner's chat decisions, ``amw_operator``) has no
path to mark evidence verified or confirmed: only the verifier component (``amw_verifier``)
can, and Agent 16 (``amw_app``) can only read and re-check the MAC.
"""

import ast
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from agent_16_compliance_qa.authorisation.evidence import (
    OwnerEvidenceVerifier,
    StoreMacValidator,
    derive_approval_state,
)
from agent_16_compliance_qa.authorisation.facts import EvidenceFacts, StepFacts
from agent_16_compliance_qa.authorisation.guards import evidence_problems
from agent_16_compliance_qa.checks.rules import MethodSegment, method_release
from amw_core.enums import (
    ApprovalChannel,
    ApprovalState,
    ApprovalStepState,
    ComplianceVerdict,
    EvidenceRecordKind,
    EvidenceState,
    InstructionSourceKind,
    QualityDimension,
)
from amw_core.errors import (
    IdempotencyConflictError,
    InvalidTransitionError,
    PermissionDeniedError,
)
from amw_core.interfaces import DbRole
from amw_core.owner_evidence_mac import MacKeyring
from amw_core.owner_evidence_service import EvidenceVerifierService
from tests.agents.agent_16_compliance_qa.r14_support import CODE, POLICY, R14, REQUESTED

pytestmark = pytest.mark.security
ACC = frozenset({ApprovalChannel.OWNER_CHAT_OPERATOR})
STEP = EvidenceRecordKind.STEP_DECISION


def g4(h: R14, ref, created=REQUESTED, code=CODE, loaded=()) -> list[str]:  # type: ignore[no-untyped-def]
    facts = h.a16.facts(h.tx("agent_16"), ref, h.anchor(created, code), loaded)
    decision = ref.record_kind in (STEP, EvidenceRecordKind.COMPLIANCE_DECISION)
    return evidence_problems(ref.approval_channel, facts, ACC, decision_kind=decision)


# --- positive paths ------------------------------------------------------------------------
def test_sec_r14_01_confirmed_decision_passes_g4() -> None:
    h = R14()
    row = h.record(f"approve {CODE}")
    assert row.state is EvidenceState.CONFIRMED
    assert g4(h, h.step_ref(row.id)) == []


def test_sec_r14_15_and_46_scores_and_contribution_confirmed() -> None:
    h = R14()
    scores = ((QualityDimension.RESEARCH_ACCURACY, 18), (QualityDimension.STORYTELLING, 12))
    row = h.record(
        f"{CODE} research_accuracy 18 storytelling 12",
        EvidenceRecordKind.HUMAN_SCORE,
        claimed_scores=scores,
    )
    assert row.state is EvidenceState.CONFIRMED
    ref = h.score_ref(row.id, ((QualityDimension.RESEARCH_ACCURACY, 18.0),))
    assert g4(h, ref) == []
    wrong = h.score_ref(row.id, ((QualityDimension.RESEARCH_ACCURACY, 19.0),))
    assert "parsed decision = recorded state" in g4(h, wrong)  # points != claimed_scores
    text = (
        "the 2008 gap example shows how a protective order limits the decision while the fill moves"
    )
    crow = h.record(f"{CODE} {text}", EvidenceRecordKind.CONTRIBUTION)
    assert crow.state is EvidenceState.CONFIRMED
    assert g4(h, h.contribution_ref(crow.id, text)) == []
    assert g4(h, h.contribution_ref(crow.id, "words the owner never wrote here")) != []


# --- sources other than the owner's own chat message ---------------------------------------
@pytest.mark.parametrize(
    "source",
    [
        InstructionSourceKind.SUBAGENT_MESSAGE,
        InstructionSourceKind.TOOL_RESULT,
        InstructionSourceKind.DOCUMENT,
        InstructionSourceKind.NOTIFICATION,
    ],
)
def test_sec_r14_02_03_non_owner_sources_never_back_a_record(source: InstructionSourceKind) -> None:
    h = R14()
    row = h.record(f"approve {CODE}", source_kind=source)
    assert row.state is EvidenceState.REFUSED
    problems = g4(h, h.step_ref(row.id))
    assert "state CONFIRMED" in problems and "source OWNER_CHAT_MESSAGE" in problems


@pytest.mark.parametrize(
    "change",
    [
        {"inbound_origin": "subagent"},
        {"inbound_origin": "peer_session"},
        {"parent_session_id": "ses-parent"},
        {"sender_account": "acct-other-human"},
        {"is_synthetic": True},
        {"role": "assistant"},
    ],
)
def test_sec_r14_09_10_11_origin_and_sender_checks(change: dict[str, object]) -> None:
    h = R14()
    row = h.record(f"approve {CODE}", event_change=change)
    assert row.state is EvidenceState.REFUSED
    assert g4(h, h.step_ref(row.id)) != []


@pytest.mark.parametrize(
    "change",
    [
        {"inbound_origin": "subagent"},
        {"inbound_origin": "tool_result"},
        {"inbound_origin": "notification"},
        {"sender_account": "acct-other-human"},
    ],
)
def test_sec_r14_13_44_confirmation_from_other_sources_leaves_verified(
    change: dict[str, object],
) -> None:
    h = R14()
    row = h.record(f"approve {CODE}", confirm_change=change)
    assert row.state is EvidenceState.VERIFIED
    assert "state CONFIRMED" in g4(h, h.step_ref(row.id))


@pytest.mark.parametrize("confirm", ["yes", "confirm", f"reject {CODE}", f"confirm {CODE} 2AB9"])
def test_sec_r14_13_36_bad_confirmations(confirm: str) -> None:
    h = R14()
    row = h.record(f"approve {CODE}", confirm=confirm)
    assert row.state is EvidenceState.VERIFIED  # a dispute or bare yes never confirms
    assert g4(h, h.step_ref(row.id)) != []


def test_sec_r14_12_27_unconfirmed_record_fails() -> None:
    h = R14()
    row = h.record(f"approve {CODE}", confirm=None)
    assert row.state is EvidenceState.VERIFIED
    assert "state CONFIRMED" in g4(h, h.step_ref(row.id))
    # the store itself refuses to apply a human row for it
    with pytest.raises(PermissionDeniedError):
        h.db.human_record_apply(h.operator, h.tx(), row.id)


# --- grammar negatives (whitelist decision grammar, CCR-087) -------------------------------
@pytest.mark.parametrize(
    "message",
    [
        "approve",
        f"don't approve {CODE}",
        f"approve {CODE}?",
        f"approve {CODE} after I check",
        f"would approve {CODE}",
        f"my editor said: approve {CODE}",
        f'"approve {CODE}"',
        f"approve {CODE} but redo the thumbnail",
        f"approve {CODE} 2AB9",
        f"changes {CODE}",
    ],
)
def test_sec_r14_05_06_30_to_34_45_grammar_refusals(message: str) -> None:
    h = R14()
    row = h.record(message)
    assert row.state is EvidenceState.REFUSED
    assert g4(h, h.step_ref(row.id)) != []


def test_sec_r14_43_score_self_correction_refused() -> None:
    h = R14()
    row = h.record(
        f"{CODE} research_accuracy 18 no 15",
        EvidenceRecordKind.HUMAN_SCORE,
        claimed_scores=((QualityDimension.RESEARCH_ACCURACY, 15),),
    )
    assert row.state is EvidenceState.REFUSED
    assert g4(h, h.score_ref(row.id, ((QualityDimension.RESEARCH_ACCURACY, 15.0),))) != []


def test_sec_r14_07_quote_not_verbatim() -> None:
    h = R14()
    row = h.record(f"approve {CODE}", quote=f"approve {CODE} now")
    assert row.state is EvidenceState.REFUSED


def test_sec_r14_08_fabricated_event_stays_pending() -> None:
    h = R14()
    t = h.tx()
    ev = h.event(f"approve {CODE}")
    forged = replace(h.new_evidence(ev, STEP), event_uuid="ev-not-in-store")
    row = h.db.insert_evidence(h.operator, t, forged)
    with pytest.raises(Exception):  # noqa: B017, PT011 - MissingDependencyError: stays pending
        h.verifier.verify_recorded(t, row.id, REQUESTED, ev.timestamp + timedelta(hours=1))
    assert "state CONFIRMED" in g4(h, h.step_ref(row.id))


# --- binding: decision, code, subject, identity, order ------------------------------------
def test_sec_r14_20_decision_mismatch() -> None:
    h = R14()
    row = h.record(f"reject {CODE}", parsed_decision=ApprovalStepState.REJECTED)
    assert row.state is EvidenceState.CONFIRMED
    assert "parsed decision = recorded state" in g4(h, h.step_ref(row.id))


def test_sec_r14_22_37_other_approvals_code() -> None:
    h = R14()
    row = h.record(f"approve {CODE}")
    assert "review code = the approval's code" in g4(h, h.step_ref(row.id), code="2AB9")


def test_sec_r14_19_35_replay_for_a_re_requested_approval() -> None:
    h = R14()
    row = h.record(f"approve {CODE}")
    later = REQUESTED + timedelta(hours=2)  # the approval was re-requested after the message
    assert "message later than the request (A7)" in g4(h, h.step_ref(row.id), created=later)


def test_sec_r14_identity_and_subject_binding() -> None:
    h = R14()
    row = h.record(f"approve {CODE}")
    from amw_core import ids

    assert "on_behalf_of = the record's human" in g4(h, h.step_ref(row.id, human=ids.USER.new()))
    other = ids.new_id(ids.Prefix.RENDER)
    assert "subject / record binding" in g4(h, h.step_ref(row.id, subject_id=other))
    assert "subject / record binding" in g4(h, h.step_ref(row.id, step_no=2))


@pytest.mark.parametrize("channel", [None, ApprovalChannel.WEB_DASHBOARD])
def test_sec_r14_17_channel_null_or_not_accepted(channel: ApprovalChannel | None) -> None:
    h = R14()
    row = h.record(f"approve {CODE}")
    assert g4(h, h.step_ref(row.id, approval_channel=channel)) != []


def test_sec_r14_16_18_records_without_evidence_fail() -> None:
    h = R14()
    for ref in (
        h.step_ref(None),
        h.score_ref(None, ((QualityDimension.COMPLIANCE, 5.0),)),
        h.contribution_ref(None, "some owner words of twenty plus"),
    ):
        assert "no evidence_id" in g4(h, ref)


def test_sec_r14_25_evidence_of_another_org_is_invisible() -> None:
    h = R14()
    row = h.record(f"approve {CODE}")
    other = R14()  # org B reads with its own context: the row of org A does not exist for it
    other.db = h.db
    other.a16 = OwnerEvidenceVerifier(StoreMacValidator(h.db, h.app), h.index)
    facts = other.a16.facts(other.tx("agent_16"), other.step_ref(row.id), other.anchor())
    assert facts is not None and not facts.same_org and not facts.mac_valid


# --- provenance: MAC, direct inserts, tampering, spoofed actor ------------------------------
def test_sec_r14_38_direct_insert_in_confirmed_is_refused_and_forced_rows_fail_the_mac() -> None:
    h = R14()
    ev = h.event(f"approve {CODE}")
    ne = h.new_evidence(ev, STEP)
    for role_session in (h.operator,):
        with pytest.raises(PermissionDeniedError):
            h.db.insert_evidence(role_session, h.tx(), ne, state=EvidenceState.CONFIRMED)
        with pytest.raises(PermissionDeniedError):
            h.db.insert_evidence(role_session, h.tx(), ne, verifier_result={"x": True})
    for session in (h.app, h.verifier_session):
        with pytest.raises(PermissionDeniedError):
            h.db.insert_evidence(session, h.tx(), ne)
    # a superuser forces a CONFIRMED row with an all-pass verifier result and a valid hash
    row = h.db.insert_evidence(h.operator, h.tx(), ne)
    good = h.record(f"approve {CODE}")
    h.db.superuser_tamper(
        h.tx(),
        row.id,
        state=EvidenceState.CONFIRMED,
        verifier_result=dict(good.verifier_result),
        confirmation_event_uuid="ev-x",
        confirmation_message_at=good.confirmation_message_at,
    )
    problems = g4(h, h.step_ref(row.id))
    assert "MAC re-verifies (amw_evidence_mac_valid)" in problems
    assert h.a16.log.mac_invalid  # security event recorded


def test_sec_r14_39_wrong_mac_on_a_human_score() -> None:
    h = R14()
    scores = ((QualityDimension.RESEARCH_ACCURACY, 18),)
    row = h.record(
        f"{CODE} research_accuracy 18", EvidenceRecordKind.HUMAN_SCORE, claimed_scores=scores
    )
    other_key = MacKeyring({1: bytes(range(1, 33))})
    h.db.superuser_tamper(h.tx(), row.id, evidence_mac=other_key.sign(1, {"x": 1}))
    ref = h.score_ref(row.id, ((QualityDimension.RESEARCH_ACCURACY, 18.0),))
    assert "MAC re-verifies (amw_evidence_mac_valid)" in g4(h, ref)
    # a content edit after confirmation also breaks the MAC (and the unkeyed hash)
    row2 = h.record(f"approve {CODE}")
    h.db.superuser_tamper(h.tx(), row2.id, evidence=replace(row2.evidence, quote="approve"))
    problems = g4(h, h.step_ref(row2.id))
    assert "MAC re-verifies (amw_evidence_mac_valid)" in problems
    assert "evidence_sha256 recomputes" in problems  # the stored hash no longer matches
    # recomputing the unkeyed hash as well does not help: only the verifier can stamp a MAC
    from amw_core.owner_evidence_verifier import evidence_sha256

    tampered = h.db.get(h.app, h.tx(), row2.id)
    assert tampered is not None
    h.db.superuser_tamper(h.tx(), row2.id, evidence_sha256=evidence_sha256(tampered.evidence))
    problems = g4(h, h.step_ref(row2.id))
    assert "MAC re-verifies (amw_evidence_mac_valid)" in problems
    assert "evidence_sha256 recomputes" not in problems


def test_sec_r14_40_spoofed_actor_gains_nothing() -> None:
    h = R14()
    ev = h.event(f"approve {CODE}")
    spoof = h.tx(actor="sys_operator")  # app.actor is only a label
    with pytest.raises(PermissionDeniedError):
        h.db.insert_evidence(h.app, spoof, h.new_evidence(ev, STEP))
    genuine = h.record(f"approve {CODE}")
    first = h.step_ref(genuine.id)
    second = h.contribution_ref(genuine.id, f"approve {CODE}")
    assert g4(h, first, loaded=[first]) == []
    problems = g4(h, second, loaded=[first, second])
    assert "backs only this record" in problems and "subject / record binding" in problems
    assert "recorded_by sys_operator" in g4(h, h.step_ref(genuine.id, recorded_by="agent_16"))


def test_sec_r14_35_37_one_event_two_roles() -> None:
    h = R14()
    row = h.record(f"approve {CODE}")
    t = h.tx()
    assert row.confirmation_event_uuid is not None
    conf_event = h.source.fetch("ses-1", row.confirmation_event_uuid)
    assert conf_event is not None
    ne = replace(h.new_evidence(conf_event, STEP), step_no=2)
    with pytest.raises(IdempotencyConflictError):  # DB key: one message, one role
        h.db.insert_evidence(h.operator, t, ne)
    own = h.source.fetch("ses-1", row.evidence.event_uuid)
    assert own is not None
    with pytest.raises(IdempotencyConflictError):  # one live row per event
        h.db.insert_evidence(h.operator, t, h.new_evidence(own, STEP))
    # a row forced in with the reused event fails G4 (MAC and replay keys)
    forced = h.db.insert_evidence(h.operator, t, h.new_evidence(h.event(f"approve {CODE}"), STEP))
    h.db.superuser_tamper(
        t, forced.id, evidence=replace(forced.evidence, event_uuid=row.confirmation_event_uuid)
    )
    problems = g4(h, h.step_ref(forced.id))
    assert "replay keys free (CCR-101)" in problems


def test_sec_r14_47_mac_check_unavailable_is_a_fail() -> None:
    h = R14()
    row = h.record(f"approve {CODE}")

    class Broken:
        def get(self, tx, evidence_id):  # type: ignore[no-untyped-def]
            return h.db.get(h.app, tx, evidence_id)

        def mac_valid(self, tx, evidence_id):  # type: ignore[no-untyped-def]
            return False  # what StoreMacValidator returns when the function raises

    v = OwnerEvidenceVerifier(Broken(), h.index)
    facts = v.facts(h.tx(), h.step_ref(row.id), h.anchor())
    assert facts is not None and not facts.mac_valid

    class Raising:
        role = DbRole.APP

    class DbRaises:
        def mac_valid(self, session, tx, evidence_id):  # type: ignore[no-untyped-def]
            raise RuntimeError("function amw_evidence_mac_valid does not exist")

    reader = StoreMacValidator(DbRaises(), Raising())  # type: ignore[arg-type]
    assert reader.mac_valid(h.tx(), row.id) is False


# --- the operator assistant has no path to VERIFIED / CONFIRMED ------------------------------
def test_operator_has_no_path_to_verified() -> None:
    h = R14()
    t = h.tx()
    ev = h.event(f"approve {CODE}")
    row = h.db.insert_evidence(h.operator, t, h.new_evidence(ev, STEP))
    for session in (h.operator, h.app):
        with pytest.raises(PermissionDeniedError):
            h.db.mark_verified(session, t, row.id, {"clarity": True}, ev.timestamp)
        with pytest.raises(PermissionDeniedError):
            h.db.mark_confirmed(session, t, row.id, "ev-z", "confirm", ev.timestamp, {})
        with pytest.raises(PermissionDeniedError):
            h.db.refuse(session, t, row.id, "x", {})
    with pytest.raises(PermissionDeniedError):  # the verifier component needs amw_verifier
        EvidenceVerifierService(h.db, h.operator, h.source, POLICY)
    with pytest.raises(PermissionDeniedError):  # Agent 16 reads as amw_app only
        StoreMacValidator(h.db, h.operator)
    with pytest.raises(PermissionDeniedError):
        StoreMacValidator(h.db, h.verifier_session)
    with pytest.raises(InvalidTransitionError):  # confirming needs VERIFIED first
        h.verifier.confirm(t, row.id, "ses-1", ev.event_uuid, "confirm R7K2", ev.timestamp)
    assert h.db.get(h.app, t, row.id).state is EvidenceState.PENDING_VERIFICATION  # type: ignore[union-attr]


def test_agent_16_source_never_calls_evidence_write_functions() -> None:
    """Static guarantee: no Agent 16 module references a write or verify function of the
    evidence store, a verifier credential or the operator role."""
    import agent_16_compliance_qa

    root = Path(str(agent_16_compliance_qa.__file__)).parent
    banned = {
        "mark_verified",
        "mark_confirmed",
        "insert_evidence",
        "human_record_apply",
        "refuse",
        "superuser_tamper",
        "EvidenceVerifierService",
        "MacKeyring",
    }
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert not (names & banned), (path.name, names & banned)
        assert (
            "DbRole.OPERATOR" not in path.read_text() and "DbRole.VERIFIER" not in path.read_text()
        )


# --- relied-on approvals: state from steps only (CCR-102) ----------------------------------
def _ev(**over: object) -> EvidenceFacts:
    from tests.agents.agent_16_compliance_qa.support import evidence_mapping

    return EvidenceFacts.model_validate(evidence_mapping(**over))


def _step(**over: object) -> StepFacts:
    base: dict[str, object] = {
        "step_no": 1,
        "state": "APPROVED",
        "decided_by_kind": "HUMAN",
        "membership_active": True,
        "holds_required_role": True,
        "recorded_by_kind": "OPERATOR",
        "approval_channel": "OWNER_CHAT_OPERATOR",
        "evidence": _ev(),
    }
    return StepFacts.model_validate(base | over)


def test_sec_r14_41_release_by_state_only_blocks_fin_r12() -> None:
    undecided = _step(state="PENDING", approval_channel=None, evidence=None)
    state = derive_approval_state(ApprovalState.APPROVED, [undecided], ACC)
    assert state == "APPROVED_UNVERIFIED"
    assert derive_approval_state(ApprovalState.APPROVED, [], ACC) == "APPROVED_UNVERIFIED"
    bad_mac = _step(evidence=_ev(mac_valid=False))
    assert derive_approval_state(ApprovalState.APPROVED, [bad_mac], ACC) == "APPROVED_UNVERIFIED"
    assert derive_approval_state(ApprovalState.APPROVED, [_step()], ACC) == "APPROVED"
    assert derive_approval_state(ApprovalState.PENDING, [undecided], ACC) == "PENDING"
    assert (
        derive_approval_state(ApprovalState.REJECTED, [_step(state="REJECTED")], ACC) == "REJECTED"
    )
    assert derive_approval_state(None, [], ACC) == "NONE"
    seg = MethodSegment(
        segment_ref="s01", cites_method_chunk=True, labelled=True, release_state=state
    )
    assert method_release([seg], True).compliance_verdict is ComplianceVerdict.BLOCKED
