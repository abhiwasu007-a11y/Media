"""Input builders (CCR-203, ticket PASS6-B1): pure functions of ``BuildContext`` that produce the
payload of one Task Input per 3A task type. They are the ONLY code that builds a Task Input; they
import no agent package (the payload is plain data, validated by the registered model before the
worker runs) and never rewrite an upstream document: they pass references and facts.

A task type without a builder is refused (``PERMANENT.UNSUPPORTED_TASK``), never given a guess.
"""

from collections.abc import Mapping

from amw_core.errors import UnsupportedTaskError
from amw_orchestrator.executor import BuildContext, BuiltInput, InputBuilder
from amw_orchestrator.input_builders import agent_04


class BuilderTable:
    """``InputBuilder`` lookup by task type."""

    def __init__(self, extra: Mapping[str, InputBuilder] | None = None) -> None:
        self._by_type: dict[str, InputBuilder] = {
            "agent_04.research_pack": agent_04.ResearchPackBuilder(),
            **(extra or {}),
        }

    def task_types(self) -> frozenset[str]:
        return frozenset(self._by_type)

    def build(self, ctx: BuildContext) -> BuiltInput:
        builder = self._by_type.get(ctx.stage.task_type)
        if builder is None:
            raise UnsupportedTaskError(
                "no input builder for the task type", details={"task_type": ctx.stage.task_type}
            )
        return builder.build(ctx)
