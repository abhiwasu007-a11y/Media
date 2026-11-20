# ruff: noqa: E501, PT018
"""``ProductionBuildServices``: the S4 cost report and the delivery policy of a REAL run, over
PostgreSQL (tenant isolation, REQUIRES REVIEW instead of zero, disclaimer status kept, no secret).
PLUMBING TEST - NOT QUALITY. No network, no key, no paid call."""

import json
from pathlib import Path

import pytest

from amw_core.errors import TenantMismatchError
from amw_core.ids import CORRELATION
from amw_orchestrator.composition import build_infrastructure
from amw_orchestrator.executor import JobFacts
from amw_orchestrator.real_services import ProductionBuildServices
from amw_orchestrator.registry import job_graph, record
from amw_orchestrator.run_settings import load_run_entry_settings
from amw_orchestrator.services import intake
from amw_runtime.config import load_runtime_config
from amw_runtime.disclaimer import get_disclaimer
from tests.orchestrator.run_job_world import SATURDAY, World, make_world
from tests.orchestrator.test_run_job import REAL_ENV
from tests.orchestrator.world import LONG

pytestmark = pytest.mark.integration


@pytest.fixture
def world(pg_dsn: str, tmp_path: Path) -> World:
    return make_world(pg_dsn, tmp_path)


def _services(world: World) -> tuple[ProductionBuildServices, JobFacts]:
    config = load_runtime_config(REAL_ENV)
    settings = world.settings()
    run = load_run_entry_settings(world.run_entry_file())
    infra = build_infrastructure(settings, run, config)
    req = world.request()
    job = intake(
        infra.tenancy, infra.jobs, org_id=req.org_id, workspace_id=req.workspace_id,
        project_id=req.project_id, channel_id=req.channel_id, topic=req.topic,
        production_type=LONG, version=record(LONG).version,
        correlation_id=str(CORRELATION.new()), currency=config.currency,
        rule_packs=settings.rule_packs, run_mode="REAL_RUN",
    )  # fmt: skip
    services = ProductionBuildServices(
        org_id=req.org_id, tenancy=infra.tenancy, jobs=infra.jobs, ledger=infra.ledger,
        guard=infra.guard, now=lambda: SATURDAY, policy=run.delivery,
        disclaimer=get_disclaimer(config.disclaimer_version),
        minor_exponents=config.currency_minor_exponent, run_label=settings.environment,
    )  # fmt: skip
    return services, job


def test_the_cost_report_of_a_job_without_paid_calls_says_review_not_zero(world: World) -> None:
    services, job = _services(world)
    report = dict(services.cost_report(job))
    assert report["job_id"] == job.job_id
    assert report["rows"] == [] and report["total_micros"] == 0
    assert "REQUIRES REVIEW" in str(report["currency"])  # unknown is never printed as a currency
    assert "REQUIRES REVIEW" in str(report["human_review_minutes"])
    assert report["query_scope"] == f"cost_ledger WHERE job_id = {job.job_id}"
    assert report["run_mode"] == world.settings().environment
    json.dumps(report)  # plain JSON data, ready for the delivery input
    # the per-video and pilot caps the world seeded are reported with their status
    kinds = {line["period"] for line in report["budgets"]}
    assert {"PER_VIDEO", "PILOT_TOTAL"} <= kinds


def test_the_delivery_facts_come_from_config_and_the_runtime_disclaimer(world: World) -> None:
    services, job = _services(world)
    facts = services.delivery_facts(job)
    run = load_run_entry_settings(world.run_entry_file())
    disclaimer = get_disclaimer(load_runtime_config(REAL_ENV).disclaimer_version)
    assert facts["config_version"] == run.delivery.config_version
    assert facts["banner"] == run.delivery.banner and "PLUMBING" not in facts["banner"]
    assert facts["disclosure_note"] == run.delivery.disclosure_note
    assert facts["disclaimer"] == {
        "text": disclaimer.text,
        "version": disclaimer.version,
        "status_label": disclaimer.status,
    }  # the DRAFT status label is passed on, never dropped
    assert "DRAFT" in facts["disclaimer"]["status_label"]
    lim = run.delivery.limits
    assert facts["limits"] == {
        "max_file_bytes": lim.max_file_bytes, "max_total_bytes": lim.max_total_bytes,
        "max_thumbnail_bytes": lim.max_thumbnail_bytes,
    }  # fmt: skip


def test_another_tenants_job_is_refused_before_any_read(world: World) -> None:
    services, job = _services(world)
    import dataclasses

    foreign = dataclasses.replace(job, org_id="org_" + "0" * 32)
    with pytest.raises(TenantMismatchError):
        services.cost_report(foreign)
    with pytest.raises(TenantMismatchError):
        services.delivery_facts(foreign)


def test_the_runner_serves_the_document_reads_not_these_services(world: World) -> None:
    services, _job = _services(world)
    with pytest.raises(NotImplementedError):
        services.read_json("amw-blob://x", "0" * 64)
    assert job_graph(LONG)  # the graph this job belongs to exists


def test_a_ledger_row_of_the_job_is_reported_and_adds_up(world: World) -> None:
    from amw_core.enums import CostFigureKind, CostOperation
    from amw_core.ids import ActorRef, JobId, OrgId
    from amw_core.interfaces import TenantContext
    from amw_core.interfaces.cost_ledger import NewCostEntry

    services, job = _services(world)
    infra = build_infrastructure(
        world.settings(), load_run_entry_settings(world.run_entry_file()),
        load_runtime_config(REAL_ENV),
    )  # fmt: skip
    with infra.tenancy.transaction(
        TenantContext(OrgId(job.org_id), ActorRef("sys_operator"))
    ) as tx:
        infra.ledger.record(
            tx,
            NewCostEntry(
                provider="anthropic", operation=CostOperation.LLM_COMPLETION, amount_micros=1234,
                currency="USD", figure_kind=CostFigureKind.ESTIMATE, occurred_at=SATURDAY,
                job_id=JobId(job.job_id), model="a-model", tokens_in=10, tokens_out=5, price_ref="pricing.v1",
            ),
        )  # fmt: skip
    report = dict(services.cost_report(job))
    assert report["total_micros"] == 1234 and report["currency"] == "USD"
    assert sum(r["cost_micros"] for r in report["rows"]) == 1234
    assert report["rows"][0]["provider"] == "anthropic"
    assert "REQUIRES REVIEW" in str(report["rows"][0]["task_type"])  # no task link: not guessed
