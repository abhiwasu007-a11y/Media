"""``RefusalMapper`` (blueprint 8.2, 18; 27 section 4.3): where a refusal becomes a status."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_05_scriptwriter.contracts import Refusal
from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import CheckKind, CheckVerdict


@dataclass(frozen=True, slots=True)
class MappedRefusal:
    status: str  # SUCCEEDED | FAILED
    error_code: str | None
    verdict: str | None  # BLOCKED | NEEDS_HUMAN_REVIEW for SUCCEEDED
    scripts_row: bool = False
    earlier_sections_discarded: bool = False
    results: list[ValidationResult] = field(default_factory=list)


_FAILED = {
    "INSUFFICIENT_INPUT": "PERMANENT.INSUFFICIENT_INPUT",
    "OUT_OF_SCOPE": "PERMANENT.INPUT_INVALID",
    "CONFLICTING_INSTRUCTIONS": "PERMANENT.INPUT_INVALID",
}
_SUCCEEDED = {"RULE_WOULD_BE_BROKEN": "BLOCKED", "UNSAFE_CONTENT": "NEEDS_HUMAN_REVIEW"}


def schema_check_id(step: str) -> str:
    if step == "plan":
        return "a05.plan.schema"
    if step == "cut":
        return "a05.sh.schema"
    return "a05.sec.schema"


def passing_result(check_id: str, message: str) -> ValidationResult:
    return ValidationResult(
        check_id=check_id,
        kind=CheckKind.DETERMINISTIC,
        verdict=CheckVerdict.PASS,
        blocking=True,
        message=message,
    )


def map_refusal(
    refusal: Refusal, step: str, pre_results: Sequence[ValidationResult] = ()
) -> MappedRefusal:
    """On the BLOCKED / NEEDS_HUMAN_REVIEW path only ``a05.pre.*`` and the step's ``schema`` result
    are emitted, all PASS; no assembly check exists (blueprint 8.1)."""
    if refusal.reason in _FAILED:
        return MappedRefusal("FAILED", _FAILED[refusal.reason], None)
    results = [*pre_results, passing_result(schema_check_id(step), "refusal object valid")]
    return MappedRefusal(
        "SUCCEEDED",
        None,
        _SUCCEEDED[refusal.reason],
        earlier_sections_discarded=step.startswith("section_"),
        results=results,
    )
