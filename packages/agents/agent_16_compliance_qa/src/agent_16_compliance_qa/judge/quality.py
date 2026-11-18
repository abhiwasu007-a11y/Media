"""Quality judge post-check (F-19; prompt ``quality_score.v1`` D-1, D-2, D-6, D-7, D-8).

Only the J criteria of one group are judged; integers ``0 <= points <= max`` of the versioned
rubric (out of range => ``AGENT.OUTPUT_SCHEMA_INVALID``); a criterion the judge did not return,
or returned without an evidence reference that exists in the input, earns 0 with a finding; a
refusal scores the group 0. The judged checks ``edit.promise_alignment`` /
``edit.hook.beat_content`` become non-blocking check rows: ``PASS`` when every element scores
>= 1, ``WARN`` otherwise, ``SKIPPED`` when their inputs do not exist (18 section 3).
"""

from collections.abc import Sequence
from typing import Literal

from agent_16_compliance_qa.base import Model
from agent_16_compliance_qa.judge.models import QualityOutput
from agent_16_compliance_qa.scoring.aggregate import CriterionScore
from agent_16_compliance_qa.scoring.rubric import Criterion
from amw_core.errors import OutputSchemaInvalidError

CheckId = Literal["edit.promise_alignment", "edit.hook.beat_content"]


class JudgedCheckRow(Model):
    check_id: CheckId
    verdict: Literal["PASS", "WARN", "SKIPPED"]
    elements: tuple[tuple[str, int], ...]
    absent_content_elements: tuple[str, ...]
    rationale: str


class QualityGroupResult(Model):
    scores: tuple[CriterionScore, ...]
    checks: tuple[JudgedCheckRow, ...]
    injection: tuple[str, ...]
    refusal_reason: str | None


def apply_quality(
    criteria: Sequence[Criterion],
    out: QualityOutput | None,
    known_refs: frozenset[str],
    requested_checks: Sequence[CheckId],
    expected_elements: dict[CheckId, frozenset[str]],
) -> QualityGroupResult:
    """``out = None``: the call did not happen (no inputs) => 0 points with a finding."""
    refusal = out.refusal.reason if out is not None and out.refusal is not None else None
    given = {} if out is None or refusal else {s.criterion_id: s for s in out.scores}
    scores: list[CriterionScore] = []
    for c in criteria:
        s = given.get(c.criterion_id)
        base = {
            "criterion_id": c.criterion_id,
            "dimension": c.dimension,
            "kind": "LLM_JUDGE",
            "max": c.max_points,
            "status": "SCORED",
        }
        if s is None:
            why = f"judge refusal {refusal}" if refusal else "criterion not scored by the judge"
            scores.append(CriterionScore(**base, earned=0, finding=why))
            continue
        if s.max_points != c.max_points or s.points > c.max_points:
            raise OutputSchemaInvalidError(f"{c.criterion_id}: points outside 0..{c.max_points}")
        refs = tuple(r for r in s.evidence_refs if r in known_refs)
        if not refs:
            scores.append(CriterionScore(**base, earned=0, finding="no evidence ref in the input"))
            continue
        scores.append(CriterionScore(**base, earned=s.points, evidence_refs=refs))
    rows: list[JudgedCheckRow] = []
    results = {} if out is None or refusal else {r.check_id: r for r in out.check_results}
    for cid in requested_checks:
        expected = expected_elements.get(cid, frozenset())
        r = results.get(cid)
        if not expected:
            rows.append(
                JudgedCheckRow(
                    check_id=cid,
                    verdict="SKIPPED",
                    elements=(),
                    absent_content_elements=(),
                    rationale="inputs for the check do not exist",
                )
            )
            continue
        if r is None:
            rows.append(
                JudgedCheckRow(
                    check_id=cid,
                    verdict="WARN",
                    elements=(),
                    absent_content_elements=(),
                    rationale="judged check not returned",
                )
            )
            continue
        els = {e.element_id: e.score for e in r.elements if e.element_id in expected}
        complete = set(els) == set(expected)
        verdict: Literal["PASS", "WARN"] = (
            "PASS" if complete and all(v >= 1 for v in els.values()) else "WARN"
        )
        rows.append(
            JudgedCheckRow(
                check_id=cid,
                verdict=verdict,
                elements=tuple(sorted(els.items())),
                absent_content_elements=tuple(
                    a for a in r.absent_content_elements if a in expected
                ),
                rationale=r.rationale,
            )
        )
    injection = tuple(sorted(set(out.injection_suspected))) if out is not None else ()
    return QualityGroupResult(
        scores=tuple(scores), checks=tuple(rows), injection=injection, refusal_reason=refusal
    )
