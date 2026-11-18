"""``agent_06.claim_extraction`` (stage ``s06_claims``): E0-E6, D0-D11 (blueprint 6.8, 10).

The model proposes claims, offsets, types and flags; code validates them (D1, D2, D5), enforces
the severity table of 13 (a flag's severity can only be raised), adds the code-only net over the
script's own sentences (``detect.py``: D3 chart age, D4 URL / referral, D11 markers and the FIN
detectors) and recomputes every verdict (D7). The model's verdicts are never kept, and a model
refusal or an empty answer can never lower what code detected on its own.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_06_fact_checker.detect import Finding
from agent_06_fact_checker.models import (
    DataAge,
    ExtractedClaim,
    ExtractionOutput,
    ExtractionOverall,
    Refusal,
    RefusalReason,
    RuleFlag,
    Segment,
    Verdict,
    most_severe,
)
from agent_06_fact_checker.rulepack import FinLexicon
from amw_core.enums import ClaimType, RuleSeverity

FINANCE_PACK = "rp.finance_sebi_in"
FINANCE_CATEGORY = "finance"
REASON_CITATION = "A claim that needs a citation has none."
REASON_TYPE = "A claim of a type that finance rules restrict carries no rule flag."
REASON_UNSAFE = "The model refused part of the script as unsafe to process."
REASON_REFUSED = "The model refused part of the script; its segments need a human look."
_RAISING = (
    RefusalReason.CONFLICTING_INSTRUCTIONS,
    RefusalReason.OUT_OF_SCOPE,
    RefusalReason.INSUFFICIENT_INPUT,
)
_PRECEDENCE = (
    RefusalReason.UNSAFE_CONTENT,
    RefusalReason.RULE_WOULD_BE_BROKEN,
    *_RAISING,
)


def reason_for_warning(rule_id: str) -> str:
    return f"Warning flag {rule_id} needs a human look."


def reason_for_finding(finding: Finding) -> str:
    where = finding.segment_id or "the script"
    return f"Code check {finding.rule_id} matched in {where} without an extracted claim."


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


def floor_severity(lexicon: FinLexicon, rule_id: str, claim_type: ClaimType) -> RuleSeverity | None:
    """The severity floor of 13 for ``rule_id`` (data of the rule-pack record), else ``None``."""
    entry = lexicon.severity_floor.get(rule_id)
    if entry is None:
        return None
    if isinstance(entry, str):
        return RuleSeverity(entry)
    return RuleSeverity(entry.get(claim_type.value, entry["default"]))


def apply_floor(claims: Sequence[ExtractedClaim], lexicon: FinLexicon) -> list[ExtractedClaim]:
    """M-4: the model may raise a flag's severity, never lower it below the table of 13."""
    out: list[ExtractedClaim] = []
    for c in claims:
        flags = c.rule_flags
        for flag in c.rule_flags:
            floor = floor_severity(lexicon, flag.rule_id, c.claim_type)
            if floor is RuleSeverity.BLOCKING and flag.severity is RuleSeverity.WARNING:
                flags = with_flag(flags, flag.rule_id, RuleSeverity.BLOCKING, flag.evidence)
        out.append(c.model_copy(update={"rule_flags": flags}))
    return out


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


# ------------------------------------------------------------------ D3 and the code findings
def apply_chart_flags(
    claims: Sequence[ExtractedClaim], ages: Mapping[str, DataAge | None]
) -> list[ExtractedClaim]:
    """D3: a claim linked to a chart WITHIN_LAG or UNKNOWN gets a BLOCKING FIN-R9 flag."""
    out: list[ExtractedClaim] = []
    for c in claims:
        flags = c.rule_flags
        if c.chart_data_ref is not None and ages.get(c.chart_data_ref) in (
            DataAge.WITHIN_LAG,
            DataAge.UNKNOWN,
        ):
            flags = with_flag(flags, "FIN-R9", RuleSeverity.BLOCKING, c.chart_data_ref)
        out.append(c.model_copy(update={"rule_flags": flags}))
    return out


def attach_findings(
    claims: Sequence[ExtractedClaim], findings: Sequence[Finding]
) -> tuple[list[ExtractedClaim], list[Finding]]:
    """A finding flags every claim that overlaps its sentence; one that overlaps no claim stays a
    segment-level finding (it still decides the verdict; it is never dropped)."""
    flags: dict[int, tuple[RuleFlag, ...]] = {i: c.rule_flags for i, c in enumerate(claims)}
    loose: list[Finding] = []
    for f in findings:
        hit = [
            i
            for i, c in enumerate(claims)
            if f.segment_id is not None
            and c.segment_id == f.segment_id
            and c.char_start < f.end
            and f.start < c.char_end
        ]
        if not hit:
            loose.append(f)
        for i in hit:
            flags[i] = with_flag(flags[i], f.rule_id, f.severity, f.evidence)
    return [c.model_copy(update={"rule_flags": flags[i]}) for i, c in enumerate(claims)], loose


def drop_fin_flags(claims: Sequence[ExtractedClaim]) -> tuple[list[ExtractedClaim], int]:
    """D10: without ``rp.finance_sebi_in`` no FIN flag survives."""
    dropped = 0
    out: list[ExtractedClaim] = []
    for c in claims:
        kept = tuple(f for f in c.rule_flags if not f.rule_id.startswith("FIN-"))
        dropped += len(c.rule_flags) - len(kept)
        out.append(c.model_copy(update={"rule_flags": kept}))
    return out, dropped


# ------------------------------------------------------------------ D6, D7
def claim_verdict(claim: ExtractedClaim, restricted_types: frozenset[str] = frozenset()) -> Verdict:
    """D7 for one claim: BLOCKING flag, else WARNING flag, D6, or a restricted type with no FIN
    flag (finance pack only), else ALLOWED."""
    if any(f.severity is RuleSeverity.BLOCKING for f in claim.rule_flags):
        return Verdict.BLOCKED
    missing_citation = claim.requires_citation and not claim.citation_refs
    unflagged_type = claim.claim_type.value in restricted_types and not any(
        f.rule_id.startswith("FIN-") for f in claim.rule_flags
    )
    if (
        missing_citation
        or unflagged_type
        or any(f.severity is RuleSeverity.WARNING for f in claim.rule_flags)
    ):
        return Verdict.NEEDS_HUMAN_REVIEW
    return Verdict.ALLOWED


@dataclass(frozen=True, slots=True)
class RefusalEffect:
    """What the model's refusals contribute to the verdict (deterministic, most severe wins)."""

    verdict: Verdict = Verdict.ALLOWED
    rule_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    shown: Refusal | None = None
    """The refusal object reported when no claim survives: UNSAFE_CONTENT, then
    RULE_WOULD_BE_BROKEN, then the rest."""


def refusal_effect(refusals: Sequence[Refusal]) -> RefusalEffect:
    """Order: ``UNSAFE_CONTENT`` > ``RULE_WOULD_BE_BROKEN`` > the others, as a *report* order;
    the verdict is the most severe of all of them (RULE_WOULD_BE_BROKEN is BLOCKED)."""
    if not refusals:
        return RefusalEffect()
    verdict = Verdict.ALLOWED
    ids: set[str] = set()
    reasons: set[str] = set()
    for r in refusals:
        if r.reason is RefusalReason.RULE_WOULD_BE_BROKEN:
            verdict = most_severe(verdict, Verdict.BLOCKED)
            ids.update(r.violated_rule_ids)
        elif r.reason is RefusalReason.UNSAFE_CONTENT:
            verdict = most_severe(verdict, Verdict.NEEDS_HUMAN_REVIEW)
            reasons.add(REASON_UNSAFE)
        else:
            verdict = most_severe(verdict, Verdict.NEEDS_HUMAN_REVIEW)
            reasons.add(REASON_REFUSED)
    shown = min(refusals, key=lambda r: _PRECEDENCE.index(r.reason))
    return RefusalEffect(verdict, tuple(sorted(ids)), tuple(sorted(reasons)), shown)


def raising_refusal(refusals: Sequence[Refusal]) -> Refusal | None:
    """The refusal that fails the task (only when no claim exists), by a fixed order."""
    raising = [r for r in refusals if r.reason in _RAISING]
    if not raising:
        return None
    return min(raising, key=lambda r: _RAISING.index(r.reason))


def recompute(
    claims: Sequence[ExtractedClaim],
    loose: Sequence[Finding],
    effect: RefusalEffect,
    restricted_types: frozenset[str] = frozenset(),
) -> tuple[list[ExtractedClaim], ExtractionOverall, int]:
    """D7: per-claim and overall verdicts by code; returns the number of model verdicts changed."""
    out: list[ExtractedClaim] = []
    changed = 0
    blocking: set[str] = set(effect.rule_ids)
    reasons: set[str] = set(effect.reasons)
    verdicts: list[Verdict] = [effect.verdict]
    for c in claims:
        verdict = claim_verdict(c, restricted_types)
        changed += verdict is not c.proposed_verdict
        out.append(c.model_copy(update={"proposed_verdict": verdict}))
        verdicts.append(verdict)
        blocking.update(f.rule_id for f in c.rule_flags if f.severity is RuleSeverity.BLOCKING)
        reasons.update(
            reason_for_warning(f.rule_id)
            for f in c.rule_flags
            if f.severity is RuleSeverity.WARNING
        )
        if c.requires_citation and not c.citation_refs:
            reasons.add(REASON_CITATION)
        if (
            verdict is Verdict.NEEDS_HUMAN_REVIEW
            and c.claim_type.value in restricted_types
            and not any(f.rule_id.startswith("FIN-") for f in c.rule_flags)
        ):
            reasons.add(REASON_TYPE)
    for f in loose:
        if f.severity is RuleSeverity.BLOCKING:
            blocking.add(f.rule_id)
            verdicts.append(Verdict.BLOCKED)
        else:
            reasons.add(reason_for_finding(f))
            verdicts.append(Verdict.NEEDS_HUMAN_REVIEW)
    overall = most_severe(*verdicts)
    return (
        out,
        ExtractionOverall(
            proposed_verdict=overall,
            blocking_rule_ids=tuple(sorted(blocking)),
            needs_human_review_reasons=tuple(sorted(reasons)),
        ),
        changed,
    )


def refusal_only_output(overall: ExtractionOverall, effect: RefusalEffect) -> ExtractionOutput:
    """No claim survived: the output carries the refusal object (claims stay empty)."""
    return ExtractionOutput(claims=(), overall=overall, refusal=effect.shown)


@dataclass(slots=True)
class ExtractionReport:
    """Counts for logs and validation results (ids and counts only, NFR-6)."""

    batches: int = 0
    dropped_fin_flags: int = 0
    verdicts_changed: int = 0
    loose_findings: list[Finding] = field(default_factory=list)
    refused_batches: int = 0


__all__ = [
    "FINANCE_CATEGORY",
    "FINANCE_PACK",
    "ExtractionReport",
    "RefusalEffect",
    "SegmentBatch",
    "apply_chart_flags",
    "apply_floor",
    "attach_findings",
    "batch_segments",
    "claim_verdict",
    "drop_fin_flags",
    "raising_refusal",
    "recompute",
    "refusal_effect",
    "refusal_only_output",
    "structural_problems",
    "with_flag",
]
