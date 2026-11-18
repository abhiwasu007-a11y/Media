"""Deterministic rule checks of the gate (C1; blueprint section 6.1 rows 2-7a, section 6.4).

Verdict mapping (section 6.3): deterministic FAIL of a BLOCKING rule => ``BLOCKED`` (V3); a
missing or unparseable input => ``WARN`` + ``NEEDS_HUMAN_REVIEW`` (V2, never PASS or SKIPPED);
a recorded false precondition => ``SKIPPED`` with no compliance verdict (V1).
"""

from typing import Any

from pydantic import Field

from agent_16_compliance_qa.base import Model
from amw_core.enums import CheckKind, CheckVerdict, ComplianceVerdict


class RuleResult(Model):
    rule_id: str = Field(pattern=r"^[A-Z]{2,8}-R[0-9]{1,3}$")
    check_verdict: CheckVerdict
    compliance_verdict: ComplianceVerdict | None
    kind: CheckKind = CheckKind.DETERMINISTIC
    rationale: str = Field(max_length=1000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    precondition: str | None = None
    item_refs: tuple[str, ...] = ()
    remedy: str | None = None
    """``script`` / ``assets`` / ``thumbnails``: which routed stage fixes it (section 15.0)."""
    extras: dict[str, Any] = Field(default_factory=dict)


def passed(rule_id: str, rationale: str, **kw: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        check_verdict=CheckVerdict.PASS,
        compliance_verdict=ComplianceVerdict.ALLOWED,
        rationale=rationale,
        **kw,
    )


def failed(rule_id: str, rationale: str, **kw: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        check_verdict=CheckVerdict.FAIL,
        compliance_verdict=ComplianceVerdict.BLOCKED,
        rationale=rationale,
        **kw,
    )


def needs_human(rule_id: str, rationale: str, **kw: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        check_verdict=CheckVerdict.WARN,
        compliance_verdict=ComplianceVerdict.NEEDS_HUMAN_REVIEW,
        rationale=rationale,
        **kw,
    )


def skipped(rule_id: str, precondition: str, **kw: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        check_verdict=CheckVerdict.SKIPPED,
        compliance_verdict=None,
        rationale=precondition,
        precondition=precondition,
        **kw,
    )


__all__ = ["RuleResult", "failed", "needs_human", "passed", "skipped"]
