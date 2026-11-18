"""Interfaces import cleanly, are runtime-checkable Protocols, and their records are frozen."""

import dataclasses
import inspect
from typing import Protocol

import pytest

from amw_core import interfaces

PROTOCOLS = [
    interfaces.AuditLog,
    interfaces.BudgetGuard,
    interfaces.BlobStorage,
    interfaces.Clock,
    interfaces.CostLedger,
    interfaces.JobStore,
    interfaces.TaskQueue,
    interfaces.TenancyContext,
    interfaces.TenantTransaction,
]


@pytest.mark.parametrize("proto", PROTOCOLS)
def test_is_runtime_checkable_protocol(proto: type) -> None:
    assert Protocol in proto.__mro__
    assert not isinstance(object(), proto)
    for name, member in inspect.getmembers(proto, inspect.isfunction):
        if not name.startswith("_"):
            assert "return" in inspect.get_annotations(member), name


def test_records_are_frozen() -> None:
    for name in interfaces.__all__:
        obj = getattr(interfaces, name)
        if dataclasses.is_dataclass(obj):
            assert obj.__dataclass_params__.frozen, name  # type: ignore[attr-defined]


def test_structural_match() -> None:
    from datetime import UTC, datetime

    class FixedClock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

        def monotonic_ms(self) -> int:
            return 0

    assert isinstance(FixedClock(), interfaces.Clock)
