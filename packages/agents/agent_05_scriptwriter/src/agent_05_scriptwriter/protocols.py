"""Ports of Agent 05 (blueprint 9.1): everything that touches a database, storage or the clock.

The worker wires adapters over ``amw_core`` (tenancy transaction, ``BlobStorage``,
``CheckpointStore``, ``CostLedger``, ``BudgetGuard``, ``IdempotencyStore``, ``AuditLog``) behind
these narrow Protocols; the package never opens a connection itself and never imports another
agent. Every method takes the ``StepContext`` so tenant scoping (org and channel) is explicit.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class StepContext:
    """Identity of one task attempt. Never logged as a whole (it names tenant IDs only)."""

    org_id: str
    job_id: str
    task_id: str
    attempt_id: str
    channel_id: str
    project_id: str | None
    correlation_id: str
    max_llm_calls: int
    max_cost_micros: int
    actor: str = "agent_05"


@dataclass(frozen=True, slots=True)
class RulePack:
    key: str
    version: str
    text: str
    scope: Literal["PLATFORM", "TENANT"]


@dataclass(frozen=True, slots=True)
class CheckpointState:
    step_key: str
    state: dict[str, Any]
    completed_effects: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SavedScript:
    script_id: str
    version: int
    uri: str
    sha256: str
    inserted: bool
    """False when the replay found the same ``(job, language, version)`` row with an equal hash."""


@dataclass(frozen=True, slots=True)
class HookHistoryEntry:
    channel_id: str
    text: str
    hook_style: str
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class LedgerRow:
    cost_entry_id: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    tokens_cached_in: int
    amount_micros: int


@runtime_checkable
class ChunkReader(Protocol):
    def read_cited(self, ctx: StepContext, refs: Sequence[str]) -> Mapping[str, str]:
        """Text of the chunks the pack cited (org and channel predicates). ``WORKING`` memory only:
        never sent to the model, never logged, never persisted."""
        ...


@runtime_checkable
class RulePackStore(Protocol):
    def get(self, ctx: StepContext, key: str) -> RulePack: ...


@runtime_checkable
class ScriptStore(Protocol):
    def next_version(self, ctx: StepContext, language: str) -> int:
        """Previous maximum ``version`` of ``(job, language)`` plus one."""
        ...

    def read_blob(self, ctx: StepContext, uri: str, sha256: str) -> bytes:
        """Read a script blob by URI; verifies org in the URI and SHA-256 (``CrossTenantRef`` /
        ``CorruptedOutput`` otherwise)."""
        ...

    def save(
        self,
        ctx: StepContext,
        *,
        script_id: str,
        version: int,
        iteration: int,
        language: str,
        content: bytes,
        sha256: str,
        parent_script_id: str | None,
        segment_count: int,
        word_count: int,
        est_duration_ms: int | None,
        prompt_id: str,
    ) -> SavedScript:
        """Blob first (write-once), then one transaction: ``scripts`` row (status ``DRAFT``), the
        previous iteration's row ``SUPERSEDED``, audit. Idempotent per job, language, version."""
        ...


@runtime_checkable
class HookHistoryStore(Protocol):
    def read(self, ctx: StepContext, n: int) -> Sequence[HookHistoryEntry]: ...

    def write(self, ctx: StepContext, entries: Sequence[HookHistoryEntry]) -> None: ...


@runtime_checkable
class CheckpointPort(Protocol):
    def latest(self, ctx: StepContext) -> CheckpointState | None: ...

    def write(self, ctx: StepContext, checkpoint: CheckpointState) -> None: ...


@runtime_checkable
class CallBudget(Protocol):
    def check_call(self, ctx: StepContext, estimated_cost_micros: int) -> None:
        """E2: raise ``BudgetExhausted`` before a call that would exceed a budget."""
        ...


@runtime_checkable
class CallLedger(Protocol):
    def record(self, ctx: StepContext, step_key: str, call_seq: int, usage: Any) -> LedgerRow:
        """Append one ESTIMATE row for a paid call (idempotent on the call key)."""
        ...


@runtime_checkable
class RunControl(Protocol):
    def stop_requested(self, ctx: StepContext) -> Literal["DRAIN", "PAUSE", "CANCEL"] | None:
        """Honoured between calls and between persist sub-steps (never mid-write)."""
        ...


@runtime_checkable
class TaskIdempotency(Protocol):
    def stored_output(self, ctx: StepContext) -> Any | None:
        """The stored output of a ``COMPLETED`` same-hash task key (T04), else ``None``."""
        ...

    def complete(self, ctx: StepContext, output: Any) -> None: ...


@runtime_checkable
class AuditPort(Protocol):
    def record(self, ctx: StepContext, event: str, details: Mapping[str, str | int]) -> None: ...


@dataclass(slots=True)
class Ports:
    """The collaborators injected into a step (constructor injection, no service locator)."""

    scripts: ScriptStore
    hook_history: HookHistoryStore
    checkpoints: CheckpointPort
    budget: CallBudget
    ledger: CallLedger
    control: RunControl
    idempotency: TaskIdempotency
    audit: AuditPort
    chunks: ChunkReader
    extras: dict[str, Any] = field(default_factory=dict)
