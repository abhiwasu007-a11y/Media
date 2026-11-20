"""Idempotency store interface (03 section 9.1 rule 3; 04 section 5.9 ``idempotency_keys``).

Before an external side effect the executor calls ``begin`` in the tenant transaction:

* no row -> insert ``IN_PROGRESS`` (``request_sha256``, ``locked_until``) -> ``PROCEED``;
* ``COMPLETED`` with the same ``request_sha256`` -> ``RETURN_STORED`` (perform nothing);
* ``COMPLETED`` or ``IN_PROGRESS`` with a different ``request_sha256`` ->
  ``IdempotencyConflictError``;
* ``IN_PROGRESS`` with the same hash and ``locked_until`` in the past -> ``RECONCILE``: the
  effect's reconciliation procedure runs before any new attempt (07 section 11); the lock is
  renewed for the reconciling caller (``locked_until = now + lock_ms``), so a concurrent or
  later caller gets ``IN_FLIGHT`` until it expires again;
* ``IN_PROGRESS`` with the same hash still locked -> ``IN_FLIGHT`` (another attempt holds it);
* ``FAILED`` with the same hash -> ``PROCEED`` again (the row returns to ``IN_PROGRESS``).

``scope`` must be a 03 section 9.2 scope (``amw_core.ids.is_idempotency_scope``, else
``InputInvalidError``). ``expires_at`` is NULL for ``upload.*`` / ``publish.*`` (rule 4).
Implementation: lane L1; ``amw_core.testing.memory.MemoryIdempotencyStore`` is an in-memory fake.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from amw_core.enums import IdempotencyStatus
from amw_core.ids import IdempotencyKey, OrgId, TaskId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    org_id: OrgId
    key: IdempotencyKey
    scope: str
    request_sha256: str
    status: IdempotencyStatus
    task_id: TaskId | None
    result_ref: str | None
    locked_until: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class BeginAction(StrEnum):
    """Outcome of ``begin`` (the four cases of 03 section 9.1 rule 3 plus "still locked").
    Code-local: not a stored value."""

    PROCEED = "PROCEED"
    RETURN_STORED = "RETURN_STORED"
    RECONCILE = "RECONCILE"
    IN_FLIGHT = "IN_FLIGHT"


@dataclass(frozen=True, slots=True)
class BeginDecision:
    action: BeginAction
    record: IdempotencyRecord


@runtime_checkable
class IdempotencyStore(Protocol):
    def begin(
        self,
        tx: TenantTransaction,
        key: IdempotencyKey,
        scope: str,
        request_sha256: str,
        task_id: TaskId | None,
        now: datetime,
        lock_ms: int,
    ) -> BeginDecision: ...

    def complete(
        self, tx: TenantTransaction, key: IdempotencyKey, result_ref: str, now: datetime
    ) -> IdempotencyRecord:
        """``IN_PROGRESS`` -> ``COMPLETED`` with ``result_ref``; ``InvalidTransitionError`` from
        any other status."""
        ...

    def fail(self, tx: TenantTransaction, key: IdempotencyKey, now: datetime) -> IdempotencyRecord:
        """``IN_PROGRESS`` -> ``FAILED`` (the effect definitely did not happen)."""
        ...

    def get(self, tx: TenantTransaction, key: IdempotencyKey) -> IdempotencyRecord | None: ...
