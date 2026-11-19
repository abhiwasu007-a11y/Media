"""Stage Protocols of the package (blueprint 9)."""

from typing import Protocol, runtime_checkable

from agent_04_research_knowledge.library.models import TenantScope
from agent_04_research_knowledge.models.ingest import IngestInput, IngestOutput
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.exec_context import ExecContext


@runtime_checkable
class ResearchStage(Protocol):
    def run(
        self,
        task_input: TaskInput,
        ctx: ExecContext,
    ) -> TaskOutput:
        """Run ``agent_04.research_pack``; every failure is returned as a ``TaskOutput``."""
        ...


@runtime_checkable
class IngestStage(Protocol):
    def run(self, scope: TenantScope, request: IngestInput) -> IngestOutput:
        """Run ``agent_04.knowledge_ingest`` for one registered source (the TaskOutput envelope is
        built by the document worker)."""
        ...
