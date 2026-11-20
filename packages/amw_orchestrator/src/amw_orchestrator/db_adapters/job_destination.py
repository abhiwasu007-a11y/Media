"""``JobDestinationReader`` of agent_08 on PostgreSQL: ``jobs.monetized_destination`` (04 section
5.3, CCR-028). One SELECT with explicit ``org_id`` plus RLS; writes nothing.

A job that is not in the tenant (absent, or another tenant's: RLS and the predicate hide it) is a
typed ``MissingDependencyError`` (fail closed), never ``True``; the stage turns a value that is not
a real ``bool`` into the same refusal.
"""

from amw_core.errors import MissingDependencyError
from amw_core.ids import JOB
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_orchestrator.db_adapters._sql import org_of, rows, uuid_of


class PgJobDestinationReader:
    def monetized_destination(self, tx: TenantTransaction, job_id: str) -> bool | None:
        found = rows(
            tx,
            "SELECT monetized_destination FROM jobs WHERE org_id = %s AND id = %s",
            (org_of(tx), uuid_of(JOB, job_id)),
        )
        if not found:
            raise MissingDependencyError("job not found", details={"class": "job"})
        value = found[0][0]
        return value if isinstance(value, bool) else None
