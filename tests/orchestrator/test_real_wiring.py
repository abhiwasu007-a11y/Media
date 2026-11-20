# ruff: noqa: E501, PT018
"""Production wiring of a REAL_RUN (``ProductionWiring``). PLUMBING TEST - NOT QUALITY.

Providers are faked at the HTTP transport level (mock transports that record any request; no
network, no key value, no paid call). The run goes through the sealed preflight, builds the real
adapters from it, builds the ports, and ends in a typed MISSING_DEPENDENCY listing the exact ports
that have no production wiring."""

import dataclasses
import io
from pathlib import Path
from typing import Any

import pytest

from amw_core.errors import ConfigInvalidError, MissingDependencyError
from amw_orchestrator.composition import compose
from amw_orchestrator.real_wiring import (
    AGENT_TASK_TYPES,
    LazyRealWorker,
    PortSet,
    ProductionWiring,
    WorkerSpec,
    required_parameters,
    summarize,
    unmet_ports,
    worker_specs,
)
from amw_orchestrator.registry import job_graph
from amw_orchestrator.run_job import main
from amw_orchestrator.run_settings import load_run_entry_settings
from amw_runtime.config import load_runtime_config
from amw_runtime.providers import build_providers
from tests.adapters.conftest import packaged_with_render_minutes  # noqa: F401  (autouse)
from tests.adapters.mock_providers import ANTHROPIC_SECRET, TEST_ENV
from tests.adapters.preflight_support import EVENING, limits
from tests.orchestrator.run_job_world import SATURDAY, World, make_world
from tests.orchestrator.test_run_job import REAL_ENV, NoNetwork, lookup_factory
from tests.orchestrator.world import LONG

pytestmark = pytest.mark.integration


@pytest.fixture
def world(pg_dsn: str, tmp_path: Path) -> World:
    return make_world(pg_dsn, tmp_path)


def _compose(world: World, net: NoNetwork, run_file: Path | None = None, **kw: Any) -> Any:
    records = [r for r in limits(world.seed.org_id) if r.provider]
    return compose(
        world.request(confirmations=tuple(records)), config=load_runtime_config(REAL_ENV),
        settings=world.settings(),
        run=load_run_entry_settings(run_file or world.run_entry_file()), env=REAL_ENV,
        evidence_factory=lookup_factory(world, records), transports=net.transports(),
        render_start=EVENING, clock=lambda: SATURDAY, **kw,
    )  # fmt: skip


def test_the_specs_cover_the_15_agent_task_types_of_the_graph() -> None:
    assert len(AGENT_TASK_TYPES) == 15
    in_graph = {s.task_type for s in job_graph(LONG)}
    assert set(AGENT_TASK_TYPES) <= in_graph
    for spec in worker_specs().values():
        assert spec.parameters, spec.task_type


def test_real_run_builds_the_wiring_and_stops_at_the_missing_ports(world: World) -> None:
    net = NoNetwork()
    with pytest.raises(MissingDependencyError) as exc:
        _compose(world, net)
    err = exc.value
    unmet: list[str] = err.details["unmet"]
    assert err.code.endswith("MISSING_DEPENDENCY")
    for needed in (
        "agent_05.script_draft:resolver",  # InputResolver
        "agent_08.asset_sourcing:brand_kits",  # brand kit reader
        "agent_05.script_draft:chunks",  # library chunk index
        "agent_16.quality_score:groups",  # GroupRequestBuilder
        "agent_06.claim_verification:quotes",  # quote check needs library config
    ):
        assert needed in unmet
    # ports with a real implementation are provided, not listed
    assert not any(
        u.endswith((":llm", ":tenancy", ":storage", ":clock", ":checkpoints")) for u in unmet
    )
    assert not any(
        u.startswith("agent_16.quality_score:")
        and u.split(":")[1] in {"rows", "store", "budget", "costs", "llm"}
        for u in unmet
    )
    provided = set(err.details["provided"])
    assert {
        "llm",
        "tts",
        "script_rows",
        "job_destination",
        "fact_rows",
        "score_store",
        "budget_guard",
        "approval_worker",
        "library_ref",
    } <= provided
    assert net.requests == []  # nothing was called


def test_unset_tts_provider_refuses_naming_the_missing_choice(world: World) -> None:
    net = NoNetwork()
    with pytest.raises(MissingDependencyError) as exc:
        _compose(world, net, world.run_entry_file(tts_provider=None))
    assert exc.value.details["unmet"] == ["tts.provider"]
    assert net.requests == []


def test_an_unknown_tts_provider_is_refused_not_replaced(world: World) -> None:
    net = NoNetwork()
    with pytest.raises(ConfigInvalidError):
        _compose(world, net, world.run_entry_file(tts_provider="some_free_engine"))


def test_the_seeded_run_entry_file_has_no_tts_default() -> None:
    assert load_run_entry_settings().tts.provider is None


def test_missing_one_authorisation_refuses_that_provider(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    net = NoNetwork()
    records = [r for r in limits(world.seed.org_id) if r.provider]
    captured: dict[str, Any] = {}

    real_build = build_providers

    def spy_build(config: Any, *, preflight: Any, **kw: Any) -> Any:
        captured["report"] = preflight
        return real_build(config, preflight=preflight, **kw)

    monkeypatch.setattr("amw_orchestrator.composition.build_providers", spy_build)
    with pytest.raises(MissingDependencyError):
        _compose(world, net)
    report = captured["report"]
    assert {a.provider for a in report.provider_authorisations} == {"anthropic", "elevenlabs"}
    for dropped in ("anthropic", "elevenlabs"):
        partial = dataclasses.replace(
            report,
            provider_authorisations=tuple(
                a for a in report.provider_authorisations if a.provider != dropped
            ),
        )
        with pytest.raises(ConfigInvalidError):
            build_providers(
                load_runtime_config(REAL_ENV),
                preflight=partial,
                env=REAL_ENV,
                guard_for=lambda _a: None,  # type: ignore[arg-type,return-value]
                transports=net.transports(),
            )
    assert records and net.requests == []


def test_no_key_value_reaches_the_output_of_a_refused_real_run(world: World) -> None:
    net = NoNetwork()
    records = [r for r in limits(world.seed.org_id) if r.provider]
    out = io.StringIO()
    code = main(
        ["--request", str(world.request_file(world.request(confirmations=tuple(records)))),
         "--run-entry-config", str(world.run_entry_file())],
        world.env(**REAL_ENV), out=out, evidence_factory=lookup_factory(world, records),
        transports=net.transports(), render_start=EVENING, clock=lambda: SATURDAY,
    )  # fmt: skip
    text = out.getvalue()
    assert code == 2 and "MISSING_DEPENDENCY" in text and "unmet:" in text
    for name, value in TEST_ENV.items():
        assert value not in text, name
    assert TEST_ENV[ANTHROPIC_SECRET] not in text
    assert net.requests == []


def test_dry_run_is_unchanged_by_the_wiring(world: World) -> None:
    out = io.StringIO()
    code = main(
        ["--request", str(world.request_file()), "--run-entry-config", str(world.run_entry_file(None))],
        world.env(AMW_RUNTIME_MODE="DRY_RUN"), out=out, clock=lambda: SATURDAY,
    )  # fmt: skip
    assert code == 0 and "status: DELIVERED" in out.getvalue()


# ---- the wiring unit: specs, lazy workers, fail closed --------------------------------------


def test_a_fake_provider_set_is_refused_by_the_port_builder(world: World) -> None:
    from amw_orchestrator.real_wiring import build_port_set

    holder: dict[str, Any] = {}

    class Spy(ProductionWiring):
        def registry(self, ctx: Any, approval: Any) -> Any:
            holder["ctx"] = ctx
            raise MissingDependencyError("stop", details={"unmet": ["x"]})

    records = [r for r in limits(world.seed.org_id) if r.provider]
    with pytest.raises(MissingDependencyError):
        compose(
            world.request(confirmations=tuple(records)), config=load_runtime_config(REAL_ENV),
            settings=world.settings(), run=load_run_entry_settings(world.run_entry_file()),
            env=REAL_ENV, real_wiring=Spy(), evidence_factory=lookup_factory(world, records),
            transports=NoNetwork().transports(), render_start=EVENING, clock=lambda: SATURDAY,
        )  # fmt: skip
    ctx = holder["ctx"]
    fake_ctx = dataclasses.replace(ctx, providers=dataclasses.replace(ctx.providers, real=False))
    with pytest.raises(ConfigInvalidError):
        build_port_set(fake_ctx)
    ports = build_port_set(ctx)
    assert ctx.config.per_video_cap_micros == 5_000_000  # the per-video hard stop (USD 5), config
    assert "budget_guard" in ports and "ids" in ports


def test_a_spec_with_every_port_and_a_factory_builds_lazily_from_the_first_input() -> None:
    ports = PortSet({"llm": object(), "storage": object()})
    seen: list[str] = []

    class W:
        def run(self, ti: Any, ctx: Any) -> Any:
            return "out"

    def factory(p: PortSet, ti: Any) -> Any:
        seen.append(ti.org_id)
        return W()

    spec = WorkerSpec("agent_x.t", ("llm", "storage"), factory)
    assert spec.unmet(ports.ports) == ()
    lazy = LazyRealWorker(spec, ports)
    assert seen == []  # nothing is built before the first input
    ti = type("TI", (), {"org_id": "org_1"})()
    assert str(lazy.run(ti, None)) == "out"  # type: ignore[arg-type]
    assert str(lazy.run(ti, None)) == "out"  # type: ignore[arg-type]
    assert seen == ["org_1"]
    with pytest.raises(MissingDependencyError):
        LazyRealWorker(WorkerSpec("agent_x.t", (), None), ports)


def test_unmet_ports_names_task_and_parameter_and_summarises() -> None:
    specs = {"a.b": WorkerSpec("a.b", ("llm", "mystery"), None)}
    unmet = unmet_ports(specs, PortSet({"llm": 1}))
    assert unmet == ["a.b:mystery"] and summarize(unmet) == {"a.b": ["mystery"]}


def test_required_parameters_read_the_agent_classes() -> None:
    class P:
        def __init__(self, a: int, b: int = 1, *, c: int) -> None: ...

    assert required_parameters(P) == ("a", "c")
