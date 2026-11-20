"""Production composition root of the 3A graph runner (the one place that builds a ``GraphRunner``).

Everything operational comes from configuration: ``amw_core`` settings (database URL, storage
root, limits, per-stage cost budgets), the ``amw_runtime`` config (mode, caps, calendar,
providers) and the seeded ``run_entry.json``. Nothing is a literal here.

The run mode is ``RuntimeConfig.mode`` and nothing else. ``real_run`` is derived from it
(``mode is not DRY_RUN``: anything but an explicit dry run is real, fail closed) and never read
from the job request, the caller or an argument.

DRY_RUN builds the fake providers (no key is read, no socket opened), the stand-in workers, the
test approval desk and TEST_FIXTURE evidence of ``plumbing`` and a ``GraphRunner`` with
``real_run=False``. PLUMBING TEST - NOT QUALITY.

REAL_RUN builds nothing before the sealed preflight passes: ``run_job_preflight`` (every unmet
item listed, ``PreflightRefused``), then ``build_providers`` (real adapters only from that report,
secrets by NAME), then the approval desk and ``PgApprovalEvidencePort`` of the database, and a
``GraphRunner`` with ``real_run=True``. The worker registry of the real agents is not built here:
it comes from a ``RealRunWiring`` the caller supplies, and without one a passed preflight still
ends in a ``MISSING_DEPENDENCY`` naming ``REAL_WIRING`` (honest: no production worker wiring
exists yet).

Tenant isolation: every database access goes through ``PgTenancy`` transactions of the job's org
(explicit org filters in the callees, RLS as the second line); the approval desk and its evidence
port are bound to the request's org and refuse another tenant's task.
"""

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import psycopg

from amw_adapters.real.guard import BudgetCallGuard
from amw_core.audit.pg import PgAuditLog
from amw_core.budget_guard import BudgetGuardCore
from amw_core.budget_guard.pg import PgBudgetBackend
from amw_core.config import AmwSettings
from amw_core.contracts import Stage, violation
from amw_core.contracts.payloads import PayloadSchemaRegistry
from amw_core.cost.pg import PgCostLedger
from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError
from amw_core.ids import CORRELATION, ActorRef, JobId, OrgId
from amw_core.interfaces import TenancyContext, TenantContext
from amw_core.interfaces.owner_evidence import DbRole
from amw_core.job_store.pg import PgJobStore
from amw_core.owner_evidence_approvals import ApprovalEvidencePort
from amw_core.owner_evidence_pg import PgDbSession, PgEvidenceDatabase
from amw_core.owner_evidence_real import ConfirmedEvidenceLookup, EvidenceMode
from amw_core.owner_evidence_status import EvidenceStatusLookup
from amw_core.queue.pg import PgTaskQueue
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy import PgTenancy, dsn_connection_factory
from amw_orchestrator.approval_desk import PgApprovalDesk
from amw_orchestrator.driver import GraphRunner, RunnerConfig
from amw_orchestrator.executor import (
    ApprovalDesk,
    ApprovalWorker,
    BuildServices,
    JobDocuments,
    JobFacts,
    TaskExecutor,
    WorkerRegistry,
)
from amw_orchestrator.outputs import now_z
from amw_orchestrator.plumbing import (
    DryRunDesk,
    PlumbingServices,
    build_plumbing_registry,
    plumbing_schemas,
    seed_job_documents,
)
from amw_orchestrator.registry import job_graph, record
from amw_orchestrator.run_request import JobRequest
from amw_orchestrator.run_settings import RunEntrySettings
from amw_orchestrator.services import (
    PgMeter,
    StageBudgets,
    intake,
    job_create_key,
    require_per_video_budget,
    run_job_preflight,
)
from amw_orchestrator.task_io import TaskIo
from amw_orchestrator.workers import read_workers
from amw_runtime.calendar import MarketCalendar
from amw_runtime.config import RunMode, RuntimeConfig
from amw_runtime.confirmations import ConfirmationRecord
from amw_runtime.preflight import PreflightReport
from amw_runtime.providers import ProviderSet, build_providers

_MS_PER_SECOND = 1000

EvidenceFactory = Callable[
    [TenancyContext, str, Sequence[ConfirmationRecord]],
    AbstractContextManager[EvidenceStatusLookup],
]
"""``(tenancy, org_id, confirmations) -> evidence lookup`` for the preflight of a real run."""


@dataclass(frozen=True, slots=True)
class WiringContext:
    """What a real worker wiring may use: the providers the preflight authorised, the tenant
    plumbing, and the library reference (path + commit SHA only; the text is read by the agent that
    needs it, never here)."""

    providers: ProviderSet
    storage: LocalDiskStorage
    tenancy: TenancyContext
    meter: PgMeter
    settings: AmwSettings
    config: RuntimeConfig
    request: JobRequest


class RealRunWiring(Protocol):
    def registry(self, ctx: WiringContext, approval: ApprovalWorker) -> WorkerRegistry: ...

    def schemas(self) -> PayloadSchemaRegistry: ...

    def job_documents(self, ctx: WiringContext, job: JobFacts) -> JobDocuments: ...

    def build_services(self, ctx: WiringContext) -> BuildServices: ...


@dataclass
class Composition:
    mode: RunMode
    real_run: bool
    runner: GraphRunner
    job: JobFacts
    graph: tuple[Stage, ...]
    providers: ProviderSet
    desk: DryRunDesk | None
    """The dry-run desk; ``None`` in a real run (the owner decides in chat, never this process)."""
    preflight: PreflightReport | None
    notes: list[str] = field(default_factory=list)
    resume: bool = False
    """True when the job already has tasks (a second call resumes it instead of starting it)."""


@dataclass(frozen=True, slots=True)
class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        return int(time.monotonic() * _MS_PER_SECOND)


@dataclass(frozen=True, slots=True)
class Infrastructure:
    tenancy: PgTenancy
    jobs: PgJobStore
    queue: PgTaskQueue
    guard: BudgetGuardCore
    ledger: PgCostLedger
    storage: LocalDiskStorage
    connections: Callable[[], AbstractContextManager[Any]]


def _dsn(settings: AmwSettings) -> str:
    url = settings.database.url
    if url is None:
        raise ConfigInvalidError("no database URL configured", details={"fields": ["database.url"]})
    return url.get_secret_value()


def _storage_root(settings: AmwSettings) -> Path:
    if settings.storage.backend != "local" or settings.storage.root is None:
        raise ConfigInvalidError(
            "the run entry point needs the local storage backend with a root",
            details={"fields": ["storage.backend", "storage.root"]},
        )
    return settings.storage.root


def build_infrastructure(
    settings: AmwSettings, run: RunEntrySettings, config: RuntimeConfig
) -> Infrastructure:
    connections = dsn_connection_factory(_dsn(settings), role=run.database_role)
    tenancy = PgTenancy(connections)
    audit = PgAuditLog()
    jobs = PgJobStore(audit, max_tasks_per_job=settings.limits.max_tasks_per_job)
    queue = PgTaskQueue(connections)
    exponents = {**config.currency_minor_exponent, **settings.finance.currency_minor_exponent}
    effective = settings.model_copy(
        update={
            "finance": settings.finance.model_copy(update={"currency_minor_exponent": exponents})
        }
    )
    guard = BudgetGuardCore(PgBudgetBackend(), effective, _Clock(), audit)
    return Infrastructure(
        tenancy, jobs, queue, guard, PgCostLedger(), LocalDiskStorage(_storage_root(settings)),
        connections,
    )  # fmt: skip


@contextmanager
def _pg_confirmation_evidence(
    tenancy: TenancyContext, org_id: str, confirmations: Sequence[ConfirmationRecord]
) -> Iterator[EvidenceStatusLookup]:
    """The production evidence lookup of the preflight: owner confirmations read from the evidence
    store inside one tenant transaction. ``allowed_kinds`` stays empty (CCR-260: no record kind
    exists yet for these statements), so every confirmation is refused with its own item until the
    contract decides (fail closed)."""
    with tenancy.transaction(TenantContext(OrgId(org_id), ActorRef("sys_operator"))) as tx:
        yield ConfirmedEvidenceLookup.for_confirmations(
            PgEvidenceDatabase(), PgDbSession(DbRole.APP), tx, confirmations
        )


def _loader_for(
    schemas: PayloadSchemaRegistry,
) -> Callable[[PayloadSchemaRegistry], tuple[str, ...]] | None:
    """An empty registry gets the agents' payload plugins (the executor's own loader); a registry
    the caller already filled is complete as given (the plumbing one, a test wiring's)."""
    if not schemas.names():
        return None
    return lambda _registry: ()


def _runner(
    infra: Infrastructure,
    *,
    job_type_graph: tuple[Stage, ...],
    run: RunEntrySettings,
    settings: AmwSettings,
    config: RuntimeConfig,
    registry: WorkerRegistry,
    schemas: PayloadSchemaRegistry,
    desk: ApprovalDesk,
    meter: PgMeter,
    evidence: ApprovalEvidencePort | None,
    real_run: bool,
    build_services: BuildServices,
    clock: Callable[[], datetime] | None,
) -> GraphRunner:
    workers, capabilities = read_workers(
        infra.connections,
        sorted({s.resource_class for s in job_type_graph}, key=lambda r: r.value),
        run.worker_statuses,
        run.worker_name_prefix,
    )
    extra: dict[str, Any] = {} if clock is None else {"clock": clock}
    runner = GraphRunner(
        tenancy=infra.tenancy,
        jobs=infra.jobs,
        queue=infra.queue,
        budget=infra.guard,
        executor=TaskExecutor(registry, schemas=schemas, load_plugins=_loader_for(schemas)),
        approvals=desk,
        budgets=StageBudgets(
            dict(run.paid_budgets(settings)),
            config.currency,
            run.stage_max_wall_ms,
            run.stage_max_llm_calls,
        ),
        calendar=MarketCalendar(config.data_dir / "calendar"),
        config=RunnerConfig(
            max_attempts=settings.limits.max_attempts_per_task,
            lease_ms=run.claim_lease_ms,
            workers=workers,
            capabilities=capabilities,
        ),
        task_io=TaskIo(infra.storage),
        spend=meter,
        build_services=build_services,
        evidence=evidence,
        real_run=real_run,
        require_per_video=lambda tx, job_id, cur: require_per_video_budget(
            infra.guard, tx, job_id, cur
        ),
        **extra,
    )
    return runner


def compose(
    request: JobRequest,
    *,
    config: RuntimeConfig,
    settings: AmwSettings,
    run: RunEntrySettings,
    env: Mapping[str, str],
    real_wiring: RealRunWiring | None = None,
    evidence_factory: EvidenceFactory | None = None,
    transports: Mapping[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    scratch: Path | None = None,
    render_start: datetime | None = None,
) -> Composition:
    """Build the runner for ONE job. ``config.mode`` alone decides dry or real."""
    try:  # never trust the caller's object: re-run the validators (model_copy bypasses them)
        config = RuntimeConfig.model_validate(config.model_dump(warnings=False))
    except ValueError:
        raise ConfigInvalidError("runtime config fails re-validation") from None
    real_run = config.mode is not RunMode.DRY_RUN
    infra = build_infrastructure(settings, run, config)
    production = request.production_type
    try:
        job = intake(
            infra.tenancy, infra.jobs,
            org_id=request.org_id, workspace_id=request.workspace_id,
            project_id=request.project_id, channel_id=request.channel_id, topic=request.topic,
            production_type=production, version=record(production).version,
            correlation_id=str(CORRELATION.new()), currency=config.currency,
            rule_packs=settings.rule_packs, run_mode=config.mode.value,
        )  # fmt: skip
    except psycopg.errors.ForeignKeyViolation:
        raise InputInvalidError(
            "the request names a workspace, project or channel that is not in this org",
            details={"violations": [violation("REQUEST_REFERENCE_UNKNOWN", "/request")]},
        ) from None
    _require_job_of_this_mode(infra, request, job, config.mode)
    graph = job_graph(production)
    comp = (
        _dry_run(infra, request, job, graph, config, settings, run, clock, scratch)
        if not real_run
        else _real_run(
            infra, request, job, graph, config, settings, run, env, real_wiring,
            evidence_factory, transports, clock, render_start,
        )
    )  # fmt: skip
    with infra.tenancy.transaction(
        TenantContext(OrgId(job.org_id), ActorRef("sys_operator"))
    ) as tx:
        comp.resume = any(t.stage_id for t in infra.jobs.list_tasks(tx, JobId(job.job_id)))
    return comp


def _require_job_of_this_mode(
    infra: Infrastructure, request: JobRequest, job: JobFacts, mode: RunMode
) -> None:
    """A run only ever works on a job created in its own run mode (its ``job.create`` key carries
    the mode). A REAL run must never resume or reuse anything a DRY_RUN produced (stand-in outputs,
    TEST_FIXTURE approvals), and a DRY run must never overwrite real outputs: any other key is a
    typed refusal before anything is built."""
    expected = job_create_key(
        request.org_id, request.channel_id, request.topic, request.production_type,
        None, mode.value,
    )  # fmt: skip
    with infra.tenancy.transaction(
        TenantContext(OrgId(job.org_id), ActorRef("sys_operator"))
    ) as tx:
        rec = infra.jobs.get_job(tx, JobId(job.job_id))
    if rec is None or str(rec.idempotency_key) != str(expected):
        raise InputInvalidError(
            "the job was not created in this run mode; a dry run and a real run never share a job",
            details={"violations": [violation("RUN_MODE_JOB_MISMATCH", "/mode")]},
        )


def _meter(infra: Infrastructure, providers: ProviderSet, currency: str) -> PgMeter:
    names = {providers.llm.provider, providers.tts.provider}
    return PgMeter(
        infra.tenancy, infra.ledger, infra.guard, infra.jobs, lambda p: p in names, currency
    )


def _dry_run(
    infra: Infrastructure,
    request: JobRequest,
    job: JobFacts,
    graph: tuple[Stage, ...],
    config: RuntimeConfig,
    settings: AmwSettings,
    run: RunEntrySettings,
    clock: Callable[[], datetime] | None,
    scratch: Path | None,
) -> Composition:
    providers = build_providers(config, preflight=None, env={})  # fakes; no key is read
    if providers.real:  # pragma: no cover - build_providers returns fakes for DRY_RUN
        raise ConfigInvalidError("a dry run never builds real providers")
    desk = DryRunDesk()
    meter = _meter(infra, providers, config.currency)
    registry = build_plumbing_registry(infra.storage, ApprovalWorker(desk, now_z), scratch)
    runner = _runner(
        infra, job_type_graph=graph, run=run, settings=settings, config=config,
        registry=registry, schemas=plumbing_schemas(), desk=desk, meter=meter,
        evidence=desk.evidence, real_run=False,
        build_services=PlumbingServices(run.delivery_limits()), clock=clock,
    )  # fmt: skip
    runner.set_max_revision_loops(record(request.production_type).limits.max_revision_loops)
    docs = seed_job_documents(infra.storage, job)
    return Composition(
        RunMode.DRY_RUN, False, runner, replace(job, documents=docs), graph, providers, desk, None,
        ["PLUMBING TEST - NOT QUALITY: fake providers, stand-in workers, test approval desk"],
    )  # fmt: skip


def _real_run(
    infra: Infrastructure,
    request: JobRequest,
    job: JobFacts,
    graph: tuple[Stage, ...],
    config: RuntimeConfig,
    settings: AmwSettings,
    run: RunEntrySettings,
    env: Mapping[str, str],
    wiring: RealRunWiring | None,
    evidence_factory: EvidenceFactory | None,
    transports: Mapping[str, Any] | None,
    clock: Callable[[], datetime] | None,
    render_start: datetime | None,
) -> Composition:
    factory = evidence_factory or _pg_confirmation_evidence
    # 1. the sealed preflight: refuses with EVERY unmet item, mints the provider authorisations
    with factory(infra.tenancy, job.org_id, request.confirmations) as lookup:
        report = run_job_preflight(
            job, config, list(request.confirmations),
            tenancy=infra.tenancy, jobs=infra.jobs, rule_packs=settings.rule_packs,
            env=env, evidence=lookup, render_start=render_start,
        )  # fmt: skip

    # 2. real adapters only from that report; secrets by NAME
    def guard_for(auth: Any) -> BudgetCallGuard:
        return BudgetCallGuard(
            auth, budget=infra.guard, ledger=infra.ledger, tenancy=infra.tenancy, clock=_Clock()
        )

    providers = build_providers(
        config, preflight=report, env=env, guard_for=guard_for, transports=transports
    )
    if wiring is None:
        raise MissingDependencyError(
            "the preflight passed but no production worker wiring is available",
            details={"unmet": ["REAL_WIRING"]},
        )
    meter = PgMeter(
        infra.tenancy, infra.ledger, infra.guard, infra.jobs,
        lambda p: p in {s.name for s in config.providers}, config.currency,
    )  # fmt: skip
    ctx = WiringContext(providers, infra.storage, infra.tenancy, meter, settings, config, request)
    # 3. the S7 desk and the approval evidence port of the database (REAL profile only)
    desk = PgApprovalDesk(
        infra.tenancy, PgEvidenceDatabase(), PgDbSession(DbRole.APP),
        org_id=OrgId(request.org_id), mode=EvidenceMode.REAL,
    )  # fmt: skip
    runner = _runner(
        infra, job_type_graph=graph, run=run, settings=settings, config=config,
        registry=wiring.registry(ctx, ApprovalWorker(desk, now_z)), schemas=wiring.schemas(),
        desk=desk, meter=meter, evidence=desk.evidence_port(), real_run=True,
        build_services=wiring.build_services(ctx), clock=clock,
    )  # fmt: skip
    runner.set_max_revision_loops(record(request.production_type).limits.max_revision_loops)
    docs = wiring.job_documents(ctx, job)
    return Composition(
        RunMode.REAL_RUN, True, runner, replace(job, documents=docs), graph, providers, None,
        report, list(report.notes),
    )  # fmt: skip
