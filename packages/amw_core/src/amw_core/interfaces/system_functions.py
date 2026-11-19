"""Cross-tenant system functions (04 section 3.6), the ones the 3A lanes need.

Platform processes (scheduler, reaper, adapters) must find work before they know its tenant. They
call ``SECURITY DEFINER`` functions owned by ``amw_sysfn`` (fixed ``search_path``) that return
**identifiers only** - never content columns - and are **not** bound to a tenant transaction. The
caller then opens a normal tenant transaction (``TenancyContext.transaction``) per returned
``org_id`` before reading or changing anything. Every call is logged with the caller's actor.

Covered: ``amw_due_retries``, ``amw_due_resumes``, ``amw_expired_leases``, ``amw_stuck_tasks``,
``amw_breaker_admit`` and ``amw_breaker_record`` (CCR-108: probe admission, probe flag, epoch).
``amw_queue_claim`` is ``TaskQueue.claim``. Not in 3A: ``amw_quota_reserve`` /
``amw_quota_release`` (no upload in 3A) and ``amw_platform_ops_summary`` (Tier 1).
Implementation: lane L1.
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


@dataclass(frozen=True, slots=True)
class BreakerAdmission:
    """Outcome of ``amw_breaker_admit`` (04 section 3.6, 07 section 4.3; CCR-108): ``admitted`` is
    the decision, ``state`` the breaker state after it, ``epoch`` the probe generation."""

    admitted: bool
    state: BreakerState
    epoch: int = 0
    """Probe generation: pass it to ``breaker_record`` as ``probe_epoch``."""

    @property
    def probe(self) -> bool:
        """True when the call was admitted as a HALF_OPEN probe: pass it to ``breaker_record``."""
        return self.admitted and self.state.state is CircuitState.HALF_OPEN


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

    def breaker_admit(self, caller: ActorRef, key: BreakerKey) -> BreakerAdmission:
        """``amw_breaker_admit(provider, operation_class, credential_scope, half_open_max_probes,
        probe_timeout_ms)``; caller an adapter, before every call (07 section 4.3): under a row
        lock, ``OPEN`` before ``open_until`` refuses, the first check at or after it moves the row
        to ``HALF_OPEN``, ``HALF_OPEN`` admits while fewer than ``half_open_max_probes`` probes are
        in flight. ``half_open_probe_timeout_ms`` has no default: unset is ``CONFIG_INVALID``.
        Server-side (migration 0055; home PROPOSED as CCR-168) the lease may not exceed the
        ``platform_controls`` bound ``breaker_probe_timeout_max_ms`` of the key's
        ``"<provider>.<operation_class>"``; no bound, or a lease above it, is ``CONFIG_INVALID``
        (the bound values are REQUIRES REVIEW (Phase 1))."""
        ...

    def breaker_record(
        self,
        caller: ActorRef,
        key: BreakerKey,
        succeeded: bool,
        error_code: str | None,
        probe: bool | None = None,
        probe_epoch: int | None = None,
    ) -> BreakerState:
        """``amw_breaker_record(provider, operation_class, credential_scope, outcome, ...,
        probe, probe_epoch)``; caller an adapter. With ``amw_breaker_admit``, the only writer of
        ``circuit_breakers`` (07 section 4 rules). ``outcome`` has no named value set in 04, so it
        is passed as ``succeeded`` plus the 07 ``error_code`` (``circuit_breakers.last_error_code``)
        of a failure. ``probe`` / ``probe_epoch``: ``BreakerAdmission.probe`` / ``.epoch`` of the
        call's admission; ``None`` (no admission used) is the legacy "treated as a probe"."""
        ...
