"""VerdictAlgebra (C7, F-15; blueprint section 6.3 V1-V13): pure and monotonic.

Code checks run first; the policy judge reads only the items the pre-filter or Agent 06 flagged.
Every row is evaluated for each (item, rule); the worst outcome applies and no row can improve a
verdict set by another row (P-01). **A judge answer can never clear a code flag**: an upstream
BLOCKING flag, a named-instrument future marker (V6), a historical claim without a dated chart
(V9), a failed frame test (V7) or any deterministic FAIL stays in force whatever the judge says.
Doubt goes to the owner (``NEEDS_HUMAN_REVIEW``), never to ``ALLOWED``.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from agent_16_compliance_qa.base import worst
from agent_16_compliance_qa.checks import RuleResult
from agent_16_compliance_qa.config import Lexicon
from agent_16_compliance_qa.judge.models import (
    FrameTest,
    PolicyFinding,
    PolicyInput,
    PolicyItem,
    PolicyOutput,
)
from agent_16_compliance_qa.prefilter import future_marker, quote_verified
from amw_core.enums import CheckKind, CheckVerdict, ComplianceVerdict, DataAgeVsLag

Severity = Literal["BLOCKING", "WARNING"]
_FINDING_RANK: Final = {"NO_VIOLATION": 0, "UNCERTAIN": 1, "VIOLATION": 2}
_DIRECTION_RULES: Final = frozenset({"FIN-R3", "FIN-R13"})
KIDS_RULE: Final = "YTG-R7"
FINANCE_PREFIX: Final = "FIN-"


@dataclass(slots=True)
class PolicyCheck:
    """Post-checked judge output (D-1...D-9): only findings code could verify survive."""

    findings: dict[tuple[str, str], PolicyFinding] = field(default_factory=dict)
    frame_tests: dict[str, FrameTest] = field(default_factory=dict)
    injection_items: tuple[str, ...] = ()
    refusal_reason: str | None = None
    quote_failures: int = 0
    dropped: int = 0


def post_check(inp: PolicyInput, out: PolicyOutput) -> PolicyCheck:
    """D-2 local IDs exist, D-4 rule in the item's ``rules_to_check``, D-9 no finding for an
    inactive pack, D-3 an unverifiable quote turns the finding into ``UNCERTAIN``, D-7 a refusal
    carries no findings, D-8 injection items are reported (never obeyed)."""
    items = {i.item_id: i for i in inp.items}
    active = frozenset(inp.active_rule_ids)
    check = PolicyCheck(
        injection_items=tuple(sorted({i for i in out.injection_suspected if i in items})),
        refusal_reason=out.refusal.reason if out.refusal else None,
    )
    if out.refusal is not None:
        return check
    for f in out.findings:
        item = items.get(f.item_id)
        if item is None or f.rule_id not in item.rules_to_check or f.rule_id not in active:
            check.dropped += 1
            continue
        if f.finding != "NO_VIOLATION" and not quote_verified(f.quote, item.text):
            check.quote_failures += 1
            f = f.model_copy(update={"finding": "UNCERTAIN", "quote": None})
        key = (f.item_id, f.rule_id)
        old = check.findings.get(key)
        if old is None or _FINDING_RANK[f.finding] > _FINDING_RANK[old.finding]:
            check.findings[key] = f
    check.frame_tests = {t.item_id: t for t in out.frame_tests if t.item_id in items}
    return check


def _row(
    rule: str,
    check: CheckVerdict,
    verdict: ComplianceVerdict | None,
    why: str,
    item: PolicyItem,
    kind: CheckKind = CheckKind.LLM_JUDGE,
) -> RuleResult:
    return RuleResult(
        rule_id=rule,
        check_verdict=check,
        compliance_verdict=verdict,
        kind=kind,
        rationale=why[:1000],
        item_refs=(item.item_id,),
        remedy="thumbnails" if item.surface == "THUMBNAIL_TEXT" else "script",
    )


def judged_rule(
    item: PolicyItem,
    rule: str,
    check: PolicyCheck,
    lexicon: Lexicon,
    severity: Severity,
) -> RuleResult:
    """Every matching row of V4-V11 for one (item, rule); the worst one is returned."""
    nhr, blocked = ComplianceVerdict.NEEDS_HUMAN_REVIEW, ComplianceVerdict.BLOCKED
    rows: list[RuleResult] = []
    f = check.findings.get((item.item_id, rule))
    finding = f.finding if f is not None else "UNCERTAIN"  # a missing finding is doubt
    if check.refusal_reason is not None:
        rows.append(
            _row(rule, CheckVerdict.WARN, nhr, f"judge refusal {check.refusal_reason}", item)
        )
    elif finding == "VIOLATION":
        if rule == KIDS_RULE:  # V11: never BLOCKED by a judge, never ALLOWED
            rows.append(_row(rule, CheckVerdict.WARN, nhr, "child-directed content (V11)", item))
        elif severity == "BLOCKING":  # V4: verified exact quote
            rows.append(_row(rule, CheckVerdict.FAIL, blocked, f.rationale if f else rule, item))
        else:  # V8
            rows.append(_row(rule, CheckVerdict.WARN, None, "warning-severity rule", item))
    elif finding == "UNCERTAIN":  # V5 (also an unverified quote or a missing finding)
        rows.append(_row(rule, CheckVerdict.WARN, nhr, "judge uncertain or quote unverified", item))
    else:
        flagged = any(rule in c.rule_flags for c in item.claims)
        marker = (
            rule in _DIRECTION_RULES
            and bool(item.named_instruments)
            and future_marker(item.text, lexicon)
        )
        if flagged or marker:  # V6: the judge alone never clears an upstream or code flag
            why = "upstream BLOCKING flag" if flagged else "named instrument + future marker"
            rows.append(_row(rule, CheckVerdict.WARN, nhr, f"{why}; judge NO_VIOLATION (V6)", item))
    if rule == "FIN-R13" and item.named_instruments:
        test = check.frame_tests.get(item.item_id)
        if test is None and check.refusal_reason is None:
            rows.append(_row(rule, CheckVerdict.WARN, nhr, "frame test missing (A9)", item))
        elif test is not None and (not test.past_tense_frame or test.leaves_expectation):
            rows.append(_row(rule, CheckVerdict.FAIL, blocked, "frame test not met (V7)", item))
        if (
            finding != "VIOLATION"
            and item.chart is None
            and any(c.claim_type == "HISTORICAL_MARKET" for c in item.claims)
        ):  # V9: deterministic, whatever the judge said
            rows.append(
                _row(
                    rule,
                    CheckVerdict.WARN,
                    nhr,
                    "historical claim, no dated chart (V9)",
                    item,
                    CheckKind.DETERMINISTIC,
                )
            )
    if not rows:  # V13
        return _row(rule, CheckVerdict.PASS, ComplianceVerdict.ALLOWED, "no violation", item)
    v = worst(r.compliance_verdict for r in rows)
    fails = [r for r in rows if r.compliance_verdict is v]
    return fails[0] if v is not ComplianceVerdict.ALLOWED or fails else rows[0]


def chart_age_rule(items: Sequence[PolicyItem], finance_active: bool) -> list[RuleResult]:
    """FIN-R9 recomputed from each item's chart (``WITHIN_LAG`` and ``UNKNOWN`` block; a
    schematic chart carries ``null`` and is skipped; GLOSSARY section 6.52, CCR-042)."""
    if not finance_active:
        return []
    out = []
    for item in items:
        age = item.chart.data_age_vs_lag if item.chart else None
        if age in (DataAgeVsLag.WITHIN_LAG, DataAgeVsLag.UNKNOWN):
            out.append(
                RuleResult(
                    rule_id="FIN-R9",
                    check_verdict=CheckVerdict.FAIL,
                    compliance_verdict=ComplianceVerdict.BLOCKED,
                    rationale=f"chart data age {age.value if age else ''} vs the lag",
                    item_refs=(item.item_id,),
                    remedy="assets",
                )
            )
    return out


def evaluate_policy(
    inp: PolicyInput,
    check: PolicyCheck,
    lexicon: Lexicon,
    severities: Mapping[str, Severity],
) -> list[RuleResult]:
    """All judged rule rows of one policy batch plus the item-level FIN-R9 rows."""
    results: list[RuleResult] = []
    active = frozenset(inp.active_rule_ids)
    for item in inp.items:
        for rule in item.rules_to_check:
            if rule not in active:  # D-9 / REF: an inactive rule is never judged as clean
                results.append(
                    _row(
                        rule,
                        CheckVerdict.WARN,
                        ComplianceVerdict.NEEDS_HUMAN_REVIEW,
                        "rule not active for this channel",
                        item,
                    )
                )
                continue
            results.append(
                judged_rule(item, rule, check, lexicon, severities.get(rule, "BLOCKING"))
            )
    results += chart_age_rule(inp.items, any(r.startswith(FINANCE_PREFIX) for r in active))
    return results


def policy_verdict(results: Iterable[RuleResult]) -> ComplianceVerdict:
    return worst(r.compliance_verdict for r in results)


def overall_verdict(
    rule_results: Iterable[RuleResult],
    uniqueness: ComplianceVerdict,
    disclosure_nhr: bool,
    extra: Iterable[ComplianceVerdict | None] = (),
) -> ComplianceVerdict:
    """Section 6.3 last paragraph: worst pack verdict, the S2 verdict and the disclosure
    decision (NHR decision => at least NHR). A disclaimer never changes another rule."""
    parts: list[ComplianceVerdict | None] = [r.compliance_verdict for r in rule_results]
    parts += [uniqueness, *extra]
    if disclosure_nhr:
        parts.append(ComplianceVerdict.NEEDS_HUMAN_REVIEW)
    return worst(parts)
