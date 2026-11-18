"""``svc_s02.uniqueness_check`` 3A part (F-17; blueprint section 8.3; YTG-R1 b/c; 3A R7).

Deterministic only: masked-structure identity with the template (or a prior video of the same
channel and org), template text share, section-role sequence, shot-type sequence identity. The
cross-video comparator is 3C: ``SKIPPED`` below ``uniqueness.cross_video.skip_below_prior_count``
prior videos, ``NEEDS_HUMAN_REVIEW`` after that until it exists (13 section 3.1). Thresholds are
config and ``None`` (REQUIRES REVIEW) => the measure is recorded as ``WARN`` only.
Failing results name the script stage (the gate's only target, section 15.0).
"""

import re
from collections.abc import Sequence
from typing import Final

from pydantic import Field

from agent_16_compliance_qa.base import Model, worst
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import CheckKind, CheckVerdict, ComplianceVerdict
from amw_core.errors import CrossTenantRefError
from amw_core.text_normalise import normalise_for_matching

_SLOT: Final = re.compile(r"\{[a-z0-9_]+\}")
_WS: Final = re.compile(r"\s+")


class Segment(Model):
    section_role: str
    text: str


class Measures(Model):
    masked_structure_identical_to_template: bool
    masked_structure_identical_to_prior_video: bool
    template_text_share: float = Field(ge=0, le=1)
    section_role_sequence_equal_to_template: bool
    shot_type_sequence_identity: float = Field(ge=0, le=1)
    prior_videos_on_channel: int = Field(ge=0)
    cross_video_comparator_built: bool
    cross_video_max_similarity: float | None = Field(default=None, ge=0, le=1)
    inputs_complete: bool
    refs_same_org: bool


class Thresholds(Model):
    template_text_share: float | None
    shot_type_sequence_identity: float | None
    cross_video_similarity: float | None


def _norm(text: str) -> str:
    """``amw_core.text_normalise`` (zero-width, compatibility and look-alike characters folded,
    review minor 6); ``{slot}`` placeholders survive it unchanged."""
    return _WS.sub(" ", normalise_for_matching(text).text.strip())


def _pattern(template_text: str) -> re.Pattern[str]:
    parts = _SLOT.split(_norm(template_text))
    return re.compile(".+?".join(re.escape(p) for p in parts), re.DOTALL)


def masked_identical(script: Sequence[Segment], template: Sequence[Segment]) -> bool:
    """The script is the template with only its ``{slot}`` placeholders filled (YTG-R1 c)."""
    if not template or len(script) != len(template):
        return False
    return all(
        s.section_role == t.section_role and _pattern(t.text).fullmatch(_norm(s.text)) is not None
        for s, t in zip(script, template, strict=True)
    )


def template_text_share(script: Sequence[Segment], template: Sequence[Segment]) -> float:
    """Share of script characters that are the template's fixed (non-slot) text."""
    total = sum(len(_norm(s.text)) for s in script)
    if not total:
        return 0.0
    fixed = 0
    for s in script:
        text = _norm(s.text)
        for t in template:
            for part in _SLOT.split(_norm(t.text)):
                part = part.strip()
                if len(part) > 1 and part in text:
                    fixed += len(part)
                    text = text.replace(part, "", 1)
    return round(min(fixed / total, 1.0), 4)


def role_sequence_equal(script: Sequence[Segment], template: Sequence[Segment]) -> bool:
    return [s.section_role for s in script] == [t.section_role for t in template]


def shot_sequence_identity(shots: Sequence[str], template_shots: Sequence[str]) -> float:
    """Positions with the same shot type / the longer sequence length."""
    n = max(len(shots), len(template_shots))
    if not n:
        return 0.0
    same = sum(1 for a, b in zip(shots, template_shots, strict=False) if a == b)
    return round(same / n, 4)


class UniquenessDecision(Model):
    verdict: ComplianceVerdict
    checks: dict[str, CheckVerdict]
    results: tuple[ValidationResult, ...]
    cross_video_status: str
    remedy_stage_id: str | None


def _res(
    check_id: str,
    verdict: CheckVerdict,
    blocking: bool,
    msg: str,
    measured: float | bool | None,
    threshold: float | None,
    remedy: str | None,
) -> ValidationResult:
    return ValidationResult(
        check_id=check_id,
        kind=CheckKind.DETERMINISTIC,
        verdict=verdict,
        blocking=blocking and verdict is CheckVerdict.FAIL,
        rule_id="YTG-R1",
        measured=measured,
        threshold=threshold,
        message=msg,
        gate=True,
        remedy_stage_id=remedy if verdict is CheckVerdict.FAIL else None,
    )


def _threshold_check(
    check_id: str, value: float, limit: float | None, what: str
) -> tuple[CheckVerdict, ComplianceVerdict, str]:
    if limit is None:
        return CheckVerdict.WARN, ComplianceVerdict.ALLOWED, f"{what} {value}; threshold not set"
    if value > limit:
        return CheckVerdict.WARN, ComplianceVerdict.NEEDS_HUMAN_REVIEW, f"{what} {value} > {limit}"
    return CheckVerdict.PASS, ComplianceVerdict.ALLOWED, f"{what} {value} <= {limit}"


def decide(m: Measures, t: Thresholds, skip_below: int, script_stage_id: str) -> UniquenessDecision:
    """Section 8.3 verdict rule; worst verdict wins."""
    if not m.refs_same_org:
        raise CrossTenantRefError("uniqueness input references another org")
    verdicts: list[ComplianceVerdict] = []
    results: list[ValidationResult] = []
    checks: dict[str, CheckVerdict] = {}

    def add(
        cid: str,
        cv: CheckVerdict,
        v: ComplianceVerdict,
        msg: str,
        blocking: bool,
        measured: float | bool | None,
        limit: float | None,
    ) -> None:
        checks[cid] = cv
        verdicts.append(v)
        results.append(_res(cid, cv, blocking, msg, measured, limit, script_stage_id))

    if not m.inputs_complete:
        add(
            "a16.uniq.inputs",
            CheckVerdict.WARN,
            ComplianceVerdict.NEEDS_HUMAN_REVIEW,
            "uniqueness inputs incomplete",
            False,
            None,
            None,
        )
    identical = (
        m.masked_structure_identical_to_template or m.masked_structure_identical_to_prior_video
    )
    add(
        "a16.uniq.masked_structure",
        CheckVerdict.FAIL if identical else CheckVerdict.PASS,
        ComplianceVerdict.BLOCKED if identical else ComplianceVerdict.ALLOWED,
        "masked structure identical to the template or a prior video"
        if identical
        else "masked structure differs",
        True,
        identical,
        None,
    )
    cv, v, msg = _threshold_check(
        "a16.uniq.template_share",
        m.template_text_share,
        t.template_text_share,
        "template text share",
    )
    add("a16.uniq.template_share", cv, v, msg, False, m.template_text_share, t.template_text_share)
    cv, v, msg = _threshold_check(
        "a16.uniq.shot_sequence",
        m.shot_type_sequence_identity,
        t.shot_type_sequence_identity,
        "shot-type sequence identity",
    )
    add(
        "a16.uniq.shot_sequence",
        cv,
        v,
        msg,
        False,
        m.shot_type_sequence_identity,
        t.shot_type_sequence_identity,
    )
    if m.prior_videos_on_channel < skip_below:
        status = "SKIPPED"
        add(
            "a16.uniq.cross_video",
            CheckVerdict.SKIPPED,
            ComplianceVerdict.ALLOWED,
            f"fewer than {skip_below} prior videos",
            False,
            m.prior_videos_on_channel,
            None,
        )
    elif not m.cross_video_comparator_built or m.cross_video_max_similarity is None:
        status = "NOT_BUILT"
        add(
            "a16.uniq.cross_video",
            CheckVerdict.WARN,
            ComplianceVerdict.NEEDS_HUMAN_REVIEW,
            "cross-video comparator not built (3C)",
            False,
            None,
            None,
        )
    else:
        status = "COMPARED"
        cv, v, msg = _threshold_check(
            "a16.uniq.cross_video",
            m.cross_video_max_similarity,
            t.cross_video_similarity,
            "cross-video similarity",
        )
        if t.cross_video_similarity is None:
            v = ComplianceVerdict.NEEDS_HUMAN_REVIEW  # compared but no decision value
        add(
            "a16.uniq.cross_video",
            cv,
            v,
            msg,
            False,
            m.cross_video_max_similarity,
            t.cross_video_similarity,
        )
    verdict = worst(verdicts)
    return UniquenessDecision(
        verdict=verdict,
        checks=checks,
        results=tuple(results),
        cross_video_status=status,
        remedy_stage_id=script_stage_id if verdict is ComplianceVerdict.BLOCKED else None,
    )
