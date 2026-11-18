"""``agent_06.claim_extraction`` (stage ``s06_claims``): E0-E6, D0-D11 (blueprint 6.8, 10).

The model proposes claims, offsets, types and flags; code validates them (D1, D2, D5), adds the
deterministic net (D3 chart age, D4 URL / referral, D11 future markers), drops FIN flags of an
inactive pack (D10) and recomputes every verdict (D7). The model's verdicts are never kept.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_06_fact_checker.config import FactCheckSettings
from agent_06_fact_checker.lexicon import all_markers, find_marker, find_patterns, find_urls
from agent_06_fact_checker.models import (
    ChartDataRef,
    DataAge,
    ExtractedClaim,
    ExtractionInput,
    ExtractionOutput,
    ExtractionOverall,
    Refusal,
    RefusalReason,
    RuleFlag,
    Segment,
    Verdict,
    most_severe,
)
from agent_06_fact_checker.rulepack import RulePack, RulePackResolver
from amw_core.enums import RuleSeverity

FINANCE_PACK = "rp.finance_sebi_in"
REASON_CITATION = "A claim that needs a citation has none."
REASON_UNATTACHED = "A URL or referral code appears in a segment without any extracted claim."
REASON_UNSAFE = "The model refused the script as unsafe to process."


def reason_for_warning(rule_id: str) -> str:
    return f"Warning flag {rule_id} needs a human look."


# ------------------------------------------------------------------ D8: batching
@dataclass(frozen=True, slots=True)
class SegmentBatch:
    index: int
    segments: tuple[Segment, ...]


def batch_segments(segments: Sequence[Segment], max_chars: int) -> list[SegmentBatch]:
    """D8: pack whole segments under ``max_chars``; a segment is never split."""
    batches: list[list[Segment]] = [[]]
    used = 0
    for seg in segments:
        size = len(seg.text)
        if batches[-1] and used + size > max_chars:
            batches.append([])
            used = 0
        batches[-1].append(seg)
        used += size
    return [SegmentBatch(i, tuple(b)) for i, b in enumerate(batches)]


# ------------------------------------------------------------------ flags
def with_flag(
    flags: tuple[RuleFlag, ...], rule_id: str, severity: RuleSeverity, evidence: str
) -> tuple[RuleFlag, ...]:
    """Add ``rule_id`` at ``severity``; an existing flag is only ever raised, never lowered."""
    text = (evidence.strip() or rule_id)[:500]
    for i, flag in enumerate(flags):
        if flag.rule_id == rule_id:
            if flag.severity is RuleSeverity.WARNING and severity is RuleSeverity.BLOCKING:
                out = list(flags)
                out[i] = RuleFlag(rule_id=rule_id, severity=severity, evidence=flag.evidence)
                return tuple(out)
            return flags
    return (*flags, RuleFlag(rule_id=rule_id, severity=severity, evidence=text))


# ------------------------------------------------------------------ structural checks (D1/D2/D5)
def structural_problems(
    claims: Sequence[ExtractedClaim],
    segments: Mapping[str, Segment],
    chart_refs: frozenset[str],
    citations: frozenset[str],
) -> list[str]:
    """D2, D5 and reference existence; messages carry local ids only, never claim text."""
    problems: list[str] = []
    seen: set[str] = set()
    for c in claims:
        if c.local_id in seen:
            problems.append(f"{c.local_id}: duplicate local_id")
        seen.add(c.local_id)
        seg = segments.get(c.segment_id)
        if seg is None:
            problems.append(f"{c.local_id}: unknown segment_id")
            continue
        if c.char_end <= c.char_start or c.char_end > len(seg.text):
            problems.append(f"{c.local_id}: offsets outside the segment")
        elif seg.text[c.char_start : c.char_end] != c.quote:
            problems.append(f"{c.local_id}: quote is not the exact text at the offsets")
        if c.chart_data_ref is not None and c.chart_data_ref not in chart_refs:
            problems.append(f"{c.local_id}: chart_data_ref is not in the input")
        missing = [r for r in c.citation_refs if r not in citations]
        if missing:
            problems.append(f"{c.local_id}: citation_refs not in available_citations")
    return problems


# ------------------------------------------------------------------ D3, D4, D10, D11
def apply_flags(
    claims: Sequence[ExtractedClaim],
    inp: ExtractionInput,
    ages: Mapping[str, DataAge | None],
    refs: Mapping[str, ChartDataRef],
    pack: RulePack | None,
    settings: FactCheckSettings,
) -> tuple[list[ExtractedClaim], list[str], int]:
    """D3, D4, D10, D11 in that order (D11 before D7). Returns claims, unattached-segment ids
    and the number of FIN flags dropped by D10."""
    finance = pack is not None
    dropped = 0
    out: list[ExtractedClaim] = []
    markers = all_markers(pack.markers) if pack else ()
    for claim in claims:
        flags = claim.rule_flags
        if not finance:  # D10
            kept = tuple(f for f in flags if not f.rule_id.startswith("FIN-"))
            dropped += len(flags) - len(kept)
            out.append(claim.model_copy(update={"rule_flags": kept}))
            continue
        if claim.chart_data_ref is not None and ages.get(claim.chart_data_ref) in (
            DataAge.WITHIN_LAG,
            DataAge.UNKNOWN,
        ):  # D3
            flags = with_flag(flags, "FIN-R9", RuleSeverity.BLOCKING, claim.chart_data_ref)
        named = claim.instrument is not None or (
            claim.chart_data_ref is not None and refs[claim.chart_data_ref].instrument != ""
        )
        hit = find_marker(claim.quote, markers) if named else None
        if hit is not None:  # D11
            flags = with_flag(flags, "FIN-R13", RuleSeverity.WARNING, hit)
        out.append(claim.model_copy(update={"rule_flags": flags}))
    unattached: list[str] = []
    if finance:
        out, unattached = _referral_flags(out, inp.segments, settings)
    return out, unattached, dropped


def _referral_flags(
    claims: list[ExtractedClaim], segments: Sequence[Segment], settings: FactCheckSettings
) -> tuple[list[ExtractedClaim], list[str]]:
    """D4: a URL or referral code flags the claim that contains it, else the nearest claim of
    its segment; a segment with such text and no claim is reported (never silently dropped)."""
    unattached: list[str] = []
    for seg in segments:
        spans = find_urls(seg.text) + find_patterns(seg.text, settings.referral_patterns)
        if not spans:
            continue
        idx = [i for i, c in enumerate(claims) if c.segment_id == seg.segment_id]
        if not idx:
            unattached.append(seg.segment_id)
            continue
        for start, end in spans:

            def gap(i: int, start: int = start, end: int = end) -> int:
                c = claims[i]
                return max(c.char_start - end, start - c.char_end, 0)

            target = min(idx, key=lambda i: (gap(i), i))
            claim = claims[target]
            evidence = seg.text[start:end]
            claims[target] = claim.model_copy(
                update={
                    "rule_flags": with_flag(
                        claim.rule_flags, "FIN-R8", RuleSeverity.WARNING, evidence
                    )
                }
            )
    return claims, unattached


# ------------------------------------------------------------------ D6, D7
def claim_verdict(claim: ExtractedClaim) -> Verdict:
    """D7 for one claim: BLOCKING flag, else WARNING flag or D6, else ALLOWED."""
    if any(f.severity is RuleSeverity.BLOCKING for f in claim.rule_flags):
        return Verdict.BLOCKED
    missing_citation = claim.requires_citation and not claim.citation_refs
    if missing_citation or any(f.severity is RuleSeverity.WARNING for f in claim.rule_flags):
        return Verdict.NEEDS_HUMAN_REVIEW
    return Verdict.ALLOWED


def recompute(
    claims: Sequence[ExtractedClaim], unattached: Sequence[str]
) -> tuple[list[ExtractedClaim], ExtractionOverall, int]:
    """D7: per-claim and overall verdicts by code; returns the number of model verdicts changed."""
    out: list[ExtractedClaim] = []
    changed = 0
    blocking: set[str] = set()
    reasons: set[str] = set()
    for c in claims:
        verdict = claim_verdict(c)
        changed += verdict is not c.proposed_verdict
        out.append(c.model_copy(update={"proposed_verdict": verdict}))
        blocking.update(f.rule_id for f in c.rule_flags if f.severity is RuleSeverity.BLOCKING)
        reasons.update(
            reason_for_warning(f.rule_id)
            for f in c.rule_flags
            if f.severity is RuleSeverity.WARNING
        )
        if c.requires_citation and not c.citation_refs:
            reasons.add(REASON_CITATION)
    if unattached:
        reasons.add(REASON_UNATTACHED)
    overall = most_severe(*(c.proposed_verdict for c in out))
    if unattached:
        overall = most_severe(overall, Verdict.NEEDS_HUMAN_REVIEW)
    return (
        out,
        ExtractionOverall(
            proposed_verdict=overall,
            blocking_rule_ids=tuple(sorted(blocking)),
            needs_human_review_reasons=tuple(sorted(reasons)),
        ),
        changed,
    )


def refusal_output(refusal: Refusal) -> ExtractionOutput | None:
    """Success-class refusals (blueprint 18): UNSAFE_CONTENT -> NEEDS_HUMAN_REVIEW, claims [];
    RULE_WOULD_BE_BROKEN -> BLOCKED. Other reasons fail the task (the step raises)."""
    if refusal.reason is RefusalReason.UNSAFE_CONTENT:
        return ExtractionOutput(
            claims=(),
            overall=ExtractionOverall(
                proposed_verdict=Verdict.NEEDS_HUMAN_REVIEW,
                blocking_rule_ids=(),
                needs_human_review_reasons=(REASON_UNSAFE,),
            ),
            refusal=refusal,
        )
    if refusal.reason is RefusalReason.RULE_WOULD_BE_BROKEN:
        return ExtractionOutput(
            claims=(),
            overall=ExtractionOverall(
                proposed_verdict=Verdict.BLOCKED,
                blocking_rule_ids=tuple(sorted(set(refusal.violated_rule_ids))),
                needs_human_review_reasons=(),
            ),
            refusal=refusal,
        )
    return None


@dataclass(slots=True)
class ExtractionReport:
    """Counts for logs and validation results (ids and counts only, NFR-6)."""

    batches: int = 0
    dropped_fin_flags: int = 0
    verdicts_changed: int = 0
    unattached_segments: list[str] = field(default_factory=list)


__all__ = [
    "FINANCE_PACK",
    "ExtractionReport",
    "RulePackResolver",
    "SegmentBatch",
    "apply_flags",
    "batch_segments",
    "claim_verdict",
    "recompute",
    "refusal_output",
    "structural_problems",
    "with_flag",
]
