"""``VerificationPlanner`` (V1; blueprint 6.3, 10.3): the policy table gives a mode per claim.

Pure. A skipped claim keeps status ``EXTRACTED`` and its extraction verdict; a claim that cannot
be checked by design never reaches the model (NFR-15)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_06_fact_checker.config import FactCheckSettings, VerifyPolicy
from agent_06_fact_checker.models import (
    ChartFacts,
    ClaimMode,
    ReasonCode,
    VerificationClaim,
    VerifyMode,
)
from amw_core.enums import ClaimType
from amw_core.errors import InputInvalidError


@dataclass(frozen=True, slots=True)
class ClaimPlan:
    claim: VerificationClaim
    mode: ClaimMode
    reason: ReasonCode | None = None
    """Set for ``SKIPPED`` and ``CODE_ONLY`` plans (the reason code of blueprint 6.4 step 2)."""


def reject_blocked_input(
    claims: Sequence[VerificationClaim], overall: str, verify_mode: VerifyMode
) -> None:
    """V2: an input whose extraction verdict is BLOCKED is rejected before any read or call."""
    if overall == "BLOCKED" or any(c.extraction_verdict.value == "BLOCKED" for c in claims):
        raise InputInvalidError("input carries a BLOCKED extraction verdict; it is never verified")
    if verify_mode is VerifyMode.EVIDENCE and not claims:
        raise InputInvalidError("verify_mode EVIDENCE needs at least one claim")
    if verify_mode is VerifyMode.CHART_FACTS and any(
        c.chart_data_ref is None or c.claim_type is not ClaimType.HISTORICAL_MARKET for c in claims
    ):
        raise InputInvalidError("verify_mode CHART_FACTS takes only chart claims")


def plan_claims(
    claims: Sequence[VerificationClaim],
    verify_mode: VerifyMode,
    settings: FactCheckSettings,
    chart_facts: Mapping[str, ChartFacts],
) -> list[ClaimPlan]:
    plans: list[ClaimPlan] = []
    for claim in claims:
        policy = settings.policy[claim.claim_type]
        plans.append(_plan_one(claim, policy, verify_mode, chart_facts))
    return plans


def _plan_one(
    claim: VerificationClaim,
    policy: VerifyPolicy,
    verify_mode: VerifyMode,
    chart_facts: Mapping[str, ChartFacts],
) -> ClaimPlan:
    skipped = ClaimPlan(claim, ClaimMode.SKIPPED, ReasonCode.SKIPPED_BY_POLICY)
    match policy:
        case VerifyPolicy.SKIPPED:
            return skipped
        case VerifyPolicy.EVIDENCE:
            return ClaimPlan(claim, ClaimMode.EVIDENCE)
        case VerifyPolicy.EVIDENCE_IF_CITATION_REQUIRED:
            return ClaimPlan(claim, ClaimMode.EVIDENCE) if claim.requires_citation else skipped
        case VerifyPolicy.EVIDENCE_IF_CITED:
            if claim.citation_refs:
                return ClaimPlan(claim, ClaimMode.EVIDENCE)
            return ClaimPlan(claim, ClaimMode.CODE_ONLY, ReasonCode.QUOTE_NOT_ATTRIBUTABLE)
        case VerifyPolicy.CHART_FACTS_OR_PENDING:
            if claim.chart_data_ref is None:
                return ClaimPlan(claim, ClaimMode.EVIDENCE)
            if verify_mode is VerifyMode.EVIDENCE:
                return ClaimPlan(claim, ClaimMode.SKIPPED, ReasonCode.CHART_PENDING)
            facts = chart_facts.get(claim.chart_data_ref)
            if facts is None or not facts.facts:
                return ClaimPlan(claim, ClaimMode.CODE_ONLY, ReasonCode.NO_CHART_FACTS)
            return ClaimPlan(claim, ClaimMode.CHART_FACTS)
    raise AssertionError("unreachable")  # pragma: no cover - the match covers the enum
