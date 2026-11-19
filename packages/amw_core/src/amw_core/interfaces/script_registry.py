"""Read of ``scripts.content_sha256`` (04 5.9; CCR-130, ticket P4-17)."""

from typing import Protocol, runtime_checkable

from amw_core.interfaces.tenancy_context import TenantTransaction


@runtime_checkable
class ScriptRegistry(Protocol):
    def content_sha256(
        self, tx: TenantTransaction, *, script_id: str, script_version: int
    ) -> str | None:
        """``scripts.content_sha256`` of a script of the tx org, else ``None``."""
        ...
