"""PublicationAuthorisationStage (``agent_16.publication_authorisation``, ``s16_auth``; F-21/F-22).

Reads the approval, its steps, the contributions bound to it, the HUMAN scores, the human
verdict rows, the gate and score results and the render through ``AuthorisationRepository``
(RLS reads as ``amw_app`` inside one tenant transaction, explicit ``org_id`` filter in the
repository), computes every fact itself, evaluates G0-G14 / G9a and writes the only
``is_final = true`` verdict an agent may write. **In 3A it authorises DELIVERY only.**

Nothing here trusts ``approvals.state``, ``app.actor`` or a caller: the input carries IDs and
hashes only (section 7.5), facts are computed from rows, every human record's evidence is
re-checked by ``OwnerEvidenceVerifier`` (MAC through ``amw_evidence_mac_valid``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import Field

from agent_16_compliance_qa.authorisation.evidence import (
    OPERATOR_ACTOR,
    ApprovalAnchor,
    HumanRecordRef,
    OwnerEvidenceVerifier,
    VerifiedApprovalState,
    derive_approval_state,
)
from agent_16_compliance_qa.authorisation.facts import (
    ApprovalFacts,
    AuthRows,
    ContributionFacts,
    EvidenceFacts,
    GateFacts,
    HumanScoreFacts,
    LicenceFacts,
    NhrResolution,
    PriceLagFacts,
    RecorderKind,
    ReliedApproval,
    RenderFacts,
    ResolvingApproval,
    Scores,
    StepFacts,
)
from agent_16_compliance_qa.authorisation.guards import (
    AuthDecision,
    AuthorisationGuards,
    GuardPolicy,
)
from agent_16_compliance_qa.base import Model
from agent_16_compliance_qa.config import Agent16Config
from amw_core.enums import (
    ActorKind,
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
from amw_core.ids import ActorRef, ApprovalId, OrgId, Prefix, UserId, WireId, is_valid_id
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.owner_evidence_review_code import is_valid_review_code

_SHA = r"^[0-9a-f]{64}$"


class Subject(Model):
    render_id: str = Field(pattern=r"^rnd_")
    render_sha256: str = Field(pattern=_SHA)
    script_id: str = Field(pattern=r"^scr_")
    script_sha256: str = Field(pattern=_SHA)
    thumbnail_set_sha256: tuple[str, ...] = Field(min_length=1)


class PackVersion(Model):
    rule_pack_id: str = Field(pattern=r"^rpk_")
    version: int = Field(ge=1)


class AuthorisationInput(Model):
    """``agent_16.publication_authorisation.input`` 1.0.0 (section 7.5): IDs and hashes only."""

    subject: Subject
    iteration: int = Field(ge=0)
    approval_id: str = Field(pattern=r"^apr_")
    gate_task_id: str = Field(pattern=r"^tsk_")
    score_task_id: str = Field(pattern=r"^tsk_")
    requested_action: Literal["DELIVERY", "UPLOAD_PRIVATE", "PUBLISH"]
    intended_publish_date_utc: date | None
    pack_versions: tuple[PackVersion, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class ApprovalRow:
    id: ApprovalId
    org_id: OrgId
    kind: ApprovalKind
    state: ApprovalState
    subject_kind: str
    subject_id: WireId
    subject_sha256: str
    review_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StepRow:
    approval_id: ApprovalId
    org_id: OrgId
    step_no: int
    state: ApprovalStepState
    decided_by: str | None
    membership_active: bool
    holds_required_role: bool
    recorded_by: str | None
    approval_channel: ApprovalChannel | None
    evidence_id: WireId | None
    record_key: str
    target_stage_id: str | None = None


@dataclass(frozen=True, slots=True)
class ContributionRow:
    approval_id: ApprovalId | None
    org_id: OrgId
    type: EditorialContributionType
    description: str
    contributor_user_id: str | None
    recorded_by: str | None
    approval_channel: ApprovalChannel | None
    evidence_id: WireId | None
    record_key: str


@dataclass(frozen=True, slots=True)
class HumanScoreRow:
    org_id: OrgId
    dimension: QualityDimension
    points: float
    subject_sha256: str
    scorer_ref: str | None
    recorded_by: str | None
    approval_channel: ApprovalChannel | None
    evidence_id: WireId | None
    record_key: str
    """Rows written from one ``claimed_scores`` share one key (one record)."""


@dataclass(frozen=True, slots=True)
class NhrItemRow:
    """One ``NEEDS_HUMAN_REVIEW`` ``compliance_verdicts`` row the gate wrote (an item to
    resolve). The item is identified by its ``rule_id`` and ``subject_sha256``."""

    org_id: OrgId
    verdict_id: str
    rule_id: str
    subject_sha256: str

    @property
    def ref(self) -> str:
        return item_ref(self.rule_id, self.subject_sha256)


def item_ref(rule_id: str, subject_sha256: str) -> str:
    return f"{rule_id}@{subject_sha256}"


@dataclass(frozen=True, slots=True)
class HumanVerdictRow:
    """A human NHR resolution row (written with its step by ``amw_human_record_apply``)."""

    org_id: OrgId
    verdict: ComplianceVerdict
    is_final: bool
    decided_by: str | None
    subject_sha256: str
    approval_id: ApprovalId
    step_no: int
    recorded_by: str | None
    approval_channel: ApprovalChannel | None
    evidence_id: WireId | None
    record_key: str
    rule_id: str | None = None
    """The rule of the NHR item it resolves; ``None`` = unbound (G5 FAIL)."""


@dataclass(frozen=True, slots=True)
class GateSummary:
    """The latest ``agent_16.compliance_gate`` result for the render hash (its rows)."""

    org_id: OrgId
    overall: ComplianceVerdict
    render_sha256: str
    script_sha256: str
    thumbnail_set_sha256: tuple[str, ...]
    pack_versions: tuple[tuple[str, int], ...]
    nhr_items: tuple[NhrItemRow, ...]
    """The gate's NHR rows themselves (never a count: G5 binds a resolution to each)."""
    blocked_rows: int
    disclosure_decision: DisclosureDecision
    disclosure_verdict_id: str
    relied_approvals: tuple[
        tuple[ApprovalId, Literal["FIN_R12", "YTG_R9_QUOTATION", "NHR_RESOLUTION"]], ...
    ]
    latest_price_date: date | None


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    org_id: OrgId
    render_sha256: str
    machine: dict[QualityDimension, float]


@dataclass(frozen=True, slots=True)
class RenderRow:
    id: str
    org_id: OrgId
    status: RenderStatus
    content_sha256: str
    script_sha256: str
    thumbnail_set_sha256: tuple[str, ...]
    blocking_qc_fail: int
    licences_all_active: bool
    licences_expiring: int


class AuthorisationRepository(Protocol):
    """RLS-scoped reads as ``amw_app`` (explicit ``org_id`` filter in every query)."""

    def approval(self, tx: TenantTransaction, approval_id: str) -> ApprovalRow | None: ...
    def steps(self, tx: TenantTransaction, approval_id: str) -> Sequence[StepRow]: ...
    def contributions(
        self, tx: TenantTransaction, approval_id: str
    ) -> Sequence[ContributionRow]: ...
    def human_scores(self, tx: TenantTransaction, render_id: str) -> Sequence[HumanScoreRow]: ...
    def human_verdicts(
        self, tx: TenantTransaction, gate_task_id: str
    ) -> Sequence[HumanVerdictRow]: ...
    def gate(self, tx: TenantTransaction, gate_task_id: str) -> GateSummary | None: ...
    def score(self, tx: TenantTransaction, score_task_id: str) -> ScoreSummary | None: ...
    def render(self, tx: TenantTransaction, render_id: str) -> RenderRow | None: ...
    def destination(self, tx: TenantTransaction) -> Literal["FILE_DELIVERY", "YOUTUBE"]: ...


class AuthorisationWriter(Protocol):
    def write_final(
        self, tx: TenantTransaction, subject: Subject, decision: AuthDecision, idempotency_key: str
    ) -> str:
        """INSERT the final ``compliance_verdicts`` row (``is_final = true``, ``decided_by =
        agent_16``) + audit; idempotent per key; returns its ``cvd_`` id."""
        ...


def _human(ref: str | None) -> bool:
    return ref is not None and is_valid_id(ref, Prefix.USER)


def _recorder(recorded_by: str | None, decided_by: str | None) -> RecorderKind:
    if recorded_by == OPERATOR_ACTOR:
        return "OPERATOR"
    if recorded_by is not None and recorded_by == decided_by and _human(recorded_by):
        return "SELF"
    return "AGENT"


def step_ref(approval: ApprovalRow, s: StepRow) -> HumanRecordRef:
    """One step as the human record G4 re-checks."""
    return HumanRecordRef(
        record_kind=EvidenceRecordKind.STEP_DECISION,
        record_key=s.record_key,
        org_id=s.org_id,
        subject_kind=approval.subject_kind,
        subject_id=approval.subject_id,
        approval_id=approval.id,
        step_no=s.step_no,
        human=UserId(s.decided_by) if s.decided_by else None,
        approval_channel=s.approval_channel,
        recorded_by=s.recorded_by,
        evidence_id=s.evidence_id,
        step_state=s.state,
        target_stage_id=s.target_stage_id,
    )


def anchor_of(approval: ApprovalRow) -> ApprovalAnchor:
    return ApprovalAnchor(approval.id, approval.org_id, approval.review_code, approval.created_at)


def step_facts(
    evidence: OwnerEvidenceVerifier,
    tx: TenantTransaction,
    approval: ApprovalRow,
    steps: Sequence[StepRow],
    loaded: Sequence[HumanRecordRef],
) -> tuple[StepFacts, ...]:
    """Every fact G2 / G4 read for the steps of one approval, computed from the rows."""
    anchor = anchor_of(approval)
    return tuple(
        StepFacts(
            step_no=s.step_no,
            state=s.state,
            decided_by_kind="HUMAN" if _human(s.decided_by) else "AGENT",
            membership_active=s.membership_active,
            holds_required_role=s.holds_required_role,
            recorded_by_kind=_recorder(s.recorded_by, s.decided_by),
            approval_channel=s.approval_channel,
            evidence=evidence.facts(tx, step_ref(approval, s), anchor, loaded),
        )
        for s in steps
    )


class ApprovalReader(Protocol):
    """RLS-scoped approval and step reads as ``amw_app`` (explicit ``org_id`` filter)."""

    def approval(self, tx: TenantTransaction, approval_id: str) -> ApprovalRow | None: ...
    def steps(self, tx: TenantTransaction, approval_id: str) -> Sequence[StepRow]: ...


class ApprovalStepVerifier:
    """F-26 (section 19.3 rule 13, CCR-102): the state of a relied-on approval (FIN-R12 release,
    V12 quotation) derived from its steps through G2 + G4; ``approvals.state`` alone never
    counts. An approval of another org, of the wrong kind or for another subject is ``NONE``."""

    def __init__(
        self,
        reader: ApprovalReader,
        evidence: OwnerEvidenceVerifier,
        accepted_channels: frozenset[ApprovalChannel],
    ) -> None:
        self._reader, self._evidence, self._accepted = reader, evidence, accepted_channels

    def derive(
        self,
        tx: TenantTransaction,
        approval_id: str | None,
        kind: ApprovalKind,
        subject_sha256: str | None,
    ) -> VerifiedApprovalState:
        """``subject_sha256``: the hash of what is released / quoted; ``None`` (the binding is
        unknown) is ``NONE`` — an approval for another subject never counts (re-review m3)."""
        if approval_id is None:
            return "NONE"
        approval = self._reader.approval(tx, approval_id)
        if (
            approval is None
            or approval.org_id != tx.context.org_id
            or approval.kind is not kind
            or subject_sha256 is None
            or approval.subject_sha256 != subject_sha256
        ):
            return "NONE"
        steps = [s for s in self._reader.steps(tx, approval.id) if s.org_id == approval.org_id]
        loaded = [step_ref(approval, s) for s in steps]
        facts = step_facts(self._evidence, tx, approval, steps, loaded)
        return derive_approval_state(approval.state, facts, self._accepted)


@dataclass(frozen=True, slots=True)
class AuthorisationResult:
    decision: AuthDecision
    rows: AuthRows
    evidence_ids: tuple[str, ...]
    disclosure_verdict_id: str
    earliest_compliant_publish_date: date | None
    authorisation_verdict_id: str


class PublicationAuthorisationStage:
    def _event(
        self,
        tx: TenantTransaction,
        now: datetime,
        action: str,
        req: AuthorisationInput,
        details: dict[str, object],
    ) -> None:
        """NF-09: every authorisation emits an ``audit_log`` entry with actor ``agent_16``."""
        self._audit.append(
            tx,
            NewAuditEntry(
                actor_kind=ActorKind.AGENT,
                actor_ref=ActorRef("agent_16"),
                authority="agent_16",
                action=action,
                target_kind="render",
                target_id=req.subject.render_id,
                occurred_at=now,
                correlation_id=tx.context.correlation_id,
                details=details,
            ),
        )

    def __init__(
        self,
        config: Agent16Config,
        repository: AuthorisationRepository,
        evidence: OwnerEvidenceVerifier,
        writer: AuthorisationWriter,
        audit: AuditLog,
    ) -> None:
        self._audit = audit
        self._cfg = config
        self._repo = repository
        self._evidence = evidence
        self._writer = writer
        self._guards = AuthorisationGuards(
            GuardPolicy(config.accepted_channels, config.min_description_chars)
        )

    # -- fact builders --------------------------------------------------------------------
    def _step_facts(
        self,
        tx: TenantTransaction,
        approval: ApprovalRow,
        steps: Sequence[StepRow],
        loaded: Sequence[HumanRecordRef],
    ) -> tuple[StepFacts, ...]:
        return step_facts(self._evidence, tx, approval, steps, loaded)

    @staticmethod
    def _step_ref(approval: ApprovalRow, s: StepRow) -> HumanRecordRef:
        return step_ref(approval, s)

    def build_rows(
        self, tx: TenantTransaction, req: AuthorisationInput, evaluation_date: date
    ) -> tuple[AuthRows, tuple[str, ...], GateSummary | None]:
        org = tx.context.org_id
        repo = self._repo
        approval = repo.approval(tx, req.approval_id)
        if approval is None:
            raise InputInvalidError("approval not found in this tenant")
        steps = repo.steps(tx, approval.id)
        contribs = repo.contributions(tx, approval.id)
        scores = repo.human_scores(tx, req.subject.render_id)
        verdicts = repo.human_verdicts(tx, req.gate_task_id)
        gate = repo.gate(tx, req.gate_task_id)
        score = repo.score(tx, req.score_task_id)
        render = repo.render(tx, req.subject.render_id)
        anchor = ApprovalAnchor(
            approval.id, approval.org_id, approval.review_code, approval.created_at
        )
        r_hash = req.subject.render_sha256
        contrib_refs = [
            HumanRecordRef(
                record_kind=EvidenceRecordKind.CONTRIBUTION,
                record_key=c.record_key,
                org_id=c.org_id,
                subject_kind=approval.subject_kind,
                subject_id=approval.subject_id,
                approval_id=c.approval_id,
                step_no=None,
                human=UserId(c.contributor_user_id) if c.contributor_user_id else None,
                approval_channel=c.approval_channel,
                recorded_by=c.recorded_by,
                evidence_id=c.evidence_id,
                description=c.description,
            )
            for c in contribs
        ]
        score_groups: dict[str, list[HumanScoreRow]] = {}
        for h in scores:
            score_groups.setdefault(h.record_key, []).append(h)
        score_refs = {
            key: HumanRecordRef(
                record_kind=EvidenceRecordKind.HUMAN_SCORE,
                record_key=key,
                org_id=rows[0].org_id,
                subject_kind=approval.subject_kind,
                subject_id=approval.subject_id,
                approval_id=approval.id,
                step_no=None,
                human=UserId(rows[0].scorer_ref) if rows[0].scorer_ref else None,
                approval_channel=rows[0].approval_channel,
                recorded_by=rows[0].recorded_by,
                evidence_id=rows[0].evidence_id,
                scores=tuple((r.dimension, r.points) for r in rows),
            )
            for key, rows in score_groups.items()
        }
        relied: list[tuple[ApprovalRow, Sequence[StepRow], str]] = []
        for rid, why in gate.relied_approvals if gate else ():
            other = repo.approval(tx, rid)
            if other is not None:
                relied.append((other, repo.steps(tx, other.id), why))
        loaded: list[HumanRecordRef] = [self._step_ref(approval, s) for s in steps]
        loaded += contrib_refs + list(score_refs.values())
        loaded += [self._step_ref(o, s) for o, ss, _ in relied for s in ss]

        def ev(ref: HumanRecordRef) -> EvidenceFacts | None:
            return self._evidence.facts(tx, ref, anchor, loaded)

        step_facts = self._step_facts(tx, approval, steps, loaded)
        contrib_facts = tuple(
            ContributionFacts(
                type=c.type,
                description_chars=len(c.description),
                contributor_kind="HUMAN" if _human(c.contributor_user_id) else "AGENT",
                bound_to_this_approval=c.approval_id == approval.id,
                approval_channel=c.approval_channel,
                evidence=ev(ref),
            )
            for c, ref in zip(contribs, contrib_refs, strict=True)
        )
        human_facts: list[HumanScoreFacts] = []
        for key, group_rows in score_groups.items():
            facts = ev(score_refs[key])
            human_facts.extend(
                HumanScoreFacts(
                    dimension=h.dimension,
                    points=h.points,
                    bound_to_render_hash=h.subject_sha256 == r_hash,
                    approval_channel=h.approval_channel,
                    evidence=facts,
                )
                for h in group_rows
            )
        other_facts = tuple(
            ReliedApproval(
                kind=o.kind.value,
                state=o.state,
                relied_on_by=why,
                steps=self._step_facts(tx, o, ss, loaded),
            )
            for o, ss, why in relied
            if o.kind.value in ("KNOWLEDGE_RELEASE", "SENSITIVE_CLAIM", "COPYRIGHT_DOUBT")
        )
        items = {i.ref: i for i in gate.nhr_items} if gate else {}
        resolutions = []
        res_rows: list[object] = []
        for v in verdicts:
            res_approval = repo.approval(tx, v.approval_id)
            res_steps = list(repo.steps(tx, v.approval_id)) if res_approval else []
            res_rows += [res_approval, *res_steps]
            step = next((s for s in res_steps if s.step_no == v.step_no), None)
            item = items.get(item_ref(v.rule_id, v.subject_sha256)) if v.rule_id else None
            ref = HumanRecordRef(
                record_kind=EvidenceRecordKind.STEP_DECISION,
                record_key=v.record_key,
                org_id=v.org_id,
                subject_kind=res_approval.subject_kind if res_approval else "",
                subject_id=res_approval.subject_id if res_approval else WireId(""),
                approval_id=v.approval_id,
                step_no=v.step_no,
                human=UserId(v.decided_by) if v.decided_by else None,
                approval_channel=v.approval_channel,
                recorded_by=v.recorded_by,
                evidence_id=v.evidence_id,
                step_state=step.state if step else None,
                target_stage_id=step.target_stage_id if step else None,
            )
            resolving = None
            res_anchor = anchor
            if res_approval is not None:
                res_anchor = ApprovalAnchor(
                    res_approval.id,
                    res_approval.org_id,
                    res_approval.review_code,
                    res_approval.created_at,
                )
                res_loaded = [*loaded, *(self._step_ref(res_approval, s) for s in res_steps)]
                resolving = ResolvingApproval(
                    kind=res_approval.kind,
                    state=res_approval.state,
                    subject_matches_item=item is not None
                    and res_approval.subject_sha256 == item.subject_sha256,
                    steps=self._step_facts(tx, res_approval, res_steps, res_loaded),
                )
            resolutions.append(
                NhrResolution(
                    verdict_is_final=v.is_final,
                    decided_by_kind="HUMAN" if _human(v.decided_by) else "AGENT",
                    same_subject_hash=item is not None
                    and v.subject_sha256 == item.subject_sha256
                    and item.subject_sha256 in (r_hash, req.subject.script_sha256),
                    approval_channel=v.approval_channel,
                    evidence=self._evidence.facts(tx, ref, res_anchor, loaded),
                    verdict=v.verdict,
                    item_ref=item.ref if item else None,
                    step_state=step.state if step else None,
                    reuses_step_evidence=step is not None
                    and step.evidence_id is not None
                    and step.evidence_id == v.evidence_id
                    and step.record_key == v.record_key,
                    resolving_approval=resolving,
                    step_key=f"{v.approval_id}:{v.step_no}",
                )
            )
        lag = self._cfg.price_data_lag_days
        price_date = gate.latest_price_date if gate else None
        same_org = all(
            x.org_id == org
            for x in (approval, gate, score, render, *steps, *contribs, *scores, *verdicts)
            if x is not None
        ) and all(o.org_id == org for o, _, _ in relied)
        same_org = same_org and all(
            getattr(x, "org_id", org) == org for x in res_rows if x is not None
        )
        same_org = same_org and all(i.org_id == org for i in (gate.nhr_items if gate else ()))
        unchanged = (
            gate is not None
            and score is not None
            and render is not None
            and gate.render_sha256 == score.render_sha256 == render.content_sha256 == r_hash
            and gate.script_sha256 == render.script_sha256 == req.subject.script_sha256
            and tuple(sorted(gate.thumbnail_set_sha256))
            == tuple(sorted(render.thumbnail_set_sha256))
            == tuple(sorted(req.subject.thumbnail_set_sha256))
            and tuple(sorted(gate.pack_versions))
            == tuple(sorted((p.rule_pack_id, p.version) for p in req.pack_versions))
        )
        rows = AuthRows(
            requested_action=req.requested_action,
            approval=ApprovalFacts(
                kind=approval.kind,
                state=approval.state,
                subject_hash_matches_render=approval.subject_sha256 == r_hash,
                review_code_present=approval.review_code is not None
                and is_valid_review_code(approval.review_code, self._cfg.review_code_length),
            ),
            steps=step_facts,
            contributions=contrib_facts,
            other_approvals=other_facts,
            scores=Scores(machine=dict(score.machine) if score else {}, human=tuple(human_facts)),
            gate=GateFacts(
                overall=gate.overall if gate else ComplianceVerdict.NEEDS_HUMAN_REVIEW,
                unresolved_nhr=len(
                    set(items) - {r.item_ref for r in resolutions if r.item_ref is not None}
                )
                if gate
                else 1,
                blocked_rows=gate.blocked_rows if gate else 0,
                nhr_resolutions=tuple(resolutions),
                nhr_items=tuple(sorted(items)),
            ),
            disclosure_decision=(
                gate.disclosure_decision if gate else DisclosureDecision.NEEDS_HUMAN_REVIEW
            ),
            render=RenderFacts(
                status=render.status if render else RenderStatus.RENDERING,
                blocking_qc_fail=render.blocking_qc_fail if render else 0,
            ),
            licences=LicenceFacts(
                all_active=bool(render and render.licences_all_active),
                expiring=render.licences_expiring if render else 0,
            ),
            fin_r9=(
                PriceLagFacts(
                    latest_price_age_days_at_evaluation=max((evaluation_date - price_date).days, 0),
                    lag_days=lag,
                )
                if price_date
                else None
            ),
            hashes_unchanged=unchanged,
            all_refs_same_org=same_org,
            threshold=self._cfg.publish_min_score,
            destination=repo.destination(tx),
        )
        ids = tuple(
            sorted(
                {r.evidence_id for r in loaded if r.evidence_id is not None}
                | {v.evidence_id for v in verdicts if v.evidence_id is not None}
            )
        )
        return rows, ids, gate

    def run(
        self, tx: TenantTransaction, req: AuthorisationInput, now: datetime, idempotency_key: str
    ) -> AuthorisationResult:
        evaluation_date = now.date()
        rows, evidence_ids, gate = self.build_rows(tx, req, evaluation_date)
        decision = self._guards.evaluate(rows)
        verdict_id = self._writer.write_final(tx, req.subject, decision, idempotency_key)
        for kind, evidence_id in self._evidence.log.mac_invalid:  # section 22 security event
            self._event(
                tx,
                now,
                "security.evidence_mac_invalid",
                req,
                {"evidence_id": evidence_id, "record_kind": kind.value},
            )
        self._evidence.log.mac_invalid.clear()
        self._event(
            tx,
            now,
            "publication_authorisation.decided",
            req,
            {
                "verdict": decision.verdict.value,
                "authorised_action": decision.authorised_action,
                "failed_guards": decision.failed_guards,
                "authorisation_verdict_id": verdict_id,
            },
        )
        price = gate.latest_price_date if gate else None
        earliest = (
            date.fromordinal(price.toordinal() + self._cfg.price_data_lag_days) if price else None
        )
        return AuthorisationResult(
            decision=decision,
            rows=rows,
            evidence_ids=evidence_ids,
            disclosure_verdict_id=gate.disclosure_verdict_id if gate else verdict_id,
            earliest_compliant_publish_date=earliest,
            authorisation_verdict_id=verdict_id,
        )
