"""Dead-letter record and controlled manual replay (07 section 5; 03 T14 / T17 / T18;
04 section 5.7 ``dead_letter``).

Pure logic: the record content, the ``dlq_recovery_status`` workflow, and the T17 replay guard.
A replay never edits the input and keeps the same idempotency key (07 section 5.2 rule 1), so a
replay of an effect that already completed returns the stored result instead of repeating it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from amw_core.config import AmwSettings
from amw_core.enums import DlqRecoveryStatus, EscalationLevel, FailureClass
from amw_core.errors import (
    InputInvalidError,
    InvalidTransitionError,
    LoopCapExceededError,
    PermissionDeniedError,
)
from amw_core.ids import ApprovalId, AttemptId, IdempotencyKey, JobId, TaskId, UserId
from amw_core.retries.policy import spec_for

S = DlqRecoveryStatus

ALLOWED: Mapping[DlqRecoveryStatus, frozenset[DlqRecoveryStatus]] = {
    S.NEW: frozenset({S.TRIAGED, S.DISCARDED}),
    S.TRIAGED: frozenset({S.REPLAY_REQUESTED, S.DISCARDED}),
    S.REPLAY_REQUESTED: frozenset({S.REPLAY_APPROVED, S.TRIAGED, S.DISCARDED}),
    S.REPLAY_APPROVED: frozenset({S.REPLAYED, S.DISCARDED}),
    S.REPLAYED: frozenset({S.RESOLVED, S.NEW}),
    S.RESOLVED: frozenset(),
    S.DISCARDED: frozenset(),
}
"""07 section 5.2 steps 1-7 and the ``DISCARDED`` alternative (T18)."""

SIDE_EFFECT_SCOPE_PREFIXES: tuple[str, ...] = ("upload.", "publish.", "billing.", "stock.license")
"""07 section 5.2 step 5: replays in these scopes need a ``DLQ_REPLAY`` approval."""

RECONCILE_SCOPE_PREFIXES: tuple[str, ...] = (
    "upload.",
    "publish.",
    "billing.",
    "stock.license",
    "delivery.",
    "thumbnail.",
    "captions.",
    "notify.",
    "webhook.",
    "llm.call",
    "tts.",
    "media.",
)
"""Scopes with an external effect: reconciliation of the idempotency row runs before a replay
(07 section 5.2 step 6, section 11 rule 6)."""


@dataclass(frozen=True, slots=True)
class AttemptHistoryItem:
    """One entry of ``dead_letter.retry_history`` (04 section 5.7)."""

    attempt_no: int
    started_at: datetime
    ended_at: datetime | None
    worker_id: str | None
    error_code: str

    def to_json(self) -> dict[str, Any]:
        return {
            "attempt_no": self.attempt_no,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "worker_id": self.worker_id,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """The ``dead_letter`` row content written at T14 (07 section 5.1)."""

    task_id: TaskId
    job_id: JobId
    failure_class: FailureClass
    error_code: str
    reason: str
    error: Mapping[str, Any]
    payload_ref: str
    payload_sha256: str
    retry_history: tuple[AttemptHistoryItem, ...]
    escalation_level: EscalationLevel
    idempotency_key: IdempotencyKey | None = None
    idempotency_scope: str | None = None
    estimated_cost_micros: int = 0
    traceback_ref: str | None = None
    last_attempt_id: AttemptId | None = None
    last_run_at: datetime | None = None
    recovery_status: DlqRecoveryStatus = DlqRecoveryStatus.NEW
    replay_count: int = 0
    replay_approval_id: ApprovalId | None = None
    triaged_by: UserId | None = None
    root_cause_note: str | None = None
    resolved_at: datetime | None = None
    events: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    """Audit-ready record of each workflow step (who, when, from, to)."""


def build_dead_letter(
    *,
    task_id: TaskId,
    job_id: JobId,
    error: Mapping[str, Any],
    reason: str,
    payload_ref: str,
    payload_sha256: str,
    retry_history: Sequence[AttemptHistoryItem],
    traceback_ref: str | None = None,
    last_attempt_id: AttemptId | None = None,
    idempotency_key: IdempotencyKey | None = None,
    idempotency_scope: str | None = None,
    estimated_cost_micros: int = 0,
) -> DeadLetter:
    """T14 content. The error object must carry a catalogue ``code``; the class and escalation
    level come from the catalogue (never from the raising component, 07 section 1.1)."""
    code = error.get("code")
    if not isinstance(code, str):
        raise InputInvalidError("DLQ error object has no code")
    spec = spec_for(code)
    if len(payload_sha256) != 64:
        raise InputInvalidError("payload_sha256 must be 64 hex characters")
    history = tuple(sorted(retry_history, key=lambda h: h.attempt_no))
    escalation = EscalationLevel.L3 if spec.escalation is EscalationLevel.L3 else EscalationLevel.L2
    return DeadLetter(
        task_id=task_id,
        job_id=job_id,
        failure_class=spec.error_class,
        error_code=code,
        reason=reason,
        error=dict(error),
        payload_ref=payload_ref,
        payload_sha256=payload_sha256,
        retry_history=history,
        escalation_level=escalation,
        traceback_ref=traceback_ref,
        last_attempt_id=last_attempt_id,
        last_run_at=(history[-1].ended_at or history[-1].started_at) if history else None,
        idempotency_key=idempotency_key,
        idempotency_scope=idempotency_scope,
        estimated_cost_micros=estimated_cost_micros,
    )


def _move(
    item: DeadLetter,
    to: DlqRecoveryStatus,
    actor: str,
    now: datetime,
    note: str | None = None,
    **changes: Any,
) -> DeadLetter:
    if to not in ALLOWED[item.recovery_status]:
        raise InvalidTransitionError(
            f"DLQ recovery {item.recovery_status} -> {to} is not allowed (07 section 5.2)"
        )
    event: dict[str, Any] = {
        "from": str(item.recovery_status),
        "to": str(to),
        "actor": actor,
        "at": now.isoformat(),
    }
    if note is not None:
        event["note"] = note
    return replace(item, recovery_status=to, events=(*item.events, event), **changes)


def _require(permission: str, granted: frozenset[str]) -> None:
    if permission not in granted:
        raise PermissionDeniedError(f"permission {permission} required")


def triage(
    item: DeadLetter, user: UserId, note: str, permissions: frozenset[str], now: datetime
) -> DeadLetter:
    """Step 2: root-cause note required (``dlq.triage``)."""
    _require("dlq.triage", permissions)
    if not note.strip():
        raise InputInvalidError("triage needs a root-cause note")
    return _move(item, S.TRIAGED, user, now, triaged_by=user, root_cause_note=note.strip())


def request_replay(
    item: DeadLetter, user: UserId, permissions: frozenset[str], now: datetime
) -> DeadLetter:
    """Step 4 (``dlq.replay``): replay = same Task Input, same idempotency key."""
    _require("dlq.replay", permissions)
    return _move(item, S.REPLAY_REQUESTED, user, now)


def needs_replay_approval(item: DeadLetter, settings: AmwSettings) -> bool:
    """Step 5: side-effect scopes, or a paid task above ``dlq.replay_cost_review_micros``.
    With the threshold unset (no value in 07) every paid replay needs the approval (fail closed)."""
    scope = item.idempotency_scope or ""
    if scope.startswith(SIDE_EFFECT_SCOPE_PREFIXES):
        return True
    if item.estimated_cost_micros > 0:
        threshold = settings.dlq.replay_cost_review_micros
        return threshold is None or item.estimated_cost_micros > threshold
    return False


def approve_replay(
    item: DeadLetter,
    user: UserId,
    permissions: frozenset[str],
    settings: AmwSettings,
    now: datetime,
    approval_id: ApprovalId | None = None,
) -> DeadLetter:
    """Step 5. Root-cause note must be present (DB CHECK); a ``DLQ_REPLAY`` approval is required
    where ``needs_replay_approval`` says so."""
    _require("dlq.replay", permissions)
    if not item.root_cause_note:
        raise InvalidTransitionError("REPLAY_APPROVED requires a root-cause note")
    if needs_replay_approval(item, settings) and approval_id is None:
        raise PermissionDeniedError("this replay needs an approvals row of kind DLQ_REPLAY")
    return _move(item, S.REPLAY_APPROVED, user, now, replay_approval_id=approval_id)


@dataclass(frozen=True, slots=True)
class ReplayPlan:
    """What T17 does: requeue the same input with the same key, after reconciliation."""

    task_id: TaskId
    idempotency_key: IdempotencyKey | None
    payload_ref: str
    payload_sha256: str
    reconcile_first: bool
    attempt_counter_reset: bool = True


def plan_replay(item: DeadLetter, settings: AmwSettings) -> ReplayPlan:
    """T17 guard: ``REPLAY_APPROVED``, root-cause note, ``replay_count <
    limits.max_replays_per_item`` (07 section 9: else refused, L3)."""
    if item.recovery_status is not S.REPLAY_APPROVED:
        raise InvalidTransitionError("replay needs recovery_status REPLAY_APPROVED")
    if not item.root_cause_note:
        raise InvalidTransitionError("replay needs a root-cause note")
    if item.replay_count >= settings.limits.max_replays_per_item:
        raise LoopCapExceededError(
            "limits.max_replays_per_item reached", details={"replay_count": item.replay_count}
        )
    scope = item.idempotency_scope or ""
    return ReplayPlan(
        task_id=item.task_id,
        idempotency_key=item.idempotency_key,
        payload_ref=item.payload_ref,
        payload_sha256=item.payload_sha256,
        reconcile_first=scope.startswith(RECONCILE_SCOPE_PREFIXES),
    )


def mark_replayed(item: DeadLetter, settings: AmwSettings, now: datetime) -> DeadLetter:
    """Step 6 (system, T17): ``replay_count += 1``; the attempt-counter reset is recorded."""
    plan_replay(item, settings)
    return _move(item, S.REPLAYED, "sys_dlq_handler", now, replay_count=item.replay_count + 1)


def mark_resolved(item: DeadLetter, now: datetime) -> DeadLetter:
    """Step 7: the replayed task completed."""
    return _move(item, S.RESOLVED, "sys_dlq_handler", now, resolved_at=now)


def mark_failed_again(item: DeadLetter, now: datetime) -> DeadLetter:
    """Step 7: the replay failed; the item returns to ``NEW`` (a new DLQ row is also written)."""
    return _move(item, S.NEW, "sys_dlq_handler", now)


def discard(
    item: DeadLetter, user: UserId, reason: str, permissions: frozenset[str], now: datetime
) -> DeadLetter:
    """T18 (``dlq.discard``): reason recorded."""
    _require("dlq.discard", permissions)
    if not reason.strip():
        raise InputInvalidError("discard needs a reason")
    return _move(item, S.DISCARDED, user, now, note=reason.strip())


def bulk_replay_batches(
    items: Sequence[DeadLetter], settings: AmwSettings
) -> list[list[DeadLetter]]:
    """07 section 5.2 rule 2: items of one ``error_code`` only, in batches of at most
    ``dlq.bulk_replay_max`` (unset -> bulk replay is not allowed)."""
    limit = settings.dlq.bulk_replay_max
    if limit is None:
        raise PermissionDeniedError(
            "dlq.bulk_replay_max is not configured; replay items one by one"
        )
    codes = {i.error_code for i in items}
    if len(codes) > 1:
        raise InputInvalidError("bulk replay needs one error_code")
    return [list(items[i : i + limit]) for i in range(0, len(items), limit)]
