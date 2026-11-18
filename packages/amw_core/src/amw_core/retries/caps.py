"""Hard caps (07 section 9): no infinite retries, no uncontrolled loops.

Each guard raises the typed error of its "On breach" column; none returns a soft warning.
"""

from amw_core.config import AmwSettings
from amw_core.errors import (
    InvalidTransitionError,
    LoopCapExceededError,
    QualityRepeatedFailureError,
)


def check_task_count(current_tasks: int, settings: AmwSettings) -> None:
    """T01 guard: job task count < ``limits.max_tasks_per_job``."""
    if current_tasks >= settings.limits.max_tasks_per_job:
        raise LoopCapExceededError(
            "limits.max_tasks_per_job reached", details={"tasks": current_tasks}
        )


def check_child_jobs(current_children: int, settings: AmwSettings) -> None:
    """Job creation: refuse beyond ``limits.max_child_jobs_per_job`` (L2)."""
    if current_children >= settings.limits.max_child_jobs_per_job:
        raise LoopCapExceededError(
            "limits.max_child_jobs_per_job reached", details={"children": current_children}
        )


def check_revision_loop(completed_loops: int, settings: AmwSettings) -> None:
    """Before a revision task: per gate per job at most ``limits.max_revision_loops``.

    The orchestrator maps this to ``BLOCKED_COMPLIANCE`` for compliance gates, else FAIL L3."""
    if completed_loops >= settings.limits.max_revision_loops:
        raise LoopCapExceededError(
            "limits.max_revision_loops reached", details={"loops": completed_loops}
        )


def check_replays(replay_count: int, settings: AmwSettings) -> None:
    """T17 guard: ``replay_count < limits.max_replays_per_item``."""
    if replay_count >= settings.limits.max_replays_per_item:
        raise LoopCapExceededError("limits.max_replays_per_item reached")


def check_llm_calls(calls_made: int, max_llm_calls: int) -> None:
    """Adapter guard before the next call: ``resource_budget.max_llm_calls`` (repairs count)."""
    if calls_made >= max_llm_calls:
        raise LoopCapExceededError(
            "resource_budget.max_llm_calls reached", details={"calls": calls_made}
        )


def check_attempts(attempt_count: int, max_attempts: int, settings: AmwSettings) -> None:
    """T10 guard: ``limits.max_attempts_per_task`` (task ceiling 10)."""
    if attempt_count >= min(max_attempts, settings.limits.max_attempts_per_task):
        raise LoopCapExceededError("limits.max_attempts_per_task reached")


def check_lock_reevaluations(reevaluations: int, settings: AmwSettings) -> None:
    """``caps.lock_conflict_reevaluations`` per transition -> ``PERMANENT.INVALID_TRANSITION``."""
    if reevaluations >= settings.caps.lock_conflict_reevaluations:
        raise InvalidTransitionError("caps.lock_conflict_reevaluations reached")


def check_in_attempt_repairs(parse_repairs: int, quality_repairs: int) -> None:
    """CCR-022: at most one parse repair and one quality repair inside an attempt."""
    if parse_repairs > 1:
        raise LoopCapExceededError("more than one parse repair inside the attempt")
    if quality_repairs > 1:
        raise QualityRepeatedFailureError("quality repair failed inside the attempt")
