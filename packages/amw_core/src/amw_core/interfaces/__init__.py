"""Typed Protocols for the 3A core services (implementations are lane L1; nothing here runs I/O)."""

from amw_core.interfaces.audit_log import AuditEntry, AuditLog, ChainVerification, NewAuditEntry
from amw_core.interfaces.budget_guard import (
    Budget,
    BudgetGuard,
    BudgetStatus,
    CallCheck,
    Reservation,
    ReservationOutcome,
)
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostEntry, CostLedger, CostTotals, NewCostEntry
from amw_core.interfaces.job_store import (
    AttemptRecord,
    JobRecord,
    JobStore,
    JobTransition,
    NewJob,
    NewTask,
    TaskRecord,
    TaskTransition,
)
from amw_core.interfaces.queue import ClaimRequest, NewQueueItem, QueueItem, TaskQueue
from amw_core.interfaces.storage import BlobHead, BlobInfo, BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext, TenantTransaction

__all__ = [
    "AttemptRecord",
    "AuditEntry",
    "AuditLog",
    "BlobHead",
    "BlobInfo",
    "BlobStorage",
    "BlobUri",
    "Budget",
    "BudgetGuard",
    "BudgetStatus",
    "CallCheck",
    "ChainVerification",
    "ClaimRequest",
    "Clock",
    "CostEntry",
    "CostLedger",
    "CostTotals",
    "JobRecord",
    "JobStore",
    "JobTransition",
    "NewAuditEntry",
    "NewCostEntry",
    "NewJob",
    "NewQueueItem",
    "NewTask",
    "QueueItem",
    "Reservation",
    "ReservationOutcome",
    "TaskQueue",
    "TaskRecord",
    "TaskTransition",
    "TenancyContext",
    "TenantContext",
    "TenantTransaction",
]
