"""Read side of ``circuit_breakers`` (04 5.8; CCR-130, ticket P4-17).

Display and gating inputs only: the writer is ``SystemFunctions.breaker_record`` and admission
is decided only by ``admit`` (a read-then-act decision is racy).
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from amw_core.enums import CircuitState
from amw_core.interfaces.system_functions import BreakerKey
from amw_core.interfaces.tenancy_context import TenantTransaction


@runtime_checkable
class BreakerReader(Protocol):
    def state_of(self, tx: TenantTransaction, key: BreakerKey) -> CircuitState | None:
        """The breaker state visible in the tenant transaction (platform rows are readable);
        ``None`` = no row yet (closed)."""
        ...

    def open_until(self, tx: TenantTransaction, key: BreakerKey) -> datetime | None: ...

    def is_open(self, tx: TenantTransaction, key: BreakerKey) -> bool:
        """``True`` when the state is ``OPEN``."""
        ...
