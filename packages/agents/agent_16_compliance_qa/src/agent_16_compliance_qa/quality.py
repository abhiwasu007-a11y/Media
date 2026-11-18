"""QualityScore (``agent_16.quality_score``, ``s16_score``; F-18...F-20; blueprint section 6.6).

100 points: deterministic rows by code, judge rows by three grouped calls (G1-G3; G2 also returns
``edit.promise_alignment`` / ``edit.hook.beat_content``), human rows only by the owner (read at
``s16_auth``). Q-O2 provisional defaults: no machine scaling (machine total <= 79) and
``REPORT_ONLY`` (the score is reported, ``blocking: false``); the BLOCKING + NONE combination is
refused at startup by ``Agent16Config``.
"""

from collections.abc import Callable, Mapping
from typing import Any, Final, Literal

from pydantic import Field

from agent_16_compliance_qa.base import Model
from agent_16_compliance_qa.config import Agent16Config
from agent_16_compliance_qa.judge.models import QualityOutput
from agent_16_compliance_qa.judge.quality import CheckId, JudgedCheckRow, apply_quality
from agent_16_compliance_qa.scoring.aggregate import (
    CriterionScore,
    DeterministicInputs,
    DimensionRow,
    aggregate,
    score_deterministic,
    score_gate,
)
from agent_16_compliance_qa.scoring.rubric import RUBRIC_VERSION, Group, group_criteria
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import CheckKind, CheckVerdict

GROUPS: Final[tuple[Group, ...]] = ("G1", "G2", "G3")
QualityJudge = Callable[[Mapping[str, Any]], QualityOutput]


class GroupRequest(Model):
    payload: dict[str, Any] | None
    """The ``quality_score.judge.input`` payload; ``None`` when the group's inputs are absent."""
    known_refs: frozenset[str]
    requested_checks: tuple[CheckId, ...] = ()
    expected_elements: dict[CheckId, frozenset[str]] = Field(default_factory=dict)


class ScoreResult(Model):
    gate: Literal["PASS", "FAIL", "NOT_GATING"]
    machine_total: float
    threshold: float
    dimensions: tuple[DimensionRow, ...]
    judged_checks: tuple[JudgedCheckRow, ...]
    judge_calls: int
    results: tuple[ValidationResult, ...]
    injection: tuple[str, ...]


class QualityScorer:
    def __init__(self, cfg: Agent16Config, judge: QualityJudge) -> None:
        self._cfg, self._judge = cfg, judge

    def score(
        self,
        det: DeterministicInputs,
        groups: Mapping[Group, GroupRequest],
        routing: Mapping[str, str | None],
    ) -> ScoreResult:
        scores: list[CriterionScore] = score_deterministic(det)
        checks: list[JudgedCheckRow] = []
        injection: list[str] = []
        calls = 0
        for g in GROUPS:
            req = groups.get(g)
            out = None
            if req is not None and req.payload is not None:
                out = self._judge(req.payload)
                calls += 1
                if out.group_id != g:
                    out = None  # a reply for another group is not this group's evidence
            res = apply_quality(
                group_criteria(g),
                out,
                req.known_refs if req else frozenset(),
                req.requested_checks if req else (),
                dict(req.expected_elements) if req else {},
            )
            scores += res.scores
            checks += res.checks
            injection += res.injection
        rows = aggregate(scores, self._cfg.machine_scaling)
        gate, gate_res, total = score_gate(
            rows, self._cfg.publish_min_score, self._cfg.score_gate_mode, routing
        )
        results: list[ValidationResult] = []
        for r in rows:
            d = [c for c in r.criteria if c.kind == "DETERMINISTIC"]
            if d:
                ok = all(c.earned == c.max for c in d if c.status == "SCORED")
                results.append(
                    ValidationResult(
                        check_id=f"a16.qs.{_abbr(r)}.d",
                        kind=CheckKind.DETERMINISTIC,
                        verdict=CheckVerdict.PASS if ok else CheckVerdict.WARN,
                        blocking=False,
                        measured=sum(c.earned for c in d),
                        threshold=sum(c.max for c in d),
                        message=f"{r.dimension.value} deterministic part",
                        gate=True,
                    )
                )
        results += [
            ValidationResult(
                check_id=c.check_id,
                kind=CheckKind.LLM_JUDGE,
                verdict=CheckVerdict(c.verdict),
                blocking=False,
                message=c.rationale[:2000] or c.verdict,
                gate=True,
            )
            for c in checks
        ]
        results.append(gate_res)
        return ScoreResult(
            gate=gate,
            machine_total=total,
            threshold=self._cfg.publish_min_score,
            dimensions=rows,
            judged_checks=tuple(checks),
            judge_calls=calls,
            results=tuple(results),
            injection=tuple(injection),
        )


def _abbr(row: DimensionRow) -> str:
    return row.criteria[0].criterion_id.split(".")[0] if row.criteria else "xx"


def score_payload(
    res: ScoreResult, qsc_ids: list[str], provenance: Mapping[str, Any]
) -> dict[str, Any]:
    """``agent_16.quality_score.output`` 1.0.0 (section 8.4)."""
    return {
        "gate": res.gate,
        "machine_total": res.machine_total,
        "threshold": res.threshold,
        "rubric_version": RUBRIC_VERSION,
        "dimensions": [
            {
                "dimension": r.dimension.value,
                "max_points": r.max_points,
                "points": r.points,
                "scorer_kind": r.scorer_kind,
                "criteria": [
                    {
                        "criterion_id": c.criterion_id,
                        "kind": c.kind,
                        "max": c.max,
                        "earned": c.earned,
                        "status": c.status,
                        "precondition": c.precondition,
                        "evidence_refs": list(c.evidence_refs),
                    }
                    for c in r.criteria
                ],
            }
            for r in res.dimensions
        ],
        "judged_checks": [
            {
                "check_id": c.check_id,
                "verdict": c.verdict,
                "elements": [{"element_id": e, "score": s} for e, s in c.elements],
                "rationale": c.rationale[:500],
            }
            for c in res.judged_checks
        ],
        "quality_score_ids": qsc_ids,
        "judge_calls": res.judge_calls,
        "revision_findings": [
            {
                "rule_id": None,
                "item_ref": c.criterion_id,
                "finding": c.finding[:500],
                "remedy_stage_id": None,
            }
            for r in res.dimensions
            for c in r.criteria
            if c.finding
        ],
        "gate_verdict": "FAILED" if res.gate == "FAIL" else "PASSED",
        "provenance": dict(provenance) | {"rubric_version": RUBRIC_VERSION},
    }
