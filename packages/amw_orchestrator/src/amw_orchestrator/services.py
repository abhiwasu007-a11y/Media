"""PostgreSQL wiring of the runner: the metering sink (ledger + E2 / E3), job intake (3A-03)
and the stage budget policy.

``PgMeter`` refuses every provider the ``allowed_providers`` predicate rejects BEFORE any
network request (the dry run allows the fake providers only, so no paid call can happen), then
applies the provider start gate (09 section 8) and E2 against the task's HELD reservation; after
the call it appends one ``cost_ledger`` row (``ESTIMATE``) and runs E3, which suspends a
breached budget (``SUSPENDED_EXCEEDED``); the next E1 / E2 then refuses (hard stop).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from amw_adapters.common import CallUsage
from amw_core.config import RulePackSettings
from amw_core.contracts import OwnerTopic, ResourceBudget, Stage, violation
from amw_core.enums import (
    BudgetPeriod,
    BudgetScopeKind,
    BudgetState,
    Capability,
    CostFigureKind,
    Priority,
    ProductionTypeKey,
)
from amw_core.errors import ConfigInvalidError, InputInvalidError
from amw_core.ids import (
    BUDGET,
    ActorRef,
    AttemptId,
    ChannelId,
    CorrelationId,
    ExecutorId,
    JobId,
    ProjectId,
    TaskId,
    WorkspaceId,
    make_idempotency_key,
)
from amw_core.interfaces import (
    Budget,
    BudgetGuard,
    CallCheck,
    CostLedger,
    JobStore,
    NewCostEntry,
    TenancyContext,
    TenantContext,
    TenantTransaction,
)
from amw_core.interfaces.job_store import NewJob
from amw_core.tenancy.channel_category import read_channel_category
from amw_orchestrator.executor import ChannelCategory, JobFacts, resolve_channel_category
from amw_orchestrator.metering import MeteredTask
from amw_runtime.config import RuntimeConfig
from amw_runtime.confirmations import ConfirmationRecord
from amw_runtime.preflight import (
    PreflightReport,
    mint_job_scope,
    register_job_scope_minter,
    run_preflight,
)


@dataclass(frozen=True, slots=True)
class AttemptSpend:
    entry_id: str
    micros: int
    currency: str


@dataclass
class PgMeter:
    tenancy: TenancyContext
    ledger: CostLedger
    budget: BudgetGuard
    jobs: JobStore
    allowed_providers: Callable[[str], bool]
    currency: str = "USD"
    calls: list[dict[str, object]] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    _spend: dict[str, list[AttemptSpend]] = field(default_factory=dict)

    def spend_of(self, attempt_id: str) -> list[AttemptSpend]:
        """The ledger rows this runner wrote for one attempt (so an error output reports the
        real cost of the calls made before the failure, never a silent 0)."""
        return list(self._spend.get(attempt_id, ()))

    def _ctx(self, task: MeteredTask) -> TenantContext:
        return TenantContext(task.org_id, ActorRef(task.agent_id))  # type: ignore[arg-type]

    def before_call(self, task: MeteredTask, provider: str, estimate_micros: int) -> None:
        if not self.allowed_providers(provider):
            self.refused.append(provider)
            raise ConfigInvalidError(
                "provider not allowed in this run (no paid call without the owner)",
                details={"provider": provider},
            )
        with self.tenancy.transaction(self._ctx(task)) as tx:
            self.budget.check_provider_gate(tx, provider)
            self.budget.check_call(
                tx,
                CallCheck(
                    TaskId(task.task_id),
                    JobId(task.job_id),
                    provider,
                    estimate_micros,
                    self.currency,
                ),
            )

    def after_call(self, task: MeteredTask, usage: CallUsage) -> None:
        entry = NewCostEntry(
            provider=usage.provider,
            operation=usage.operation,
            amount_micros=usage.amount_micros,
            currency=usage.currency,
            figure_kind=CostFigureKind.ESTIMATE,
            occurred_at=datetime.now(UTC),
            job_id=JobId(task.job_id),
            task_id=TaskId(task.task_id),
            attempt_id=AttemptId(task.attempt_id),
            channel_id=ChannelId(task.channel_id) if task.channel_id else None,
            agent_id=ExecutorId(task.agent_id),
            model=usage.model,
            billing_mode=usage.billing_mode,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            tokens_cached_in=usage.tokens_cached_in,
            chars_in=usage.chars_in,
            language=usage.language,
            units=Decimal(usage.units) if usage.units is not None else None,
            unit_kind=usage.unit_kind,
            price_ref=usage.price_ref or "fake-pricing-v0",
            idempotency_key=usage.idempotency_key,  # type: ignore[arg-type]
        )
        with self.tenancy.transaction(self._ctx(task)) as tx:
            row = self.ledger.record(tx, entry)
            self.budget.after_call(tx, row)
            self.jobs.add_job_cost(tx, JobId(task.job_id), usage.amount_micros, 0)
        self.calls.append(
            {"stage_id": task.stage_id, "provider": usage.provider, "micros": usage.amount_micros}
        )
        self._spend.setdefault(task.attempt_id, []).append(
            AttemptSpend(str(row.id), usage.amount_micros, usage.currency)
        )


PAID_CAPABILITIES = frozenset(
    {
        Capability.LLM,
        Capability.TTS,
        Capability.IMAGE_GEN,
        Capability.VIDEO_GEN,
        Capability.STOCK_SEARCH,
        Capability.MUSIC_SEARCH,
    }
)
"""GLOSSARY 6.20: the paid capabilities. Every other capability costs nothing per call."""


@dataclass(frozen=True, slots=True)
class StageBudgets:
    """Per-stage ``resource_budget`` (09 section 3.4, CCR-205; integers in micros).

    A stage that lists no paid capability gets ``max_cost_micros = 0`` and ``max_llm_calls = 0``
    (written here, never configured; Agent 10 refuses a non-zero budget). A paid stage takes the
    configured key of its task type (``paid_micros``); an unset key is NOT a zero: it refuses the
    job at J02 with ``PERMANENT.CONFIG_INVALID`` (fail closed, no silent default)."""

    paid_micros: Mapping[str, int]
    currency: str
    max_wall_ms: int
    max_llm_calls: int

    @staticmethod
    def is_paid(stage: Stage) -> bool:
        return bool(PAID_CAPABILITIES.intersection(stage.capabilities))

    def missing(self, graph: Sequence[Stage]) -> tuple[str, ...]:
        """Task types of paid stages with no configured, positive budget key."""
        return tuple(
            sorted(
                {
                    s.task_type
                    for s in graph
                    if self.is_paid(s) and self.paid_micros.get(s.task_type, 0) <= 0
                }
            )
        )

    def validate(self, graph: Sequence[Stage]) -> None:
        """J02 check: every paid stage of the graph has its budget key (else CONFIG_INVALID)."""
        gone = self.missing(graph)
        if gone:
            raise ConfigInvalidError(
                "a paid stage has no configured cost budget",
                details={
                    "violations": [
                        violation("COST_BUDGET_UNSET", f"/llm/{t}/cost_budget_micros") for t in gone
                    ]
                },
            )

    def budget_for(self, stage: Stage) -> ResourceBudget:
        if not self.is_paid(stage):
            return ResourceBudget(
                max_cost_micros=0,
                currency=self.currency,
                max_wall_ms=self.max_wall_ms,
                max_llm_calls=0,
            )
        micros = self.paid_micros.get(stage.task_type, 0)
        if micros <= 0:
            raise ConfigInvalidError(
                "a paid stage has no configured cost budget",
                details={
                    "violations": [
                        violation("COST_BUDGET_UNSET", f"/llm/{stage.task_type}/cost_budget_micros")
                    ]
                },
            )
        return ResourceBudget(
            max_cost_micros=micros,
            currency=self.currency,
            max_wall_ms=self.max_wall_ms,
            max_llm_calls=self.max_llm_calls if Capability.LLM in stage.capabilities else 0,
        )


def micros_to_minor(micros: int, exponent: int) -> int:
    """GLOSSARY 3: ``limit_minor`` of a budget row from micros (exact; a remainder is refused)."""
    factor = 10 ** (6 - exponent)
    if micros <= 0 or micros % factor:
        raise ConfigInvalidError("a cap is not a whole number of minor units")
    return int(micros // factor)


def seed_cap_budgets(
    create_budget: Callable[[TenantTransaction, Budget], None],
    tx: TenantTransaction,
    *,
    org_id: str,
    per_video_cap_micros: int,
    pilot_cap_micros: int,
    currency: str,
    minor_exponent: int,
    providers: Sequence[str] = (),
) -> tuple[Budget, ...]:
    """Owner action (the DB trigger refuses a non-human actor): the PER_VIDEO and PILOT_TOTAL
    rows from the ``amw_runtime`` caps (hard ceilings, D9: USD 5 per video, USD 50 pilot) and one
    PROVIDER start-gate row per acknowledged provider limit (09 section 8)."""
    rows = [
        (BudgetScopeKind.ORG, None, BudgetPeriod.PER_VIDEO, per_video_cap_micros),
        (BudgetScopeKind.ORG, None, BudgetPeriod.PILOT_TOTAL, pilot_cap_micros),
        *(
            (BudgetScopeKind.PROVIDER, p, BudgetPeriod.PILOT_TOTAL, pilot_cap_micros)
            for p in providers
        ),
    ]
    made = tuple(
        Budget(
            BUDGET.new(),
            org_id,  # type: ignore[arg-type]
            kind,
            None,
            key,
            period,
            micros_to_minor(micros, minor_exponent),
            currency,
            Decimal("0.800"),
            BudgetState.ACTIVE,
            True,
        )
        for kind, key, period, micros in rows
    )
    for b in made:
        create_budget(tx, b)
    return made


def require_per_video_budget(
    guard: BudgetGuard, tx: TenantTransaction, job_id: str, currency: str
) -> Budget:
    """Fail closed (D9 / D10: per-video cap, hard stop): the job must have an ACTIVE PER_VIDEO
    budget row in its currency. Absent = refuse; nothing is assumed or created here."""
    for b in guard.applicable_budgets(tx, JobId(job_id)):
        if (
            b.period is BudgetPeriod.PER_VIDEO
            and b.state is BudgetState.ACTIVE
            and b.currency == currency
        ):
            return b
    raise ConfigInvalidError(
        "no active PER_VIDEO budget row for the job: no spend without the per-video cap",
        details={"violations": [violation("PER_VIDEO_BUDGET_MISSING", "/budgets")]},
    )


def intake(
    tenancy: TenancyContext,
    jobs: JobStore,
    *,
    org_id: str,
    workspace_id: str,
    project_id: str | None,
    channel_id: str,
    topic: OwnerTopic,
    production_type: ProductionTypeKey,
    version: int,
    correlation_id: str,
    requested_by: str = "sys_operator",
    parent_job_id: str | None = None,
    currency: str = "USD",
    rule_packs: RulePackSettings | None = None,
) -> JobFacts:
    """3A-03: J01 for one owner topic (``amw.owner_topic`` recorded by the operator, D5).
    Idempotent on ``job.create`` over (channel, topic title, production type, parent).

    A production job without ``project_id`` is refused before anything is written
    (``PERMANENT.INPUT_INVALID``, violation ``PROJECT_MISSING``; 03 section 3.1, CCR-214 (b)).
    The job category is decided HERE and nowhere else (CCR-273, D13 fail closed):
    ``channels.category`` of the job's ``channel_id`` is read inside the tenant transaction
    (explicit org filter), never taken from a caller argument. It is non-finance only for an
    explicit non-finance label or a documented non-finance category of the validated rule-pack
    config (``rule_packs`` = ``settings.rule_packs``; the packaged default when omitted; PASS6-N);
    a missing channel row, a NULL, an unreadable value, an unknown value or ``finance`` = FINANCE.
    ``jobs`` has no category column (CCR-292 PROPOSED): the resolved category lives in the returned
    ``JobFacts`` and the preflight report, and a job resumed through ``intake`` is re-resolved from
    the channel row."""
    if not project_id:
        raise InputInvalidError(
            "a production job needs its project",
            details={"violations": [violation("PROJECT_MISSING", "/project_id")]},
        )
    key = make_idempotency_key(
        org_id, "job.create", [channel_id, topic.title, production_type.value, parent_job_id or ""]
    )
    with tenancy.transaction(TenantContext(org_id, ActorRef(requested_by))) as tx:  # type: ignore[arg-type]
        row_category = read_channel_category(tx, channel_id)
        category = resolve_channel_category(row_category, rule_packs)
        rec = jobs.create_job(
            tx,
            NewJob(
                workspace_id=WorkspaceId(workspace_id),
                project_id=ProjectId(project_id),
                channel_id=ChannelId(channel_id),
                parent_job_id=JobId(parent_job_id) if parent_job_id else None,
                production_type_key=production_type,
                production_type_version=version,
                language=topic.language,
                priority=Priority.NORMAL,
                deadline=None,
                correlation_id=CorrelationId(correlation_id),
                idempotency_key=key,
                requested_by=ActorRef(requested_by),
                input_ref=None,
                currency=currency,
            ),
        )
    return JobFacts(
        org_id=org_id,
        workspace_id=workspace_id,
        project_id=project_id,
        channel_id=channel_id,
        job_id=str(rec.id),
        parent_job_id=parent_job_id,
        correlation_id=correlation_id,
        production_type_key=production_type,
        production_type_version=version,
        language=topic.language,
        owner_topic=topic,
        currency=currency,
        channel_category=category,
        channel_category_row=(
            row_category if isinstance(row_category, str) and row_category.strip() else None
        ),
    )


def _preflight_category(
    tenancy: TenancyContext,
    jobs: JobStore,
    job: JobFacts,
    rule_packs: RulePackSettings | None,
) -> ChannelCategory:
    """The category the preflight decides by: re-read from the database for this job, never from
    the caller's ``JobFacts`` (a public dataclass: ``channel_category`` and ``finance_rules_apply``
    there are ignored). The job's own row names its channel (not ``JobFacts.channel_id``), and
    ``channels.category`` of that channel is read in the tenant transaction (explicit org filter)
    and resolved with the validated ``RulePackSettings``. Anything that goes wrong (no such job,
    no channel, no row, a database or tenancy error) is FINANCE: this decision fails closed."""
    try:
        with tenancy.transaction(TenantContext(job.org_id, ActorRef("sys_operator"))) as tx:  # type: ignore[arg-type]
            rec = jobs.get_job(tx, JobId(job.job_id))
            if rec is None or rec.channel_id is None or str(rec.org_id) != job.org_id:
                return ChannelCategory.FINANCE
            raw = read_channel_category(tx, str(rec.channel_id))
    except Exception:  # fail closed: every failure here means finance
        return ChannelCategory.FINANCE
    return resolve_channel_category(raw, rule_packs)


def run_job_preflight(
    job: JobFacts,
    config: RuntimeConfig,
    confirmations: Sequence[ConfirmationRecord],
    *,
    tenancy: TenancyContext,
    jobs: JobStore,
    rule_packs: RulePackSettings | None = None,
    **kwargs: Any,
) -> PreflightReport:
    """``amw_runtime`` preflight for one job. The finance-only items (FIN-R10, the price-data lag
    config item) apply only when the job's channel category is finance (D13 item 2, CCR-273
    PROPOSED); a non-finance job still needs PROVIDER_LIMIT evidence and every other item, and a
    passing REAL_RUN mints its provider authorisations as for any job.

    The decision is DERIVED HERE, never taken from a caller object: the job's channel is read from
    its row and ``channels.category`` is re-read in the tenant transaction (``_preflight_category``;
    ``rule_packs`` = the validated ``settings.rule_packs``, the packaged default when omitted). Only
    ``org_id`` and ``job_id`` of ``job`` are used; its category fields are ignored, so a
    ``JobFacts`` built or ``dataclasses.replace``d to say non-finance changes nothing. The sealed
    scope is minted below (this function is the one registered minter) and is verified, bound to
    this org and job and used once, inside ``run_preflight``; a caller cannot pass ``job_scope``,
    ``org_id`` or ``job_id`` through ``kwargs`` (they are overwritten)."""
    # the provider authorisations are bound to this org and this job (a job-scoped call guard
    # refuses a token with another or no job); the caller may not pass another job's binding
    category = _preflight_category(tenancy, jobs, job, rule_packs)
    kwargs["org_id"] = job.org_id
    kwargs["job_id"] = job.job_id
    kwargs["job_scope"] = mint_job_scope(
        org_id=job.org_id,
        job_id=job.job_id,
        finance_rules_apply=category is ChannelCategory.FINANCE,
    )
    report = run_preflight(config, confirmations, **kwargs)
    # the resolved category goes into the run report (jobs has no category column, CCR-292)
    note = f"job channel category (re-read from channels.category): {category.value}"
    return replace(report, notes=(*report.notes, note))


register_job_scope_minter(run_job_preflight.__code__)
