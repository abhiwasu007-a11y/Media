"""The boundary between the code-controlled graph runner and the stage workers (CCR-203).

The runner (``amw_orchestrator.driver``) decides everything: order, gates, revisions, approvals,
budgets. A worker has exactly one entry point, ``amw_core.interfaces.TaskWorker.run(task_input,
ctx) -> TaskOutput`` (03 section 1 rule 5); this module holds no second worker contract. What it
adds is the orchestrator's side of the hand-off:

* an ``InputBuilder`` per task type turns the job facts and the upstream outputs into the payload
  of a ``TaskInput`` (the only code that builds one);
* ``TaskExecutor`` validates the input payload through the payload registry, builds the
  ``TaskInput`` and the ``ExecContext`` (stage and iteration from the task row), calls
  ``TaskWorker.run`` and validates the output payload again (03 section 5.3 rule 2a). A schema
  failure is ``PERMANENT.SCHEMA_INVALID`` / ``SCHEMA_VERSION_UNSUPPORTED`` (03 section 6 row 6),
  raised as a typed error; the runner turns every typed error into a failed Task Output.

An LLM never makes a control decision (directive section 2).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from amw_core.config import RulePackSettings, effective_non_finance_categories
from amw_core.contracts import (
    ContextRef,
    OwnerTopic,
    ResourceBudget,
    Stage,
    TaskInput,
    TaskOutput,
    ValidationResult,
)
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.payloads import (
    PAYLOAD_SCHEMAS,
    PayloadSchemaRegistry,
    load_payload_schema_plugins,
)
from amw_core.enums import OutputStatus, Priority, ProductionTypeKey
from amw_core.errors import AmwError, MissingDependencyError, SchemaInvalidError
from amw_core.exec_context import ExecContext
from amw_core.interfaces import TaskWorker
from amw_orchestrator.outputs import SpendLike, failed_output


class ChannelCategory(StrEnum):
    """CCR-273 (PROPOSED): ``finance`` / ``non-finance``. The finance-only gates (FIN-R1..R13,
    FIN-R10, the price-data lag, the finance icon rules) apply only to ``FINANCE``."""

    FINANCE = "finance"
    NON_FINANCE = "non_finance"


_NON_FINANCE_LABELS = frozenset({"non_finance", "non-finance"})


def resolve_channel_category(
    raw: object, rule_packs: RulePackSettings | None = None
) -> ChannelCategory:
    """Fail closed (CCR-273 item 4): only an explicit non-finance label, or a documented
    non-finance channel category of the validated rule-pack config (``rule_packs`` is a
    ``RulePackSettings``: packaged data or its narrowing-only override; exact match, PASS6-N),
    skips the finance rules. ``None``, an empty or non-str value, an unknown value, ``finance`` and
    the advertising categories are FINANCE. The category set is never a caller-built collection:
    anything that is not a ``RulePackSettings`` gives FINANCE for every value, and the set is
    intersected with the packaged list (``effective_non_finance_categories``), so no value of the
    set can make ``finance`` non-finance."""
    if not isinstance(raw, str):
        return ChannelCategory.FINANCE
    if rule_packs is None:
        rule_packs = RulePackSettings()
    if not isinstance(rule_packs, RulePackSettings):
        return ChannelCategory.FINANCE
    allowed = effective_non_finance_categories(rule_packs.non_finance_categories)
    if raw.strip().lower() in _NON_FINANCE_LABELS or raw in allowed:
        return ChannelCategory.NON_FINANCE
    return ChannelCategory.FINANCE


@dataclass(frozen=True, slots=True)
class DocRef:
    """A stored document by reference: tenant-scoped URI and the SHA-256 of its bytes."""

    uri: str
    sha256: str


@dataclass(frozen=True, slots=True)
class RulePackDoc:
    """One active rule pack at its version (24 ``rule_packs``): its row ID, version and document."""

    rule_pack_id: str
    version: int
    doc: DocRef


@dataclass(frozen=True, slots=True)
class JobDocuments:
    """Job-level documents and facts that are neither job columns nor stage outputs (CCR-278
    PROPOSED): the brand kit, the compliance profile, the rule packs, the disclaimer template, the
    voice and its pronunciation dictionary, the uniqueness template. Job intake fills them from
    the channel, the brand kit and the voice rows; a builder that needs one that is absent refuses
    with ``MISSING_DEPENDENCY`` (fail closed), it never invents a value."""

    brand_kit: DocRef | None = None
    compliance_profile: DocRef | None = None
    rule_packs: Mapping[str, RulePackDoc] = field(default_factory=dict)
    """Rule pack key (``rp.youtube_general``, ...) -> the pack."""
    disclaimer_template: DocRef | None = None
    voice_id: str | None = None
    voice_dictionary: DocRef | None = None
    uniqueness_template: DocRef | None = None


@dataclass(frozen=True, slots=True)
class JobFacts:
    """What the builders may know about the job (IDs are wire IDs)."""

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
    channel_category: ChannelCategory = ChannelCategory.FINANCE
    """Fail-closed default: a job built without an explicit category is a finance job."""
    documents: JobDocuments = field(default_factory=JobDocuments)

    @property
    def finance_rules_apply(self) -> bool:
        return self.channel_category is ChannelCategory.FINANCE


@runtime_checkable
class BuildServices(Protocol):
    """What a builder may read besides the job facts and the upstream outputs (never a worker).

    ``read_json`` is a hash-verified read of a stored document (a typed error when it is missing
    or does not match); ``cost_report`` and ``delivery_facts`` are the S4 ledger report of the job
    and the policy values of the delivery bundle (banner, disclaimer text, limits), which belong
    to the runtime lane and are never decided here."""

    def read_json(self, uri: str, sha256: str) -> Mapping[str, Any]: ...

    def payload_document(self, job: JobFacts, output: TaskOutput) -> DocRef: ...

    # ``payload_document``: the payload of an upstream output as a write-once document (verbatim,
    # never rewritten) for a consumer whose contract reads a producer's payload by reference
    # (agent_10 section 7.1, CCR-279 PROPOSED).

    def cost_report(self, job: JobFacts) -> Mapping[str, Any]: ...

    def delivery_facts(self, job: JobFacts) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BuildContext:
    """Everything an input builder reads: the job, the stage and its task row, the latest
    ``COMPLETED`` output per stage (a child job: also ``parent.<id>``), and the revision facts."""

    job: JobFacts
    stage: Stage
    task_id: str
    iteration: int
    attempt_no: int
    idempotency_key: str
    resource_budget: ResourceBudget
    upstream: Mapping[str, TaskOutput]
    upstream_task_ids: Mapping[str, str] = field(default_factory=dict)
    prior_output: TaskOutput | None = None
    """The previous iteration's output of this stage (24 section 3.3 rule 6, ``PRIOR_OUTPUT``)."""
    revision_feedback: tuple[ValidationResult, ...] = ()
    revision_source_stage_id: str | None = None
    services: BuildServices | None = None

    def upstream_output(self, stage_id: str) -> TaskOutput:
        out = self.upstream.get(stage_id)
        if out is None:
            raise MissingDependencyError(
                "upstream output missing", details={"stage_id": stage_id[:64]}
            )
        return out

    def upstream_data(self, stage_id: str) -> dict[str, Any]:
        out = self.upstream_output(stage_id)
        if out.payload is None or out.payload.data is None:
            raise MissingDependencyError(
                "upstream payload is stored by reference", details={"stage_id": stage_id[:64]}
            )
        return dict(out.payload.data)


@dataclass(frozen=True, slots=True)
class BuiltInput:
    """The payload of one Task Input (03 section 3): schema name, version, inline data and the
    context refs. The executor validates ``data`` against the registered model."""

    payload_schema: str
    payload_schema_version: str
    data: Mapping[str, Any]
    context_refs: tuple[ContextRef, ...] = ()
    priority: Priority = Priority.NORMAL


@runtime_checkable
class InputBuilder(Protocol):
    def build(self, ctx: BuildContext) -> BuiltInput: ...


@runtime_checkable
class WorkerRegistry(Protocol):
    """Worker and input builder per task type (``MissingDependencyError`` when none)."""

    def worker_for(self, stage: Stage) -> TaskWorker: ...

    def builder_for(self, stage: Stage) -> InputBuilder: ...


class ApprovalDesk(Protocol):
    """S7 boundary: open the approval request and report the owner's decision.

    ``decision`` returns ``None`` while no confirmed owner evidence (R14) exists, else the
    approval payload (``state`` APPROVED / REJECTED / CHANGES_REQUESTED, approval and evidence
    IDs). ``decided`` is the cheap check the runner makes before it resumes a parked task."""

    def open(self, task_input: TaskInput, ctx: ExecContext) -> Mapping[str, object]: ...

    def decision(self, task_input: TaskInput, ctx: ExecContext) -> Mapping[str, object] | None: ...

    def decided(self, job_id: str, task_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class PreparedTask:
    task_input: TaskInput
    ctx: ExecContext
    worker: TaskWorker


BlobReader = Callable[[str, str], Mapping[str, Any]]
"""``(data_ref, data_sha256) -> parsed JSON`` for payloads stored by reference."""


class TaskExecutor:
    """Build, validate, ``TaskWorker.run``, validate (one attempt: ``prepare`` then ``run``)."""

    def __init__(
        self,
        workers: WorkerRegistry,
        *,
        schemas: PayloadSchemaRegistry = PAYLOAD_SCHEMAS,
        blob_reader: BlobReader | None = None,
        load_plugins: Callable[[PayloadSchemaRegistry], tuple[str, ...]] | None = None,
    ) -> None:
        self._workers, self._schemas, self._blob = workers, schemas, blob_reader
        # start-up: the agents' payload models register through the allow-listed loader; any
        # failure is a ConfigInvalidError, so validation is never silently disabled (27 sec 7.3).
        # ``load_plugins`` lets a test substitute stand-in models for ``schemas``; an empty
        # registry still refuses every payload (fail closed), so it cannot weaken production.
        loader = load_plugins if load_plugins is not None else load_payload_schema_plugins
        self.plugins: tuple[str, ...] = loader(schemas)

    def _payload_data(self, payload: PayloadObject) -> Mapping[str, Any]:
        if payload.data is not None:
            return payload.data
        if self._blob is None or payload.data_ref is None or payload.data_sha256 is None:
            # fail closed: a payload nobody can read is never trusted (27 section 7.3)
            raise SchemaInvalidError(
                "payload stored by reference cannot be read for validation",
                details={"schema": payload.payload_schema},
            )
        return self._blob(payload.data_ref, payload.data_sha256)

    def validate_payload(self, payload: PayloadObject) -> None:
        self._schemas.validate(
            payload.payload_schema, payload.payload_schema_version, self._payload_data(payload)
        )

    def prepare(self, bc: BuildContext, attempt_id: str) -> PreparedTask:
        stage = bc.stage
        built = self._workers.builder_for(stage).build(bc)
        job = bc.job
        agent = stage.task_type.split(".", 1)[0]
        task_input = TaskInput.model_validate(
            {
                "org_id": job.org_id,
                "job_id": job.job_id,
                "task_id": bc.task_id,
                "project_id": job.project_id,
                "channel_id": job.channel_id,
                "agent_id": agent,
                "source_agent": "agent_01",
                "priority": built.priority.value,
                "deadline": None,
                "context_refs": [
                    r.model_dump(mode="json", by_alias=True) for r in built.context_refs
                ],
                "resource_budget": bc.resource_budget.model_dump(mode="json"),
                "payload": {
                    "payload_schema": built.payload_schema,
                    "payload_schema_version": built.payload_schema_version,
                    "data": dict(built.data),
                },
                "correlation_id": job.correlation_id,
                "idempotency_key": bc.idempotency_key,
                "retry_count": bc.attempt_no - 1,
                "schema_version": "1.0.0",
            }
        )
        self.validate_payload(task_input.payload)
        ctx = ExecContext.from_task_input(
            task_input,
            attempt_id,
            agent,
            envelope_org_id=job.org_id,
            stage_id=stage.stage_id,
            iteration=bc.iteration,
        )
        return PreparedTask(task_input, ctx, self._workers.worker_for(stage))

    def run(self, prepared: PreparedTask, spend: Sequence[SpendLike] = ()) -> TaskOutput:
        """``TaskWorker.run`` plus the 03 section 5.3 rule 2a payload check of the output.

        Typed errors raised by the worker propagate to the runner (it reports them with the real
        spend of the attempt). An output whose payload fails its schema is returned as a FAILED
        output that keeps the worker's own ``resource_usage`` (the money was spent)."""
        output = prepared.worker.run(prepared.task_input, prepared.ctx)
        if output.status is OutputStatus.SUCCEEDED:
            try:
                if output.payload is None:  # TaskOutput already refuses this; explicit guard
                    raise SchemaInvalidError("a succeeded output carries no payload")
                self.validate_payload(output.payload)
            except AmwError as exc:
                return failed_output(
                    exc,
                    actor=prepared.task_input.agent_id,
                    attempt_no=prepared.ctx.attempt_no,
                    correlation_id=prepared.task_input.correlation_id,
                    usage=output.resource_usage,
                )
        return output


class ApprovalWorker:
    """``svc_s07.request_approval`` as a ``TaskWorker`` over the ``ApprovalDesk`` boundary:
    SUSPENDED (``AWAITING_APPROVAL``) until the desk reports R14-backed evidence, then SUCCEEDED
    with the approval payload. It never infers a decision."""

    def __init__(self, desk: ApprovalDesk, clock: Callable[[], str]) -> None:
        self._desk, self._clock = desk, clock

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        decided = self._desk.decision(task_input, ctx)
        if decided is None:
            return _approval_output(
                "SUSPENDED", dict(self._desk.open(task_input, ctx)), self._clock()
            )
        return _approval_output("SUCCEEDED", dict(decided), self._clock())


def _approval_output(status: str, data: dict[str, object], stamp: str) -> TaskOutput:
    waiting = status == "SUSPENDED"
    return TaskOutput.model_validate(
        {
            "status": status,
            "payload": {
                "payload_schema": "svc_s07.request_approval.output",
                "payload_schema_version": "1.0.0",
                "data": data,
            },
            "output_refs": [],
            "quality_score": None,
            "confidence": None,
            "validation_results": [],
            "duration": 0,
            "resource_usage": {
                "cpu_ms": 0,
                "peak_rss_bytes": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_cached_in": 0,
                "llm_calls": 0,
                "provider_calls": 0,
                "cost_estimate_micros": 0,
                "currency": "USD",
                "cost_entry_ids": [],
            },
            "error": None,
            "next_action": {
                "type": "WAIT" if waiting else "CONTINUE",
                "wait_reason": "AWAITING_APPROVAL" if waiting else None,
                "escalation_level": None,
                "reason": "waiting for the owner's decision"
                if waiting
                else "owner decision recorded with R14 evidence",
            },
            "downstream_agent": None,
            "timestamp": stamp,
        }
    )
