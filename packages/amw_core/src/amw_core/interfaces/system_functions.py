"""Cross-tenant system functions (04 section 3.6), the ones the 3A lanes need.

Platform processes (scheduler, reaper, adapters) must find work before they know its tenant. They
call ``SECURITY DEFINER`` functions owned by ``amw_sysfn`` (fixed ``search_path``) that return
**identifiers only** - never content columns - and are **not** bound to a tenant transaction. The
caller then opens a normal tenant transaction (``TenancyContext.transaction``) per returned
``org_id`` before reading or changing anything. Every call is logged with the caller's actor.

Covered: ``amw_due_retries``, ``amw_due_resumes``, ``amw_expired_leases``, ``amw_stuck_tasks``,
``amw_breaker_record``. ``amw_queue_claim`` is ``TaskQueue.claim``. Not in 3A:
``amw_quota_reserve`` / ``amw_quota_release`` (no upload in 3A) and ``amw_platform_ops_summary``
(Tier 1). Implementation: lane L1.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from amw_core.enums import CircuitState, TaskState, WaitReason
from amw_core.ids import ActorRef, OrgId, QueueItemId, TaskId


@dataclass(frozen=True, slots=True)
class DueTask:
    """``amw_due_retries``: a ``RETRY_WAIT`` task with ``next_attempt_at <= now()``."""

    org_id: OrgId
    task_id: TaskId


@dataclass(frozen=True, slots=True)
class DueResume:
    """``amw_due_resumes``: a ``CHECKPOINTED`` task whose wait condition may have cleared."""

    org_id: OrgId
    task_id: TaskId
    wait_reason: WaitReason


@dataclass(frozen=True, slots=True)
class ExpiredLease:
    """``amw_expired_leases``: a ``CLAIMED`` queue row with ``lease_expires_at < now()``."""

    org_id: OrgId
    task_id: TaskId
    queue_item_id: QueueItemId


@dataclass(frozen=True, slots=True)
class StuckTask:
    """``amw_stuck_tasks``: a task past the dwell limits of 07 section 6."""

    org_id: OrgId
    task_id: TaskId
    state: TaskState


@dataclass(frozen=True, slots=True)
class BreakerKey:
    """``UNIQUE (provider, operation_class, credential_scope)`` of ``circuit_breakers`` (04 5.8)."""

    provider: str
    operation_class: str
    credential_scope: str
    """``platform`` or ``gcp_<wire id>``."""


@dataclass(frozen=True, slots=True)
class BreakerState:
    """New breaker state returned by ``amw_breaker_record``."""

    key: BreakerKey
    state: CircuitState
    open_until: datetime | None


@runtime_checkable
class SystemFunctions(Protocol):
    def due_retries(self, caller: ActorRef, limit: int) -> Sequence[DueTask]:
        """``amw_due_retries(limit)``; caller ``sys_scheduler`` (T12 / T13 input)."""
        ...

    def due_resumes(self, caller: ActorRef, limit: int) -> Sequence[DueResume]:
        """``amw_due_resumes(limit)``; caller ``sys_scheduler`` (T15 / T16 input)."""
        ...

    def expired_leases(self, caller: ActorRef, limit: int) -> Sequence[ExpiredLease]:
        """``amw_expired_leases(limit)``; caller ``sys_reaper`` (T10 / T11 / T20, 07 section 6)."""
        ...

    def stuck_tasks(self, caller: ActorRef, limit: int) -> Sequence[StuckTask]:
        """``amw_stuck_tasks(limit)``; caller ``sys_reaper`` (interrupted hand-offs, e.g. T14)."""
        ...

    def breaker_record(
        self, caller: ActorRef, key: BreakerKey, succeeded: bool, error_code: str | None
    ) -> BreakerState:
        """``amw_breaker_record(provider, operation_class, credential_scope, outcome)``; caller an
        adapter. The only writer of ``circuit_breakers`` (07 section 4 rules). ``outcome`` has no
        named value set in 04, so it is passed as ``succeeded`` plus the 07 ``error_code``
        (``circuit_breakers.last_error_code``) of a failure."""
        ...
