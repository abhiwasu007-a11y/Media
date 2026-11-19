"""Read of the document an approval's ``subject_ref`` points to (CCR-119, CCR-130, P4-17)."""

from typing import Protocol, runtime_checkable

from amw_core.interfaces.tenancy_context import TenantTransaction


@runtime_checkable
class SubjectDocuments(Protocol):
    def read(self, tx: TenantTransaction, subject_ref: str) -> bytes | None:
        """The stored bytes of a subject document of the tx org (tenant-scoped storage read),
        else ``None``. A ref of another tenant is ``CrossTenantRefError``."""
        ...
