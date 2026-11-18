"""PostgreSQL ``AuditLog`` (04 section 5.13).

``append`` runs in the caller's tenant transaction: it makes sure the tenant's chain head exists,
locks it (``SELECT ... FOR UPDATE``), assigns ``seq = last_seq + 1``, computes the hash, inserts
the row and moves the head. Two concurrent writers of one tenant therefore serialise on the head
row; ``seq`` stays gap-free. ``amw_app`` may only INSERT into ``audit_log`` (no UPDATE, DELETE or
SELECT); ``verify_chain`` and ``export`` need a transaction of the read-only role.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from amw_core.audit.chain import (
    GENESIS_HASH,
    ChainHead,
    row_hash,
    stored_columns,
    target_prefix,
    validate_entry,
    verify_entries,
    wire_from_uuid,
)
from amw_core.enums import ActorKind
from amw_core.ids import (
    AUDIT_ENTRY,
    CORRELATION,
    JOB,
    USER,
    ActorRef,
    AuditEntryId,
    CorrelationId,
    JobId,
    OrgId,
    Prefix,
    UserId,
    parse_id,
)
from amw_core.interfaces.audit_log import AuditEntry, ChainVerification, NewAuditEntry
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy import connection_of, org_uuid_of, translate_db_error

_COLUMNS = (
    "id, org_id, seq, occurred_at, actor_kind, actor_ref, on_behalf_of, authority, action,"
    " target_kind, target_id, job_id, correlation_id, details, prev_hash, row_hash"
)


def _uuid_or_none(wire: str | None, prefix: Prefix) -> uuid.UUID | None:
    return None if wire is None else parse_id(wire, prefix)


class PgAuditLog:
    def append(self, tx: TenantTransaction, entry: NewAuditEntry) -> AuditEntry:
        validate_entry(entry)
        conn = connection_of(tx)
        org = org_uuid_of(tx)
        org_wire = tx.context.org_id
        try:
            conn.execute(
                "INSERT INTO audit_chain_heads (org_id, last_seq, last_hash) VALUES (%s, 0, %s)"
                " ON CONFLICT (org_id) DO NOTHING",
                (org, GENESIS_HASH),
            )
            head = conn.execute(
                "SELECT last_seq, last_hash FROM audit_chain_heads WHERE org_id = %s FOR UPDATE",
                (org,),
            ).fetchone()
            assert head is not None  # noqa: S101 - inserted just above in this transaction
            last_seq, last_hash = int(head[0]), bytes(head[1])
            entry_id = AUDIT_ENTRY.new()
            seq = last_seq + 1
            columns = stored_columns(entry_id, org_wire, seq, entry, last_hash)
            digest = row_hash(last_hash, columns)
            conn.execute(
                f"INSERT INTO audit_log ({_COLUMNS})"  # noqa: S608 - constant column list
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    AUDIT_ENTRY.to_uuid(entry_id),
                    org,
                    seq,
                    entry.occurred_at,
                    str(entry.actor_kind),
                    entry.actor_ref,
                    _uuid_or_none(entry.on_behalf_of, Prefix.USER),
                    entry.authority,
                    entry.action,
                    entry.target_kind,
                    None
                    if entry.target_id is None
                    else parse_id(entry.target_id, target_prefix(entry.target_kind)),
                    _uuid_or_none(entry.job_id, Prefix.JOB),
                    _uuid_or_none(entry.correlation_id, Prefix.CORRELATION),
                    Jsonb(columns["details"]),
                    last_hash,
                    digest,
                ),
            )
            conn.execute(
                "UPDATE audit_chain_heads SET last_seq = %s, last_hash = %s WHERE org_id = %s",
                (seq, digest, org),
            )
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        return AuditEntry(
            id=entry_id, org_id=org_wire, seq=seq, entry=entry, prev_hash=last_hash, row_hash=digest
        )

    def _rows(
        self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None
    ) -> Iterator[AuditEntry]:
        conn = connection_of(tx)
        org = org_uuid_of(tx)
        query = f"SELECT {_COLUMNS} FROM audit_log WHERE org_id = %s AND seq > %s"  # noqa: S608
        params: list[Any] = [org, since_seq]
        if target_id is not None:
            query += " AND target_id = %s"
            params.append(uuid.UUID(target_id.split("_", 1)[1]))
        query += " ORDER BY seq"
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                for row in cur:
                    yield self._entry(row)
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc

    @staticmethod
    def _entry(row: tuple[Any, ...]) -> AuditEntry:
        (rid, org, seq, occurred_at, actor_kind, actor_ref, obo, authority, action, target_kind,
         target_id, job_id, corr, details, prev_hash, digest) = row  # fmt: skip
        target_wire = (
            None if target_id is None else wire_from_uuid(target_prefix(target_kind), target_id)
        )
        new = NewAuditEntry(
            actor_kind=ActorKind(actor_kind),
            actor_ref=ActorRef(actor_ref),
            authority=authority,
            action=action,
            target_kind=target_kind,
            target_id=target_wire,
            occurred_at=occurred_at,
            job_id=JobId(w) if (w := wire_from_uuid(JOB.prefix, job_id)) else None,
            correlation_id=(
                CorrelationId(w) if (w := wire_from_uuid(CORRELATION.prefix, corr)) else None
            ),
            on_behalf_of=UserId(w) if (w := wire_from_uuid(USER.prefix, obo)) else None,
            details=details,
        )
        return AuditEntry(
            id=AuditEntryId(f"aud_{rid}"),
            org_id=OrgId(f"org_{org}"),
            seq=int(seq),
            entry=new,
            prev_hash=bytes(prev_hash),
            row_hash=bytes(digest),
        )

    def verify_chain(self, tx: TenantTransaction) -> ChainVerification:
        conn = connection_of(tx)
        try:
            head_row = conn.execute(
                "SELECT last_seq, last_hash FROM audit_chain_heads WHERE org_id = %s",
                (org_uuid_of(tx),),
            ).fetchone()
        except psycopg.Error as exc:
            raise translate_db_error(exc) from exc
        head = None if head_row is None else ChainHead(int(head_row[0]), bytes(head_row[1]))
        return verify_entries(self._rows(tx), head)

    def export(
        self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None
    ) -> Iterator[AuditEntry]:
        return self._rows(tx, since_seq, target_id)
