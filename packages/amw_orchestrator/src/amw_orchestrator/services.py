"""PostgreSQL wiring of the runner: the metering sink (ledger + E2 / E3), job intake (3A-03)
and the stage budget policy.

``PgMeter`` refuses every provider the ``allowed_providers`` predicate rejects BEFORE any
network request (the dry run allows the fake providers only, so no paid call can happen), then
applies the provider start gate (09 section 8) and E2 against the task's HELD reservation; after
the call it appends one ``cost_ledger`` row (``ESTIMATE``) and runs E3, which suspends a
breached budget (``SUSPENDED_EXCEEDED``); the next E1 / E2 then refuses (hard stop).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from amw_adapters.common import CallUsage
from amw_core.contracts import OwnerTopic, ResourceBudget, Stage
from amw_core.enums import CostFigureKind, Priority, ProductionTypeKey
from amw_core.errors import ConfigInvalidError
from amw_core.ids import (
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
    BudgetGuard,
    CallCheck,
    CostLedger,
    JobStore,
    NewCostEntry,
    TenancyContext,
    TenantContext,
)
from amw_core.interfaces.job_store import NewJob
from amw_orchestrator.executor import JobFacts
from amw_orchestrator.metering import MeteredTask


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


@dataclass(frozen=True, slots=True)
class StageBudgets:
    """Per-stage ``resource_budget`` (config; integers in micros). Stages with no paid call
    carry ``max_cost_micros = 0`` (Agent 10 refuses a non-zero budget, its blueprint 7.1)."""

    paid_micros: Mapping[str, int]
    currency: str
    max_wall_ms: int
    max_llm_calls: int

    def budget_for(self, stage: Stage) -> ResourceBudget:
        micros = self.paid_micros.get(stage.task_type, 0)
        return ResourceBudget(
            max_cost_micros=micros,
            currency=self.currency,
            max_wall_ms=self.max_wall_ms,
            max_llm_calls=self.max_llm_calls if micros else 0,
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
) -> JobFacts:
    """3A-03: J01 for one owner topic (``amw.owner_topic`` recorded by the operator, D5).
    Idempotent on ``job.create`` over (channel, topic title, production type, parent)."""
    key = make_idempotency_key(
        org_id, "job.create", [channel_id, topic.title, production_type.value, parent_job_id or ""]
    )
    with tenancy.transaction(TenantContext(org_id, ActorRef(requested_by))) as tx:  # type: ignore[arg-type]
        rec = jobs.create_job(
            tx,
            NewJob(
                workspace_id=WorkspaceId(workspace_id),
                project_id=ProjectId(project_id) if project_id else None,
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
    )
