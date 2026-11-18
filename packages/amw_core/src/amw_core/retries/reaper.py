"""Stuck-work detection (``sys_reaper``, 07 section 6) as pure decisions.

The reaper finds candidates with the identifier-only system functions (04 section 3.6), opens a
tenant transaction per org, reads the task snapshot and asks ``classify`` what to do. The actual
transition is applied through the state machine (lane L1a); this module never writes.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from amw_core.config import AmwSettings
from amw_core.enums import EscalationLevel, TaskState, WaitReason


class ReaperAction(StrEnum):
    """Code-local action names (not stored values)."""

    NONE = "NONE"
    FAIL_ATTEMPT = "FAIL_ATTEMPT"
    """Fail the running attempt with ``error_code`` (T10 / T11 decided by ``policy.decide``)."""
    REVALIDATE = "REVALIDATE"
    FAIL_TASK = "FAIL_TASK"
    COMPLETE_DEAD_LETTER = "COMPLETE_DEAD_LETTER"
    ALERT = "ALERT"
    WAIT_TIMEOUT = "WAIT_TIMEOUT"
    """T16."""
    REMIND = "REMIND"


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    state: TaskState
    state_changed_at: datetime
    wait_reason: WaitReason | None = None
    lease_expires_at: datetime | None = None
    worker_heartbeat_at: datetime | None = None
    running_since: datetime | None = None
    max_wall_ms: int | None = None
    next_attempt_at: datetime | None = None
    has_dead_letter_row: bool = False
    validation_reruns: int = 0
    queue_max_wait_ms: int | None = None
    last_reminder_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReaperDecision:
    action: ReaperAction
    error_code: str | None = None
    escalation: EscalationLevel | None = None
    mark_worker_lost: bool = False
    reason: str = ""


NOTHING = ReaperDecision(ReaperAction.NONE)


def _ms(delta_ms: int) -> timedelta:
    return timedelta(milliseconds=delta_ms)


def classify(task: TaskSnapshot, now: datetime, settings: AmwSettings) -> ReaperDecision:
    """One row of the 07 section 6 table for one task."""
    r = settings.reaper
    match task.state:
        case TaskState.RUNNING:
            return _running(task, now, settings)
        case TaskState.VALIDATING:
            if now - task.state_changed_at <= _ms(r.validating_max_ms):
                return NOTHING
            if task.validation_reruns < 1:
                return ReaperDecision(ReaperAction.REVALIDATE, reason="VALIDATING too long")
            return ReaperDecision(
                ReaperAction.FAIL_TASK,
                "PERMANENT.DEADLINE_EXCEEDED",
                EscalationLevel.L2,
                reason="VALIDATING too long after one re-run",
            )
        case TaskState.FAILED:
            if not task.has_dead_letter_row and now - task.state_changed_at > _ms(
                r.failed_without_dlq_ms
            ):
                return ReaperDecision(ReaperAction.COMPLETE_DEAD_LETTER, reason="complete T14")
            return NOTHING
        case TaskState.RETRY_WAIT:
            if task.next_attempt_at is not None and now - task.next_attempt_at > _ms(
                r.retry_wait_overdue_ms
            ):
                return ReaperDecision(
                    ReaperAction.ALERT, escalation=EscalationLevel.L2, reason="retry overdue"
                )
            return NOTHING
        case TaskState.QUEUED:
            if task.queue_max_wait_ms is not None and now - task.state_changed_at > _ms(
                task.queue_max_wait_ms
            ):
                return ReaperDecision(ReaperAction.ALERT, reason="queued beyond class wait")
            return NOTHING
        case TaskState.CHECKPOINTED:
            return _checkpointed(task, now, settings)
        case _:
            return NOTHING


def _running(task: TaskSnapshot, now: datetime, settings: AmwSettings) -> ReaperDecision:
    r = settings.reaper
    if task.lease_expires_at is not None and task.lease_expires_at < now:
        stale_after = _ms(r.stale_heartbeat_factor * r.heartbeat_ms)
        stale = task.worker_heartbeat_at is None or now - task.worker_heartbeat_at > stale_after
        if stale:
            return ReaperDecision(
                ReaperAction.FAIL_ATTEMPT,
                "INFRASTRUCTURE.WORKER_LOST",
                EscalationLevel.L1,
                mark_worker_lost=True,
                reason="lease expired, worker heartbeat stale",
            )
        return ReaperDecision(
            ReaperAction.FAIL_ATTEMPT,
            "AGENT.HANG",
            EscalationLevel.L1,
            reason="lease expired, worker heartbeat fresh",
        )
    if (
        task.max_wall_ms is not None
        and task.running_since is not None
        and now - task.running_since > _ms(task.max_wall_ms)
    ):
        return ReaperDecision(
            ReaperAction.FAIL_ATTEMPT,
            "AGENT.HANG",
            EscalationLevel.L1,
            reason="beyond resource_budget.max_wall_ms",
        )
    return NOTHING


def _checkpointed(task: TaskSnapshot, now: datetime, settings: AmwSettings) -> ReaperDecision:
    w = settings.wait
    waited = now - task.state_changed_at
    match task.wait_reason:
        case WaitReason.AWAITING_EXTERNAL:
            if w.awaiting_external_timeout_ms is not None and waited > _ms(
                w.awaiting_external_timeout_ms
            ):
                return ReaperDecision(
                    ReaperAction.WAIT_TIMEOUT,
                    "PERMANENT.DEADLINE_EXCEEDED",
                    EscalationLevel.L2,
                    reason="wait.awaiting_external.timeout_ms",
                )
        case WaitReason.AWAITING_APPROVAL:
            if w.approval_escalate_ms is not None and waited > _ms(w.approval_escalate_ms):
                return ReaperDecision(
                    ReaperAction.ALERT, escalation=EscalationLevel.L3, reason="approval overdue"
                )
            if w.approval_reminder_ms is not None:
                since = now - (task.last_reminder_at or task.state_changed_at)
                if since >= _ms(w.approval_reminder_ms):
                    return ReaperDecision(ReaperAction.REMIND, reason="approval reminder")
        case WaitReason.AWAITING_QUOTA:
            if w.quota_max_wait_days is not None and waited > timedelta(days=w.quota_max_wait_days):
                return ReaperDecision(
                    ReaperAction.ALERT, escalation=EscalationLevel.L3, reason="quota wait too long"
                )
        case _:
            pass  # DRAIN, AWAITING_BUDGET, OPERATOR_PAUSE: no timeout (07 section 6)
    return NOTHING


def job_active_cap_reached(active_ms: int, settings: AmwSettings) -> bool:
    """``limits.max_job_active_ms`` (07 section 9, excludes CHECKPOINTED time): L2, then L3."""
    return active_ms > settings.limits.max_job_active_ms


def job_idle(last_transition_at: datetime, now: datetime, settings: AmwSettings) -> bool:
    """Job ``RUNNING`` with no task transition for ``job.max_idle_ms`` (L2); off when unset."""
    limit = settings.reaper.job_max_idle_ms
    return limit is not None and now - last_transition_at > _ms(limit)
