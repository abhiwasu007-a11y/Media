"""PostgreSQL tenant transactions (04 section 3.2; 03 section 10.3; 27 section 7.3 rule 3).

``PgTenancy.transaction(ctx)`` opens ``BEGIN``, then ``set_config('app.org_id', ..., true)``
(= ``SET LOCAL``), ``app.actor`` and, for a human actor, ``app.user_id``. Nothing is set for the
session, so a pooled connection never carries a tenant into the next transaction. The org must be
``ACTIVE`` (``TenantInactiveError`` otherwise, 07 section 2).

Stores receive the ``TenantTransaction`` handle and reach the connection only through
``connection_of(tx)``, which refuses a handle that is not an open ``PgTenantTransaction``
(application-level guard of 04 section 3.2: no query outside a tenant transaction).
"""

import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import psycopg
from psycopg import errors as pg_errors

from amw_core.enums import OrgStatus
from amw_core.errors import (
    AmwError,
    ConfigInvalidError,
    DbTransientError,
    DbUnavailableError,
    InputInvalidError,
    InvalidTransitionError,
    MissingDependencyError,
    PermissionDeniedError,
    TenantInactiveError,
    TenantMismatchError,
)
from amw_core.ids import ORG, USER, OrgId, Prefix, is_actor_ref, prefix_of
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction

Connection = psycopg.Connection[tuple[Any, ...]]
ConnectionFactory = Callable[[], AbstractContextManager[Connection]]
"""Yields an open connection for one transaction (a pool checkout or a fresh connection)."""

SQLSTATE_INVALID_TRANSITION = "AMW01"
SQLSTATE_GUARD_REJECTED = "AMW02"
SQLSTATE_MISSING_DEPENDENCY = "AMW03"
SQLSTATE_CONFIG_INVALID = "AMW04"
"""Raised by a database function whose server-side configuration is missing or exceeded (0055:
the probe lease bound of ``amw_breaker_admit``)."""


class PgTenantTransaction:
    """``TenantTransaction`` bound to one open psycopg transaction."""

    __slots__ = ("_conn", "_context", "_open", "org_uuid")

    def __init__(self, conn: Connection, context: TenantContext, org_uuid: uuid.UUID) -> None:
        self._conn = conn
        self._context = context
        self._open = True
        self.org_uuid = org_uuid

    @property
    def context(self) -> TenantContext:
        return self._context

    @property
    def is_open(self) -> bool:
        return self._open

    def _close(self) -> None:
        self._open = False


def connection_of(tx: TenantTransaction) -> Connection:
    """The connection of an open tenant transaction; ``TypeError`` for anything else."""
    if not isinstance(tx, PgTenantTransaction):
        raise TypeError("a PostgreSQL store needs a PgTenantTransaction")
    if not tx.is_open:
        raise TypeError("tenant transaction is closed")
    return tx._conn


def org_uuid_of(tx: TenantTransaction) -> uuid.UUID:
    """The tenant's stored UUID of an open tenant transaction (for explicit org filters)."""
    connection_of(tx)
    return tx.org_uuid if isinstance(tx, PgTenantTransaction) else ORG.to_uuid(tx.context.org_id)


def translate_db_error(exc: psycopg.Error) -> AmwError:
    """Map a driver error to the 07 section 2 typed exception."""
    state = exc.sqlstate or ""
    if state == SQLSTATE_INVALID_TRANSITION:
        return InvalidTransitionError(str(exc).split("\n", 1)[0])
    if state == SQLSTATE_MISSING_DEPENDENCY:
        return MissingDependencyError(str(exc).split("\n", 1)[0])
    if state == SQLSTATE_CONFIG_INVALID:
        return ConfigInvalidError(str(exc).split("\n", 1)[0])
    if state in (SQLSTATE_GUARD_REJECTED, "42501"):
        return PermissionDeniedError(str(exc).split("\n", 1)[0])
    if isinstance(exc, (pg_errors.SerializationFailure, pg_errors.DeadlockDetected)):
        return DbTransientError(str(exc).split("\n", 1)[0])
    if isinstance(exc, psycopg.OperationalError):
        return DbUnavailableError("database unavailable")
    raise exc


def dsn_connection_factory(conninfo: str, role: str | None = None) -> ConnectionFactory:
    """A factory that opens one connection per transaction (no pool). ``role``, when given, is
    set for the session with ``SET ROLE`` (a role is not a tenant setting)."""

    @contextmanager
    def factory() -> Iterator[Connection]:
        with psycopg.connect(conninfo) as conn:
            if role is not None:
                conn.execute(psycopg.sql.SQL("SET ROLE {}").format(psycopg.sql.Identifier(role)))
                conn.commit()
            yield conn

    return factory


class PgTenancy:
    """``TenancyContext`` on PostgreSQL."""

    def __init__(self, connections: ConnectionFactory) -> None:
        self._connections = connections

    @contextmanager
    def _transaction(self, context: TenantContext) -> Iterator[TenantTransaction]:
        org_uuid = ORG.to_uuid(context.org_id)
        if not is_actor_ref(context.actor):
            raise TenantMismatchError("tenant context needs a valid actor reference")
        user_uuid = USER.to_uuid(context.actor) if context.actor.startswith("usr_") else None
        try:
            with self._connections() as conn, conn.transaction():
                conn.execute("SELECT set_config('app.org_id', %s, true)", (str(org_uuid),))
                conn.execute("SELECT set_config('app.actor', %s, true)", (context.actor,))
                if user_uuid is not None:
                    conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_uuid),))
                row = conn.execute(
                    "SELECT status FROM organisations WHERE id = %s", (org_uuid,)
                ).fetchone()
                if row is None or row[0] != OrgStatus.ACTIVE:
                    raise TenantInactiveError(
                        "organisation is not active",
                        details={"org_id": context.org_id, "status": row[0] if row else None},
                    )
                tx = PgTenantTransaction(conn, context, org_uuid)
                try:
                    yield tx
                finally:
                    tx._close()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc

    def transaction(self, context: TenantContext) -> AbstractContextManager[TenantTransaction]:
        return self._transaction(context)

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        if org_id != tx.context.org_id:
            raise TenantMismatchError(
                "org IDs disagree", details={"expected": tx.context.org_id, "got": org_id[:80]}
            )

    def cache_key(self, org_id: OrgId, area: str, key: str) -> str:
        return cache_key(org_id, area, key)


def cache_key(org_id: OrgId, area: str, key: str) -> str:
    """``amw:<org wire id>:<area>:<key>`` (GLOSSARY section 2.4; the org part is mandatory)."""
    if prefix_of(org_id) is not Prefix.ORGANISATION:
        raise TenantMismatchError("cache key needs an organisation ID")
    if not area or ":" in area:
        raise InputInvalidError("cache key area must be non-empty and contain no ':'")
    if not key:
        raise InputInvalidError("cache key must be non-empty")
    return f"amw:{org_id}:{area}:{key}"
