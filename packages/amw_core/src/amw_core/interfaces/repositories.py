"""Repository base Protocol (CCR-048 code-level table allow-list; CCR-130, ticket P4-17).

One repository class per agent; its tables are an explicit allow-list, checked by an import
lint and by tests. Every method takes the tenant transaction.
"""

from typing import Protocol, runtime_checkable

from amw_core.interfaces.tenancy_context import TenantTransaction


@runtime_checkable
class TenantRepository[RowT](Protocol):
    @property
    def allowed_tables(self) -> frozenset[str]:
        """The only tables this repository may name in SQL."""
        ...

    def get(self, tx: TenantTransaction, row_id: str) -> RowT | None:
        """The row of the tx org, else ``None``."""
        ...

    def add(self, tx: TenantTransaction, row: RowT) -> RowT:
        """Insert (idempotent where the table has a natural key)."""
        ...
