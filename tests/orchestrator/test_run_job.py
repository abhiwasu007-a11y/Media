# ruff: noqa: E501, PT018
"""``run_job`` and the composition root. PLUMBING TEST - NOT QUALITY.

DRY_RUN: the real ``GraphRunner`` / builders / ``ApprovalWorker`` / agent_13 entry point on the
PostgreSQL tables behind fake providers and stand-in workers, started through ``main()``.
REAL_RUN: only the refusals and the wiring are exercised (preflight items, no key read, no adapter
before the sealed preflight, ``PgApprovalEvidencePort`` injected); no model, no network, no paid
call anywhere (the adapter transports are mocks that record a request if one is ever made)."""

import ast
import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from amw_core.errors import ConfigInvalidError, InputInvalidError, MissingDependencyError
from amw_core.owner_evidence_approvals import PgApprovalEvidencePort
from amw_core.owner_evidence_status import EvidenceStatusLookup
from amw_orchestrator import composition as composition_module
from amw_orchestrator.approval_desk import PgApprovalDesk
from amw_orchestrator.composition import (
    RealRunWiring,
    WiringContext,
    compose,
)
from amw_orchestrator.driver import RunReport, StageRun
from amw_orchestrator.executor import ApprovalWorker, BuildServices, JobDocuments, JobFacts
from amw_orchestrator.plumbing import (
    BANNER,
    DryRunEvidence,
    PlumbingServices,
    build_plumbing_registry,
    plumbing_schemas,
    seed_job_documents,
)
from amw_orchestrator.run_job import format_report, main, scrub
from amw_orchestrator.run_request import load_request
from amw_orchestrator.run_settings import load_run_entry_settings
from amw_orchestrator.services import intake
from amw_orchestrator.workers import read_workers
from amw_runtime.config import ENV_MODE, RunMode, RuntimeConfig, load_runtime_config
from amw_runtime.confirmations import ConfirmationRecord
from tests.adapters.conftest import packaged_with_render_minutes  # noqa: F401  (autouse)
from tests.adapters.mock_providers import ANTHROPIC_SECRET, ELEVENLABS_SECRET, TEST_ENV
from tests.adapters.preflight_support import EVENING, Lookup, limits
from tests.orchestrator.run_job_world import SATURDAY, World, make_world

pytestmark = pytest.mark.integration

DRY_ENV = {ENV_MODE: "DRY_RUN"}
REAL_ENV = {ENV_MODE: "REAL_RUN", "AMW_ENVIRONMENT": "development", **TEST_ENV}
SECRET_VALUE = TEST_ENV[ANTHROPIC_SECRET]


@pytest.fixture
def world(pg_dsn: str, tmp_path: Path) -> World:
    return make_world(pg_dsn, tmp_path)


def run_main(world: World, env: dict[str, str], **inject: Any) -> tuple[int, str]:
    out = io.StringIO()
    code = main(
        ["--request", str(world.request_file()), "--run-entry-config", str(world.run_entry_file())],
        world.env(**env),
        out=out,
        **inject,
    )
    return code, out.getvalue()


@contextmanager
def _lookup_of(records: list[ConfirmationRecord], org: str) -> Iterator[EvidenceStatusLookup]:
    yield Lookup(records, org)


def lookup_factory(world: World, records: list[ConfirmationRecord]) -> Any:
    return lambda _tenancy, org, _confirmations: _lookup_of(records, org)


class NoNetwork:
    """Transports for the real adapters: any request that reaches them is recorded and refused."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(500)

    def transports(self) -> dict[str, httpx.BaseTransport]:
        return {
            "anthropic": httpx.MockTransport(self._handle),
            "elevenlabs": httpx.MockTransport(self._handle),
        }


# ---- DRY_RUN end to end --------------------------------------------------------------------


def test_dry_run_through_main_delivers_with_the_plumbing_label(world: World) -> None:
    code, text = run_main(world, DRY_ENV, clock=lambda: SATURDAY)
    assert code == 0, text
    assert "status: DELIVERED" in text
    assert BANNER in text
    assert "mode: DRY_RUN (real_run=False)" in text
    assert "first stage not completed: none" in text
    assert f"commit {'a' * 40}" in text and "no-such-library" in text
    for stage in ("s04_research", "s16_auth", "s13_deliver"):
        assert f"  {stage}: COMPLETED" in text
    assert "  a_final: COMPLETED" in text  # the test desk decided, the run resumed


def test_dry_run_never_reads_a_key_even_when_every_secret_is_present(world: World) -> None:
    code, text = run_main(world, {**DRY_ENV, **TEST_ENV}, clock=lambda: SATURDAY)
    assert code == 0, text
    assert SECRET_VALUE not in text


def test_dry_run_composition_is_dry_all_the_way(world: World) -> None:
    comp = compose(
        world.request(), config=load_runtime_config(DRY_ENV), settings=world.settings(),
        run=load_run_entry_settings(world.run_entry_file()), env={**DRY_ENV, **TEST_ENV},
        clock=lambda: SATURDAY,
    )  # fmt: skip
    assert comp.mode is RunMode.DRY_RUN and comp.real_run is False
    assert comp.providers.real is False and comp.preflight is None
    assert comp.desk is not None and isinstance(comp.runner._evidence, DryRunEvidence)
    assert comp.runner._real_run is False
    assert comp.job.documents.brand_kit is not None  # plumbing documents were stored


def test_a_dry_run_resumes_a_finished_job_without_new_work(world: World) -> None:
    first = run_main(world, DRY_ENV, clock=lambda: SATURDAY)
    second = run_main(world, DRY_ENV, clock=lambda: SATURDAY)
    assert first[0] == 0 and "status: DELIVERED" in first[1]
    assert second[0] == 0, second[1]  # the same job (idempotent intake), not a second one
    assert [line for line in first[1].splitlines() if line.startswith("job:")] == [
        line for line in second[1].splitlines() if line.startswith("job:")
    ]


def test_the_render_window_guard_stops_a_dry_run_inside_the_guard_window(world: World) -> None:
    from datetime import UTC, datetime

    monday_in_session = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # 10:30 IST on a trading day
    code, text = run_main(world, DRY_ENV, clock=lambda: monday_in_session)
    assert code == 1
    assert "status: RENDER_WINDOW_CLOSED" in text
    assert "first stage not completed: s07_master (PENDING)" in text


# ---- REAL_RUN refusals ---------------------------------------------------------------------


def _unmet(text: str) -> set[str]:
    return {
        line.split(": ")[0].removeprefix("  - ")
        for line in text.splitlines()
        if line.startswith("  - ")
    }


def test_real_run_without_evidence_or_keys_lists_every_unmet_item(world: World) -> None:
    code, text = run_main(
        world, {ENV_MODE: "REAL_RUN", "AMW_ENVIRONMENT": "development"}, render_start=EVENING
    )
    assert code == 2
    assert text.startswith("REFUSED before start: 3 unmet item(s), nothing was run")
    assert _unmet(text) == {"PROVIDER_LIMIT:anthropic", "PROVIDER_LIMIT:elevenlabs", "SECRETS"}
    assert ANTHROPIC_SECRET in text and ELEVENLABS_SECRET in text  # names only
    assert SECRET_VALUE not in text


def test_the_production_evidence_lookup_refuses_a_connection_that_is_not_the_app_login(
    world: World,
) -> None:
    """The default lookup reads the evidence store as ``amw_app`` and checks the connection's own
    login (a SET ROLE is not enough): a superuser connection that merely switched role is refused
    with a typed error and nothing is run (fail closed, no secret in the output)."""
    records = [r for r in limits(world.seed.org_id) if r.provider]
    req = world.request(confirmations=tuple(records))
    out = io.StringIO()
    code = main(
        ["--request", str(world.request_file(req)), "--run-entry-config", str(world.run_entry_file())],
        world.env(**REAL_ENV), out=out, render_start=EVENING,
    )  # fmt: skip
    assert code == 2
    assert "PERMISSION_DENIED" in out.getvalue()
    assert SECRET_VALUE not in out.getvalue()


def test_the_production_evidence_lookup_knows_no_row_for_a_confirmation(world: World) -> None:
    """With the app login the lookup is built over the evidence store and, with no allowed record
    kind (CCR-260), answers nothing for any evidence ID."""
    import psycopg
    from psycopg import sql

    from amw_core.tenancy import PgTenancy
    from amw_orchestrator.composition import _pg_confirmation_evidence

    @contextmanager
    def app_login() -> Iterator[Any]:
        with psycopg.connect(world.dsn) as conn:
            conn.execute(sql.SQL("SET SESSION AUTHORIZATION amw_app"))
            conn.commit()
            yield conn

    records = [r for r in limits(world.seed.org_id) if r.provider]
    with _pg_confirmation_evidence(PgTenancy(app_login), world.seed.org_id, records) as lookup:
        assert all(lookup.get(str(r.evidence_id)) is None for r in records)


def test_real_run_refuses_a_missing_mode_and_a_mode_in_the_request(world: World) -> None:
    code, text = run_main(world, {})  # no AMW_RUNTIME_MODE: there is no default
    assert code == 2 and "CONFIG_INVALID" in text
    for field in ("real_run", "mode", "run_mode", "providers"):
        data = json.loads(world.request().model_dump_json()) | {field: "DRY_RUN"}
        path = world.tmp / "bad.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(InputInvalidError) as exc:
            load_request(path)
        assert field in exc.value.details["fields"]


def test_a_tampered_config_is_refused_before_anything_is_built(world: World) -> None:
    cfg = load_runtime_config(DRY_ENV)
    forged = RuntimeConfig.model_construct(**{**dict(cfg), "mode": "NOT_A_MODE"})
    with pytest.raises(ConfigInvalidError):
        compose(
            world.request(), config=forged, settings=world.settings(),
            run=load_run_entry_settings(world.run_entry_file()), env={},
        )  # fmt: skip


def test_a_passed_preflight_without_worker_wiring_ends_in_the_honest_refusal(world: World) -> None:
    net = NoNetwork()
    records = [r for r in limits(world.seed.org_id) if r.provider]
    req = world.request(confirmations=tuple(records))
    with pytest.raises(MissingDependencyError) as exc:
        compose(
            req, config=load_runtime_config(REAL_ENV), settings=world.settings(),
            run=load_run_entry_settings(world.run_entry_file()), env=REAL_ENV,
            evidence_factory=lookup_factory(world, records), transports=net.transports(),
            render_start=EVENING, clock=lambda: SATURDAY,
        )  # fmt: skip
    assert isinstance(exc.value, MissingDependencyError)
    assert exc.value.details["unmet"] == ["REAL_WIRING"]
    assert net.requests == []


class FakeWiring:
    """A test wiring: the plumbing registry behind the REAL composition (never executed here)."""

    def __init__(self) -> None:
        self.contexts: list[WiringContext] = []

    def registry(self, ctx: WiringContext, approval: ApprovalWorker) -> Any:
        self.contexts.append(ctx)
        return build_plumbing_registry(ctx_storage(ctx), approval, None)

    def schemas(self) -> Any:
        return plumbing_schemas()

    def job_documents(self, ctx: WiringContext, job: JobFacts) -> JobDocuments:
        return seed_job_documents(ctx_storage(ctx), job)

    def build_services(self, ctx: WiringContext) -> BuildServices:
        return PlumbingServices(load_run_entry_settings().delivery_limits())


def ctx_storage(ctx: WiringContext) -> Any:
    return ctx.storage


def test_real_composition_uses_the_real_providers_desk_and_evidence_port(world: World) -> None:
    net = NoNetwork()
    records = [r for r in limits(world.seed.org_id) if r.provider]
    wiring: RealRunWiring = FakeWiring()
    comp = compose(
        world.request(confirmations=tuple(records)), config=load_runtime_config(REAL_ENV),
        settings=world.settings(), run=load_run_entry_settings(world.run_entry_file()),
        env=REAL_ENV, real_wiring=wiring, evidence_factory=lookup_factory(world, records),
        transports=net.transports(), render_start=EVENING, clock=lambda: SATURDAY,
    )  # fmt: skip
    assert comp.mode is RunMode.REAL_RUN and comp.real_run is True
    assert comp.runner._real_run is True
    assert comp.providers.real is True  # built only from the passed preflight report
    assert comp.preflight is not None and {a.provider for a in comp.preflight.provider_authorisations} == {"anthropic", "elevenlabs"}  # fmt: skip
    assert comp.desk is None  # no test desk in a real run
    assert isinstance(comp.runner._evidence, PgApprovalEvidencePort)
    assert isinstance(comp.runner._desk, PgApprovalDesk)
    assert any("non-finance channel category" in n or "FIN_R10 and LAG not checked" in n for n in comp.notes)  # fmt: skip
    assert net.requests == []  # building the adapters made no request


def test_a_dry_config_never_reaches_the_real_path_even_with_everything_supplied(
    world: World,
) -> None:
    records = [r for r in limits(world.seed.org_id) if r.provider]
    spy = FakeWiring()

    def refusing_factory(*_args: Any) -> Any:
        raise AssertionError("the preflight evidence lookup must not be built in a dry run")

    net = NoNetwork()
    comp = compose(
        world.request(confirmations=tuple(records)), config=load_runtime_config(DRY_ENV),
        settings=world.settings(), run=load_run_entry_settings(world.run_entry_file()),
        env={**DRY_ENV, **TEST_ENV}, real_wiring=spy, evidence_factory=refusing_factory,
        transports=net.transports(), clock=lambda: SATURDAY,
    )  # fmt: skip
    assert comp.real_run is False and comp.providers.real is False and comp.preflight is None
    assert spy.contexts == [] and net.requests == []
    assert not isinstance(comp.runner._evidence, PgApprovalEvidencePort)


# ---- tenant isolation ----------------------------------------------------------------------


def test_a_request_naming_another_tenants_channel_creates_no_job(
    world: World, pg_dsn: str, tmp_path: Path
) -> None:
    other = make_world(pg_dsn, tmp_path / "other")
    req = world.request(channel_id=other.seed.channel_id)
    out = io.StringIO()
    code = main(
        ["--request", str(world.request_file(req)), "--run-entry-config", str(world.run_entry_file())],
        world.env(**DRY_ENV), out=out, clock=lambda: SATURDAY,
    )  # fmt: skip
    assert code == 2, out.getvalue()
    assert "REFUSED before start" in out.getvalue()


# ---- report, scrubbing, settings, workers --------------------------------------------------


def test_the_report_names_the_first_stage_that_failed_and_why(world: World) -> None:
    from amw_core.contracts import TaskOutput
    from amw_core.enums import TaskState
    from amw_orchestrator.outputs import failed_output, usage_dict

    comp = compose(
        world.request(), config=load_runtime_config(DRY_ENV), settings=world.settings(),
        run=load_run_entry_settings(world.run_entry_file()), env=DRY_ENV, clock=lambda: SATURDAY,
    )  # fmt: skip
    failed: TaskOutput = failed_output(
        InputInvalidError("bad input"), actor="agent_05", attempt_no=1,
        correlation_id=comp.job.correlation_id, usage=usage_dict(),
    )  # fmt: skip
    report = RunReport(comp.job.job_id, "FAILED", order=["s04_research", "s05_script"])
    assert report.status == "FAILED"
    report.stages["s04_research"] = StageRun("s04_research", "tsk_1", 0, TaskState.COMPLETED)
    report.stages["s05_script"] = StageRun("s05_script", "tsk_2", 0, TaskState.FAILED, failed)
    text = format_report(comp, report, world.request())
    assert "first stage not completed: s05_script (FAILED)" in text
    assert "PERMANENT.INPUT_INVALID: bad input" in text


def test_scrub_removes_secret_values_and_the_database_url() -> None:
    env = {"AMW_SECRET_X_API_KEY": "sk-live-abcdef", "PATH": "/usr/bin", "AMW_DATABASE__URL": "postgresql://u:pw123456@h/db"}  # fmt: skip
    text = scrub(
        "key sk-live-abcdef url postgresql://u:pw123456@h/db /usr/bin", env, ["other-secret-1"]
    )
    assert "sk-live-abcdef" not in text and "pw123456" not in text and "/usr/bin" in text


def test_seeded_settings_and_the_amw_core_budget_override(world: World) -> None:
    from amw_core.config import load_settings

    run = load_run_entry_settings()
    assert (
        run.worker_name_prefix == "" and run.stage_cost_budget_micros["agent_05.script_draft"] > 0
    )
    seeded = run.paid_budgets(world.settings())
    over = load_settings(environ={"AMW_LLM__TASKS": json.dumps({"agent_05.script_draft": {"model_tier": "MID", "cost_budget_micros": 7}})})  # fmt: skip
    assert run.paid_budgets(over)["agent_05.script_draft"] == 7
    assert seeded["agent_05.script_draft"] == run.stage_cost_budget_micros["agent_05.script_draft"]


def test_bad_run_entry_settings_are_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigInvalidError):
        load_run_entry_settings(bad)
    with pytest.raises(ConfigInvalidError):
        load_run_entry_settings(tmp_path / "missing.json")


def test_a_resource_class_without_a_registered_worker_is_refused(world: World) -> None:
    from amw_core.enums import ResourceClass
    from amw_core.tenancy import dsn_connection_factory

    conns = dsn_connection_factory(world.dsn, role="amw_app")
    workers, caps = read_workers(conns, [ResourceClass.LIGHT], ["IDLE"], "orchtest-")
    assert set(workers) == {ResourceClass.LIGHT} and caps
    with pytest.raises(MissingDependencyError) as exc:
        read_workers(conns, [ResourceClass.LIGHT, ResourceClass.PUBLISH], ["IDLE"], "orchtest-")
    assert exc.value.details["resource_classes"] == ["PUBLISH", "LIGHT"] or exc.value.details["resource_classes"] == ["PUBLISH"]  # fmt: skip


def test_missing_database_url_and_unreadable_request_are_refusals(tmp_path: Path) -> None:
    out = io.StringIO()
    code = main(["--request", str(tmp_path / "nope.json")], dict(DRY_ENV), out=out)
    assert code == 2 and "INPUT_INVALID" in out.getvalue()


def test_the_run_entry_code_has_no_operational_number_literals() -> None:
    """D16: operational limits are configuration. In the run entry modules a number literal other
    than 0, 1 or 2 may appear only in an upper-case constant (exit codes, a scrub length)."""
    root = Path(__file__).resolve().parents[2] / "packages/amw_orchestrator/src/amw_orchestrator"
    for name in ("composition.py", "run_job.py", "run_settings.py", "run_request.py", "workers.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        allowed: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and all(
                (isinstance(t, ast.Name) and t.id.isupper()) or isinstance(t, ast.Tuple)
                for t in node.targets
            ):
                allowed |= {id(n) for n in ast.walk(node)}
        bad = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, int)
            and not isinstance(n.value, bool)
            and n.value > 2
            and id(n) not in allowed
        ]
        assert bad == [], f"{name}: number literals at lines {bad}"


# ---- a dry run and a real run never share a job (CCR-299) ----------------------------------


def _real_comp(world: World) -> Any:
    records = [r for r in limits(world.seed.org_id) if r.provider]
    return compose(
        world.request(confirmations=tuple(records)), config=load_runtime_config(REAL_ENV),
        settings=world.settings(), run=load_run_entry_settings(world.run_entry_file()),
        env=REAL_ENV, real_wiring=FakeWiring(), evidence_factory=lookup_factory(world, records),
        transports=NoNetwork().transports(), render_start=EVENING, clock=lambda: SATURDAY,
    )  # fmt: skip


def _dry_comp(world: World) -> Any:
    return compose(
        world.request(), config=load_runtime_config(DRY_ENV), settings=world.settings(),
        run=load_run_entry_settings(world.run_entry_file()), env=DRY_ENV, clock=lambda: SATURDAY,
    )  # fmt: skip


def _task_count(world: World, comp: Any) -> int:
    from amw_core.ids import ActorRef, JobId, OrgId
    from amw_core.interfaces import TenantContext
    from amw_orchestrator.composition import build_infrastructure

    infra = build_infrastructure(
        world.settings(), load_run_entry_settings(world.run_entry_file()),
        load_runtime_config(DRY_ENV),
    )  # fmt: skip
    ctx = TenantContext(OrgId(comp.job.org_id), ActorRef("sys_operator"))
    with infra.tenancy.transaction(ctx) as tx:
        return len([t for t in infra.jobs.list_tasks(tx, JobId(comp.job.job_id)) if t.stage_id])


def test_a_real_run_never_resumes_the_job_of_an_earlier_dry_run(world: World) -> None:
    code, text = run_main(world, DRY_ENV, clock=lambda: SATURDAY)
    assert code == 0 and "status: DELIVERED" in text
    dry_job = next(ln for ln in text.splitlines() if ln.startswith("job:"))
    real = _real_comp(world)
    assert real.resume is False  # not the dry job: a fresh job with no tasks
    assert real.job.job_id not in dry_job
    assert _task_count(world, real) == 0  # nothing of the dry run was reused
    again = run_main(world, DRY_ENV, clock=lambda: SATURDAY)  # the dry job still resumes as before
    assert dry_job in again[1] and again[0] == 0


def test_a_dry_run_never_resumes_or_overwrites_the_job_of_an_earlier_real_run(
    world: World,
) -> None:
    real = _real_comp(world)  # intake created the real job (idempotent) and nothing ran
    dry = _dry_comp(world)
    assert dry.job.job_id != real.job.job_id
    assert dry.resume is False and real.resume is False
    code, text = run_main(world, DRY_ENV, clock=lambda: SATURDAY)
    assert code == 0 and "status: DELIVERED" in text
    assert real.job.job_id not in text  # the dry run worked on its own job
    assert _task_count(world, _real_comp(world)) == 0  # the real job stayed untouched
    assert _real_comp(world).job.job_id == real.job.job_id  # and a second real intake reuses it


def test_a_job_created_in_another_run_mode_is_refused_with_a_typed_error(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def mode_less(*args: Any, **kwargs: Any) -> JobFacts:
        return intake(*args, **{**kwargs, "run_mode": None})

    monkeypatch.setattr(composition_module, "intake", mode_less)
    for env in (DRY_ENV, REAL_ENV):
        with pytest.raises(InputInvalidError) as exc:
            compose(
                world.request(), config=load_runtime_config(env), settings=world.settings(),
                run=load_run_entry_settings(world.run_entry_file()), env=env,
                clock=lambda: SATURDAY,
            )  # fmt: skip
        assert [v.keyword for v in exc.value.details["violations"]] == ["RUN_MODE_JOB_MISMATCH"]
