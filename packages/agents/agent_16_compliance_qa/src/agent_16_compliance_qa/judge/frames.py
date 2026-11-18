"""Frames judge post-processing (F-24; blueprint section 6.3 V10, V10b; D-11, D-12).

A vision finding cannot be verified by code the way a quote can, so it **never blocks alone**:
``qc.visual.no_synthetic_presenter`` maps to ``WARN`` + ``NEEDS_HUMAN_REVIEW``;
``qc.watermark.visual`` is ``WARN`` (``blocking: false``) until the owner sets
``compliance.watermark_visual.calibrated``, then ``FAIL`` with ``remedy_stage_id`` = the assets
stage. Frame IDs must exist in the input; ``NOT_EVALUATED`` is never a clean result.
"""

from collections.abc import Sequence
from typing import Final

from agent_16_compliance_qa.base import Model
from agent_16_compliance_qa.judge.models import FrameCheckId, FrameFindingV, FramesOutput
from amw_core.enums import CheckVerdict, ComplianceVerdict

WATERMARK: Final = "qc.watermark.visual"
PRESENTER: Final = "qc.visual.no_synthetic_presenter"
_POSITIVE: Final = {WATERMARK: "WATERMARK_PRESENT", PRESENTER: "PRESENTER_PRESENT"}


class FrameCheck(Model):
    check_id: FrameCheckId
    finding: FrameFindingV
    frame_ids: tuple[str, ...]
    verdict: CheckVerdict
    blocking: bool
    compliance_verdict: ComplianceVerdict | None
    rationale: str


def apply_frames(
    checks_requested: Sequence[FrameCheckId],
    sensitive_channel: bool,
    frame_ids: Sequence[str],
    out: FramesOutput | None,
    watermark_calibrated: bool,
) -> list[FrameCheck]:
    """``out = None``: the judge did not run (no frames / refused) => every check NOT_EVALUATED."""
    known = set(frame_ids)
    results: list[FrameCheck] = []
    for check in dict.fromkeys(checks_requested):
        if check == PRESENTER and not sensitive_channel:
            continue
        finding: FrameFindingV = "NOT_EVALUATED"
        ids: tuple[str, ...] = ()
        why = "frames not evaluated"
        if out is not None and out.refusal is None:
            found = [f for f in out.findings if f.check_id == check]
            if found:
                f = max(found, key=lambda x: _order(x.finding, check))
                ids = tuple(i for i in f.frame_ids if i in known)
                finding, why = f.finding, f.rationale
                if finding in (_POSITIVE[check], "UNCERTAIN") and not ids:
                    finding, why = "UNCERTAIN", "finding cites no frame of the input (D-11)"
                if finding == "NONE_FOUND" and f.frame_ids:
                    finding, why = "UNCERTAIN", "NONE_FOUND with frame IDs (D-2)"
        results.append(_map(check, finding, ids, why, watermark_calibrated))
    return results


def _order(finding: str, check: str) -> int:
    return {"NONE_FOUND": 0, "NOT_EVALUATED": 1, "UNCERTAIN": 2}.get(finding, 3)


def _map(
    check: FrameCheckId, finding: FrameFindingV, ids: tuple[str, ...], why: str, calibrated: bool
) -> FrameCheck:
    clean = finding == "NONE_FOUND"
    if check == PRESENTER:
        return FrameCheck(
            check_id=check,
            finding=finding,
            frame_ids=ids,
            verdict=CheckVerdict.PASS if clean else CheckVerdict.WARN,
            blocking=False,
            compliance_verdict=(
                ComplianceVerdict.ALLOWED if clean else ComplianceVerdict.NEEDS_HUMAN_REVIEW
            ),
            rationale=why[:500],
        )
    if clean:
        verdict, blocking = CheckVerdict.PASS, False
    elif calibrated and finding in ("WATERMARK_PRESENT", "UNCERTAIN"):
        verdict, blocking = CheckVerdict.FAIL, True
    else:
        verdict, blocking = CheckVerdict.WARN, False
    return FrameCheck(
        check_id=check,
        finding=finding,
        frame_ids=ids,
        verdict=verdict,
        blocking=blocking,
        compliance_verdict=None,
        rationale=why[:500],
    )
