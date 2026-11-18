"""Clock interface (27 section 7.3 rule 8: aware UTC only; GLOSSARY section 4).

Injected wherever code reads time (deadlines T12/T13, leases T07/T10, wait timeouts T16, budget
periods 09 section 3.1) so tests can drive time deterministically. Implementation: lane L1.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as an aware ``datetime`` in UTC (never naive, never a local zone)."""
        ...

    def monotonic_ms(self) -> int:
        """Monotonic milliseconds for measuring ``duration`` / ``*_ms`` (03 section 5.1)."""
        ...
