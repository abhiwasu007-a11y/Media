"""Tenant transaction context (04 section 3.2; 03 section 10.3; 27 section 7.3 rule 3).

Every DB access runs inside a tenant transaction that began with ``SET LOCAL app.org_id`` and
``SET LOCAL app.actor`` (INF-11); no session-wide tenant setting exists, so pooled connections never
leak context. Store interfaces take the ``TenantTransaction`` handle as their first argument, which
makes "one transaction per transition" (03 section 11.4) explicit. Implementation: lane L1.
"""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from amw_core.ids import ActorRef, CorrelationId, OrgId


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Who acts for which tenant; ``org_id`` is the only tenant a transaction can see."""

    org_id: OrgId
    actor: ActorRef
    correlation_id: CorrelationId | None = None


@runtime_checkable
class TenantTransaction(Protocol):
    """An open DB transaction bound to one tenant (``app.org_id`` set with ``SET LOCAL``)."""

    @property
    def context(self) -> TenantContext: ...


@runtime_checkable
class TenancyContext(Protocol):
    def transaction(self, context: TenantContext) -> AbstractContextManager[TenantTransaction]:
        """Open a tenant transaction: ``BEGIN; SET LOCAL app.org_id; SET LOCAL app.actor``.

        Commits on normal exit, rolls back on exception. Raises ``TenantInactiveError`` for a
        suspended/offboarding org (07 section 2).
        """
        ...

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        """03 7.1 step 6: raise ``TenantMismatchError`` unless ``org_id`` is the tx tenant."""
        ...

    def cache_key(self, org_id: OrgId, area: str, key: str) -> str:
        """``amw:<org wire id>:<area>:<key>`` (GLOSSARY section 2.4; the org part is mandatory)."""
        ...
