"""YTG-R9 close-paraphrase post-processing (F-14 / F-25; blueprint section 6.3 V12).

Code re-applies prompt rule 3 to the four booleans and keeps the stricter of the model's
decision and the re-derived one (D-5). A short attributed quotation is ``NEEDS_HUMAN_REVIEW``
(``COPYRIGHT_DOUBT``) unless **code** finds a ``COPYRIGHT_DOUBT`` approval for that span's hash
whose state F-26 derived as ``APPROVED`` from its steps (G2 + G4, CCR-102); the model never sees
approval state (D-10). Runs only in the private worker; no passage text is persisted.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from agent_16_compliance_qa.authorisation.evidence import VerifiedApprovalState
from agent_16_compliance_qa.base import Model, worst
from agent_16_compliance_qa.judge.models import (
    ParaphraseInput,
    ParaphraseOutput,
    ParaphraseResult,
)
from amw_core.enums import ComplianceVerdict

Decision = Literal["OWN_WORDS", "CLOSE_PARAPHRASE", "UNCERTAIN"]
_RANK: Final[Mapping[str, int]] = {"OWN_WORDS": 0, "UNCERTAIN": 1, "CLOSE_PARAPHRASE": 2}
_VERDICT: Final[Mapping[str, ComplianceVerdict]] = {
    "OWN_WORDS": ComplianceVerdict.ALLOWED,
    "UNCERTAIN": ComplianceVerdict.NEEDS_HUMAN_REVIEW,
    "CLOSE_PARAPHRASE": ComplianceVerdict.BLOCKED,
}


def rule3(r: ParaphraseResult) -> Decision:
    trio = sum((r.same_structure, r.same_examples, r.same_sequence))
    if r.surface_change_only or trio >= 2:
        return "CLOSE_PARAPHRASE"
    if trio == 0:
        return "OWN_WORDS"
    return "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class QuotationApproval:
    span_sha256: str
    state: VerifiedApprovalState
    """F-26 ``derive_approval_state`` of the ``COPYRIGHT_DOUBT`` approval."""


class PairVerdict(Model):
    pair_id: str
    decision: Decision
    is_quotation: bool
    verdict: ComplianceVerdict
    approval_applied: bool
    rationale: str


class ParaphraseDecision(Model):
    pairs: tuple[PairVerdict, ...]
    verdict: ComplianceVerdict
    injection_pairs: tuple[str, ...]
    refusal_reason: str | None


def apply_paraphrase(
    inp: ParaphraseInput,
    out: ParaphraseOutput,
    span_hashes: Mapping[str, str],
    approvals: list[QuotationApproval],
) -> ParaphraseDecision:
    pairs = {p.pair_id: p for p in inp.pairs}
    injection = tuple(sorted({i for i in out.injection_suspected if i in pairs}))
    if out.refusal is not None:
        verdicts = tuple(
            PairVerdict(
                pair_id=p,
                decision="UNCERTAIN",
                is_quotation=False,
                verdict=ComplianceVerdict.NEEDS_HUMAN_REVIEW,
                approval_applied=False,
                rationale=f"judge refusal {out.refusal.reason}",
            )
            for p in pairs
        )
        return ParaphraseDecision(
            pairs=verdicts,
            verdict=ComplianceVerdict.NEEDS_HUMAN_REVIEW,
            injection_pairs=injection,
            refusal_reason=out.refusal.reason,
        )
    by_id: dict[str, ParaphraseResult] = {}
    for res in out.results:
        if res.pair_id in pairs:
            by_id[res.pair_id] = res
    released = {a.span_sha256 for a in approvals if a.state == "APPROVED"}
    verdicts_l: list[PairVerdict] = []
    for pid, pair in pairs.items():
        r = by_id.get(pid)
        if r is None:  # a pair the judge did not answer is never cleared
            verdicts_l.append(
                PairVerdict(
                    pair_id=pid,
                    decision="UNCERTAIN",
                    is_quotation=False,
                    verdict=ComplianceVerdict.NEEDS_HUMAN_REVIEW,
                    approval_applied=False,
                    rationale="no judge result",
                )
            )
            continue
        if r.is_quotation and pair.attribution_present:
            ok = span_hashes.get(pid) in released
            verdicts_l.append(
                PairVerdict(
                    pair_id=pid,
                    decision=r.decision,
                    is_quotation=True,
                    verdict=ComplianceVerdict.ALLOWED
                    if ok
                    else ComplianceVerdict.NEEDS_HUMAN_REVIEW,
                    approval_applied=ok,
                    rationale="quotation cleared by a verified COPYRIGHT_DOUBT approval"
                    if ok
                    else "quotation: COPYRIGHT_DOUBT review needed",
                )
            )
            continue
        derived = rule3(r)
        decision = derived if _RANK[derived] > _RANK[r.decision] else r.decision
        verdicts_l.append(
            PairVerdict(
                pair_id=pid,
                decision=decision,
                is_quotation=False,
                verdict=_VERDICT[decision],
                approval_applied=False,
                rationale=r.rationale,
            )
        )
    return ParaphraseDecision(
        pairs=tuple(verdicts_l),
        verdict=worst(v.verdict for v in verdicts_l),
        injection_pairs=injection,
        refusal_reason=None,
    )
