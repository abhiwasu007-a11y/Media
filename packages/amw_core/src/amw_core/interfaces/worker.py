"""The shared worker entry point (03 section 1 rule 5, CCR-203).

Every task type has exactly one entry point ``run(task_input, ctx) -> TaskOutput`` in its package.
Domain failures, rejections and refusals are returned as a Task Output, never raised past it; an
agent-internal result type never crosses it; inputs come only from the Task Input and the documents
it references. The orchestrator's input builder is the only code that builds the Task Input.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput

if TYPE_CHECKING:  # exec_context imports this package; annotations are lazy (Python 3.14)
    from amw_core.exec_context import ExecContext


@runtime_checkable
class TaskWorker(Protocol):
    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        """Execute one task attempt and return its ``amw.task_output`` document."""
        ...
