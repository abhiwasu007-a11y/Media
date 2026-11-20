"""Production worker wiring of a REAL_RUN (``ProductionWiring``, the default ``RealRunWiring``).

What it does, in order, once the sealed preflight has passed and the providers were built from it:

1. ``PortSet``: the ports this lane CAN build from real adapters and database adapters. The LLM and
   TTS ports are the adapters of ``ctx.providers`` (they exist only behind the sealed preflight
   authorisation, never built here; the Anthropic adapter reads ``AMW_SECRET_ANTHROPIC_API_KEY`` at
   call time); the database ports are the PostgreSQL adapters of this package and ``amw_core``; the
   storage is the ``LocalDiskStorage`` of the composition root (core path builders); clock, ids,
   cost ledger, budget guard (per-video hard stop), checkpoints and idempotency are the core ones.
2. ``WorkerSpec`` per agent task type: the constructor parameters of the agent's own entry point(s)
   (read from the classes themselves, so a new parameter of an agent shows up here by itself).
   Every parameter that has no provider in the ``PortSet`` is listed as ``<task_type>:<name>``.
3. Any such port makes the REAL run refuse with ``MissingDependencyError`` (``MISSING_DEPENDENCY``)
   listing exactly those ports in ``details["unmet"]``: fail closed, no fake, no stand-in worker, no
   silent fallback. Nothing is called and nothing is spent.

When no port is missing the workers are built lazily (``LazyRealWorker``: on its first Task Input,
with the tenant taken from that input) by the spec's factory; a spec without a factory refuses
too. The ports that are missing today are those no production implementation exists for in this
repository (inventory, not a verdict on what the agents need in the end).
"""

import dataclasses
import inspect
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

from agent_04_research_knowledge.steps.research_pack import StepDeps as Agent04Deps
from agent_05_scriptwriter import ScriptDraftStage, ScriptDraftStep
from agent_05_scriptwriter.protocols import Ports as Agent05Ports
from agent_06_fact_checker.extraction_step import ClaimExtractionStep
from agent_06_fact_checker.library.reader import LibraryRef
from agent_06_fact_checker.verification_step import ClaimVerificationStep
from agent_07_voice_production.master_stage import MasterDeps
from agent_07_voice_production.voice_stage import VoiceDeps
from agent_08_visual_assets.stage import AssetSourcingStage
from agent_09_video_director.protocol import ShotPlanTask
from agent_09_video_director.step import ShotPlanStep
from agent_10_video_editor.deps import StageDeps as Agent10Deps
from agent_11_thumbnail_design.stage import StageDeps as Agent11Deps
from agent_16_compliance_qa.scoring.stage import ScoreStageDeps
from agent_16_compliance_qa.stages import GateStageDeps, UniquenessStageDeps
from amw_core.audit.pg import PgAuditLog
from amw_core.checkpoint_store import PgCheckpointStore
from amw_core.contracts import Stage, TaskInput, TaskOutput
from amw_core.errors import ConfigInvalidError, MissingDependencyError
from amw_core.exec_context import ExecContext
from amw_core.idempotency_store import PgIdempotencyStore
from amw_core.ids import new_id
from amw_core.interfaces import TaskWorker
from amw_orchestrator.db_adapters import (
    PgFactRowReader,
    PgJobDestinationReader,
    PgScoreStore,
    PgScriptRowPort,
)
from amw_orchestrator.executor import (
    ApprovalWorker,
    BuildServices,
    JobDocuments,
    JobFacts,
    WorkerRegistry,
)
from amw_orchestrator.input_builders import BuilderTable

if TYPE_CHECKING:  # composition imports this module; the context type is only needed for typing
    from amw_core.contracts.payloads import PayloadSchemaRegistry
    from amw_orchestrator.composition import WiringContext

APPROVAL_TASK_TYPE: Final = "svc_s07.request_approval"
DELIVERY_TASK_TYPE: Final = "agent_13.file_delivery"
_SKIP_COMPOSED: Final = frozenset({"self", "step", "ports"})
"""Parameters that are built from other parameters of the same spec (a step, the ports bundle)."""

_ALIASES: Final[Mapping[str, str]] = {
    "llm": "llm",
    "tts": "tts",
    "tenancy": "tenancy",
    "storage": "storage",
    "blobs": "storage",
    "clock": "clock",
    "budget": "budget_guard",
    "ledger": "cost_ledger",
    "costs": "cost_ledger",
    "cost_ledger": "cost_ledger",
    "audit": "audit",
    "idempotency": "idempotency",
    "idem": "idempotency",
    "checkpoints": "checkpoints",
    "rows": "fact_rows",
    "store": "score_store",
    "job_destinations": "job_destination",
}
"""Parameter name of an agent entry point to the port id this lane provides for it."""

_TASK_ALIASES: Final[Mapping[tuple[str, str], str]] = {
    ("agent_05.script_draft", "scripts"): "script_rows",
}

_EXTRA_REQUIRED: Final[Mapping[str, tuple[str, ...]]] = {
    # optional in the signature, but fail closed (CCR-302, #117): a quote claim with no quote check
    # ends in a typed MISSING_DEPENDENCY, so the real run needs the factory
    "agent_06.claim_verification": ("quotes",),
    # optional in the signature; without it agent_08 cannot read the brand kit / destination
    "agent_08.asset_sourcing": ("brand_kits", "job_destinations"),
}
_EXTRA_ALIASES: Final[Mapping[tuple[str, str], str]] = {
    ("agent_06.claim_verification", "quotes"): "quote_check_factory",
    ("agent_08.asset_sourcing", "brand_kits"): "brand_kit_reader",
}

_TARGETS: Final[Mapping[str, tuple[type, ...]]] = {
    "agent_04.research_pack": (Agent04Deps,),
    "agent_05.script_draft": (Agent05Ports, ScriptDraftStep, ScriptDraftStage),
    "agent_06.claim_extraction": (ClaimExtractionStep,),
    "agent_06.claim_verification": (ClaimVerificationStep,),
    "agent_07.voice_synthesis": (VoiceDeps,),
    "agent_07.audio_master": (MasterDeps,),
    "agent_08.asset_sourcing": (AssetSourcingStage,),
    "agent_09.shot_plan": (ShotPlanStep, ShotPlanTask),
    "agent_10.render": (Agent10Deps,),
    "agent_10.subtitles": (Agent10Deps,),
    "agent_10.technical_qc": (Agent10Deps,),
    "agent_11.thumbnail_variants": (Agent11Deps,),
    "agent_16.compliance_gate": (GateStageDeps,),
    "svc_s02.uniqueness_check": (UniquenessStageDeps,),
    "agent_16.quality_score": (ScoreStageDeps,),
}
"""The 15 agent task types of the graph and the classes that take their ports."""

AGENT_TASK_TYPES: Final = tuple(sorted(_TARGETS))


def required_parameters(cls: type) -> tuple[str, ...]:
    """The parameters of ``cls`` that have no default (a dataclass: its fields)."""
    if dataclasses.is_dataclass(cls):
        names = [
            f.name
            for f in dataclasses.fields(cls)
            if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        ]
    else:
        params = inspect.signature(cls.__init__).parameters.values()  # type: ignore[misc]
        names = [
            p.name
            for p in params
            if p.default is inspect.Parameter.empty
            and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        ]
    return tuple(n for n in names if n not in _SKIP_COMPOSED)


class TenantRef(Protocol):
    org_id: str
    job_id: str


WorkerFactory = Callable[["PortSet", TaskInput], TaskWorker]
"""``(ports, first task input) -> worker``: the production factory of one agent (tenant from the
input, never a guess)."""


@dataclass(frozen=True)
class WorkerSpec:
    task_type: str
    parameters: tuple[str, ...]
    factory: WorkerFactory | None = None

    def unmet(self, provided: Mapping[str, Any]) -> tuple[str, ...]:
        """Parameters of this worker without a provider, as ``<task_type>:<name>``."""
        missing: list[str] = []
        for name in self.parameters:
            port = (
                _TASK_ALIASES.get((self.task_type, name))
                or _EXTRA_ALIASES.get((self.task_type, name))
                or _ALIASES.get(name)
            )
            if port is None or port not in provided:
                missing.append(f"{self.task_type}:{name}")
        return tuple(missing)


def worker_specs(factories: Mapping[str, WorkerFactory] | None = None) -> dict[str, WorkerSpec]:
    """One spec per agent task type; ``factories`` carries the production factories (none yet)."""
    out: dict[str, WorkerSpec] = {}
    for task_type, classes in _TARGETS.items():
        names: list[str] = []
        for cls in classes:
            for name in required_parameters(cls):
                if name not in names:
                    names.append(name)
        for name in _EXTRA_REQUIRED.get(task_type, ()):
            if name not in names:
                names.append(name)
        out[task_type] = WorkerSpec(task_type, tuple(names), (factories or {}).get(task_type))
    return out


class _SystemClock:
    """The production ``Clock``."""

    def now(self) -> Any:
        from datetime import UTC, datetime

        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        import time

        return int(time.monotonic() * 1000)


@dataclass(frozen=True)
class PortSet:
    """The ports this lane built, by port id. Everything else is unmet (never faked)."""

    ports: Mapping[str, Any]
    library: LibraryRef | None = None

    def __contains__(self, name: str) -> bool:
        return name in self.ports

    def get(self, name: str) -> Any:
        try:
            return self.ports[name]
        except KeyError:
            raise MissingDependencyError(
                "a port the worker needs is not wired", details={"unmet": [name]}
            ) from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.ports))


def build_port_set(ctx: WiringContext, approval: ApprovalWorker | None = None) -> PortSet:
    """Build every port that has a real implementation. Refuses unless the providers are the real
    ones of a passed preflight (``ctx.providers.real``): a fake LLM or TTS must never be taken for a
    real run's port."""
    if not ctx.providers.real:
        raise ConfigInvalidError("the real wiring needs the providers of a passed preflight")
    clock = _SystemClock()
    audit = PgAuditLog()
    idempotency = PgIdempotencyStore()
    lock_ms = ctx.run.score_lock_ms  # its own config key (CCR-304); seeded equal to the lease
    ports: dict[str, Any] = {
        "llm": ctx.providers.llm,
        "tts": ctx.providers.tts,
        "storage": ctx.storage,
        "tenancy": ctx.tenancy,
        "clock": clock,
        "ids": new_id,
        "budget_guard": ctx.guard,
        "cost_ledger": ctx.ledger,
        "audit": audit,
        "idempotency": idempotency,
        "checkpoints": PgCheckpointStore(),
        "script_rows": PgScriptRowPort(ctx.tenancy, audit, clock),
        "job_destination": PgJobDestinationReader(),
        "fact_rows": PgFactRowReader(),
        "score_store": PgScoreStore(clock, idempotency, lock_ms=lock_ms),
    }
    if approval is not None:
        ports["approval_worker"] = approval
    library = LibraryRef(ctx.request.library.repo_path, ctx.request.library.commit_sha)
    ports["library_ref"] = library
    return PortSet(ports, library)


class LazyRealWorker:
    """Builds the production worker on its first Task Input (tenant from the input) and keeps it."""

    def __init__(self, spec: WorkerSpec, ports: PortSet) -> None:
        if spec.factory is None:
            raise MissingDependencyError(
                "no production factory for this worker", details={"unmet": [spec.task_type]}
            )
        self._spec, self._ports = spec, ports
        self._worker: TaskWorker | None = None
        self._lock = threading.Lock()

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        with self._lock:
            if self._worker is None:
                assert self._spec.factory is not None  # noqa: S101 - checked in __init__
                self._worker = self._spec.factory(self._ports, task_input)
            worker = self._worker
        return worker.run(task_input, ctx)


@dataclass
class RealRegistry:
    """Worker per task type of a real run: the real approval worker, the real delivery stage (when
    supplied) and one ``LazyRealWorker`` per agent. A task type with none is refused."""

    workers: Mapping[str, TaskWorker]
    table: BuilderTable = field(default_factory=BuilderTable)

    def worker_for(self, stage: Stage) -> TaskWorker:
        worker = self.workers.get(stage.task_type)
        if worker is None:
            raise MissingDependencyError(
                "no worker wired for this task type", details={"unmet": [stage.task_type]}
            )
        return worker

    def builder_for(self, stage: Stage) -> BuilderTable:
        return self.table


def unmet_ports(specs: Mapping[str, WorkerSpec], ports: PortSet) -> list[str]:
    out: list[str] = []
    for spec in specs.values():
        out += spec.unmet(ports.ports)
    return sorted(out)


class ProductionWiring:
    """``RealRunWiring`` of the production composition root. Fails closed on every missing port."""

    def __init__(
        self,
        factories: Mapping[str, WorkerFactory] | None = None,
        *,
        delivery_scratch: Path | None = None,
    ) -> None:
        self._specs = worker_specs(factories)
        self._scratch = delivery_scratch
        self.last_ports: PortSet | None = None

    def registry(self, ctx: WiringContext, approval: ApprovalWorker) -> WorkerRegistry:
        ports = build_port_set(ctx, approval)
        self.last_ports = ports
        unmet = unmet_ports(self._specs, ports)
        if unmet:
            raise MissingDependencyError(
                f"the real run cannot start: {len(unmet)} port(s) have no production wiring",
                details={"unmet": unmet, "provided": list(ports.names())},
            )
        lacking = sorted(s.task_type for s in self._specs.values() if s.factory is None)
        if lacking:
            raise MissingDependencyError(
                "every port exists but the production worker factories are not built",
                details={"unmet": [f"factory:{t}" for t in lacking]},
            )
        workers: dict[str, TaskWorker] = {
            t: LazyRealWorker(s, ports) for t, s in self._specs.items()
        }
        workers[APPROVAL_TASK_TYPE] = approval
        return RealRegistry(workers)

    def schemas(self) -> PayloadSchemaRegistry:
        from amw_core.contracts.payloads import PayloadSchemaRegistry

        return PayloadSchemaRegistry()  # the executor loads the agents' payload plugins into it

    def job_documents(self, ctx: WiringContext, job: JobFacts) -> JobDocuments:
        raise MissingDependencyError(
            "the job documents (brand kit, compliance profile, voice, dictionary, uniqueness "
            "template) have no production reader",
            details={"unmet": ["job_documents"]},
        )

    def build_services(self, ctx: WiringContext) -> BuildServices:
        raise MissingDependencyError(
            "the build services (document reader, cost report, delivery policy) are not wired",
            details={"unmet": ["build_services"]},
        )


def summarize(unmet: Sequence[str]) -> dict[str, list[str]]:
    """``{task_type: [parameter, ...]}`` of ``<task_type>:<name>`` entries (for reports)."""
    out: dict[str, list[str]] = {}
    for item in unmet:
        task, _, name = item.partition(":")
        out.setdefault(task, []).append(name)
    return out
