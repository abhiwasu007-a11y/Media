"""``VerdictEngine``, ``RevisionAdvisor``, ``AccuracyCounter`` (blueprint 6.4 steps 3-6). Pure.

Verdicts, gate results and revision requests are derived by code from statuses, reasons and
config (``factcheck.verdict_map``); Agent 16 keeps the final authority."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.models import (
    AccuracySummary,
    BatchConflict,
    ClaimMode,
    GateVerdict,
    OutputConflict,
    ReasonCode,
    RevisionAction,
    RevisionRequest,
    StatusCounts,
    Verdict,
    VerificationOverall,
    VerifiedClaim,
    most_severe,
)
from agent_06_fact_checker.reconcile import Outcome
from amw_core.enums import ClaimStatus, ClaimType

_CHECKABLE = frozenset({ClaimType.FACTUAL, ClaimType.STATISTICAL, ClaimType.HISTORICAL_MARKET})
REASON_CONFLICT = "Two claims of this script contradict each other."
_ACTIONS: tuple[tuple[ReasonCode, RevisionAction], ...] = (
    (ReasonCode.CONTRADICTED_BY_EVIDENCE, RevisionAction.CORRECT_CLAIM),
    (ReasonCode.OVERREACH, RevisionAction.CORRECT_CLAIM),
    (ReasonCode.NO_SCRIPT_CITATION, RevisionAction.ADD_CITATION),
    (ReasonCode.LOW_RELIABILITY_ONLY, RevisionAction.PROVIDE_EVIDENCE),
    (ReasonCode.NOT_FOUND_IN_EVIDENCE, RevisionAction.PROVIDE_EVIDENCE),
    (ReasonCode.NO_CHART_FACTS, RevisionAction.PROVIDE_EVIDENCE),
    (ReasonCode.CLAIM_CONFLICT, RevisionAction.RESOLVE_CONFLICT),
    (ReasonCode.QUOTE_NOT_ATTRIBUTABLE, RevisionAction.REMOVE_OR_REWORD),
)


def reason_text(status: ClaimStatus, code: ReasonCode) -> str:
    return f"{status.value}: {code.value}"


def apply_conflicts(
    outcomes: Sequence[Outcome], reported: Sequence[BatchConflict]
) -> list[tuple[BatchConflict, Outcome, Outcome]]:
    """Step 3: keep a pair only if both claims exist, differ and are in the verifiable set; both
    get ``CLAIM_CONFLICT``; two ``VERIFIED`` claims become ``UNVERIFIABLE``; a ``CONTRADICTED``
    claim keeps its status."""
    verifiable = {
        o.claim.local_id: o
        for o in outcomes
        if o.status is not ClaimStatus.EXTRACTED and o.mode is not ClaimMode.SKIPPED
    }
    kept: list[tuple[BatchConflict, Outcome, Outcome]] = []
    seen: set[frozenset[str]] = set()
    for pair in reported:
        a, b = verifiable.get(pair.claim_a), verifiable.get(pair.claim_b)
        key = frozenset((pair.claim_a, pair.claim_b))
        if a is None or b is None or a is b or key in seen:
            continue
        seen.add(key)
        kept.append((pair, a, b))
    both_verified = [(a, b) for _, a, b in kept if a.status is b.status is ClaimStatus.VERIFIED]
    for _, a, b in kept:
        for o in (a, b):
            if ReasonCode.CLAIM_CONFLICT not in o.reasons:
                o.reasons.append(ReasonCode.CLAIM_CONFLICT)
    for a, b in both_verified:
        a.status = b.status = ClaimStatus.UNVERIFIABLE
    return kept


@dataclass(frozen=True, slots=True)
class StageResult:
    claims: tuple[VerifiedClaim, ...]
    conflicts: tuple[OutputConflict, ...]
    overall: VerificationOverall
    gate: GateVerdict
    revisions: tuple[RevisionRequest, ...]
    accuracy: AccuracySummary


def verification_verdict(
    status: ClaimStatus, verdict_map: Mapping[ClaimStatus, Verdict]
) -> Verdict | None:
    if status is ClaimStatus.EXTRACTED:
        return None
    return verdict_map[status]


def finalize(
    outcomes: Sequence[Outcome],
    kept: Sequence[tuple[BatchConflict, Outcome, Outcome]],
    extraction_verdicts: Mapping[str, Verdict],
    extraction_overall: Verdict,
    claim_ids: Mapping[str, str],
    settings: FactCheckSettings,
    *,
    include_extraction_overall: bool,
) -> StageResult:
    claims: list[VerifiedClaim] = []
    for o in outcomes:
        ver = verification_verdict(o.status, settings.verdict_map)
        combined = most_severe(extraction_verdicts[o.claim.local_id], ver or Verdict.ALLOWED)
        claims.append(
            VerifiedClaim(
                claim_id=o.claim.claim_id,
                local_id=o.claim.local_id,
                mode=o.mode,
                status=o.status,
                reason_codes=tuple(o.reasons),
                verification_verdict=ver,
                combined_verdict=combined,
                assessment=o.assessment,
                certainty=o.certainty,
                script_cited=o.script_cited,
                evidence=tuple(o.evidence),
                discrepancies=tuple(o.discrepancies),
                suggested_correction=o.suggested_correction,
                suggested_citation_refs=tuple(o.suggested_citation_refs),
            )
        )
    conflicts = tuple(
        OutputConflict(
            claim_ids=(a.claim.claim_id, b.claim.claim_id),
            local_ids=(a.claim.local_id, b.claim.local_id),
            kind=pair.kind,
            explanation=pair.explanation,
        )
        for pair, a, b in kept
    )
    verifs = [c.verification_verdict for c in claims if c.verification_verdict is not None]
    ver_overall = most_severe(*verifs)
    stage = most_severe(*(c.combined_verdict for c in claims))
    if include_extraction_overall:
        stage = most_severe(stage, extraction_overall)
    if conflicts:
        stage = most_severe(stage, Verdict.NEEDS_HUMAN_REVIEW)
        ver_overall = most_severe(ver_overall, Verdict.NEEDS_HUMAN_REVIEW)
    reasons: set[str] = set()
    for c in claims:
        if c.status in (ClaimStatus.UNVERIFIABLE, ClaimStatus.NEEDS_SUBSTANTIATION):
            reasons.update(reason_text(c.status, code) for code in c.reason_codes)
    if conflicts:
        reasons.add(REASON_CONFLICT)
    counts = {s: sum(1 for c in claims if c.status is s) for s in ClaimStatus}
    overall = VerificationOverall(
        proposed_verdict=stage,
        verification_verdict=ver_overall,
        blocking_claim_ids=tuple(
            c.claim_id for c in claims if c.combined_verdict is Verdict.BLOCKED
        ),
        needs_human_review_reasons=tuple(sorted(reasons)),
        counts=StatusCounts(
            EXTRACTED=counts[ClaimStatus.EXTRACTED],
            VERIFIED=counts[ClaimStatus.VERIFIED],
            CONTRADICTED=counts[ClaimStatus.CONTRADICTED],
            UNVERIFIABLE=counts[ClaimStatus.UNVERIFIABLE],
            NEEDS_SUBSTANTIATION=counts[ClaimStatus.NEEDS_SUBSTANTIATION],
        ),
    )
    gate = (
        GateVerdict.FAILED
        if any(c.status is ClaimStatus.CONTRADICTED for c in claims)
        else GateVerdict.PASSED
    )
    return StageResult(
        tuple(claims),
        conflicts,
        overall,
        gate,
        revision_requests(outcomes),
        accuracy(outcomes),
    )


def _segment_no(segment_id: str) -> int:
    return int(segment_id[1:])


def revision_requests(outcomes: Sequence[Outcome]) -> tuple[RevisionRequest, ...]:
    """Step 5 (advisory), ordered by segment then claim; each names its ``segment_id``."""
    out: list[tuple[int, int, RevisionRequest]] = []
    for pos, o in enumerate(outcomes):
        if o.status is ClaimStatus.EXTRACTED:
            continue
        done: set[RevisionAction] = set()
        for code, action in _ACTIONS:
            if code not in o.reasons or action in done:
                continue
            done.add(action)
            detail = _detail(o, action)
            out.append(
                (
                    _segment_no(o.claim.segment_id),
                    pos,
                    RevisionRequest(
                        claim_id=o.claim.claim_id,
                        segment_id=o.claim.segment_id,
                        action=action,
                        detail=detail,
                        suggested_citation_refs=tuple(o.suggested_citation_refs)
                        if action is RevisionAction.ADD_CITATION
                        else (),
                    ),
                )
            )
    out.sort(key=lambda t: (t[0], t[1]))
    return tuple(r for _, _, r in out)


def _detail(o: Outcome, action: RevisionAction) -> str:
    if action is RevisionAction.CORRECT_CLAIM:
        if o.suggested_correction:
            return o.suggested_correction[:300]
        if o.discrepancies:
            return "; ".join(
                f"{d.kind.value}: '{d.claim_value}' vs '{d.evidence_value}'"
                for d in o.discrepancies
            )[:300]
        return "The evidence does not support the claim as written."
    return {
        RevisionAction.ADD_CITATION: "Cite the supporting source.",
        RevisionAction.PROVIDE_EVIDENCE: "No usable evidence decides this claim; provide a source.",
        RevisionAction.RESOLVE_CONFLICT: "This claim contradicts another claim of the script.",
        RevisionAction.REMOVE_OR_REWORD: "A quotation without an attributable citation.",
    }[action]


def accuracy(outcomes: Sequence[Outcome]) -> AccuracySummary:
    """Step 6: counters for 18 9.2 over FACTUAL, STATISTICAL and HISTORICAL_MARKET claims."""
    rows = [o for o in outcomes if o.claim.claim_type in _CHECKABLE]
    return AccuracySummary(
        checkable_total=len(rows),
        with_citation_or_chart=sum(
            1 for o in rows if o.claim.citation_refs or o.claim.chart_data_ref is not None
        ),
        verified=sum(1 for o in rows if o.status is ClaimStatus.VERIFIED),
        contradicted=sum(1 for o in rows if o.status is ClaimStatus.CONTRADICTED),
        unverifiable=sum(1 for o in rows if o.status is ClaimStatus.UNVERIFIABLE),
        needs_substantiation=sum(1 for o in rows if o.status is ClaimStatus.NEEDS_SUBSTANTIATION),
        chart_pending=sum(
            1
            for o in rows
            if o.status is ClaimStatus.EXTRACTED and ReasonCode.CHART_PENDING in o.reasons
        ),
    )
