"""Per-attempt runtime state shared by the steps (counters, usage totals, ids)."""

from dataclasses import dataclass, field

from agent_04_research_knowledge.errors import LoopCapExceeded
from agent_04_research_knowledge.library.models import TenantScope
from agent_04_research_knowledge.observability import AuditSink, EventLogger
from amw_core.ids import AttemptId, JobId, TaskId
from amw_core.interfaces import TenantContext


@dataclass
class CallCounter:
    """``max_llm_calls`` cap (NFR-4): every call, repair calls included, takes one."""

    max_calls: int
    used: int = 0

    def take(self) -> None:
        if self.used >= self.max_calls:
            raise LoopCapExceeded("max_llm_calls reached", details={"max_calls": self.max_calls})
        self.used += 1


@dataclass
class UsageTotals:
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached_in: int = 0
    llm_calls: int = 0
    provider_calls: int = 0
    cost_micros: int = 0
    cost_entry_ids: list[str] = field(default_factory=list)


@dataclass
class RunInfo:
    """Everything a step needs to act for one attempt of one task."""

    context: TenantContext
    scope: TenantScope
    job_id: JobId
    task_id: TaskId
    attempt_id: AttemptId
    currency: str
    log: EventLogger
    audit: AuditSink
    counter: CallCounter
    usage: UsageTotals = field(default_factory=UsageTotals)
    effects: list[str] = field(default_factory=list)
    """idempotency keys of completed external effects (checkpoint ``completed_effects``)."""
