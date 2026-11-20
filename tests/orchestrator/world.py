"""Test world for the DB-backed runner tests: one TEST tenant on the real PostgreSQL tables,
fake workers behind the real ``TaskExecutor`` / ``GraphRunner``. PLUMBING TEST - NOT QUALITY.

No paid call is possible: providers are the fakes of ``amw_adapters`` behind the metering
wrappers, the allow-list names only fake providers, nothing touches the network."""

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel, ConfigDict

from amw_adapters.llm import LlmMessage, LlmRequest
from amw_adapters.llm.fake import FakeLlmAdapter
from amw_core.audit.pg import PgAuditLog
from amw_core.budget_guard import BudgetGuardCore
from amw_core.budget_guard.pg import PgBudgetBackend
from amw_core.config import FinanceSettings, load_settings
from amw_core.contracts import OwnerTopic, Stage, TaskInput, TaskOutput
from amw_core.contracts.payloads import PayloadSchemaRegistry
from amw_core.cost.pg import PgCostLedger
from amw_core.enums import Capability, ProductionTypeKey, ResourceClass
from amw_core.exec_context import ExecContext
from amw_core.ids import (
    CHANNEL,
    CORRELATION,
    ORG,
    PROJECT,
    USER,
    WORKER,
    WORKSPACE,
    ActorRef,
    new_uuid7,
)
from amw_core.interfaces import TenantContext
from amw_core.job_store.pg import PgJobStore
from amw_core.queue.pg import PgTaskQueue
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy import PgTenancy, dsn_connection_factory
from amw_orchestrator.driver import GraphRunner, RunnerConfig
from amw_orchestrator.executor import (
    ApprovalWorker,
    BuildContext,
    BuiltInput,
    JobFacts,
    TaskExecutor,
)
from amw_orchestrator.metering import MeteredLlm
from amw_orchestrator.outputs import now_z
from amw_orchestrator.registry import job_graph, record, record_sha256
from amw_orchestrator.services import (
    PgMeter,
    StageBudgets,
    intake,
    require_per_video_budget,
    seed_cap_budgets,
)
from amw_orchestrator.task_io import TaskIo
from tests.orchestrator.evidence_fake import FakeEvidenceStatuses

M = 1_000_000
FAKE_PROVIDERS = ("fake_llm", "fake_tts")
LONG = ProductionTypeKey.CHANNEL_LONG_FORM
PAID = {
    "agent_04.research_pack": 100_000,
    "agent_05.script_draft": 100_000,
    "agent_06.claim_extraction": 100_000,
    "agent_06.claim_verification": 100_000,
    "agent_07.voice_synthesis": 100_000,
    "agent_08.asset_sourcing": 100_000,
    "agent_09.shot_plan": 100_000,
    "agent_11.thumbnail_variants": 100_000,
    "agent_16.compliance_gate": 100_000,
    "agent_16.quality_score": 100_000,
}
LLM_TYPES = frozenset({"agent_05.script_draft", "agent_09.shot_plan"})


class Open(BaseModel):
    """Permissive stand-in model for the payload registry of the fake world."""

    model_config = ConfigDict(extra="allow")


def no_plugins(_registry: PayloadSchemaRegistry) -> tuple[str, ...]:
    """Skip the agents' real payload plugins: these tests use stand-in models (``Open``) for the
    schema names of the graph; the real models are covered in ``test_agent_payloads.py``."""
    return ()


def schema_registry(graph: tuple[Stage, ...]) -> PayloadSchemaRegistry:
    reg = PayloadSchemaRegistry()
    for s in graph:
        reg.register(f"{s.task_type}.input", "1.0.0", Open)
        reg.register(f"{s.task_type}.output", "1.0.0", Open)
    reg.register("svc_s07.request_approval.input", "1.0.0", Open)
    reg.register("svc_s07.request_approval.output", "1.0.0", Open)
    return reg


@dataclass
class Seed:
    org_id: str
    workspace_id: str
    channel_id: str
    owner: str
    project_id: str
    workers: dict[ResourceClass, Any]


def set_channel_category(dsn: str, channel_id: str, category: str | None) -> None:
    """Test setup: write ``channels.category`` as the table owner (bypasses RLS on purpose)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "UPDATE channels SET category = %s WHERE id = %s",
            (category, CHANNEL.to_uuid(channel_id)),
        )


def seed(dsn: str) -> Seed:
    org, wsp, chn, usr, prj = (new_uuid7() for _ in range(5))
    workers: dict[ResourceClass, Any] = {}
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO organisations (id, name, slug, kind, status, is_platform_owner)"
            " VALUES (%s, 'TEST org', %s, 'CLIENT', 'ACTIVE', false)",
            (org, f"orch-{org.hex[-12:]}"),
        )
        conn.execute(
            "INSERT INTO workspaces (id, org_id, name, status) VALUES (%s, %s, 'main', 'ACTIVE')",
            (wsp, org),
        )
        conn.execute(
            "INSERT INTO channels (id, org_id, workspace_id, platform, title, language,"
            " category, status) VALUES (%s, %s, %s, 'YOUTUBE', 'TEST channel', 'mr-IN',"
            " 'philosophy', 'DRAFT')",
            (chn, org, wsp),
        )
        conn.execute(
            "INSERT INTO projects (id, org_id, workspace_id, channel_id, name, kind, status,"
            " default_production_type) VALUES (%s, %s, %s, %s, 'TEST series', 'SERIES',"
            " 'ACTIVE', 'CHANNEL_LONG_FORM')",
            (prj, org, wsp, chn),
        )
        conn.execute(
            "INSERT INTO users (id, email, display_name, status)"
            " VALUES (%s, %s, 'TEST owner', 'ACTIVE')",
            (usr, f"owner-{usr.hex[-8:]}@example.invalid"),
        )
        conn.execute(
            "INSERT INTO memberships (id, org_id, user_id, role, status)"
            " VALUES (%s, %s, %s, 'ORG_OWNER', 'ACTIVE')",
            (new_uuid7(), org, usr),
        )
        for key in (LONG, ProductionTypeKey.SHORTS):
            pt = record(key)
            conn.execute(
                "INSERT INTO production_types (id, key, version, status, tier, record,"
                " record_sha256) VALUES (%s, %s, %s, 'IN_DEVELOPMENT', 'TIER_0', %s, %s)"
                " ON CONFLICT DO NOTHING",
                (new_uuid7(), key.value, pt.version, json.dumps(pt.to_doc()), record_sha256(pt)),
            )
        caps = [c.value for c in Capability]
        for rc in (ResourceClass.LIGHT, ResourceClass.AI_IO, ResourceClass.HEAVY_CPU):
            wid = new_uuid7()
            conn.execute(
                "INSERT INTO workers (id, logical_name, capabilities, resource_classes,"
                " max_concurrency, status, software_version) VALUES (%s, %s, %s, %s, 1,"
                " 'IDLE', 'test')",
                (wid, f"orchtest-{rc.value.lower()}-{wid.hex[-6:]}", caps, [rc.value]),
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


class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        return int(time.monotonic() * 1000)


def ok_output(
    schema: str, data: dict[str, Any], *, results: list[dict[str, Any]] | None = None
) -> TaskOutput:
    return TaskOutput.model_validate(
        {
            "status": "SUCCEEDED",
            "payload": {"payload_schema": schema, "payload_schema_version": "1.0.0", "data": data},
            "output_refs": [],
            "quality_score": None,
            "confidence": None,
            "validation_results": results or [],
            "duration": 1,
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
                "type": "CONTINUE",
                "wait_reason": None,
                "escalation_level": None,
                "reason": "test",
            },
            "downstream_agent": None,
            "timestamp": now_z(),
        }
    )


def gate_fail(check: str, remedy: str | None) -> dict[str, Any]:
    return {
        "check_id": check,
        "kind": "DETERMINISTIC",
        "verdict": "FAIL",
        "blocking": True,
        "message": "scripted failure",
        "gate": True,
        "remedy_stage_id": remedy,
    }


@dataclass
class FakeWorld:
    """Scriptable workers: one ``TaskWorker`` serves every task type and dispatches on
    ``ctx.stage_id``; ``fail_gate[stage]`` is a list consumed one run at a time."""

    llm: MeteredLlm | None = None
    fail_gate: dict[str, list[list[dict[str, Any]]]] = field(default_factory=dict)
    calls: list[tuple[str, int, int]] = field(default_factory=list)
    seen_finance: list[bool] = field(default_factory=list)
    on_call: Callable[[str], None] | None = None
    task_types: dict[str, str] = field(default_factory=dict)

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        stage = str(ctx.stage_id)
        self.calls.append((stage, ctx.iteration, ctx.attempt_no))
        if self.on_call is not None:
            self.on_call(stage)
        task_type = str(task_input.payload.payload_schema).removesuffix(".input")
        if self.llm is not None and task_type in LLM_TYPES:
            self.llm.complete(
                LlmRequest(
                    model="fake-model",
                    system="s",
                    messages=(LlmMessage(role="user", content=stage),),
                    max_output_tokens=8,
                ),
                idempotency_key="idk_"
                + hashlib.sha256(f"{ctx.task_id}{ctx.attempt_no}".encode()).hexdigest(),
            )
        results: list[dict[str, Any]] = []
        queue = self.fail_gate.get(stage)
        if queue:
            results = queue.pop(0)
        return ok_output(
            f"{task_type}.output",
            {"stage": stage, "iteration": ctx.iteration},
            results=results,
        )


class FakeBuilder:
    def __init__(self, world: FakeWorld) -> None:
        self.world = world

    def build(self, ctx: BuildContext) -> BuiltInput:
        self.world.seen_finance.append(ctx.job.finance_rules_apply)
        return BuiltInput(
            f"{ctx.stage.task_type}.input",
            "1.0.0",
            {
                "stage": ctx.stage.stage_id,
                "iteration": ctx.iteration,
                "upstream": sorted(ctx.upstream),
                "feedback": [r.check_id for r in ctx.revision_feedback],
            },
        )


class FakeRegistry:
    def __init__(self, world: FakeWorld, approval: ApprovalWorker) -> None:
        self.world, self.approval = world, approval
        self.builder = FakeBuilder(world)

    def worker_for(self, stage: Stage) -> Any:
        return self.approval if stage.task_type == "svc_s07.request_approval" else self.world

    def builder_for(self, stage: Stage) -> Any:
        return self.builder


def approval_output(
    subject_sha256: str,
    *,
    kind: str = "FINAL_VIDEO",
    state: str = "APPROVED",
    target_stage: str | None = None,
    evidence_ids: list[str] | None = None,
) -> dict[str, object]:
    """An ``svc_s07.request_approval.output`` document in the CCR-283 PROVISIONAL shape."""
    from amw_core.ids import APPROVAL, OWNER_EVIDENCE

    owner = state in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}
    return {
        "approval_id": str(APPROVAL.new()),
        "approval_kind": kind,
        "state": state,
        "subject_sha256": subject_sha256,
        "evidence_ids": evidence_ids
        if evidence_ids is not None
        else ([str(OWNER_EVIDENCE.new())] if owner else []),
        "parsed_target_stage_id": target_stage,
    }


class TestDesk:
    """S7 stand-in: the owner's decision exists only after ``decide`` (test of the boundary). Its
    payloads have the CCR-283 shape (a real approval ID and confirmed-evidence ID per decision)."""

    __test__ = False

    def __init__(self, state: str = "APPROVED") -> None:
        self.state = state
        self.opened: list[str] = []
        self.decisions: set[str] = set()
        self.last_subject_sha256: str | None = None
        self.evidence = FakeEvidenceStatuses()

    def _payload(self, task_input: TaskInput, state: str) -> dict[str, object]:
        data = task_input.payload.data or {}
        subject = data.get("subject") or {}
        self.last_subject_sha256 = str(subject.get("sha256", "0" * 64))
        owner = state in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}
        evidence = (  # TEST_FIXTURE owner evidence bound to the subject of the request
            [
                self.evidence.record(
                    str(task_input.org_id), str(subject.get("kind", "")), str(subject.get("id", ""))
                )
            ]
            if owner
            else []
        )
        return approval_output(
            self.last_subject_sha256,
            evidence_ids=evidence,
            kind=str(data.get("approval_kind", "FINAL_VIDEO")),
            state=state,
            target_stage="s05_script" if state == "CHANGES_REQUESTED" else None,
        )

    def open(self, task_input: TaskInput, ctx: ExecContext) -> Mapping[str, object]:
        self.opened.append(str(ctx.task_id))
        return self._payload(task_input, "PENDING")

    def decision(self, task_input: TaskInput, ctx: ExecContext) -> Mapping[str, object] | None:
        if str(ctx.task_id) not in self.decisions:
            return None
        return self._payload(task_input, self.state)

    def decided(self, job_id: str, task_id: str) -> bool:
        return task_id in self.decisions


@dataclass
class Rig:
    dsn: str
    seed: Seed
    tenancy: PgTenancy
    jobs: PgJobStore
    queue: PgTaskQueue
    guard: BudgetGuardCore
    ledger: PgCostLedger
    meter: PgMeter
    storage: LocalDiskStorage
    world: FakeWorld
    desk: TestDesk
    runner: GraphRunner
    graph: tuple[Stage, ...]
    registry: Any
    make_runner: Callable[[], GraphRunner]

    def set_channel_category(self, category: str | None) -> None:
        """Test setup only: the job category is read from ``channels.category`` (CCR-273, D13); the
        seeded channel stores ``philosophy`` (unknown = finance), so a test that needs another
        value writes it here as the table owner, outside the code under test."""
        set_channel_category(self.dsn, self.seed.channel_id, category)

    def intake(
        self, category: str | None = "youtube_general", title: str = "Seneca test"
    ) -> JobFacts:
        self.set_channel_category(category)
        topic = OwnerTopic.model_validate(
            {
                "schema_version": "1.0.0",
                "title": title,
                "brief": None,
                "angle": None,
                "language": "mr-IN",
                "video_kind": "GENERAL",
                "course_chapter_pointer": None,
                "owner_references": [],
                "target_duration_ms": 60_000,
                "shorts_wanted": False,
            }
        )
        return intake(
            self.tenancy,
            self.jobs,
            org_id=self.seed.org_id,
            workspace_id=self.seed.workspace_id,
            project_id=self.seed.project_id,
            channel_id=self.seed.channel_id,
            topic=topic,
            production_type=LONG,
            version=2,
            correlation_id=str(CORRELATION.new()),
        )


def build_rig(
    dsn: str,
    root: Path,
    *,
    graph: tuple[Stage, ...] | None = None,
    paid: Mapping[str, int] | None = None,
    per_video_budget: bool = True,
    max_attempts: int = 2,
    calendar_allows: bool = True,
    registry_factory: Callable[[ApprovalWorker, LocalDiskStorage], Any] | None = None,
    schemas: PayloadSchemaRegistry | None = None,
    build_services: Any | None = None,
    desk: TestDesk | None = None,
    real_run: bool = False,
) -> Rig:
    s = seed(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        # the claim is cross-tenant and not keyed by task: rows left live by an earlier test of
        # this session must not be handed to this runner (test isolation only)
        conn.execute(
            "UPDATE task_queue SET status = 'CANCELLED' WHERE status IN ('READY', 'CLAIMED')"
        )
    tenancy = PgTenancy(dsn_connection_factory(dsn, role="amw_app"))
    audit = PgAuditLog()
    jobs = PgJobStore(audit, max_tasks_per_job=400)
    queue = PgTaskQueue(dsn_connection_factory(dsn, role="amw_app"))
    settings = load_settings(environ={}).model_copy(
        update={"finance": FinanceSettings(currency_minor_exponent={"INR": 2, "USD": 2})}
    )
    backend = PgBudgetBackend()
    guard = BudgetGuardCore(backend, settings, _Clock(), audit)
    ledger = PgCostLedger()
    if per_video_budget:
        with tenancy.transaction(TenantContext(s.org_id, ActorRef(s.owner))) as tx:  # type: ignore[arg-type]
            seed_cap_budgets(
                backend.create_budget,
                tx,
                org_id=s.org_id,
                per_video_cap_micros=5 * M,
                pilot_cap_micros=50 * M,
                currency="USD",
                minor_exponent=2,
                providers=FAKE_PROVIDERS,
            )
    meter = PgMeter(tenancy, ledger, guard, jobs, allowed_providers=lambda p: p in FAKE_PROVIDERS)
    graph = graph or job_graph(LONG)
    world = FakeWorld()
    world.llm = MeteredLlm(FakeLlmAdapter(), meter, 1_000)
    desk = desk or TestDesk()
    storage = LocalDiskStorage(root)
    approval = ApprovalWorker(desk, now_z)
    registry = (
        registry_factory(approval, storage)
        if registry_factory is not None
        else FakeRegistry(world, approval)
    )
    budgets = StageBudgets(dict(PAID if paid is None else paid), "USD", 3_600_000, 40)

    def make_runner() -> GraphRunner:
        runner = GraphRunner(
            tenancy=tenancy,
            jobs=jobs,
            queue=queue,
            budget=guard,
            executor=TaskExecutor(
                registry,
                schemas=schemas or schema_registry(graph),
                load_plugins=no_plugins,
            ),
            approvals=desk,
            budgets=budgets,
            calendar=_Cal(calendar_allows),
            config=RunnerConfig(
                max_attempts=max_attempts,
                lease_ms=3_600_000,
                workers=s.workers,
                capabilities=tuple(Capability),
            ),
            task_io=TaskIo(storage),
            spend=meter,
            build_services=build_services,
            evidence=desk.evidence,
            real_run=real_run,
            require_per_video=lambda tx, job_id, cur: require_per_video_budget(
                guard, tx, job_id, cur
            ),
        )
        runner.set_max_revision_loops(record(LONG).limits.max_revision_loops)
        return runner

    runner = make_runner()
    return Rig(
        dsn, s, tenancy, jobs, queue, guard, ledger, meter, storage, world, desk, runner, graph,
        registry,
        make_runner,
    )  # fmt: skip


class _Cal:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed

    def render_allowed(self, dt: datetime) -> bool:
        return self.allowed


def db_rows(dsn: str, query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(query, params).fetchall()
