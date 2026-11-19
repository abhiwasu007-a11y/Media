"""Typed Protocols for the 3A core services (implementations are lane L1; nothing here runs I/O)."""

from amw_core.interfaces.audit_log import AuditEntry, AuditLog, ChainVerification, NewAuditEntry
from amw_core.interfaces.breaker_read import BreakerReader
from amw_core.interfaces.budget_guard import (
    Budget,
    BudgetGuard,
    BudgetStatus,
    CallCheck,
    Reservation,
    ReservationOutcome,
)
from amw_core.interfaces.checkpoint_store import CheckpointRecord, CheckpointStore, NewCheckpoint
from amw_core.interfaces.claims import (
    CitationRow,
    ClaimStatusUpdate,
    ClaimStore,
    NewClaim,
    RuleFlag,
)
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostEntry, CostLedger, CostTotals, NewCostEntry
from amw_core.interfaces.idempotency_store import (
    BeginAction,
    BeginDecision,
    IdempotencyRecord,
    IdempotencyStore,
)
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
from amw_core.interfaces.knowledge_collections import (
    KnowledgeCollection,
    KnowledgeCollections,
    NewKnowledgeCollection,
)
from amw_core.interfaces.knowledge_reader import KnowledgeReader, SourceText
from amw_core.interfaces.memory_items import MemoryItem, MemoryItems, StoredMemoryItem
from amw_core.interfaces.owner_evidence import (
    DbRole,
    DbSession,
    EvidenceDatabase,
    EvidenceRecord,
    HumanRecord,
    NewEvidence,
    SessionEvent,
    SessionEventSource,
)
from amw_core.interfaces.queue import (
    ClaimedItem,
    ClaimRequest,
    NewQueueItem,
    QueueItem,
    TaskQueue,
)
from amw_core.interfaces.repositories import TenantRepository
from amw_core.interfaces.script_registry import ScriptRegistry
from amw_core.interfaces.storage import BlobHead, BlobInfo, BlobStorage, BlobUri, ReadableStream
from amw_core.interfaces.subject_documents import SubjectDocuments
from amw_core.interfaces.system_functions import (
    BreakerKey,
    BreakerState,
    DueResume,
    DueTask,
    ExpiredLease,
    StuckTask,
    SystemFunctions,
)
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext, TenantTransaction
from amw_core.interfaces.voices import VoiceConsentRecord, VoiceRecord, VoiceRegistry
from amw_core.interfaces.worker import TaskWorker

__all__ = [
    "AttemptRecord",
    "AuditEntry",
    "AuditLog",
    "BeginAction",
    "BeginDecision",
    "BlobHead",
    "BlobInfo",
    "BlobStorage",
    "BlobUri",
    "BreakerKey",
    "BreakerReader",
    "BreakerState",
    "Budget",
    "BudgetGuard",
    "BudgetStatus",
    "CallCheck",
    "ChainVerification",
    "CheckpointRecord",
    "CheckpointStore",
    "CitationRow",
    "ClaimRequest",
    "ClaimStatusUpdate",
    "ClaimStore",
    "ClaimedItem",
    "Clock",
    "CostEntry",
    "CostLedger",
    "CostTotals",
    "DbRole",
    "DbSession",
    "DueResume",
    "DueTask",
    "EvidenceDatabase",
    "EvidenceRecord",
    "ExpiredLease",
    "HumanRecord",
    "IdempotencyRecord",
    "IdempotencyStore",
    "JobRecord",
    "JobStore",
    "JobTransition",
    "KnowledgeCollection",
    "KnowledgeCollections",
    "KnowledgeReader",
    "MemoryItem",
    "MemoryItems",
    "NewAuditEntry",
    "NewCheckpoint",
    "NewClaim",
    "NewCostEntry",
    "NewEvidence",
    "NewJob",
    "NewKnowledgeCollection",
    "NewQueueItem",
    "NewTask",
    "QueueItem",
    "ReadableStream",
    "Reservation",
    "ReservationOutcome",
    "RuleFlag",
    "ScriptRegistry",
    "SessionEvent",
    "SessionEventSource",
    "SourceText",
    "StoredMemoryItem",
    "StuckTask",
    "SubjectDocuments",
    "SystemFunctions",
    "TaskQueue",
    "TaskRecord",
    "TaskTransition",
    "TaskWorker",
    "TenancyContext",
    "TenantContext",
    "TenantRepository",
    "TenantTransaction",
    "VoiceConsentRecord",
    "VoiceRecord",
    "VoiceRegistry",
]
