"""Check results (blueprint 8.1): deterministic, content-free, convertible to a core result."""

from dataclasses import dataclass, field
from typing import Any

from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import CheckKind, CheckVerdict


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One check outcome. ``message`` holds codes, IDs and counts only, never content."""

    check_id: str
    verdict: str  # PASS | FAIL | WARN | SKIPPED
    blocking: bool = True
    message: str = ""
    rule_ids: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)
    measured: int | float | str | bool | None = None

    @property
    def passed(self) -> bool:
        return self.verdict in ("PASS", "WARN", "SKIPPED")

    @property
    def failed_blocking(self) -> bool:
        return self.verdict == "FAIL" and self.blocking

    def to_validation_result(self) -> ValidationResult:
        verdict = CheckVerdict(self.verdict)
        blocking = self.blocking and verdict in (CheckVerdict.PASS, CheckVerdict.FAIL)
        return ValidationResult(
            check_id=self.check_id,
            kind=CheckKind.DETERMINISTIC,
            verdict=verdict,
            blocking=blocking,
            rule_id=self.rule_ids[0] if self.rule_ids else None,
            measured=self.measured,
            message=(self.message or self.check_id)[:2000],
        )


def passed(check_id: str, message: str = "ok", *, blocking: bool = True) -> CheckResult:
    return CheckResult(check_id, "PASS", blocking, message)


def failed(
    check_id: str,
    message: str,
    *,
    blocking: bool = True,
    rule_ids: tuple[str, ...] = (),
    details: dict[str, Any] | None = None,
) -> CheckResult:
    return CheckResult(check_id, "FAIL", blocking, message, rule_ids, details or {})


def skipped(check_id: str, message: str) -> CheckResult:
    return CheckResult(check_id, "SKIPPED", False, message)


def warned(
    check_id: str, message: str, measured: int | float | str | bool | None = None
) -> CheckResult:
    return CheckResult(check_id, "WARN", False, message, measured=measured)


def failing_ids(results: list[CheckResult]) -> list[str]:
    """Check IDs that failed and block (feedback of the single quality repair)."""
    return sorted({r.check_id for r in results if r.failed_blocking})
