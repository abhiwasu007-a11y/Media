"""Recording ``AuditLog`` stand-in for store tests until lane L1b's ``amw_core.audit`` lands."""

from collections.abc import Iterator
from dataclasses import dataclass, field

from amw_core.ids import AUDIT_ENTRY, OrgId
from amw_core.interfaces.audit_log import AuditEntry, ChainVerification, NewAuditEntry
from amw_core.interfaces.tenancy_context import TenantTransaction


@dataclass
class RecordingAuditLog:
    entries: list[AuditEntry] = field(default_factory=list)
    _seq: dict[OrgId, int] = field(default_factory=dict)

    def append(self, tx: TenantTransaction, entry: NewAuditEntry) -> AuditEntry:
        org = tx.context.org_id
        seq = self._seq.get(org, 0) + 1
        self._seq[org] = seq
        record = AuditEntry(AUDIT_ENTRY.new(), org, seq, entry, b"\0" * 32, b"\0" * 32)
        self.entries.append(record)
        return record

    def verify_chain(self, tx: TenantTransaction) -> ChainVerification:
        mine = [e for e in self.entries if e.org_id == tx.context.org_id]
        return ChainVerification(True, len(mine), None)

    def export(
        self, tx: TenantTransaction, since_seq: int = 0, target_id: str | None = None
    ) -> Iterator[AuditEntry]:
        for e in self.entries:
            mine = e.org_id == tx.context.org_id and e.seq > since_seq
            if mine and (target_id is None or e.entry.target_id == target_id):
                yield e

    def actions(self) -> list[str]:
        return [e.entry.action for e in self.entries]
