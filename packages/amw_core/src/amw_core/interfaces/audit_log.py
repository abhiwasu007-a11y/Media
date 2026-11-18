"""Audit log interface (04 section 5.13 ``audit_log``, ``audit_chain_heads``; 03 section 11.7;
3A slice spec section 2.1 ``audit``).

Append-only and hash-chained per tenant: the writer locks the chain head (``FOR UPDATE``),
assigns the gap-free ``seq``, computes ``row_hash = SHA-256(prev_hash || canonical JSON of the
row)`` (genesis ``prev_hash`` = 32 zero bytes), inserts and moves the head, in the caller's
transaction. ``details`` never holds secrets. Implementation (``amw_core.audit``): lane L1.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from amw_core.enums import ActorKind
from amw_core.ids import ActorRef, AuditEntryId, CorrelationId, JobId, OrgId, UserId
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass(frozen=True, slots=True)
class NewAuditEntry:
    actor_kind: ActorKind
    actor_ref: ActorRef
    authority: str
    action: str
    """Dotted event name, e.g. ``task.completed`` (03 section 11.3 audit event column)."""
    target_kind: str
    target_id: str | None
    occurred_at: datetime
    job_id: JobId | None = None
    correlation_id: CorrelationId | None = None
    on_behalf_of: UserId | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AuditEntry:
    id: AuditEntryId
    org_id: OrgId
    seq: int
    entry: NewAuditEntry
    prev_hash: bytes
    row_hash: bytes


@dataclass(frozen=True, slots=True)
class ChainVerification:
    ok: bool
    entries_checked: int
    first_bad_seq: int | None
    """Lowest ``seq`` whose recomputed hash differs (an L3 security incident)."""


@runtime_checkable
class AuditLog(Protocol):
    def append(self, tx: TenantTransaction, entry: NewAuditEntry) -> AuditEntry: ...

    def verify_chain(self, tx: TenantTransaction) -> ChainVerification:
        """Recompute the tenant's chain from genesis to the head."""
        ...

    def export(
        self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None
    ) -> Iterator[AuditEntry]:
        """Tenant export in ``seq`` order (JSON export, 27 section 9 "Records")."""
        ...
