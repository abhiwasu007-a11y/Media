"""Task Output layer (03 section 5; blueprint section 8.1) for the four task types.

``status = SUCCEEDED`` also when the verdict is ``BLOCKED`` / ``NEEDS_HUMAN_REVIEW`` or the score
gate fails (03 section 5.3 rules 3-4). Process-integrity results ``a16.out.*`` are ``gate:
false``; domain results carry ``gate: true``. ``next_action`` is advisory.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Final

from agent_16_compliance_qa.authorisation.guards import CHECK_IDS, AuthDecision
from agent_16_compliance_qa.base import Model
from agent_16_compliance_qa.uniqueness import Measures, Thresholds, UniquenessDecision
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
    ValidationResult,
)
from amw_core.enums import (
    CheckKind,
    CheckVerdict,
    ComplianceVerdict,
    EscalationLevel,
    NextActionType,
    OutputRefKind,
    OutputStatus,
)

SCHEMA_VERSION: Final = "1.0.0"


class BlobRef(Model):
    uri: str
    sha256: str
    size_bytes: int


class Usage(Model):
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached_in: int = 0
    llm_calls: int = 0
    cost_micros: int = 0
    cost_entry_ids: tuple[str, ...] = ()


def integrity(check: str, ok: bool, message: str) -> ValidationResult:
    return ValidationResult(
        check_id=f"a16.out.{check}",
        kind=CheckKind.DETERMINISTIC,
        verdict=CheckVerdict.PASS if ok else CheckVerdict.FAIL,
        blocking=True,
        message=message,
        gate=False,
    )


def next_action_for(verdict: ComplianceVerdict, results: Sequence[ValidationResult]) -> NextAction:
    failing = [
        r.check_id for r in results if r.gate and r.blocking and r.verdict is CheckVerdict.FAIL
    ]
    if verdict is ComplianceVerdict.NEEDS_HUMAN_REVIEW and not failing:
        return NextAction(
            type=NextActionType.ESCALATE,
            wait_reason=None,
            escalation_level=EscalationLevel.L3,
            reason="NEEDS_HUMAN_REVIEW items",
        )
    if failing:
        return NextAction(
            type=NextActionType.CONTINUE,
            wait_reason=None,
            escalation_level=None,
            reason=("gate FAILED: " + ", ".join(sorted(set(failing))))[:1000],
        )
    return NextAction(
        type=NextActionType.CONTINUE, wait_reason=None, escalation_level=None, reason="gate PASSED"
    )


def build_task_output(
    *,
    payload_schema: str,
    data: Mapping[str, Any],
    results: Sequence[ValidationResult],
    blob: BlobRef | None,
    usage: Usage,
    now: datetime,
    currency: str,
    quality_score: float | None,
    verdict: ComplianceVerdict,
    downstream: str | None,
) -> TaskOutput:
    refs = (
        (
            OutputRef(
                uri=blob.uri,
                kind=OutputRefKind.REPORT,
                sha256=blob.sha256,
                size_bytes=blob.size_bytes,
                media_type="application/json",
            ),
        )
        if blob
        else ()
    )
    return TaskOutput(
        status=OutputStatus.SUCCEEDED,
        payload=PayloadObject(
            payload_schema=payload_schema, payload_schema_version=SCHEMA_VERSION, data=dict(data)
        ),
        output_refs=refs,
        quality_score=quality_score,
        confidence=None,
        validation_results=tuple(results),
        duration=0,
        resource_usage=ResourceUsage(
            cpu_ms=0,
            peak_rss_bytes=0,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            tokens_cached_in=usage.tokens_cached_in,
            llm_calls=usage.llm_calls,
            provider_calls=usage.llm_calls,
            cost_estimate_micros=usage.cost_micros,
            currency=currency,
            cost_entry_ids=usage.cost_entry_ids,
        ),
        error=None,
        next_action=next_action_for(verdict, results),
        downstream_agent=downstream,
        timestamp=now,
    )


def auth_results(decision: AuthDecision) -> list[ValidationResult]:
    """One ``gate: true`` result per guard (``s16_auth`` is STOP: no remedy stage)."""
    return [
        ValidationResult(
            check_id=CHECK_IDS[g.guard_id],
            kind=CheckKind.DETERMINISTIC,
            verdict=CheckVerdict(g.result),
            blocking=g.result == "FAIL",
            message=g.detail or g.guard_id,
            gate=True,
        )
        for g in decision.guards
    ]


def auth_payload(
    decision: AuthDecision,
    subject: Mapping[str, Any],
    evaluation_date: date,
    earliest: date | None,
    authorisation_verdict_id: str,
    disclosure_verdict_id: str,
    evidence_ids: Sequence[str],
    report_uri: str,
) -> dict[str, Any]:
    """``agent_16.publication_authorisation.output`` 1.0.0 (section 8.5)."""
    return {
        "verdict": decision.verdict.value,
        "is_final": True,
        "authorised_action": decision.authorised_action,
        "subject": dict(subject),
        "guards": [g.model_dump(mode="json") for g in decision.guards],
        "human_wins_total": decision.human_wins_total,
        "per_dimension_used": [u.model_dump(mode="json") for u in decision.per_dimension_used],
        "evaluation_date": evaluation_date.isoformat(),
        "earliest_compliant_publish_date": earliest.isoformat() if earliest else None,
        "evaluated_publish_date": None,
        "authorisation_verdict_id": authorisation_verdict_id,
        "disclosure_verdict_id": disclosure_verdict_id,
        "evidence_ids": list(evidence_ids),
        "report_ref": report_uri,
    }


def uniqueness_payload(
    d: UniquenessDecision, m: Measures, t: Thresholds, report_uri: str
) -> dict[str, Any]:
    """``svc_s02.uniqueness_check.output`` 1.0.0 (section 8.3)."""
    return {
        "verdict": d.verdict.value,
        "measures": {
            "masked_structure_identical_to_template": m.masked_structure_identical_to_template,
            "template_text_share": m.template_text_share,
            "section_role_sequence_equal_to_template": m.section_role_sequence_equal_to_template,
            "shot_type_sequence_identity": m.shot_type_sequence_identity,
            "cross_video": {
                "status": d.cross_video_status,
                "prior_videos_compared": m.prior_videos_on_channel
                if d.cross_video_status == "COMPARED"
                else 0,
                "max_similarity": m.cross_video_max_similarity
                if d.cross_video_status == "COMPARED"
                else None,
            },
        },
        "thresholds": t.model_dump(mode="json"),
        "precondition": "cross-video comparator is 3C"
        if d.cross_video_status != "COMPARED"
        else None,
        "revision_findings": [
            {
                "rule_id": "YTG-R1",
                "item_ref": r.check_id,
                "finding": r.message[:500],
                "remedy_stage_id": r.remedy_stage_id,
            }
            for r in d.results
            if r.verdict is CheckVerdict.FAIL
        ],
        "report_ref": report_uri,
    }
