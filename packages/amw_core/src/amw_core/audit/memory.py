"""In-memory ``AuditLog`` (tests and the pure-logic lane); one chain per tenant, serialised by a
per-org lock that plays the role of the ``audit_chain_heads`` row lock."""

import threading
from collections.abc import Iterator

from amw_core.audit.chain import (
    GENESIS_HASH,
    ChainHead,
    row_hash,
    stored_columns,
    validate_entry,
    verify_entries,
)
from amw_core.ids import AUDIT_ENTRY, OrgId
from amw_core.interfaces.audit_log import AuditEntry, ChainVerification, NewAuditEntry
from amw_core.interfaces.tenancy_context import TenantTransaction


class MemoryAuditLog:
    def __init__(self) -> None:
        self._rows: dict[OrgId, list[AuditEntry]] = {}
        self._heads: dict[OrgId, ChainHead] = {}
        self._locks: dict[OrgId, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, org: OrgId) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(org, threading.Lock())

    def append(self, tx: TenantTransaction, entry: NewAuditEntry) -> AuditEntry:
        validate_entry(entry)
        org = tx.context.org_id
        with self._lock(org):
            head = self._heads.get(org, ChainHead(0, GENESIS_HASH))
            entry_id = AUDIT_ENTRY.new()
            seq = head.last_seq + 1
            columns = stored_columns(entry_id, org, seq, entry, head.last_hash)
            digest = row_hash(head.last_hash, columns)
            row = AuditEntry(
                id=entry_id,
                org_id=org,
                seq=seq,
                entry=entry,
                prev_hash=head.last_hash,
                row_hash=digest,
            )
            self._rows.setdefault(org, []).append(row)
            self._heads[org] = ChainHead(seq, digest)
            return row

    def verify_chain(self, tx: TenantTransaction) -> ChainVerification:
        org = tx.context.org_id
        return verify_entries(self._rows.get(org, []), self._heads.get(org))

    def export(
        self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None
    ) -> Iterator[AuditEntry]:
        for row in self._rows.get(tx.context.org_id, []):
            if row.seq > since_seq and (target_id is None or row.entry.target_id == target_id):
                yield row

    # test hooks: simulate tampering of the stored rows (never used by production code)
    def _tamper(self, org: OrgId, index: int, row: AuditEntry) -> None:
        self._rows[org][index] = row

    def _truncate(self, org: OrgId, keep: int) -> None:
        del self._rows[org][keep:]
