"""DeterministicCriteria (F-18), RubricAggregator (F-20) and the ``s16_score`` gate result
(blueprint section 6.6; Q-O2 provisional defaults: ``quality.machine_scaling = NONE``,
``quality.score_gate_mode = REPORT_ONLY``).

Missing input => the criterion earns 0 with a finding, never full points. ``SKIPPED`` criteria
(precondition false in 3A) earn 0; under ``PRO_RATA`` they leave both sums. The delivery
decision is always made at ``s16_auth`` (G9, G9a) on the human-wins total.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Final, Literal

from pydantic import Field

from agent_16_compliance_qa.base import Model
from agent_16_compliance_qa.config import MachineScaling, ScoreGateMode
from agent_16_compliance_qa.scoring.rubric import RUBRIC_V1, Criterion, machine_criteria
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import (
    CheckKind,
    CheckVerdict,
    ClaimStatus,
    ComplianceVerdict,
    DisclosureDecision,
    QualityDimension,
)

_DETERMINISTIC_DIMS: Final = frozenset(
    {QualityDimension.AUDIO_QUALITY, QualityDimension.COMPLIANCE}
)
_CITED_TYPES: Final = frozenset({"FACTUAL", "STATISTICAL", "HISTORICAL_MARKET"})


class CriterionScore(Model):
    criterion_id: str
    dimension: QualityDimension
    kind: Literal["DETERMINISTIC", "LLM_JUDGE"]
    max: float = Field(ge=0)
    earned: float = Field(ge=0)
    status: Literal["SCORED", "SKIPPED"]
    precondition: str | None = None
    evidence_refs: tuple[str, ...] = ()
    finding: str | None = None


class DimensionRow(Model):
    dimension: QualityDimension
    max_points: int
    points: float
    scorer_kind: Literal["DETERMINISTIC", "LLM_JUDGE"]
    criteria: tuple[CriterionScore, ...]


class QcRow(Model):
    check_id: str
    verdict: CheckVerdict
    precondition: str | None = None


class ClaimFact(Model):
    claim_id: str
    claim_type: str
    status: ClaimStatus | None
    has_citation_or_chart: bool
    sensitive_claim_approved: bool = False
    """``SENSITIVE_CLAIM`` approval naming the claim, derived as APPROVED from its steps."""


class ScriptFacts(Model):
    hook_options: int | None
    promise_fields_present: bool | None
    sections_with_takeaway: int | None
    sections_with_example: int | None
    section_count: int | None
    viewer_problem_addressed: bool | None


class ThumbnailFacts(Model):
    variants: int | None
    required_variants: int
    spec_ok: bool | None
    legible: bool | None
    title_length_ok: bool | None


class GateFacts(Model):
    overall: ComplianceVerdict
    licence_pass: bool | None
    disclosure_decision: DisclosureDecision | None
    disclaimer_pass: bool | None
    """``None`` when no finance pack is active (nothing to require)."""
    finance: bool


class DeterministicInputs(Model):
    qc: tuple[QcRow, ...]
    claims: tuple[ClaimFact, ...] | None
    script: ScriptFacts
    thumbnails: ThumbnailFacts
    gate: GateFacts


def _score(
    c: Criterion, ok: bool | None, refs: Iterable[str] = (), why: str = ""
) -> CriterionScore:
    if ok is None:
        return CriterionScore(
            criterion_id=c.criterion_id,
            dimension=c.dimension,
            kind="DETERMINISTIC",
            max=c.max_points,
            earned=0,
            status="SCORED",
            finding=f"input missing: {why or c.criterion_id}",
        )
    return CriterionScore(
        criterion_id=c.criterion_id,
        dimension=c.dimension,
        kind="DETERMINISTIC",
        max=c.max_points,
        earned=c.max_points if ok else 0,
        status="SCORED",
        evidence_refs=tuple(refs),
        finding=None if ok else why or "not met",
    )


def _qc(c: Criterion, qc: Sequence[QcRow]) -> CriterionScore:
    rows = [r for r in qc if any(r.check_id.startswith(p) for p in c.check_prefixes)]
    if c.precondition_3a and (not rows or all(r.verdict is CheckVerdict.SKIPPED for r in rows)):
        return CriterionScore(
            criterion_id=c.criterion_id,
            dimension=c.dimension,
            kind="DETERMINISTIC",
            max=c.max_points,
            earned=0,
            status="SKIPPED",
            precondition=c.precondition_3a,
        )
    if not rows:
        return _score(c, None, why="no qc_results row for " + ", ".join(c.check_prefixes))
    bad = [r.check_id for r in rows if r.verdict is not CheckVerdict.PASS]
    return _score(c, not bad, [r.check_id for r in rows], "not PASS: " + ", ".join(bad))


def _ratio_ok(part: int | None, whole: int | None) -> bool | None:
    if part is None or whole is None:
        return None
    return whole > 0 and part >= whole


def score_deterministic(d: DeterministicInputs) -> list[CriterionScore]:
    """Every D criterion of ``rubric.v1`` computed by code (no D criterion goes to a judge)."""
    s, t, g = d.script, d.thumbnails, d.gate
    out: list[CriterionScore] = []
    for c in RUBRIC_V1:
        if c.kind != "DETERMINISTIC":
            continue
        cid = c.criterion_id
        if c.check_prefixes:
            out.append(_qc(c, d.qc))
            continue
        claims = d.claims
        if cid == "ra.d.citations":
            ok = (
                None
                if claims is None
                else all(x.has_citation_or_chart for x in claims if x.claim_type in _CITED_TYPES)
            )
            out.append(_score(c, ok, why="a factual claim has no citation or chart reference"))
        elif cid == "ra.d.no_contradicted":
            ok = (
                None
                if claims is None
                else not any(x.status is ClaimStatus.CONTRADICTED for x in claims)
            )
            out.append(_score(c, ok, why="a CONTRADICTED claim remains"))
        elif cid == "ra.d.no_unverified":
            ok = (
                None
                if claims is None
                else all(
                    x.sensitive_claim_approved
                    for x in claims
                    if x.status in (ClaimStatus.UNVERIFIABLE, ClaimStatus.NEEDS_SUBSTANTIATION)
                )
            )
            out.append(_score(c, ok, why="unverified claim without an approved SENSITIVE_CLAIM"))
        elif cid == "st.d.promise_fields":
            out.append(_score(c, s.promise_fields_present, why="promise fields"))
        elif cid == "av.d.takeaways":
            out.append(
                _score(c, _ratio_ok(s.sections_with_takeaway, s.section_count), why="takeaway")
            )
        elif cid == "av.d.examples":
            out.append(
                _score(c, _ratio_ok(s.sections_with_example, s.section_count), why="example")
            )
        elif cid == "av.d.problem":
            out.append(_score(c, s.viewer_problem_addressed, why="viewer problem"))
        elif cid == "tm.d.variants":
            ok = None if t.variants is None else t.variants >= t.required_variants
            out.append(_score(c, ok, why="thumbnail variants"))
        elif cid == "tm.d.spec":
            out.append(_score(c, t.spec_ok, why="thumbnail size/format"))
        elif cid == "tm.d.legibility":
            out.append(_score(c, t.legible, why="thumbnail text legibility"))
        elif cid == "tm.d.title_length":
            out.append(_score(c, t.title_length_ok, why="working title length"))
        elif cid == "co.d.gate":
            out.append(_score(c, g.overall is ComplianceVerdict.ALLOWED, why="gate not ALLOWED"))
        elif cid == "co.d.licence":
            out.append(_score(c, g.licence_pass, why="licence completeness"))
        elif cid == "co.d.disclosure":
            ok = (
                None
                if g.disclosure_decision is None
                else (g.disclosure_decision is not DisclosureDecision.NEEDS_HUMAN_REVIEW)
            )
            out.append(_score(c, ok, why="disclosure decision recorded"))
        elif cid == "co.d.disclaimer":
            out.append(_score(c, True if not g.finance else g.disclaimer_pass, why="disclaimer"))
        else:  # pragma: no cover - the rubric table and this function change together
            raise ValueError(f"unscored D criterion {cid}")
    return out


def _floor2(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100


def aggregate(
    scores: Sequence[CriterionScore], scaling: MachineScaling
) -> tuple[DimensionRow, ...]:
    """Machine row per dimension: Sigma earned D + J (``NONE``); ``PRO_RATA`` scales the scored
    criteria to the dimension's points with SKIPPED criteria out of both sums."""
    by_id = {c.criterion_id: c for c in scores}
    missing = {c.criterion_id for c in machine_criteria()} - set(by_id)
    if missing:
        raise ValueError(f"criteria not scored: {sorted(missing)}")
    rows = []
    for dim in QualityDimension:
        crit = tuple(by_id[c.criterion_id] for c in machine_criteria() if c.dimension is dim)
        earned = sum(c.earned for c in crit)
        if scaling is MachineScaling.PRO_RATA:
            scored_max = sum(c.max for c in crit if c.status == "SCORED")
            scored = sum(c.earned for c in crit if c.status == "SCORED")
            points = _floor2(dim.max_points * scored / scored_max) if scored_max else 0.0
        else:
            points = round(earned, 2)
        rows.append(
            DimensionRow(
                dimension=dim,
                max_points=dim.max_points,
                points=points,
                scorer_kind="DETERMINISTIC" if dim in _DETERMINISTIC_DIMS else "LLM_JUDGE",
                criteria=crit,
            )
        )
    return tuple(rows)


_REMEDY_ROUTE: Final[Mapping[QualityDimension, str]] = {
    QualityDimension.RESEARCH_ACCURACY: "script_stage_id",
    QualityDimension.STORYTELLING: "script_stage_id",
    QualityDimension.AUDIENCE_VALUE: "script_stage_id",
    QualityDimension.VISUAL_QUALITY: "plan_stage_id",
    QualityDimension.EDITING_QUALITY: "plan_stage_id",
    QualityDimension.AUDIO_QUALITY: "voice_stage_id",
    QualityDimension.THUMBNAIL_METADATA: "thumbnails_stage_id",
}


def score_gate(
    rows: Sequence[DimensionRow],
    threshold: float,
    mode: ScoreGateMode,
    routing: Mapping[str, str | None],
) -> tuple[Literal["PASS", "FAIL", "NOT_GATING"], ValidationResult, float]:
    """``a16.qs.gate.machine_total`` (``gate: true``). REPORT_ONLY: PASS or WARN, never
    blocking, precondition recorded; BLOCKING: FAIL names the weakest dimension's stage."""
    total = round(sum(r.points for r in rows), 2)
    passed = total >= threshold
    if mode is ScoreGateMode.REPORT_ONLY:
        res = ValidationResult(
            check_id="a16.qs.gate.machine_total",
            kind=CheckKind.DETERMINISTIC,
            verdict=CheckVerdict.PASS if passed else CheckVerdict.WARN,
            blocking=False,
            measured=total,
            threshold=threshold,
            message="REPORT_ONLY: judge not calibrated (3B); delivery is decided at s16_auth",
            gate=True,
        )
        return "NOT_GATING", res, total
    remedy = None
    if not passed:

        def ratio(r: DimensionRow) -> float:
            mx = sum(c.max for c in r.criteria)
            return r.points / mx if mx else 1.0

        for r in sorted(rows, key=ratio):
            key = _REMEDY_ROUTE.get(r.dimension)
            if key and routing.get(key):
                remedy = routing[key]
                break
    res = ValidationResult(
        check_id="a16.qs.gate.machine_total",
        kind=CheckKind.DETERMINISTIC,
        verdict=CheckVerdict.PASS if passed else CheckVerdict.FAIL,
        blocking=not passed,
        measured=total,
        threshold=threshold,
        message=f"machine total {total}",
        gate=True,
        remedy_stage_id=remedy,
    )
    return ("PASS" if passed else "FAIL"), res, total
