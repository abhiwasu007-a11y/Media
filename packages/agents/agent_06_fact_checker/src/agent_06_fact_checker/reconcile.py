"""``ResultReconciler`` / ``StatusDeriver`` (P1-P10, status table of blueprint 6.4 steps 1-2).

The model's result is data, not authority: ids must be candidates of the claim, spans must lie
inside the window, discrepancy values must be verbatim, flagged passages are excluded, a
``SUPPORTED`` or ``CONTRADICTED`` assessment needs matching valid evidence. The status and reason
codes are then derived by code; the first matching row of the table wins."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.evidence import Candidate, ClaimEvidence
from agent_06_fact_checker.models import (
    Assessment,
    BatchEvidence,
    BatchResult,
    Certainty,
    ClaimMode,
    EvidenceSourceKind,
    OutputDiscrepancy,
    OutputEvidence,
    ReasonCode,
    Relation,
    VerificationClaim,
)
from agent_06_fact_checker.numbers import missing_numerals, numerals
from agent_06_fact_checker.planner import ClaimPlan
from agent_06_fact_checker.scan import scan_correction
from amw_core.enums import ClaimStatus

MAX_EVIDENCE_ITEMS = 6


@dataclass(slots=True)
class Outcome:
    """Code-derived result for one claim (before verdicts and conflicts)."""

    claim: VerificationClaim
    mode: ClaimMode
    status: ClaimStatus
    reasons: list[ReasonCode] = field(default_factory=list)
    assessment: Assessment | None = None
    certainty: Certainty | None = None
    script_cited: bool = False
    evidence: list[OutputEvidence] = field(default_factory=list)
    discrepancies: list[OutputDiscrepancy] = field(default_factory=list)
    suggested_correction: str | None = None
    suggested_citation_refs: list[str] = field(default_factory=list)
    restricted_used: bool = False
    correction_dropped: bool = False
    used_ids: list[str] = field(default_factory=list)
    """Batch evidence ids of the valid evidence items (self-checks of blueprint 8.4)."""
    support_texts: list[str] = field(default_factory=list)
    support_tiers: list[str | None] = field(default_factory=list)


def static_outcome(plan: ClaimPlan, ev: ClaimEvidence | None) -> Outcome:
    """Rows 1-5 of the table: no model call (skipped, code-only, or no evidence)."""
    claim = plan.claim
    if plan.mode is ClaimMode.SKIPPED:
        reason = plan.reason or ReasonCode.SKIPPED_BY_POLICY
        return Outcome(claim, plan.mode, ClaimStatus.EXTRACTED, [reason])
    if plan.mode is ClaimMode.CODE_ONLY:
        if plan.reason is ReasonCode.QUOTE_NOT_ATTRIBUTABLE:
            status = ClaimStatus.NEEDS_SUBSTANTIATION
        else:
            status = ClaimStatus.UNVERIFIABLE
        return Outcome(claim, plan.mode, status, [plan.reason or ReasonCode.NO_EVIDENCE_CANDIDATES])
    # EVIDENCE mode, no candidate and not part of a conflict pair
    ev = ev or ClaimEvidence()
    reasons = list(ev.reasons)
    if ev.restricted_blocked and not ev.candidates:
        reasons.append(ReasonCode.RESTRICTED_NOT_RELEASED)
    else:
        reasons.insert(0, ReasonCode.NO_EVIDENCE_CANDIDATES)
    return Outcome(claim, ClaimMode.CODE_ONLY, ClaimStatus.UNVERIFIABLE, reasons)


def refused_outcome(plan: ClaimPlan) -> Outcome:
    """Declared item-level mapping of a verification refusal (27 4.3, CCR-023)."""
    return Outcome(
        plan.claim, plan.mode, ClaimStatus.UNVERIFIABLE, [ReasonCode.MODEL_REFUSED], None, None
    )


def _verbatim(value: str, haystacks: Collection[str]) -> bool:
    return any(value in h for h in haystacks)


def reconcile_claim(
    plan: ClaimPlan,
    ev: ClaimEvidence,
    cands: Mapping[str, Candidate],
    result: BatchResult,
    flagged: Collection[str],
    settings: FactCheckSettings,
) -> Outcome:
    claim = plan.claim
    reasons: list[ReasonCode] = list(ev.reasons)
    valid: list[tuple[BatchEvidence, Candidate]] = []
    for item in result.evidence:
        cand = cands.get(item.evidence_id)
        if cand is None:  # P3: not a candidate of this claim
            continue
        if not (
            0 <= item.span_start < item.span_end <= len(cand.text)
            and item.span_end - item.span_start <= settings.max_span_chars
        ):  # P4
            _add(reasons, ReasonCode.SPAN_INVALID)
            continue
        if item.evidence_id in flagged:  # P8
            _add(reasons, ReasonCode.INJECTED_EVIDENCE_DISCARDED)
            continue
        valid.append((item, cand))
    valid = valid[:MAX_EVIDENCE_ITEMS]
    sup = [(i, c) for i, c in valid if i.relation is Relation.SUPPORTS]
    con = [(i, c) for i, c in valid if i.relation is Relation.CONTRADICTS]

    assessment = result.assessment
    if (assessment is Assessment.SUPPORTED and not sup) or (
        assessment is Assessment.CONTRADICTED and not con
    ):
        assessment = Assessment.UNCLEAR

    out = Outcome(
        claim,
        plan.mode,
        ClaimStatus.UNVERIFIABLE,
        reasons,
        assessment,
        result.certainty,
        evidence=[
            OutputEvidence(
                source_kind=c.kind,
                source_ref=c.source_ref,
                relation=i.relation,
                char_start=c.offset + i.span_start,
                char_end=c.offset + i.span_end,
                content_sha256=c.source_sha256,
            )
            for i, c in valid
        ],
        restricted_used=any(c.restricted for _, c in valid),
    )
    out.used_ids = [i.evidence_id for i, _ in valid]
    out.support_texts = [c.text for _, c in sup]
    out.support_tiers = [c.tier for _, c in sup if c.kind is not EvidenceSourceKind.CHART_FACT]
    texts = {c.text for c in cands.values()}
    claim_texts = (claim.quote, claim.normalized_claim)
    out.discrepancies = [
        OutputDiscrepancy(kind=d.kind, claim_value=d.claim_value, evidence_value=d.evidence_value)
        for d in result.discrepancies
        if _verbatim(d.claim_value, claim_texts) and _verbatim(d.evidence_value, texts)
    ]
    _derive(out, plan, sup, con, assessment, result.certainty, settings)
    out.script_cited = _script_cited(out, plan, sup)
    _correction(out, result, assessment, settings)
    return out


def _add(reasons: list[ReasonCode], code: ReasonCode) -> None:
    if code not in reasons:
        reasons.append(code)


def _script_cited(
    out: Outcome, plan: ClaimPlan, sup: list[tuple[BatchEvidence, Candidate]]
) -> bool:
    claim = plan.claim
    if plan.mode is ClaimMode.CHART_FACTS:
        return any(c.source_ref.startswith(f"{claim.chart_data_ref}#") for _, c in sup)
    return bool({c.source_ref for _, c in sup} & set(claim.citation_refs))


def _derive(
    out: Outcome,
    plan: ClaimPlan,
    sup: list[tuple[BatchEvidence, Candidate]],
    con: list[tuple[BatchEvidence, Candidate]],
    assessment: Assessment,
    certainty: Certainty,
    s: FactCheckSettings,
) -> None:
    """Rows 6-14 of blueprint 6.4 step 2, first match wins."""

    def done(status: ClaimStatus, *codes: ReasonCode) -> None:
        out.status = status
        for code in codes:
            _add(out.reasons, code)

    if sup and con:  # 6
        return done(ClaimStatus.UNVERIFIABLE, ReasonCode.EVIDENCE_CONFLICT)
    if assessment is Assessment.CONTRADICTED:  # 7
        return done(ClaimStatus.CONTRADICTED, ReasonCode.CONTRADICTED_BY_EVIDENCE)
    if assessment is Assessment.PARTIALLY_SUPPORTED:  # 8
        return done(ClaimStatus.NEEDS_SUBSTANTIATION, ReasonCode.OVERREACH)
    if assessment is Assessment.NOT_FOUND:  # 9
        return done(ClaimStatus.UNVERIFIABLE, ReasonCode.NOT_FOUND_IN_EVIDENCE)
    if assessment is Assessment.UNCLEAR or certainty is Certainty.LOW:
        return done(ClaimStatus.UNVERIFIABLE, ReasonCode.MODEL_UNCERTAIN)
    # SUPPORTED from here
    claim = plan.claim
    evidence_texts = [c.text for _, c in sup]
    wanted = numerals(claim.quote + " " + claim.normalized_claim)
    if missing_numerals(wanted, evidence_texts, s.rounding_match):  # 10 (P7)
        return done(ClaimStatus.NEEDS_SUBSTANTIATION, ReasonCode.NUMBER_NOT_IN_EVIDENCE)
    if plan.mode is ClaimMode.CHART_FACTS:  # 13
        if any(c.source_ref.startswith(f"{claim.chart_data_ref}#") for _, c in sup):
            return done(ClaimStatus.VERIFIED)
        return done(ClaimStatus.UNVERIFIABLE, ReasonCode.NOT_FOUND_IN_EVIDENCE)
    library = [c for _, c in sup if c.kind is not EvidenceSourceKind.CHART_FACT]
    best = min((s.tier_rank(c.tier) for c in library), default=None)
    if best is None or best > s.tier_rank(s.min_tier_for_verified):  # 11
        return done(ClaimStatus.NEEDS_SUBSTANTIATION, ReasonCode.LOW_RELIABILITY_ONLY)
    refs = sorted({c.source_ref for c in library})
    if not set(refs) & set(claim.citation_refs):  # 12
        out.suggested_citation_refs = refs
        return done(ClaimStatus.NEEDS_SUBSTANTIATION, ReasonCode.NO_SCRIPT_CITATION)
    return done(ClaimStatus.VERIFIED)  # 14


def _correction(
    out: Outcome, result: BatchResult, assessment: Assessment, s: FactCheckSettings
) -> None:
    """Rule 11 and P10: a correction only for contradicted / partly supported claims, and never
    one with a URL, referral, price or recommendation wording."""
    text = result.suggested_correction
    if text is None or assessment not in (Assessment.CONTRADICTED, Assessment.PARTIALLY_SUPPORTED):
        return
    findings = scan_correction(text, s.referral_patterns, s.advice_words)
    if findings:
        out.correction_dropped = True
        return
    out.suggested_correction = text
