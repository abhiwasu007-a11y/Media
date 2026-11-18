# ruff: noqa: PT018
"""PublicationAuthorisationStage over an in-memory repository and **real** evidence rows: the
stage computes every fact itself (no fact is accepted from the input), G4 re-checks MACs through
the store, the final verdict is written once, the payload validates against section 8.5 and the
Task Output against 03. Tenant isolation: a row of another org fails G13 / G4."""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest

from agent_16_compliance_qa.authorisation.guards import AuthDecision
from agent_16_compliance_qa.authorisation.stage import (
    ApprovalRow,
    AuthorisationInput,
    ContributionRow,
    GateSummary,
    HumanScoreRow,
    HumanVerdictRow,
    NhrItemRow,
    PublicationAuthorisationStage,
    RenderRow,
    ScoreSummary,
    StepRow,
    Subject,
)
from agent_16_compliance_qa.output import Usage, auth_payload, auth_results, build_task_output
from amw_core import ids
from amw_core.contracts.validation import validate_task_output
from amw_core.enums import (
    ApprovalChannel,
    ApprovalKind,
    ApprovalState,
    ApprovalStepState,
    ComplianceVerdict,
    DisclosureDecision,
    EditorialContributionType,
    EvidenceRecordKind,
    QualityDimension,
    RenderStatus,
)
from amw_core.errors import InputInvalidError
from amw_core.ids import WireId
from amw_core.interfaces.tenancy_context import TenantTransaction
from tests.agents.agent_16_compliance_qa.r14_support import CODE, R14, REQUESTED
from tests.agents.agent_16_compliance_qa.support import config, validate_against_blueprint
from tests.fake_audit import RecordingAuditLog

pytestmark = pytest.mark.integration
R_SHA, S_SHA, T_SHA = "a" * 64, "b" * 64, "c" * 64
MACHINE = {
    QualityDimension.RESEARCH_ACCURACY: 15,
    QualityDimension.STORYTELLING: 10,
    QualityDimension.AUDIENCE_VALUE: 8,
    QualityDimension.VISUAL_QUALITY: 10,
    QualityDimension.AUDIO_QUALITY: 6,
    QualityDimension.EDITING_QUALITY: 6,
    QualityDimension.THUMBNAIL_METADATA: 6,
    QualityDimension.COMPLIANCE: 5,
}  # 66
CONTRIB = "the 2008 gap example shows how a protective order limits the decision"
CH = ApprovalChannel.OWNER_CHAT_OPERATOR
AUDIT = RecordingAuditLog()
OP = "sys_operator"


@dataclass
class Repo:
    h: R14
    approvals: dict[str, ApprovalRow] = field(default_factory=dict)
    steps_: dict[str, list[StepRow]] = field(default_factory=dict)
    contribs: list[ContributionRow] = field(default_factory=list)
    scores: list[HumanScoreRow] = field(default_factory=list)
    verdicts: list[HumanVerdictRow] = field(default_factory=list)
    gate_: GateSummary | None = None
    score_: ScoreSummary | None = None
    render_: RenderRow | None = None

    def _org(self, tx: TenantTransaction, rows: Sequence[Any]) -> list[Any]:
        return list(rows)  # RLS would hide other-org rows; kept visible to test G13

    def approval(self, tx: TenantTransaction, approval_id: str) -> ApprovalRow | None:
        return self.approvals.get(approval_id)

    def steps(self, tx: TenantTransaction, approval_id: str) -> Sequence[StepRow]:
        return self.steps_.get(approval_id, [])

    def contributions(self, tx: TenantTransaction, approval_id: str) -> Sequence[ContributionRow]:
        return [c for c in self.contribs if c.approval_id == approval_id]

    def human_scores(self, tx: TenantTransaction, render_id: str) -> Sequence[HumanScoreRow]:
        return self.scores

    def human_verdicts(self, tx: TenantTransaction, gate_task_id: str) -> Sequence[HumanVerdictRow]:
        return self.verdicts

    def gate(self, tx: TenantTransaction, gate_task_id: str) -> GateSummary | None:
        return self.gate_

    def score(self, tx: TenantTransaction, score_task_id: str) -> ScoreSummary | None:
        return self.score_

    def render(self, tx: TenantTransaction, render_id: str) -> RenderRow | None:
        return self.render_

    def destination(self, tx: TenantTransaction) -> Literal["FILE_DELIVERY", "YOUTUBE"]:
        return "FILE_DELIVERY"


class Writer:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, AuthDecision]] = {}

    def write_final(
        self, tx: TenantTransaction, subject: Subject, decision: AuthDecision, idempotency_key: str
    ) -> str:
        if idempotency_key not in self.rows:  # db.output idempotency: a replay returns the row
            self.rows[idempotency_key] = (ids.new_id(ids.Prefix.COMPLIANCE_VERDICT), decision)
        return self.rows[idempotency_key][0]


def world() -> tuple[R14, Repo, AuthorisationInput]:
    h = R14()
    org = h.org
    step_ev = h.record(f"approve {CODE}")
    con_ev = h.record(f"{CODE} {CONTRIB}", EvidenceRecordKind.CONTRIBUTION)
    claimed = (
        (QualityDimension.RESEARCH_ACCURACY, 18),
        (QualityDimension.STORYTELLING, 13),
        (QualityDimension.AUDIENCE_VALUE, 13),
        (QualityDimension.VISUAL_QUALITY, 13),
        (QualityDimension.AUDIO_QUALITY, 9),
        (QualityDimension.EDITING_QUALITY, 8),
        (QualityDimension.THUMBNAIL_METADATA, 8),
    )
    msg = CODE + " " + " ".join(f"{d.value.lower()} {p}" for d, p in claimed)
    sc_ev = h.record(msg, EvidenceRecordKind.HUMAN_SCORE, claimed_scores=claimed)
    repo = Repo(h)
    repo.approvals[h.approval] = ApprovalRow(
        h.approval,
        org,
        ApprovalKind.FINAL_VIDEO,
        ApprovalState.APPROVED,
        "render",
        h.render,
        R_SHA,
        CODE,
        REQUESTED,
    )
    repo.steps_[h.approval] = [
        StepRow(
            h.approval,
            org,
            1,
            ApprovalStepState.APPROVED,
            h.owner,
            True,
            True,
            OP,
            CH,
            step_ev.id,
            f"step:{h.approval}:1",
        )
    ]
    repo.contribs = [
        ContributionRow(
            h.approval,
            org,
            EditorialContributionType.EXAMPLE,
            CONTRIB,
            h.owner,
            OP,
            CH,
            con_ev.id,
            f"c:{con_ev.id}",
        )
    ]
    repo.scores = [
        HumanScoreRow(org, d, float(p), R_SHA, h.owner, OP, CH, sc_ev.id, f"s:{sc_ev.id}")
        for d, p in claimed
    ]
    packs = ((ids.new_id(ids.Prefix.RULE_PACK), 1),)
    repo.gate_ = GateSummary(
        org,
        ComplianceVerdict.ALLOWED,
        R_SHA,
        S_SHA,
        (T_SHA,),
        packs,
        (),
        0,
        DisclosureDecision.NOT_REQUIRED,
        ids.new_id(ids.Prefix.COMPLIANCE_VERDICT),
        (),
        date(2025, 11, 1),
    )
    repo.score_ = ScoreSummary(org, R_SHA, dict(MACHINE))
    repo.render_ = RenderRow("rnd", org, RenderStatus.QC_PASSED, R_SHA, S_SHA, (T_SHA,), 0, True, 0)
    req = AuthorisationInput(
        subject=Subject(
            render_id=h.render,
            render_sha256=R_SHA,
            script_id=ids.new_id(ids.Prefix.SCRIPT),
            script_sha256=S_SHA,
            thumbnail_set_sha256=(T_SHA,),
        ),
        iteration=0,
        approval_id=h.approval,
        gate_task_id=ids.TASK.new(),
        score_task_id=ids.TASK.new(),
        requested_action="DELIVERY",
        intended_publish_date_utc=None,
        pack_versions=({"rule_pack_id": packs[0][0], "version": 1},),
    )
    return h, repo, req


def run(h: R14, repo: Repo, req: AuthorisationInput, key: str = "idk") -> Any:
    stage = PublicationAuthorisationStage(config(), repo, h.a16, Writer(), AUDIT)
    return stage.run(h.tx("agent_16"), req, datetime(2026, 1, 31, tzinfo=UTC), key)


def test_positive_path_delivers_and_outputs_validate() -> None:
    h, repo, req = world()
    res = run(h, repo, req)
    d = res.decision
    assert d.verdict is ComplianceVerdict.ALLOWED, [g for g in d.guards if g.result == "FAIL"]
    assert d.authorised_action == "DELIVERY" and d.human_wins_total == 87
    assert len(res.evidence_ids) == 3
    payload = auth_payload(
        d,
        req.subject.model_dump(mode="json"),
        date(2026, 1, 31),
        res.earliest_compliant_publish_date,
        res.authorisation_verdict_id,
        res.disclosure_verdict_id,
        res.evidence_ids,
        f"amw-blob://{h.org}/evidence/job/auth.json",
    )
    validate_against_blueprint(payload, "### 8.5 `agent_16.publication_authorisation.output`")
    assert res.earliest_compliant_publish_date == date(2025, 12, 1)
    out = build_task_output(
        payload_schema="agent_16.publication_authorisation.output",
        data=payload,
        results=auth_results(d),
        blob=None,
        usage=Usage(),
        now=datetime(2026, 1, 31, tzinfo=UTC),
        currency="USD",
        quality_score=d.human_wins_total,
        verdict=d.verdict,
        downstream="agent_13",
    )
    validate_task_output(out.model_dump(mode="json"))
    assert all(r.gate for r in out.validation_results)


NHR_RULE = "FIN-R3"


def nhr_world(
    *,
    kind: ApprovalKind = ApprovalKind.SENSITIVE_CLAIM,
    step_state: ApprovalStepState = ApprovalStepState.APPROVED,
    row_verdict: ComplianceVerdict = ComplianceVerdict.ALLOWED,
    listed: bool = True,
    items: tuple[str, ...] = (NHR_RULE,),
) -> tuple[R14, Repo, AuthorisationInput, str, WireId]:
    """A gate with NHR items and one resolution through a resolving approval."""
    h, repo, req = world()
    sc_id = ids.APPROVAL.new()
    word = {ApprovalStepState.APPROVED: "approve", ApprovalStepState.REJECTED: "reject"}
    ev = h.record(f"{word[step_state]} {CODE}", approval_id=sc_id, parsed_decision=step_state)
    repo.approvals[sc_id] = ApprovalRow(
        sc_id,
        h.org,
        kind,
        ApprovalState.APPROVED
        if step_state is ApprovalStepState.APPROVED
        else ApprovalState.REJECTED,
        "render",
        h.render,
        R_SHA,
        CODE,
        REQUESTED,
    )
    key = f"step:{sc_id}:1"
    repo.steps_[sc_id] = [
        StepRow(sc_id, h.org, 1, step_state, h.owner, True, True, OP, CH, ev.id, key)
    ]
    repo.verdicts = [
        HumanVerdictRow(
            h.org, row_verdict, True, h.owner, R_SHA, sc_id, 1, OP, CH, ev.id, key, NHR_RULE
        )
    ]
    repo.gate_ = replace(
        repo.gate_,
        overall=ComplianceVerdict.NEEDS_HUMAN_REVIEW,  # type: ignore[type-var]
        relied_approvals=((sc_id, "NHR_RESOLUTION"),) if listed else (),
        nhr_items=tuple(
            NhrItemRow(h.org, ids.new_id(ids.Prefix.COMPLIANCE_VERDICT), rule, R_SHA)
            for rule in items
        ),
    )
    return h, repo, req, sc_id, ev.id


def test_nhr_resolution_with_invalid_mac_fails_g4_and_g5() -> None:
    """SEC-R14-42 / PA-57: the SENSITIVE_CLAIM step and its verdict row share evidence whose MAC
    fails; the item stays unresolved."""
    h, repo, req, _, ev_id = nhr_world()
    ok = run(h, repo, req).decision
    assert ok.verdict is ComplianceVerdict.ALLOWED, [g for g in ok.guards if g.result == "FAIL"]
    h.db.superuser_tamper(h.tx(), ev_id, evidence_mac=b"\x00" * 32)
    d = run(h, repo, req).decision
    assert {"G4", "G5"} <= set(d.failed_guards) and d.verdict is ComplianceVerdict.BLOCKED


@pytest.mark.parametrize("listed", [False, True])
def test_rejected_sensitive_claim_step_with_allowed_row_never_resolves(listed: bool) -> None:
    """Review B1 attack 1: the SENSITIVE_CLAIM step is REJECTED (CONFIRMED "reject"), the verdict
    row claims ALLOWED. Whether or not the gate lists the approval, G5 and G6 fail."""
    h, repo, req, _, _ = nhr_world(step_state=ApprovalStepState.REJECTED, listed=listed)
    d = run(h, repo, req).decision
    assert d.verdict is ComplianceVerdict.BLOCKED and d.authorised_action is None
    assert {"G5", "G6"} <= set(d.failed_guards)
    g5 = next(g for g in d.guards if g.guard_id == "G5")
    assert "not the mapped step decision" in g5.detail


def test_rejected_step_with_blocked_row_blocks() -> None:
    h, repo, req, _, _ = nhr_world(
        step_state=ApprovalStepState.REJECTED, row_verdict=ComplianceVerdict.BLOCKED
    )
    d = run(h, repo, req).decision
    assert {"G5", "G6"} <= set(d.failed_guards) and d.verdict is ComplianceVerdict.BLOCKED


def test_final_video_step_evidence_reused_as_resolution_blocks() -> None:
    """Review B1 attack 2: the FINAL_VIDEO approval's own step and evidence are cited as the NHR
    resolution (wrong approval kind)."""
    h, repo, req = world()
    st = repo.steps_[h.approval][0]
    repo.verdicts = [
        HumanVerdictRow(
            h.org,
            ComplianceVerdict.ALLOWED,
            True,
            h.owner,
            R_SHA,
            h.approval,
            1,
            OP,
            CH,
            st.evidence_id,
            st.record_key,
            NHR_RULE,
        )
    ]
    repo.gate_ = replace(
        repo.gate_,
        overall=ComplianceVerdict.NEEDS_HUMAN_REVIEW,  # type: ignore[type-var]
        nhr_items=(NhrItemRow(h.org, "cvd", NHR_RULE, R_SHA),),
    )
    d = run(h, repo, req).decision
    assert d.verdict is ComplianceVerdict.BLOCKED and "G5" in d.failed_guards
    g5 = next(g for g in d.guards if g.guard_id == "G5")
    assert "resolving approval kind FINAL_VIDEO" in g5.detail


def test_copyright_doubt_resolution_is_accepted() -> None:
    h, repo, req, _, _ = nhr_world(kind=ApprovalKind.COPYRIGHT_DOUBT)
    assert run(h, repo, req).decision.verdict is ComplianceVerdict.ALLOWED


def test_each_nhr_item_needs_its_own_resolution() -> None:
    """Two NHR items, one resolution: the gate's own rows are counted, never a supplied
    count."""
    h, repo, req, _, _ = nhr_world(items=(NHR_RULE, "FIN-R1"))
    d = run(h, repo, req).decision
    assert d.failed_guards == ["G5"]
    assert "FIN-R1@" in next(g for g in d.guards if g.guard_id == "G5").detail


def test_resolution_for_another_rule_or_hash_does_not_resolve() -> None:
    h, repo, req, _, _ = nhr_world()
    repo.verdicts = [replace(repo.verdicts[0], rule_id="FIN-R1")]
    assert "G5" in run(h, repo, req).decision.failed_guards
    h, repo, req, _, _ = nhr_world()
    repo.verdicts = [replace(repo.verdicts[0], subject_sha256=S_SHA)]
    assert "G5" in run(h, repo, req).decision.failed_guards
    h, repo, req, _, _ = nhr_world()
    repo.verdicts = [replace(repo.verdicts[0], rule_id=None)]
    assert "G5" in run(h, repo, req).decision.failed_guards


def test_nhr_gate_without_item_rows_fails_closed() -> None:
    h, repo, req, _, _ = nhr_world(items=())
    d = run(h, repo, req).decision
    assert "G5" in d.failed_guards


def test_resolution_not_reusing_its_step_evidence_fails() -> None:
    h, repo, req, sc_id, _ = nhr_world()
    other = h.record(f"approve {CODE}", approval_id=sc_id)
    repo.verdicts = [replace(repo.verdicts[0], evidence_id=other.id)]
    assert "G5" in run(h, repo, req).decision.failed_guards


def test_resolving_approval_of_another_org_fails_g13() -> None:
    h, repo, req, sc_id, _ = nhr_world(listed=False)
    repo.approvals[sc_id] = replace(repo.approvals[sc_id], org_id=ids.ORG.new())
    d = run(h, repo, req).decision
    assert {"G5", "G13"} <= set(d.failed_guards)


@pytest.mark.parametrize(
    ("mutate", "guards"),
    [
        (
            lambda h, r: r.approvals.update(
                {h.approval: replace(r.approvals[h.approval], state=ApprovalState.PENDING)}
            ),
            {"G1"},
        ),
        (
            lambda h, r: r.approvals.update(
                {h.approval: replace(r.approvals[h.approval], subject_sha256="d" * 64)}
            ),
            {"G1"},
        ),
        (
            lambda h, r: r.approvals.update(
                {h.approval: replace(r.approvals[h.approval], review_code="ABCD")}
            ),
            {"G1", "G4"},
        ),
        (
            lambda h, r: r.steps_.update(
                {
                    h.approval: [
                        replace(
                            r.steps_[h.approval][0], decided_by="agent_16", recorded_by="agent_16"
                        )
                    ]
                }
            ),
            {"G2", "G4"},
        ),
        (lambda h, r: r.steps_.update({h.approval: []}), {"G2"}),
        (
            lambda h, r: setattr(
                r, "contribs", [replace(r.contribs[0], approval_id=ids.APPROVAL.new())]
            ),
            {"G3"},
        ),
        (
            lambda h, r: setattr(r, "contribs", [replace(r.contribs[0], approval_channel=None)]),
            {"G4"},
        ),
        (
            lambda h, r: setattr(r, "scores", [replace(s, evidence_id=None) for s in r.scores]),
            {"G4"},
        ),
        (
            lambda h, r: setattr(
                r, "scores", [replace(s, subject_sha256="e" * 64) for s in r.scores]
            ),
            {"G9", "G9a"},
        ),
        (
            lambda h, r: setattr(r, "scores", [replace(r.scores[0], points=19.0), *r.scores[1:]]),
            {"G4"},
        ),
        (
            lambda h, r: setattr(
                r, "gate_", replace(r.gate_, overall=ComplianceVerdict.BLOCKED, blocked_rows=1)
            ),
            {"G5", "G6"},
        ),
        (
            lambda h, r: setattr(
                r,
                "gate_",
                replace(r.gate_, disclosure_decision=DisclosureDecision.NEEDS_HUMAN_REVIEW),
            ),
            {"G7"},
        ),
        (lambda h, r: setattr(r, "render_", replace(r.render_, blocking_qc_fail=1)), {"G8"}),
        (
            lambda h, r: setattr(r, "render_", replace(r.render_, licences_all_active=False)),
            {"G10"},
        ),
        (
            lambda h, r: setattr(r, "gate_", replace(r.gate_, latest_price_date=date(2026, 1, 20))),
            {"G11"},
        ),
        (lambda h, r: setattr(r, "render_", replace(r.render_, script_sha256="f" * 64)), {"G12"}),
        (lambda h, r: setattr(r, "render_", replace(r.render_, org_id=ids.ORG.new())), {"G13"}),
    ],
)
def test_each_guard_fails_on_real_rows(mutate: Any, guards: set[str]) -> None:
    h, repo, req = world()
    mutate(h, repo)
    d = run(h, repo, req).decision
    assert d.verdict is ComplianceVerdict.BLOCKED and set(d.failed_guards) == guards, (
        d.failed_guards
    )


def test_direct_state_edit_of_an_approval_never_authorises() -> None:
    """approvals.state = APPROVED written directly, with no decided step: G2 (CCR-102)."""
    h, repo, req = world()
    repo.steps_[h.approval] = [
        replace(
            repo.steps_[h.approval][0],
            state=ApprovalStepState.PENDING,
            approval_channel=None,
            evidence_id=None,
            decided_by=None,
            recorded_by=None,
        )
    ]
    d = run(h, repo, req).decision
    assert d.failed_guards == ["G2"]


def test_requested_action_and_missing_approval() -> None:
    h, repo, req = world()
    up = req.model_copy(update={"requested_action": "PUBLISH"})
    assert "G0" in run(h, repo, up).decision.failed_guards
    gone = req.model_copy(update={"approval_id": ids.APPROVAL.new()})
    with pytest.raises(InputInvalidError):
        run(h, repo, gone)


def test_missing_gate_and_score_fail_closed() -> None:
    h, repo, req = world()
    repo.gate_ = None
    repo.score_ = None
    d = run(h, repo, req).decision
    assert d.verdict is ComplianceVerdict.BLOCKED and {"G5", "G12"} <= set(d.failed_guards)


def test_replay_writes_the_final_row_once() -> None:
    h, repo, req = world()
    writer = Writer()
    stage = PublicationAuthorisationStage(config(), repo, h.a16, writer, AUDIT)
    now = datetime(2026, 1, 31, tzinfo=UTC)
    a = stage.run(h.tx("agent_16"), req, now, "idk_same")
    b = stage.run(h.tx("agent_16"), req, now, "idk_same")
    assert a.authorisation_verdict_id == b.authorisation_verdict_id and len(writer.rows) == 1
    assert a.decision == b.decision  # NF-01 determinism


def test_org_b_cannot_use_org_a_evidence() -> None:
    """S-02 / SEC-R14-25: the same stage under org B's context sees no evidence of org A."""
    h, repo, req = world()
    other = R14()
    other.db, other.app = h.db, h.app
    from agent_16_compliance_qa.authorisation.evidence import (
        OwnerEvidenceVerifier,
        StoreMacValidator,
    )

    verifier = OwnerEvidenceVerifier(StoreMacValidator(h.db, h.app), h.index)
    stage = PublicationAuthorisationStage(config(), repo, verifier, Writer(), AUDIT)
    d = stage.run(other.tx("agent_16"), req, datetime(2026, 1, 31, tzinfo=UTC), "k").decision
    assert {"G4", "G13"} <= set(d.failed_guards)


def test_authorisation_and_mac_failure_are_audited() -> None:
    """NF-09 and section 22: the decision and every MAC-invalid evidence row are audit events
    (not only a log line)."""
    h, repo, req, _, ev_id = nhr_world()
    h.db.superuser_tamper(h.tx(), ev_id, evidence_mac=b"\x00" * 32)
    audit = RecordingAuditLog()
    stage = PublicationAuthorisationStage(config(), repo, h.a16, Writer(), audit)
    stage.run(h.tx("agent_16"), req, datetime(2026, 1, 31, tzinfo=UTC), "idk-audit")
    assert "security.evidence_mac_invalid" in audit.actions()
    assert audit.actions()[-1] == "publication_authorisation.decided"


NOT_APPROVED = [s for s in ApprovalState if s is not ApprovalState.APPROVED]


@pytest.mark.parametrize("state", NOT_APPROVED, ids=lambda s: s.value)
@pytest.mark.parametrize("listed", [False, True])
def test_resolving_approval_state_must_be_approved(state: ApprovalState, listed: bool) -> None:
    """Re-review N1: valid APPROVED steps and CONFIRMED evidence, but the SENSITIVE_CLAIM
    approval is PENDING / REJECTED / CHANGES_REQUESTED / EXPIRED / WITHDRAWN: never ALLOWED."""
    h, repo, req, sc_id, _ = nhr_world(listed=listed)
    repo.approvals[sc_id] = replace(repo.approvals[sc_id], state=state)
    d = run(h, repo, req).decision
    assert d.verdict is ComplianceVerdict.BLOCKED and "G5" in d.failed_guards
    if listed:
        assert "G2" in d.failed_guards
    assert f"resolving approval state {state.value}" in next(
        g.detail for g in d.guards if g.guard_id == "G5"
    )


def test_one_resolving_step_cannot_back_two_nhr_items() -> None:
    """Re-review m4: 04 section 5.17 writes one human row per evidence / step."""
    h, repo, req, _, _ = nhr_world(items=(NHR_RULE, "FIN-R1"))
    repo.verdicts = [*repo.verdicts, replace(repo.verdicts[0], rule_id="FIN-R1")]
    d = run(h, repo, req).decision
    g5 = next(g for g in d.guards if g.guard_id == "G5")
    assert d.verdict is ComplianceVerdict.BLOCKED and "backs 2 verdict rows" in g5.detail
