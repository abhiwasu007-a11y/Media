"""The boundary between the code-controlled graph runner and the stage workers.

The runner (``amw_orchestrator.driver``) decides everything: order, gates, revisions, approvals,
budgets. A ``StageExecutor`` only does the work of one task and returns an ``amw.task_output``;
it never chooses the next stage (03 section 11; directive section 2: no LLM-to-LLM control).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from amw_core.contracts import OwnerTopic, ResourceBudget, Stage, TaskOutput, ValidationResult
from amw_core.enums import ProductionTypeKey


@dataclass(frozen=True, slots=True)
class JobFacts:
    """What a worker may know about its job (IDs are wire IDs)."""

    org_id: str
    workspace_id: str
    project_id: str | None
    channel_id: str
    job_id: str
    parent_job_id: str | None
    correlation_id: str
    production_type_key: ProductionTypeKey
    production_type_version: int
    language: str
    owner_topic: OwnerTopic
    currency: str


@dataclass(frozen=True, slots=True)
class StageCall:
    """One task attempt as the runner hands it to an executor."""

    job: JobFacts
    stage: Stage
    task_id: str
    attempt_id: str
    attempt_no: int
    iteration: int
    idempotency_key: str
    resource_budget: ResourceBudget
    upstream: Mapping[str, TaskOutput]
    """Latest ``COMPLETED`` output per stage of this job (and, for a child job, ``parent.<id>``)."""
    prior_output: TaskOutput | None = None
    """The previous iteration's output of this stage (24 section 3.3 rule 6, ``PRIOR_OUTPUT``)."""
    revision_feedback: tuple[ValidationResult, ...] = field(default_factory=tuple)
    """Failing gate results that caused this iteration (24 section 3.3 rules 7 / 7b)."""
    revision_source_stage_id: str | None = None


@runtime_checkable
class StageExecutor(Protocol):
    def execute(self, call: StageCall) -> TaskOutput:
        """Run one attempt; domain failures are gate results, never exceptions (03 5.3)."""
        ...


@runtime_checkable
class ExecutorRegistry(Protocol):
    def executor_for(self, stage: Stage) -> StageExecutor:
        """The worker for a stage (by ``task_type``; ``KeyError`` when none is registered)."""
        ...
