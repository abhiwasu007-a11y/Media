"""Read ``channels.category`` for one channel inside an open tenant transaction (04 section 5.1).

The column is free nullable text (CCR-273 / CCR-288: its value set is not closed), so this module
returns it as stored and decides nothing. It fails closed: a missing row, a NULL, a non-text value,
a malformed channel ID, a transaction that is not a PostgreSQL tenant transaction and any database
error all give ``None``, which every caller must treat as finance (D13). The read runs in a
savepoint, so a database error cannot abort the caller's transaction.
"""

import psycopg

from amw_core.errors import AmwError
from amw_core.ids import CHANNEL
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy.context import PgTenantTransaction, connection_of, org_uuid_of


def read_channel_category(tx: TenantTransaction, channel_id: str) -> str | None:
    """``channels.category`` of ``channel_id`` in the tenant of ``tx``; ``None`` when unknown."""
    if not isinstance(tx, PgTenantTransaction):
        return None
    try:
        channel = CHANNEL.to_uuid(channel_id)
        org = org_uuid_of(tx)
        conn = connection_of(tx)
        with conn.transaction(), conn.cursor() as cur:  # a savepoint inside the tenant transaction
            cur.execute(
                "SELECT category FROM channels WHERE org_id = %s AND id = %s", (org, channel)
            )
            row = cur.fetchone()
    except psycopg.Error, AmwError, TypeError, ValueError:
        return None
    if row is None or not isinstance(row[0], str):
        return None
    return row[0]
