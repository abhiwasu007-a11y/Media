"""Worker entry points of Agent 05 (03 section 1 rule 5, CCR-203; blueprint 10.1).

``ScriptDraftStage`` (``agent_05.script_draft``) and ``ShortsAdaptationStage``
(``agent_05.shorts_adaptation``) are the ``amw_core.interfaces.TaskWorker``: ``run(task_input,
ctx)`` validates the Task Input (03 section 7.1 order), checks that the ``ExecContext`` names the
same org, job, task and channel as the Task Input, loads the context references through an
``InputResolver``, runs the existing step and returns ``amw.task_output``. Every failure is
returned as a Task Output, never raised. The script document is written by the ``ScriptStore``
adapter as a task artifact (CCR-208); its values (``"hook"``, ``null``, CCR-202) are those of the
assembler, unchanged.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from agent_05_scriptwriter.contracts import (
    ScriptDraftInput,
    ShortsAdaptationInput,
)
from agent_05_scriptwriter.errors import InputInvalid, TenantMismatch
from agent_05_scriptwriter.protocols import StepContext
from agent_05_scriptwriter.steps.common import ResolvedInputs, StepOutcome
from agent_05_scriptwriter.steps.script_draft import ScriptDraftRequest, ScriptDraftStep
from agent_05_scriptwriter.steps.shorts import ShortsAdaptationStep, ShortsRequest
from agent_05_scriptwriter.task_output import build_error_output, build_task_output
from amw_core.contracts.error import violation
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.errors import (
    AmwError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    UnsupportedTaskError,
)
from amw_core.exec_context import ExecContext
from amw_core.interfaces import BlobStorage, Clock
from amw_core.interfaces.storage import BlobUri

AGENT = "agent_05"
SCRIPT_DRAFT_SCHEMA = "agent_05.script_draft.input"
SHORTS_SCHEMA = "agent_05.shorts_adaptation.input"
SCHEMA_VERSION = "1.0.0"


@runtime_checkable
class InputResolver(Protocol):
    """Loads and hash-verifies the context references of the task (blueprint 7.3, D-PRE-1..3).

    It reads only tenant-scoped URIs (or ``platform`` rule packs), verifies every SHA-256 and
    returns ``ResolvedInputs``; it raises the typed errors of blueprint 18 (``CrossTenantRef``,
    ``MissingDependency``, ``InputInvalid``).
    """

    def resolve(
        self,
        ctx: StepContext,
        task_input: TaskInput,
        data: ScriptDraftInput | ShortsAdaptationInput,
    ) -> ResolvedInputs: ...


def check_ctx(task_input: TaskInput, ctx: ExecContext) -> None:
    """The context and the Task Input must name the same org, job, task and channel (19.1)."""
    if (
        str(ctx.org_id) != task_input.org_id
        or str(ctx.job_id) != task_input.job_id
        or str(ctx.task_id) != task_input.task_id
        or (None if ctx.channel_id is None else str(ctx.channel_id)) != task_input.channel_id
    ):
        raise TenantMismatch("execution context does not match the Task Input")


class _Stage[D: (ScriptDraftInput, ShortsAdaptationInput)](ABC):
    payload_schema: str
    input_model: type[D]

    def __init__(self, resolver: InputResolver, storage: BlobStorage, clock: Clock) -> None:
        self._resolver = resolver
        self._storage = storage
        self._clock = clock

    @abstractmethod
    def _invoke(self, step_ctx: StepContext, data: D, resolved: ResolvedInputs) -> StepOutcome: ...

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        """``TaskWorker`` entry point; every failure is returned as a Task Output."""
        started = self._clock.monotonic_ms()
        try:
            check_ctx(task_input, ctx)
            data = self._validate(task_input, ctx)
            step_ctx = self._step_context(task_input, ctx)
            resolved = self._resolver.resolve(step_ctx, task_input, data)
            outcome = self._invoke(step_ctx, data, resolved)
        except AmwError as exc:
            return build_error_output(
                exc,
                actor=AGENT,
                correlation_id=task_input.correlation_id,
                now=self._clock.now(),
                duration_ms=self._clock.monotonic_ms() - started,
                attempt_no=ctx.attempt_no,
                currency=task_input.resource_budget.currency,
            )
        return build_task_output(
            outcome,
            step_ctx,
            now=self._clock.now(),
            duration_ms=self._clock.monotonic_ms() - started,
            attempt_no=ctx.attempt_no,
            currency=task_input.resource_budget.currency,
        )

    @staticmethod
    def _step_context(task_input: TaskInput, ctx: ExecContext) -> StepContext:
        if ctx.channel_id is None:
            raise InputInvalid(
                "agent_05 needs a channel",
                details={"violations": [violation("CHANNEL_MISSING", "/channel_id")]},
            )
        budget = task_input.resource_budget
        return StepContext(
            org_id=str(ctx.org_id),
            job_id=str(ctx.job_id),
            task_id=str(ctx.task_id),
            attempt_id=str(ctx.attempt_id),
            channel_id=str(ctx.channel_id),
            project_id=task_input.project_id,
            correlation_id=str(ctx.correlation_id),
            max_llm_calls=budget.max_llm_calls or 0,  # unset: no paid call (pre-check refuses)
            max_cost_micros=budget.max_cost_micros,
        )

    def _validate(self, task_input: TaskInput, ctx: ExecContext) -> D:
        """03 section 7.1 / blueprint 7.6: envelope, payload schema, version, then the payload."""
        if task_input.agent_id != AGENT:
            raise UnsupportedTaskError("task is not addressed to agent_05")
        payload = task_input.payload
        if payload.payload_schema != self.payload_schema:
            raise UnsupportedTaskError("payload schema is not this entry point's")
        if payload.payload_schema_version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise SchemaVersionUnsupportedError("payload schema version not supported")
        raw: Any = payload.data
        if raw is None:
            if payload.data_ref is None or payload.data_sha256 is None:
                raise SchemaInvalidError(
                    "payload carries neither data nor a data reference",
                    details={"violations": [violation("PAYLOAD_EMPTY", "/payload")]},
                )
            chunks = self._storage.get(ctx.tenant, BlobUri(payload.data_ref), payload.data_sha256)
            raw = json.loads(b"".join(chunks))
        try:
            return self.input_model.model_validate(raw)
        except ValidationError as exc:
            raise SchemaInvalidError(
                "input fails the schema",
                details={
                    "violations": [
                        violation(
                            str(e["type"]),
                            "/payload/data/" + "/".join(str(p) for p in e["loc"]),
                            str(e["msg"])[:200],
                        )
                        for e in exc.errors()[:50]
                    ]
                },
            ) from None


class ScriptDraftStage(_Stage[ScriptDraftInput]):
    """``agent_05.script_draft`` (stage ``s05_script``)."""

    payload_schema = SCRIPT_DRAFT_SCHEMA
    input_model = ScriptDraftInput

    def __init__(
        self, step: ScriptDraftStep, resolver: InputResolver, storage: BlobStorage, clock: Clock
    ) -> None:
        super().__init__(resolver, storage, clock)
        self._step = step

    def _invoke(
        self, step_ctx: StepContext, data: ScriptDraftInput, resolved: ResolvedInputs
    ) -> StepOutcome:
        return self._step.run(ScriptDraftRequest(step_ctx, data, resolved))


class ShortsAdaptationStage(_Stage[ShortsAdaptationInput]):
    """``agent_05.shorts_adaptation`` (stage ``s05_shorts``)."""

    payload_schema = SHORTS_SCHEMA
    input_model = ShortsAdaptationInput

    def __init__(
        self,
        step: ShortsAdaptationStep,
        resolver: InputResolver,
        storage: BlobStorage,
        clock: Clock,
    ) -> None:
        super().__init__(resolver, storage, clock)
        self._step = step

    def _invoke(
        self, step_ctx: StepContext, data: ShortsAdaptationInput, resolved: ResolvedInputs
    ) -> StepOutcome:
        return self._step.run(ShortsRequest(step_ctx, data, resolved))
