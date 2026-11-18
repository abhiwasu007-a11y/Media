"""AuthorisationGuards (F-21): guards G0-G14 and G9a of blueprint section 6.5, pure over facts.

Any FAIL => verdict ``BLOCKED``, ``is_final = true``; ``on_fail STOP``. In 3A the only action that
can be authorised is ``DELIVERY`` of the file bundle (D1). Rules that make this the final
gatekeeper:

* an approval counts only from its **steps** (G2, CCR-102); ``approvals.state`` alone clears
  nothing, for this approval and for every approval the gate relied on;
* every human-originated record (each decided step of this approval and of every relied-on
  approval, each contribution bound to this approval, each HUMAN score bound to the render hash,
  each human NHR verdict row) must carry an accepted ``approval_channel`` and evidence that
  passes every G4 clause, incl. the keyed-MAC provenance re-check (CCR-100);
* compliance ``BLOCKED`` (G5 / G6) stops delivery whatever the score (section 1A.7);
* the human-wins total (G9) is computed only from HUMAN rows bound to the render hash and G9a
  requires at least one (Q-O2 provisional default: no machine scaling).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from agent_16_compliance_qa.authorisation.facts import (
    AuthRows,
    EvidenceFacts,
    HumanScoreFacts,
    NhrResolution,
    StepFacts,
)
from agent_16_compliance_qa.base import Model
from amw_core.enums import (
    ApprovalChannel,
    ApprovalKind,
    ApprovalState,
    ApprovalStepState,
    ComplianceVerdict,
    DisclosureDecision,
    EvidenceState,
    InstructionSourceKind,
    QualityDimension,
    RenderStatus,
)

GuardId = Literal[
    "G0",
    "G1",
    "G2",
    "G3",
    "G4",
    "G5",
    "G6",
    "G7",
    "G8",
    "G9",
    "G9a",
    "G10",
    "G11",
    "G12",
    "G13",
    "G14",
]
GUARD_ORDER: Final[tuple[GuardId, ...]] = (
    "G0",
    "G1",
    "G2",
    "G3",
    "G4",
    "G5",
    "G6",
    "G7",
    "G8",
    "G9",
    "G9a",
    "G10",
    "G11",
    "G12",
    "G13",
    "G14",
)
CHECK_IDS: Final[Mapping[GuardId, str]] = {
    "G0": "a16.auth.g0",
    "G1": "a16.auth.g1.approval",
    "G2": "a16.auth.g2",
    "G3": "a16.auth.g3.contribution",
    "G4": "a16.auth.g4.owner_evidence",
    "G5": "a16.auth.g5",
    "G6": "a16.auth.g6.no_blocked",
    "G7": "a16.auth.g7",
    "G8": "a16.auth.g8",
    "G9": "a16.auth.g9.score_threshold",
    "G9a": "a16.auth.g9a.human_score",
    "G10": "a16.auth.g10",
    "G11": "a16.auth.g11",
    "G12": "a16.auth.g12",
    "G13": "a16.auth.g13",
    "G14": "a16.auth.g14",
}
ACTIONS_BY_DESTINATION: Final[Mapping[str, frozenset[str]]] = {
    "FILE_DELIVERY": frozenset({"DELIVERY"}),  # 3A (D1; 24 section 7.1a)
    "YOUTUBE": frozenset(),  # UPLOAD_PRIVATE / PUBLISH are 3C (guard G14); never in 3A
}
_KIND_FOR_ACTION: Final[Mapping[str, ApprovalKind]] = {
    "DELIVERY": ApprovalKind.FINAL_VIDEO,
    "UPLOAD_PRIVATE": ApprovalKind.FINAL_VIDEO,
    "PUBLISH": ApprovalKind.PUBLISH,
}
RESOLVING_KINDS: Final = frozenset({ApprovalKind.SENSITIVE_CLAIM, ApprovalKind.COPYRIGHT_DOUBT})
_UNDECIDED: Final = frozenset({ApprovalStepState.NOT_STARTED, ApprovalStepState.PENDING})


class GuardResult(Model):
    guard_id: GuardId
    result: Literal["PASS", "FAIL", "SKIPPED"]
    detail: str


class DimensionUse(Model):
    dimension: QualityDimension
    machine: float
    human: float | None
    used: float


class AuthDecision(Model):
    verdict: ComplianceVerdict
    is_final: Literal[True] = True
    authorised_action: Literal["DELIVERY", "UPLOAD_PRIVATE", "PUBLISH"] | None
    guards: tuple[GuardResult, ...]
    human_wins_total: float
    per_dimension_used: tuple[DimensionUse, ...]

    @property
    def failed_guards(self) -> list[str]:
        return [g.guard_id for g in self.guards if g.result == "FAIL"]


@dataclass(frozen=True, slots=True)
class GuardPolicy:
    """The config the guards read (``Agent16Config``): no literal thresholds here."""

    accepted_channels: frozenset[ApprovalChannel]
    min_description_chars: int


def evidence_problems(
    channel: ApprovalChannel | None,
    ev: EvidenceFacts | None,
    accepted: frozenset[ApprovalChannel],
    *,
    decision_kind: bool,
) -> list[str]:
    """Every G4 clause that fails for one human record (empty list = PASS).

    ``decision_kind``: the record is a step decision (``DECISION`` rule set), so
    ``parsed_decision`` must positively match the recorded step state.
    """
    problems: list[str] = []
    if channel is None:
        problems.append("approval_channel NULL")
    elif channel not in accepted:
        problems.append(f"approval_channel {channel.value} not accepted")
    if ev is None:
        return [*problems, "no evidence_id"]
    checks = {
        "state CONFIRMED": ev.state is EvidenceState.CONFIRMED,
        "MAC re-verifies (amw_evidence_mac_valid)": ev.mac_valid,
        "evidence_sha256 recomputes": ev.hash_recomputes,
        "source OWNER_CHAT_MESSAGE": ev.source_kind is InstructionSourceKind.OWNER_CHAT_MESSAGE,
        "same org": ev.same_org,
        "on_behalf_of = the record's human": ev.on_behalf_of_matches,
        "subject / record binding": ev.subject_matches,
        "review code = the approval's code": ev.review_code_matches,
        "parsed decision = recorded state": (
            ev.parsed_decision_matches is True
            if decision_kind
            else ev.parsed_decision_matches is not False
        ),
        "message later than the request (A7)": ev.message_after_request,
        "confirmation later than the message": ev.confirmation_after_message,
        "verifier result complete and passed": ev.verifier_all_passed and not ev.failed_tests,
        "not refused": ev.refused_reason is None,
        "replay keys free (CCR-101)": ev.replay_free,
        "backs only this record": ev.backs_only_this_record,
        "recorded_by sys_operator": ev.recorded_by_operator,
    }
    problems.extend(name for name, ok in checks.items() if not ok)
    return problems


def _is_human_record(step: StepFacts) -> bool:
    """An undecided step with no channel and no evidence is not a human record (G2 only)."""
    return not (
        step.state in _UNDECIDED and step.approval_channel is None and step.evidence is None
    )


def step_problems(step: StepFacts) -> list[str]:
    """G2 for one step: decided ``APPROVED`` by an active human with the role, recorded by the
    operator (owner chat) or by the human (3C dashboard), never by an agent."""
    problems: list[str] = []
    if step.state is not ApprovalStepState.APPROVED:
        problems.append(f"step {step.step_no} is {step.state.value}")
    if step.decided_by_kind != "HUMAN":
        problems.append(f"step {step.step_no} not decided by a human")
    if not step.membership_active:
        problems.append(f"step {step.step_no} decider membership not ACTIVE")
    if not step.holds_required_role:
        problems.append(f"step {step.step_no} decider lacks the required role")
    owner_chat = step.approval_channel is ApprovalChannel.OWNER_CHAT_OPERATOR
    if step.recorded_by_kind == "AGENT" or (owner_chat and step.recorded_by_kind != "OPERATOR"):
        problems.append(f"step {step.step_no} recorded_by {step.recorded_by_kind}")
    return problems


def approval_from_steps(steps: Sequence[StepFacts]) -> list[str]:
    """CCR-102 / section 19.3 rule 13: an approval is APPROVED only when it has steps and every
    one passes G2; ``approvals.state`` is never read here."""
    if not steps:
        return ["approval has no decided step"]
    return [p for s in steps for p in step_problems(s)]


def steps_approved(steps: Sequence[StepFacts], accepted: frozenset[ApprovalChannel]) -> bool:
    """Section 19.3 rule 13 (F-26): an approval counts as APPROVED only when it has steps and
    every step is APPROVED and passes G2 and G4."""
    return bool(steps) and all(
        not step_problems(s)
        and not evidence_problems(s.approval_channel, s.evidence, accepted, decision_kind=True)
        for s in steps
    )


def mapped_step_verdict(state: ApprovalStepState) -> ComplianceVerdict:
    """04 section 5.17: ``APPROVED -> ALLOWED``; every other step state -> ``BLOCKED``."""
    return (
        ComplianceVerdict.ALLOWED
        if state is ApprovalStepState.APPROVED
        else (ComplianceVerdict.BLOCKED)
    )


def human_wins(rows: AuthRows) -> tuple[float, tuple[DimensionUse, ...]]:
    """Section 6.6.5: per dimension the HUMAN row bound to the render hash replaces the machine
    row. Rows bound to another hash are ignored."""
    bound: dict[QualityDimension, HumanScoreFacts] = {
        h.dimension: h for h in rows.scores.human if h.bound_to_render_hash
    }
    uses: list[DimensionUse] = []
    for dim in QualityDimension:
        machine = rows.scores.machine.get(dim, 0.0)
        human = bound[dim].points if dim in bound else None
        uses.append(
            DimensionUse(
                dimension=dim,
                machine=machine,
                human=human,
                used=machine if human is None else human,
            )
        )
    return round(sum(u.used for u in uses), 2), tuple(uses)


def _result(guard: GuardId, problems: Iterable[str], ok_detail: str) -> GuardResult:
    found = list(problems)
    if found:
        return GuardResult(guard_id=guard, result="FAIL", detail="; ".join(found)[:500])
    return GuardResult(guard_id=guard, result="PASS", detail=ok_detail[:500])


class AuthorisationGuards:
    """Evaluates G0-G14 and G9a in guard order; never short-circuits (every guard is reported)."""

    def __init__(self, policy: GuardPolicy) -> None:
        self._p = policy

    def _g4(self, rows: AuthRows) -> list[str]:
        acc = self._p.accepted_channels
        problems: list[str] = []
        for s in rows.steps:
            if _is_human_record(s):
                for p in evidence_problems(s.approval_channel, s.evidence, acc, decision_kind=True):
                    problems.append(f"step {s.step_no}: {p}")
        for a in rows.other_approvals:
            for s in a.steps:
                if _is_human_record(s):
                    for p in evidence_problems(
                        s.approval_channel, s.evidence, acc, decision_kind=True
                    ):
                        problems.append(f"{a.kind} step {s.step_no}: {p}")
        for i, c in enumerate(rows.contributions):
            if c.bound_to_this_approval:
                for p in evidence_problems(
                    c.approval_channel, c.evidence, acc, decision_kind=False
                ):
                    problems.append(f"contribution {i + 1}: {p}")
        for h in rows.scores.human:
            if h.bound_to_render_hash:
                for p in evidence_problems(
                    h.approval_channel, h.evidence, acc, decision_kind=False
                ):
                    problems.append(f"HUMAN score {h.dimension.value}: {p}")
        for i, r in enumerate(rows.gate.nhr_resolutions):
            # the verdict row reuses its step's evidence; the step's decision is checked there
            for p in evidence_problems(r.approval_channel, r.evidence, acc, decision_kind=False):
                problems.append(f"NHR resolution {i + 1}: {p}")
        return problems

    def _resolution_problems(self, r: NhrResolution, items: frozenset[str]) -> list[str]:
        """Section 6.5 G5 for one human verdict row; empty list = it resolves ``r.item_ref``."""
        acc = self._p.accepted_channels
        problems: list[str] = []
        if not r.verdict_is_final:
            problems.append("not is_final")
        if r.decided_by_kind != "HUMAN":
            problems.append("not decided by a human")
        if r.item_ref is None:
            problems.append("not bound to an NHR item of the gate")
        elif r.item_ref not in items:
            problems.append("bound to an item the gate did not raise")
        if not r.same_subject_hash:
            problems.append("bound to another subject hash")
        if evidence_problems(r.approval_channel, r.evidence, acc, decision_kind=False):
            problems.append("evidence fails G4")
        if not r.reuses_step_evidence:
            problems.append("does not reuse the evidence of the step written with it")
        ra = r.resolving_approval
        if ra is None:
            problems.append("resolving approval not visible")
        else:
            if ra.state is not ApprovalState.APPROVED:
                problems.append(f"resolving approval state {ra.state.value}")
            if ra.kind not in RESOLVING_KINDS:
                problems.append(f"resolving approval kind {ra.kind.value}")
            if not ra.subject_matches_item:
                problems.append("resolving approval is for another subject hash")
            if not steps_approved(ra.steps, acc):
                problems.append(f"resolving {ra.kind.value} approval fails G2 / G4")
        if r.step_state is None:
            problems.append("no step written with the row")
        else:
            mapped = mapped_step_verdict(r.step_state)
            if r.verdict is not mapped:
                problems.append(
                    f"verdict {r.verdict.value} is not the mapped step decision {mapped.value}"
                )
            if mapped is not ComplianceVerdict.ALLOWED:
                problems.append(f"step {r.step_state.value}: the item is BLOCKED (G6)")
        return problems

    def _g5(self, rows: AuthRows) -> list[str]:
        """Every NHR item of the gate has its own resolving row; a count is never trusted and a
        failing resolution is never outweighed by a passing one."""
        gate = rows.gate
        if gate.overall is ComplianceVerdict.ALLOWED:
            return []
        if gate.overall is ComplianceVerdict.BLOCKED:
            return ["compliance gate BLOCKED for this render hash"]
        problems: list[str] = []
        if gate.unresolved_nhr:
            problems.append(f"{gate.unresolved_nhr} NEEDS_HUMAN_REVIEW item(s) unresolved")
        items = frozenset(gate.nhr_items)
        if not items:
            problems.append("gate NEEDS_HUMAN_REVIEW without an NHR item row to resolve")
        if not gate.nhr_resolutions:
            problems.append("no resolving human verdict row")
        resolved: set[str] = set()
        for label, keys in (
            ("step", [r.step_key for r in gate.nhr_resolutions]),
            (
                "evidence",
                [r.evidence.evidence_id if r.evidence else None for r in gate.nhr_resolutions],
            ),
        ):
            used = [k for k in keys if k is not None]
            for k in sorted({k for k in used if used.count(k) > 1}):
                # 04 section 5.17: one human row per evidence / step (re-review m4)
                problems.append(f"one resolving {label} backs {used.count(k)} verdict rows ({k})")
        for i, r in enumerate(gate.nhr_resolutions):
            found = self._resolution_problems(r, items)
            problems.extend(f"resolution {i + 1} {p}" for p in found)
            if not found and r.item_ref is not None:
                resolved.add(r.item_ref)
        problems.extend(
            f"NHR item {item} has no valid resolution" for item in sorted(items - resolved)
        )
        for a in rows.other_approvals:
            if a.relied_on_by == "NHR_RESOLUTION" and approval_from_steps(a.steps):
                problems.append(f"resolving {a.kind} approval fails G2")
        return problems

    @staticmethod
    def _blocked_resolutions(rows: AuthRows) -> int:
        """Human rows that resolve an item as BLOCKED (stored or by the mapped step)."""
        return sum(
            1
            for r in rows.gate.nhr_resolutions
            if r.verdict is ComplianceVerdict.BLOCKED
            or (
                r.step_state is not None
                and mapped_step_verdict(r.step_state) is ComplianceVerdict.BLOCKED
            )
        )

    def evaluate(self, rows: AuthRows) -> AuthDecision:
        total, uses = human_wins(rows)
        appr = rows.approval
        results: list[GuardResult] = []
        allowed = ACTIONS_BY_DESTINATION.get(rows.destination, frozenset())
        results.append(
            _result(
                "G0",
                []
                if rows.requested_action in allowed
                else [f"{rows.requested_action} not allowed for destination {rows.destination}"],
                f"{rows.requested_action} allowed for {rows.destination}",
            )
        )
        g1: list[str] = []
        if appr.kind is not _KIND_FOR_ACTION[rows.requested_action]:
            g1.append(f"approval kind {appr.kind.value}")
        if appr.state is not ApprovalState.APPROVED:
            g1.append(f"approval state {appr.state.value}")
        if not appr.subject_hash_matches_render:
            g1.append("approval subject_sha256 is not the render hash")
        if not appr.review_code_present:
            g1.append("approval has no valid review code (CCR-090)")
        results.append(_result("G1", g1, "FINAL_VIDEO approval for this render hash"))
        g2 = approval_from_steps(rows.steps)
        for a in rows.other_approvals:
            g2.extend(f"{a.kind} ({a.relied_on_by}): {p}" for p in approval_from_steps(a.steps))
            if a.state is not ApprovalState.APPROVED:  # re-review N1: state AND steps
                g2.append(f"{a.kind} ({a.relied_on_by}): approval state {a.state.value}")
        results.append(_result("G2", g2, "every relied-on step APPROVED by an active human"))
        bound = [c for c in rows.contributions if c.bound_to_this_approval]
        good = [
            c
            for c in bound
            if c.contributor_kind == "HUMAN"
            and c.description_chars >= self._p.min_description_chars
        ]
        results.append(
            _result(
                "G3",
                []
                if good
                else [
                    "no human contribution bound to this approval with "
                    f">= {self._p.min_description_chars} characters"
                ],
                f"{len(good)} contribution(s) bound to this approval",
            )
        )
        results.append(_result("G4", self._g4(rows), "every human record has CONFIRMED evidence"))
        results.append(_result("G5", self._g5(rows), "compliance ALLOWED or every NHR resolved"))
        g6 = []
        blocked = rows.gate.blocked_rows + self._blocked_resolutions(rows)
        if blocked or rows.gate.overall is ComplianceVerdict.BLOCKED:
            g6.append(f"{max(blocked, 1)} BLOCKED verdict(s) for the subject hash")
        results.append(_result("G6", g6, "no BLOCKED verdict"))
        g7: list[str] = []
        if rows.disclosure_decision is DisclosureDecision.NEEDS_HUMAN_REVIEW and (
            rows.gate.overall is not ComplianceVerdict.NEEDS_HUMAN_REVIEW or self._g5(rows)
        ):
            g7.append("disclosure decision NEEDS_HUMAN_REVIEW is not resolved")
        results.append(_result("G7", g7, f"disclosure {rows.disclosure_decision.value}"))
        g8: list[str] = []
        if rows.render.status is not RenderStatus.QC_PASSED:
            g8.append(f"render status {rows.render.status.value}")
        if rows.render.blocking_qc_fail:
            g8.append(f"{rows.render.blocking_qc_fail} blocking QC FAIL row(s)")
        results.append(_result("G8", g8, "render QC_PASSED"))
        results.append(
            _result(
                "G9",
                [] if total >= rows.threshold else [f"human-wins total {total} < {rows.threshold}"],
                f"human-wins total {total} >= {rows.threshold}",
            )
        )
        ignored = sum(1 for h in rows.scores.human if not h.bound_to_render_hash)
        has_human = any(h.bound_to_render_hash for h in rows.scores.human)
        results.append(
            _result(
                "G9a",
                []
                if has_human
                else [f"no HUMAN score bound to the render hash ({ignored} bound to another hash)"],
                f"HUMAN score present ({ignored} row(s) of another hash ignored)",
            )
        )
        results.append(
            _result(
                "G10",
                [] if rows.licences.all_active else ["a licence used by the render is not ACTIVE"],
                f"licences ACTIVE ({rows.licences.expiring} EXPIRING: warning)",
            )
        )
        lag = rows.fin_r9
        g11: list[str] = []
        if lag is not None and lag.latest_price_age_days_at_evaluation < lag.lag_days:
            age = lag.latest_price_age_days_at_evaluation
            g11.append(f"price data {age} days old < lag {lag.lag_days}")
        results.append(_result("G11", g11, "FIN-R9 price-data age >= lag (or no dated price)"))
        results.append(
            _result(
                "G12",
                [] if rows.hashes_unchanged else ["a subject hash changed since the gate"],
                "script, render, thumbnails and packs unchanged",
            )
        )
        results.append(
            _result(
                "G13",
                [] if rows.all_refs_same_org else ["a referenced row belongs to another org"],
                "every reference in the envelope org",
            )
        )
        results.append(
            GuardResult(guard_id="G14", result="SKIPPED", detail="3C publish-time re-check")
        )
        failed = any(r.result == "FAIL" for r in results)
        verdict = ComplianceVerdict.BLOCKED if failed else ComplianceVerdict.ALLOWED
        return AuthDecision(
            verdict=verdict,
            authorised_action=None if failed else rows.requested_action,
            guards=tuple(results),
            human_wins_total=total,
            per_dimension_used=uses,
        )
