# ruff: noqa: E501
# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated"
# mypy: disable-error-code="index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""PLUMBING dry run of the 3A graph: fresh PostgreSQL database, real job / task / queue / budget /
ledger / audit tables, the graph runner, the dry-run world, and S2's delivery bundle.

Database: ``AMW_DRYRUN_DATABASE_URL`` (a superuser DSN of a scratch cluster; never committed).
The run creates its own database, migrates it, seeds one TEST tenant and works as ``amw_app``.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg import conninfo as pg_conninfo
from psycopg import sql

from amw_core.audit.pg import PgAuditLog
from amw_core.budget_guard import BudgetGuardCore
from amw_core.budget_guard.pg import PgBudgetBackend
from amw_core.config.settings import FinanceSettings, load_settings
from amw_core.contracts import OwnerTopic
from amw_core.cost.pg import PgCostLedger
from amw_core.cost.report import CostStageReport, JobHeader, TaskInfo, build_cost_stage_report
from amw_core.enums import (
    BudgetPeriod,
    BudgetScopeKind,
    BudgetState,
    Capability,
    ProductionTypeKey,
    ResourceClass,
)
from amw_core.ids import (
    BUDGET,
    CHANNEL,
    CORRELATION,
    ORG,
    PROJECT,
    USER,
    WORKER,
    WORKSPACE,
    ActorRef,
    JobId,
    TaskId,
    new_uuid7,
)
from amw_core.interfaces import Budget, TenantContext
from amw_core.job_store.pg import PgJobStore
from amw_core.queue.pg import PgTaskQueue
from amw_core.tenancy import PgTenancy, dsn_connection_factory
from amw_core.tenancy.migrate import migrate
from amw_orchestrator.driver import GraphRunner, RunnerConfig, RunReport
from amw_orchestrator.registry import job_graph, record, record_sha256
from amw_orchestrator.runtime_iface import Calendar, load_runtime_config, market_calendar, source
from amw_orchestrator.services import PgMeter, StageBudgets, intake
from tests.dryrun.kit import PLUMBING
from tests.dryrun.llm import FAKE_MICROS_PER_CALL, PRICE
from tests.dryrun.world import DeliveryExecutor, Registry, TestOperatorDesk, build_world

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "migrations"
M = 1_000_000
PAID_STAGE_MICROS = {
    "agent_04.research_pack": 200_000,
    "agent_05.script_draft": 200_000,
    "agent_05.shorts_adaptation": 200_000,
    "agent_06.claim_extraction": 100_000,
    "agent_06.claim_verification": 100_000,
    "agent_07.voice_synthesis": 500_000,
    "agent_09.shot_plan": 100_000,
    "agent_11.thumbnail_variants": 100_000,
    "agent_16.compliance_gate": 100_000,
    "agent_16.quality_score": 100_000,
}
"""Per-task reservation (USD micros) of the stages that make a provider call: dry-run config."""
FAKE_PROVIDERS = ("fake_llm", "fake_tts", "fake")


@dataclass
class DryRunResult:
    status: str
    job_id: str
    out_dir: str
    bundle_dir: str | None
    zip_path: str | None
    order: list[str]
    gates: list[dict[str, object]]
    revisions: list[dict[str, object]]
    cost_rows: int
    paid_calls: int
    refused_providers: list[str]
    stage_ms: dict[str, int]
    total_s: float
    calendar_source: str
    detail: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


def _with_db(dsn: str, name: str) -> str:
    params = pg_conninfo.conninfo_to_dict(dsn)
    params["dbname"] = name
    return pg_conninfo.make_conninfo(**{k: str(v) for k, v in params.items() if v is not None})


def fresh_database(admin_dsn: str) -> str:
    name = f"amw_dryrun_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(name)
            )
        )
    dsn = _with_db(admin_dsn, name)
    migrate(dsn, MIGRATIONS)
    return dsn


def drop_database(admin_dsn: str, dsn: str) -> None:
    name = pg_conninfo.conninfo_to_dict(dsn)["dbname"]
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(str(name)))
        )


@dataclass(frozen=True)
class Seed:
    org_id: str
    workspace_id: str
    channel_id: str
    owner: str
    project_id: str
    workers: dict[ResourceClass, Any]


def seed(dsn: str) -> Seed:
    """Superuser bootstrap of ONE TEST tenant (platform-owner functions in production)."""
    org, wsp, chn, usr, prj = new_uuid7(), new_uuid7(), new_uuid7(), new_uuid7(), new_uuid7()
    workers: dict[ResourceClass, Any] = {}
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO organisations (id, name, slug, kind, status, is_platform_owner)"
            " VALUES (%s, 'PLUMBING TEST org', %s, 'PLATFORM_OWNER', 'ACTIVE', true)",
            (org, f"plumbing-{org.hex[-12:]}"),
        )
        conn.execute(
            "INSERT INTO workspaces (id, org_id, name, status) VALUES (%s, %s, 'main', 'ACTIVE')",
            (wsp, org),
        )
        conn.execute(
            "INSERT INTO channels (id, org_id, workspace_id, platform, title, language, category, status)"
            " VALUES (%s, %s, %s, 'YOUTUBE', 'PLUMBING TEST channel', 'mr-IN', 'finance', 'DRAFT')",
            (chn, org, wsp),
        )
        conn.execute(
            "INSERT INTO projects (id, org_id, workspace_id, channel_id, name, kind, status, default_production_type)"
            " VALUES (%s, %s, %s, %s, 'PLUMBING TEST series', 'SERIES', 'ACTIVE', 'CHANNEL_LONG_FORM')",
            (prj, org, wsp, chn),
        )
        conn.execute(
            "INSERT INTO users (id, email, display_name, status) VALUES (%s, %s, 'TEST owner', 'ACTIVE')",
            (usr, f"test-owner-{usr.hex[-8:]}@example.invalid"),
        )
        conn.execute(
            "INSERT INTO memberships (id, org_id, user_id, role, status) VALUES (%s, %s, %s, 'ORG_OWNER', 'ACTIVE')",
            (new_uuid7(), org, usr),
        )
        for key in (ProductionTypeKey.CHANNEL_LONG_FORM, ProductionTypeKey.SHORTS):
            pt = record(key)
            conn.execute(
                "INSERT INTO production_types (id, key, version, status, tier, record, record_sha256)"
                " VALUES (%s, %s, %s, 'IN_DEVELOPMENT', 'TIER_0', %s, %s) ON CONFLICT DO NOTHING",
                (new_uuid7(), key.value, pt.version, json.dumps(pt.to_doc()), record_sha256(pt)),
            )
        caps = [c.value for c in Capability]
        for rc in (ResourceClass.LIGHT, ResourceClass.AI_IO, ResourceClass.HEAVY_CPU):
            wid = new_uuid7()
            conn.execute(
                "INSERT INTO workers (id, logical_name, capabilities, resource_classes, max_concurrency,"
                " status, software_version) VALUES (%s, %s, %s, %s, 1, 'IDLE', 'dryrun')",
                (wid, f"dryrun-{rc.value.lower()}-{wid.hex[-6:]}", caps, [rc.value]),
            )
            workers[rc] = WORKER.from_uuid(wid)
    return Seed(
        str(ORG.from_uuid(org)),
        str(WORKSPACE.from_uuid(wsp)),
        str(CHANNEL.from_uuid(chn)),
        str(USER.from_uuid(usr)),
        str(PROJECT.from_uuid(prj)),
        workers,
    )


def owner_budgets(
    tenancy: PgTenancy, s: Seed, per_video_micros: int, pilot_micros: int
) -> list[Budget]:
    """TEST owner action: per-video and pilot caps (owner-approved values from S4 config) and
    the provider start-gate rows of the FAKE providers (09 section 8: acknowledgement rows)."""
    exp = 2
    budgets = [
        Budget(
            BUDGET.new(),
            s.org_id,
            BudgetScopeKind.ORG,
            None,
            None,
            BudgetPeriod.PER_VIDEO,  # type: ignore[arg-type]
            per_video_micros // (M // 10**exp),
            "USD",
            Decimal("0.800"),
            BudgetState.ACTIVE,
            True,
        ),
        Budget(
            BUDGET.new(),
            s.org_id,
            BudgetScopeKind.ORG,
            None,
            None,
            BudgetPeriod.PILOT_TOTAL,  # type: ignore[arg-type]
            pilot_micros // (M // 10**exp),
            "USD",
            Decimal("0.800"),
            BudgetState.ACTIVE,
            True,
        ),
    ]
    for provider in FAKE_PROVIDERS:
        budgets.append(
            Budget(
                BUDGET.new(),
                s.org_id,
                BudgetScopeKind.PROVIDER,
                None,
                provider,  # type: ignore[arg-type]
                BudgetPeriod.PILOT_TOTAL,
                pilot_micros // (M // 10**exp),
                "USD",
                Decimal("0.800"),
                BudgetState.ACTIVE,
                True,
            )
        )
    backend = PgBudgetBackend()
    with tenancy.transaction(TenantContext(s.org_id, ActorRef(s.owner))) as tx:  # type: ignore[arg-type]
        for b in budgets:
            backend.create_budget(tx, b)
    return budgets


class _FixedCalendar:
    """TEST CALENDAR FIXTURE for CI: a fixed answer (the real guard code still runs)."""

    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed

    def render_allowed(self, dt: datetime) -> bool:
        return self.allowed


def run_dryrun(
    *,
    topic_title: str,
    out: Path,
    admin_dsn: str,
    scale: str = "modest",
    shorts: bool = True,
    calendar: Calendar | None = None,
    per_video_micros: int | None = None,
    pilot_micros: int | None = None,
    fake_micros_per_call: int | None = None,
    owner_says: str = "APPROVE",
    gate_override: dict[str, Any] | None = None,
    keep_db: bool = False,
    target_duration_ms: int = 60_000,
    stage_micros: dict[str, int] | None = None,
    admission: Any = None,
) -> DryRunResult:
    t_start = time.monotonic()
    cfg = load_runtime_config(
        {
            **{k: v for k, v in os.environ.items() if k.startswith("AMW_RUNTIME_")},
            "AMW_RUNTIME_MODE": "DRY_RUN",
        }
    )
    pv = per_video_micros if per_video_micros is not None else cfg.per_video_cap_micros
    pilot = pilot_micros if pilot_micros is not None else cfg.total_cap_micros
    cal = calendar or market_calendar()
    out.mkdir(parents=True, exist_ok=True)
    dsn = fresh_database(admin_dsn)
    try:
        s = seed(dsn)
        tenancy = PgTenancy(dsn_connection_factory(dsn, role="amw_app"))
        audit = PgAuditLog()
        jobs = PgJobStore(audit, max_tasks_per_job=400)
        queue = PgTaskQueue(dsn_connection_factory(dsn, role="amw_app"))
        settings = load_settings(environ={})
        settings = settings.model_copy(
            update={"finance": FinanceSettings(currency_minor_exponent={"INR": 2, "USD": 2})}
        )
        guard = BudgetGuardCore(PgBudgetBackend(), settings, _Clock(), audit)
        ledger = PgCostLedger()
        owner_budgets(tenancy, s, pv, pilot)
        meter = PgMeter(
            tenancy, ledger, guard, jobs, allowed_providers=lambda p: p in FAKE_PROVIDERS
        )
        world = build_world(out / "work", meter, s.org_id, scale=scale)
        if admission is not None:
            world.extras["admission"] = admission
        if fake_micros_per_call is not None:
            PRICE.micros = fake_micros_per_call
        bundle_dir = out / "bundle"
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)

        def cost_report(job_id: str) -> CostStageReport:
            return _cost_report(tenancy, s, ledger, guard, job_id, report_box)

        desk_box: list[TestOperatorDesk] = []
        delivery = DeliveryExecutor(world, bundle_dir, cost_report, lambda: desk_box[0])
        size = (1920, 1080) if scale == "modest" else (640, 360)
        registry = Registry(
            world, ms_per_char=50 if scale == "modest" else 12, size=size, deliver=delivery
        )
        desk = TestOperatorDesk(registry.compliance, owner_says)
        desk_box.append(desk)
        if gate_override:
            registry.overrides.update(gate_override)
        runner = GraphRunner(
            tenancy=tenancy,
            jobs=jobs,
            queue=queue,
            budget=guard,
            executors=registry,
            approvals=desk,
            budgets=StageBudgets(stage_micros or PAID_STAGE_MICROS, "USD", 3_600_000, 40),
            calendar=cal,
            config=RunnerConfig(
                max_attempts=2,
                lease_ms=3_600_000,
                workers=s.workers,
                capabilities=tuple(Capability),
            ),
        )
        topic = OwnerTopic.model_validate(
            {
                "schema_version": "1.0.0",
                "title": topic_title,
                "brief": None,
                "angle": None,
                "language": "mr-IN",
                "video_kind": "GENERAL",
                "course_chapter_pointer": None,
                "owner_references": [],
                "target_duration_ms": target_duration_ms,
                "shorts_wanted": shorts,
            }
        )
        job = intake(
            tenancy,
            jobs,
            org_id=s.org_id,
            workspace_id=s.workspace_id,
            project_id=s.project_id,
            channel_id=s.channel_id,
            topic=topic,
            production_type=ProductionTypeKey.CHANNEL_LONG_FORM,
            version=2,
            correlation_id=str(CORRELATION.new()),
        )
        graph = job_graph(ProductionTypeKey.CHANNEL_LONG_FORM)
        runner.set_max_revision_loops(
            record(ProductionTypeKey.CHANNEL_LONG_FORM).limits.max_revision_loops
        )
        report = runner.start(job, graph)
        report_box: list[RunReport] = [report]
        report = runner.run(job, graph, report)
        zip_path = None
        if delivery.manifest is not None:
            zip_path = str(bundle_dir / delivery.manifest.zip_name)
        with tenancy.transaction(TenantContext(s.org_id, ActorRef("sys_operator"))) as tx:  # type: ignore[arg-type]
            rows = ledger.for_job(tx, JobId(job.job_id))
        result = DryRunResult(
            status=report.status,
            job_id=job.job_id,
            out_dir=str(out),
            bundle_dir=str(bundle_dir) if delivery.manifest else None,
            zip_path=zip_path,
            order=report.order,
            gates=report.gates,
            revisions=report.revisions,
            cost_rows=len(rows),
            paid_calls=sum(1 for r in rows if r.entry.provider not in FAKE_PROVIDERS),
            refused_providers=list(meter.refused),
            stage_ms={k: v.duration_ms for k, v in report.stages.items()},
            total_s=round(time.monotonic() - t_start, 1),
            calendar_source=source(),
            detail=report.detail,
        )
        result.extras["db"] = _db_facts(dsn, s.org_id)
        (out / "run_summary.json").write_text(
            json.dumps(asdict(result), indent=2, default=str), encoding="utf-8"
        )
        return result
    finally:
        PRICE.micros = FAKE_MICROS_PER_CALL
        if not keep_db:
            drop_database(admin_dsn, dsn)


class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        return int(time.monotonic() * 1000)


def _cost_report(
    tenancy: PgTenancy,
    s: Seed,
    ledger: PgCostLedger,
    guard: BudgetGuardCore,
    job_id: str,
    box: list[RunReport],
) -> CostStageReport:
    report = box[0]
    tasks = {
        TaskId(r.task_id): TaskInfo(
            task_type=_ttype(sid), stage_id=sid.split("#")[0], iteration=r.iteration
        )
        for sid, r in report.stages.items()
    }
    with tenancy.transaction(TenantContext(s.org_id, ActorRef("svc_s04"))) as tx:  # type: ignore[arg-type]
        rows = ledger.for_job(tx, JobId(job_id))
        statuses = [
            guard.status(tx, b.id, JobId(job_id))
            for b in guard.applicable_budgets(tx, JobId(job_id))
        ]
    return build_cost_stage_report(
        JobHeader(JobId(job_id), "CHANNEL_LONG_FORM", 2, "owner_topic", "development"),
        rows,
        tasks,
        statuses,
        datetime.now(UTC),
        {"USD": 2, "INR": 2},
        price_ref_sources={
            "fake-pricing-v0": "synthetic fake price (test configuration, not a real price)"
        },
    )


def _ttype(stage_id: str) -> str:
    graph = job_graph(ProductionTypeKey.CHANNEL_LONG_FORM)
    sid = stage_id.split("#")[0]
    return next((s.task_type for s in graph if s.stage_id == sid), sid)


def _db_facts(dsn: str, org_id: str) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn:
        q = lambda s: conn.execute(s).fetchone()[0]  # noqa: E731
        return {
            "tasks": q("SELECT count(*) FROM tasks"),
            "tasks_completed": q("SELECT count(*) FROM tasks WHERE state = 'COMPLETED'"),
            "tasks_cancelled": q("SELECT count(*) FROM tasks WHERE state = 'CANCELLED'"),
            "state_transitions": q("SELECT count(*) FROM state_transitions"),
            "audit_rows": q("SELECT count(*) FROM audit_log"),
            "cost_ledger_rows": q("SELECT count(*) FROM cost_ledger"),
            "queue_rows_done": q("SELECT count(*) FROM task_queue WHERE status = 'DONE'"),
            "reservations": q("SELECT count(*) FROM budget_reservations"),
            "job_state": q("SELECT state || '/' || coalesce(outcome, '-') FROM jobs"),
            "budget_states": [
                r[0]
                for r in conn.execute(
                    "SELECT period || ':' || scope_kind || ':' || state FROM budgets ORDER BY 1"
                )
            ],
        }


def zip_dir(src: Path, dest: Path) -> str:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src))
    return hashlib.sha256(dest.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m amw_orchestrator.dryrun", description=PLUMBING)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--scale", choices=("modest", "tiny"), default="modest")
    ap.add_argument("--no-shorts", action="store_true")
    ap.add_argument("--keep-db", action="store_true")
    args = ap.parse_args(argv)
    dsn = os.environ.get("AMW_DRYRUN_DATABASE_URL")
    if not dsn:
        print(
            "AMW_DRYRUN_DATABASE_URL is not set (superuser DSN of a scratch cluster)",
            file=sys.stderr,
        )
        return 2
    cal = market_calendar()
    if not cal.render_allowed(datetime.now(UTC)):
        print(
            "refused: the market calendar does not allow rendering now (regular NSE session)",
            file=sys.stderr,
        )
        return 3
    res = run_dryrun(
        topic_title=args.topic,
        out=args.out.resolve(),
        admin_dsn=dsn,
        scale=args.scale,
        shorts=not args.no_shorts,
        keep_db=args.keep_db,
    )
    print(json.dumps(asdict(res), indent=2, default=str))
    return 0 if res.status == "DELIVERED" else 1


_ = timedelta
