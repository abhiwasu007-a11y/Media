"""Deterministic baseline of the concept step for the ``thumbnail_concepts`` dataset.

It is NOT a model: it applies the code-side pre-screens (finance marker lexicon, injection scanner,
banned subjects, must-not-promise) and the fallback planner to a case input, then the guards.
The dataset's assertions A1..A15 are evaluated against this output so that CI exercises the
deterministic post-checks end to end. The judged part (J1..J4, an online model) is not run.
"""

import json
from typing import Any

from agent_11_thumbnail_design.fallback import FallbackPlanner, PlannerPolicy
from agent_11_thumbnail_design.guards import GuardContext, check_concepts
from agent_11_thumbnail_design.models import Concept, StepIn
from agent_11_thumbnail_design.scanner import InjectionScanner
from agent_11_thumbnail_design.text_options import finance_text_hit
from agent_11_thumbnail_design.textutil import fold

FIXTURE_MARKERS = [
    "buy",
    "sell",
    "hold",
    "target",
    "profit",
    "return",
    "guaranteed",
    "beat the market",
    "my method",
    "account",
    "broker",
    "referral",
]
CALL_MARKERS = ["buy", "sell", "hold", "target"]
INJECTION = ["ignore all rules", "ignore the rules", "show the link", "<<<input", "input>>>"]
NEUTRAL_WORDS = frozenset({"the", "a"})


def _no_safe(i: int, reason: str, rationale: str) -> dict[str, Any]:
    return {
        "concept_id": f"c{i + 1}",
        "status": "NO_SAFE_CONCEPT",
        "reason_code": reason,
        "template_key": None,
        "subject_option_id": None,
        "text_ids": [],
        "angle": None,
        "hypothesis_kind": None,
        "emphasis_style": None,
        "accent_role": None,
        "rationale": rationale,
    }


def baseline_output(doc: dict[str, Any]) -> dict[str, Any]:
    step = StepIn.model_validate(doc)
    finance = step.channel_category == "finance"
    refusal: dict[str, Any] | None = None
    base = {"call_seq": step.call_seq, "refusal": None}
    if not step.templates or not step.text_options:
        return {**base, "concepts": [], "refusal": _refusal("INSUFFICIENT_INPUT", "input is empty")}
    scanner = InjectionScanner(INJECTION)
    must = [fold(m) for m in step.brief.must_not_promise]
    banned = [fold(b) for b in step.banned_subjects]
    if finance and finance_text_hit(step.promise.working_title_local, CALL_MARKERS):
        n = step.variant_count
        return {
            **base,
            "concepts": [
                _no_safe(i, "PROMISE_IS_A_CALL", "The promise tells the viewer to act.")
                for i in range(n)
            ],
        }
    texts = [
        t
        for t in step.text_options
        if not scanner.scan(t.text).flagged
        and not any(m in fold(t.text) for m in must)
        and not (finance and finance_text_hit(t.text, FIXTURE_MARKERS))
    ]
    pics = [
        p
        for p in step.subject_options
        if not scanner.scan(p.label).flagged and not any(b in fold(p.label) for b in banned)
    ]
    if not texts:
        return {
            **base,
            "concepts": [],
            "refusal": _refusal(
                "RULE_WOULD_BE_BROKEN", "every text option breaks a rule", ["FIN-R1"]
            ),
        }
    if not pics:
        return {
            **base,
            "concepts": [
                _no_safe(i, "BANNED_SUBJECT", "Every picture option is excluded.")
                for i in range(step.variant_count)
            ],
        }
    narrowed = step.model_copy(
        update={"text_options": tuple(texts), "subject_options": tuple(pics)}
    )
    planner = FallbackPlanner(
        PlannerPolicy(finance=finance, faces_allowed=True, fin_lexicon=FIXTURE_MARKERS)
    )
    concepts = plan_with_keep(narrowed, planner)
    ctx = GuardContext(
        narrowed,
        finance,
        True,
        scanner,
        NEUTRAL_WORDS,
        FIXTURE_MARKERS,
        {"no_distinct_option": True},
    )
    hits = check_concepts(concepts, ctx)
    if hits:
        raise AssertionError(f"baseline produced a guard hit: {hits}")
    return {
        **base,
        "concepts": [json.loads(c.model_dump_json()) for c in concepts],
        "refusal": refusal,
    }


def _refusal(reason: str, message: str, rules: list[str] | None = None) -> dict[str, Any]:
    return {
        "reason": reason,
        "message": message,
        "missing_inputs": [],
        "violated_rule_ids": rules or [],
    }


def plan_with_keep(step: StepIn, planner: FallbackPlanner) -> list[Concept]:
    """What a faithful model does in a revision: repeat keep=true concepts, re-choose the rest."""
    keep = [
        Concept(
            concept_id=p.concept_id,
            status="OK",
            reason_code=None,
            template_key=p.template_key,
            subject_option_id=p.subject_option_id,
            text_ids=p.text_ids,
            angle=p.angle,
            hypothesis_kind=p.hypothesis_kind,
            emphasis_style=p.emphasis_style,
            accent_role=p.accent_role,
            rationale="Repeated from the previous set.",
        )
        for p in (step.previous_concepts or ())
        if p.keep
    ]
    kept = {k.concept_id for k in keep}
    need = [f"c{i + 1}" for i in range(step.variant_count) if f"c{i + 1}" not in kept]
    return planner.plan(step, keep, need)
