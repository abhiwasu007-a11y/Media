"""Shared SQL helpers of the PostgreSQL port adapters (every statement runs in the caller's tenant
transaction, as ``amw_app``; each one names ``org_id`` explicitly on top of RLS).

Failure model (07 section 2): a transaction that is not a PostgreSQL tenant transaction is
``ConfigInvalidError`` (a wiring error, never a silent skip), a malformed ID is
``InputInvalidError``, a driver error becomes its typed error through ``translate_db_error``.
"""

import uuid
from typing import Any

import psycopg

from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError
from amw_core.ids import IdKind, Prefix
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

Row = tuple[Any, ...]

# ID kinds amw_core has no helper for yet (plain wire strings).
SCRIPT = IdKind(Prefix.SCRIPT, str)
CLAIM = IdKind(Prefix.CLAIM, str)
QUALITY_SCORE = IdKind(Prefix.QUALITY_SCORE, str)
QC_RESULT = IdKind(Prefix.QC_RESULT, str)


def org_of(tx: TenantTransaction) -> uuid.UUID:
    """The tenant UUID of ``tx`` for explicit ``org_id`` predicates."""
    try:
        return org_uuid_of(tx)
    except TypeError:
        raise ConfigInvalidError(
            "a PostgreSQL port adapter needs a PostgreSQL tenant transaction"
        ) from None


def uuid_of(kind: IdKind[Any], wire: str) -> uuid.UUID:
    """Parse a wire ID of ``kind``; any malformed value is ``InputInvalidError``."""
    try:
        return kind.to_uuid(wire)
    except ValueError:
        raise InputInvalidError(
            f"malformed {kind.prefix.value} id", details={"value": str(wire)[:80]}
        ) from None


def rows(tx: TenantTransaction, stmt: str, params: Any = None) -> list[Row]:
    """Run one statement and return all rows (empty for a statement without a result)."""
    try:
        connection = connection_of(tx)
    except TypeError:
        raise ConfigInvalidError(
            "a PostgreSQL port adapter needs a PostgreSQL tenant transaction"
        ) from None
    try:
        cursor = connection.execute(stmt.encode(), params)
        return cursor.fetchall() if cursor.description is not None else []
    except psycopg.Error as exc:
        raise translate_db_error(exc) from exc


_TABLES = frozenset({"jobs", "tasks", "channels", "scripts", "renders"})


def require(tx: TenantTransaction, table: str, org: uuid.UUID, row: uuid.UUID, what: str) -> None:
    """The row must exist in the tenant (another tenant's row is invisible): else
    ``MissingDependencyError``, fail closed."""
    if table not in _TABLES:  # the table name is never caller data; this keeps it that way
        raise InputInvalidError("unknown table")
    if not rows(tx, f"SELECT 1 FROM {table} WHERE org_id = %s AND id = %s", (org, row)):  # noqa: S608
        raise MissingDependencyError(f"{what} not found", details={"class": what})
