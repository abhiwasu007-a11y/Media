"""07 section 6: the reaper's decisions (pure)."""

from datetime import timedelta

import pytest

from amw_core.config import load_settings
from amw_core.enums import EscalationLevel, TaskState, WaitReason
from amw_core.retries.reaper import (
    ReaperAction,
    TaskSnapshot,
    classify,
    job_idle,
)
from tests.core_services.support import T0

pytestmark = pytest.mark.unit
CFG = load_settings(environ={})
WAITS = load_settings(
    environ={
        "AMW_WAIT__AWAITING_EXTERNAL_TIMEOUT_MS": "1000",
        "AMW_WAIT__APPROVAL_REMINDER_MS": "1000",
        "AMW_WAIT__APPROVAL_ESCALATE_MS": "5000",
        "AMW_WAIT__QUOTA_MAX_WAIT_DAYS": "2",
        "AMW_REAPER__JOB_MAX_IDLE_MS": "1000",
    }
)


def ms(n: int) -> timedelta:
    return timedelta(milliseconds=n)


def test_running_lease_expired_heartbeat_fresh_is_hang() -> None:
    task = TaskSnapshot(
        TaskState.RUNNING, T0, lease_expires_at=T0, worker_heartbeat_at=T0 + ms(40_000)
    )
    d = classify(task, T0 + ms(50_000), CFG)
    assert (d.action, d.error_code, d.mark_worker_lost) == (
        ReaperAction.FAIL_ATTEMPT, "AGENT.HANG", False,
    )  # fmt: skip


def test_running_lease_expired_heartbeat_stale_is_worker_lost() -> None:
    task = TaskSnapshot(TaskState.RUNNING, T0, lease_expires_at=T0, worker_heartbeat_at=T0)
    d = classify(task, T0 + ms(45_001), CFG)
    assert d.error_code == "INFRASTRUCTURE.WORKER_LOST" and d.mark_worker_lost
    missing = classify(TaskSnapshot(TaskState.RUNNING, T0, lease_expires_at=T0), T0 + ms(1), CFG)
    assert missing.error_code == "INFRASTRUCTURE.WORKER_LOST"


def test_running_beyond_wall_budget_and_healthy() -> None:
    task = TaskSnapshot(TaskState.RUNNING, T0, running_since=T0, max_wall_ms=1000,
                        lease_expires_at=T0 + ms(60_000))  # fmt: skip
    assert classify(task, T0 + ms(1001), CFG).error_code == "AGENT.HANG"
    assert classify(task, T0 + ms(999), CFG).action is ReaperAction.NONE


def test_validating_rerun_once_then_deadline() -> None:
    task = TaskSnapshot(TaskState.VALIDATING, T0)
    assert classify(task, T0 + ms(300_000), CFG).action is ReaperAction.NONE
    assert classify(task, T0 + ms(300_001), CFG).action is ReaperAction.REVALIDATE
    again = TaskSnapshot(TaskState.VALIDATING, T0, validation_reruns=1)
    d = classify(again, T0 + ms(300_001), CFG)
    assert d.action is ReaperAction.FAIL_TASK and d.error_code == "PERMANENT.DEADLINE_EXCEEDED"


def test_failed_without_dlq_row_completes_t14() -> None:
    assert (
        classify(TaskSnapshot(TaskState.FAILED, T0), T0 + ms(60_001), CFG).action
        is ReaperAction.COMPLETE_DEAD_LETTER
    )
    done = TaskSnapshot(TaskState.FAILED, T0, has_dead_letter_row=True)
    assert classify(done, T0 + ms(60_001), CFG).action is ReaperAction.NONE


def test_retry_wait_overdue_and_queued_too_long_alert_only() -> None:
    late = TaskSnapshot(TaskState.RETRY_WAIT, T0, next_attempt_at=T0)
    d = classify(late, T0 + ms(300_001), CFG)
    assert d.action is ReaperAction.ALERT and d.escalation is EscalationLevel.L2
    assert classify(late, T0 + ms(10), CFG).action is ReaperAction.NONE
    queued = TaskSnapshot(TaskState.QUEUED, T0, queue_max_wait_ms=100)
    assert classify(queued, T0 + ms(101), CFG).action is ReaperAction.ALERT
    assert classify(TaskSnapshot(TaskState.QUEUED, T0), T0 + ms(10**9), CFG).action is (
        ReaperAction.NONE
    )
    assert classify(TaskSnapshot(TaskState.COMPLETED, T0), T0, CFG).action is ReaperAction.NONE


@pytest.mark.parametrize(
    "reason", [WaitReason.DRAIN, WaitReason.AWAITING_BUDGET, WaitReason.OPERATOR_PAUSE]
)
def test_waits_without_timeout(reason: WaitReason) -> None:
    task = TaskSnapshot(TaskState.CHECKPOINTED, T0, wait_reason=reason)
    assert classify(task, T0 + timedelta(days=365), WAITS).action is ReaperAction.NONE


def test_wait_timeouts_and_reminders() -> None:
    ext = TaskSnapshot(TaskState.CHECKPOINTED, T0, wait_reason=WaitReason.AWAITING_EXTERNAL)
    assert classify(ext, T0 + ms(1001), WAITS).action is ReaperAction.WAIT_TIMEOUT
    assert classify(ext, T0 + ms(1001), CFG).action is ReaperAction.NONE  # unset: no timeout
    appr = TaskSnapshot(TaskState.CHECKPOINTED, T0, wait_reason=WaitReason.AWAITING_APPROVAL)
    assert classify(appr, T0 + ms(1000), WAITS).action is ReaperAction.REMIND
    reminded = TaskSnapshot(TaskState.CHECKPOINTED, T0, wait_reason=WaitReason.AWAITING_APPROVAL,
                            last_reminder_at=T0 + ms(900))  # fmt: skip
    assert classify(reminded, T0 + ms(1000), WAITS).action is ReaperAction.NONE
    escalated = classify(appr, T0 + ms(5001), WAITS)
    assert escalated.action is ReaperAction.ALERT and escalated.escalation is EscalationLevel.L3
    assert classify(appr, T0 + timedelta(days=30), CFG).action is ReaperAction.NONE
    quota = TaskSnapshot(TaskState.CHECKPOINTED, T0, wait_reason=WaitReason.AWAITING_QUOTA)
    assert classify(quota, T0 + timedelta(days=3), WAITS).escalation is EscalationLevel.L3


def test_job_idle() -> None:
    assert job_idle(T0, T0 + ms(1001), WAITS)
    assert not job_idle(T0, T0 + ms(1001), CFG)
