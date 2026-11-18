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
    interfaces.SystemFunctions,
    interfaces.IdempotencyStore,
    interfaces.CheckpointStore,
    interfaces.ReadableStream,
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
            assert vars(obj)["__dataclass_params__"].frozen, name


def test_structural_match() -> None:
    from datetime import UTC, datetime

    class FixedClock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

        def monotonic_ms(self) -> int:
            return 0

    assert isinstance(FixedClock(), interfaces.Clock)


def test_system_functions_return_identifiers_only() -> None:
    from amw_core.interfaces import system_functions as sf

    for record in (sf.DueTask, sf.DueResume, sf.ExpiredLease, sf.StuckTask):
        names = {f.name for f in dataclasses.fields(record)}
        assert names <= {"org_id", "task_id", "wait_reason", "queue_item_id", "state"}
    claimed = {f.name for f in dataclasses.fields(interfaces.ClaimedItem)}
    assert claimed == {"queue_item_id", "org_id", "task_id", "envelope"}


def test_storage_is_stream_based() -> None:
    import io

    put = inspect.get_annotations(interfaces.BlobStorage.put)
    assert put["stream"] is interfaces.ReadableStream
    assert isinstance(io.BytesIO(b"x"), interfaces.ReadableStream)
    assert hasattr(interfaces.BlobStorage, "list_prefix")


def test_job_store_has_no_cross_tenant_scans() -> None:
    assert not hasattr(interfaces.JobStore, "retry_due")
    assert not hasattr(interfaces.JobStore, "stuck_tasks")
