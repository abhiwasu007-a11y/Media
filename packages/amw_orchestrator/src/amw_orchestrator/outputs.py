"""Task Outputs the orchestrator itself writes (failures, budget stops): always real cost.

A failed attempt reports what its provider calls really cost (the ``cost_ledger`` rows the
metering wrapper wrote for that attempt, or the usage the worker itself reported); a silent 0 is
never written for an attempt that spent money (03 section 5.2, 09 section 6).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from amw_core.contracts import ResourceUsage, TaskOutput, error_object_from_exception
from amw_core.errors import AmwError


class SpendLike(Protocol):
    """Structural type of ``services.AttemptSpend`` (kept here so this module has no DB deps)."""

    @property
    def entry_id(self) -> str: ...

    @property
    def micros(self) -> int: ...

    @property
    def currency(self) -> str: ...


def now_z() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def usage_dict(spend: Sequence[SpendLike] = (), currency: str = "USD") -> dict[str, Any]:
    return {
        "cpu_ms": 0,
        "peak_rss_bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "tokens_cached_in": 0,
        "llm_calls": 0,
        "provider_calls": len(spend),
        "cost_estimate_micros": sum(s.micros for s in spend),
        "currency": spend[0].currency if spend else currency,
        "cost_entry_ids": [s.entry_id for s in spend],
    }


def _task_output(body: dict[str, Any], usage: dict[str, Any]) -> TaskOutput:
    return TaskOutput.model_validate(
        {
            "payload": None,
            "output_refs": [],
            "quality_score": None,
            "confidence": None,
            "validation_results": [],
            "duration": 0,
            "resource_usage": usage,
            "error": None,
            "downstream_agent": None,
            "timestamp": now_z(),
            **body,
        }
    )


def failed_output(
    exc: AmwError,
    *,
    actor: str,
    attempt_no: int,
    correlation_id: str,
    usage: ResourceUsage | dict[str, Any],
) -> TaskOutput:
    """A typed error as an ``amw.task_output`` (status FAILED), carrying ``usage``."""
    usage_doc = usage.to_doc() if isinstance(usage, ResourceUsage) else usage
    kwargs: dict[str, Any] = {
        "actor": actor,
        "attempt_no": attempt_no,
        "occurred_at": datetime.now(UTC),
        "correlation_id": correlation_id,
    }
    try:
        err = error_object_from_exception(exc, **kwargs)
    except ValidationError:  # details of a non-contract shape: keep the code, drop details
        exc.details = {}
        err = error_object_from_exception(exc, **kwargs, extra_details={"checks": [str(exc)[:200]]})
    return _task_output(
        {
            "status": "FAILED",
            "error": err.to_doc(),
            "next_action": {
                "type": "ESCALATE",
                "wait_reason": None,
                "escalation_level": "L3",
                "reason": "stage raised a typed error",
            },
        },
        usage_doc,
    )


def budget_stop_output(reason: str, usage: dict[str, Any]) -> TaskOutput:
    """SUSPENDED / AWAITING_BUDGET (L3): E2 refused or E3 suspended a budget."""
    return _task_output(
        {
            "status": "SUSPENDED",
            "next_action": {
                "type": "WAIT",
                "wait_reason": "AWAITING_BUDGET",
                "escalation_level": "L3",
                "reason": f"RESOURCE.BUDGET_EXHAUSTED: {reason}"[:1000],
            },
        },
        usage,
    )
