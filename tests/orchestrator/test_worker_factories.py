"""Production worker factories (``amw_orchestrator.worker_factories``). PLUMBING TEST - NOT QUALITY.

Every factory is built here over a ``PortSet`` whose ports are doubles at the PROVIDER level: the
LLM and TTS adapters, the stores and the repositories are inert objects that fail the test if a
factory USES them at construction time (construction composes only: no network, no process, no
database read). The agents' own entry points are the real classes. No key, no paid call."""

import contextlib
from pathlib import Path
from typing import Any

import pytest

from amw_core.errors import ConfigInvalidError, MissingDependencyError
from amw_orchestrator.prompt_store import PinnedPrompts, load_prompt_registry, resolve_prompts_dir
from amw_orchestrator.real_wiring import (
    APPROVAL_TASK_TYPE,
    DELIVERY_TASK_TYPE,
    PortSet,
    ProductionWiring,
    unmet_ports,
    worker_specs,
)
from amw_orchestrator.worker_factories import FACTORIES
from tests.orchestrator.run_job_world import EXPECTED_UNMET_PORTS


class Inert:
    """A provider double that must not be touched while a worker is being constructed."""

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)

    def __getattr__(self, attr: str) -> Any:
        raise AssertionError(f"{self._name}.{attr} was used while building a worker")


SHARED = (
    "llm", "tts", "storage", "tenancy", "clock", "budget_guard", "cost_ledger", "audit",
    "idempotency", "checkpoints", "script_rows", "job_destination", "fact_rows", "score_store",
    "script_registry", "render_hash_reader", "approval_worker",
)  # fmt: skip


ENTRY_POINTS = {
    "agent_04.research_pack": "ResearchPackStep",
    "agent_05.script_draft": "ScriptDraftStage",
    "agent_06.claim_extraction": "ClaimExtractionStep",
    "agent_06.claim_verification": "ClaimVerificationStep",
    "agent_07.voice_synthesis": "VoiceSynthesisStage",
    "agent_07.audio_master": "AudioMasterStage",
    "agent_08.asset_sourcing": "AssetSourcingStage",
    "agent_09.shot_plan": "ShotPlanTask",
    "agent_10.render": "RenderStage",
    "agent_10.subtitles": "SubtitleStage",
    "agent_10.technical_qc": "QcStage",
    "agent_11.thumbnail_variants": "ThumbnailStage",
    "agent_16.compliance_gate": "ComplianceGateStage",
    "agent_16.quality_score": "QualityScoreStage",
    "svc_s02.uniqueness_check": "UniquenessCheckStage",
}  # fmt: skip


def _prompts() -> PinnedPrompts:
    root = resolve_prompts_dir("docs/v4/prompts")
    assert root is not None
    return PinnedPrompts(root, load_prompt_registry())


def _configs() -> dict[str, Any]:
    """Config objects at the data level (the agents' own validated models, built from the
    agents' fixtures): the constructors of some entry points read them."""
    from tests.agents.agent_04_research_knowledge.conftest import make_settings as s04
    from tests.agents.agent_05_scriptwriter.support import make_settings as s05
    from tests.agents.agent_06_fact_checker.support import make_settings as s06

    return {
        "agent_04.research_pack:settings": s04(),
        "agent_05.script_draft:settings": s05(),
        "agent_06.claim_extraction:settings": s06(),
        "agent_06.claim_verification:settings": s06(),
    }


def full_port_set() -> PortSet:
    """Every port of every worker: the shared ones, then one inert double per remaining port."""
    ports: dict[str, Any] = {name: Inert(name) for name in SHARED}
    ports["prompts"] = _prompts()
    ports["storage"] = Inert("storage")
    for port in EXPECTED_UNMET_PORTS:
        ports[port] = Inert(port)
    ports.update(_configs())
    return PortSet(ports)


@pytest.fixture(scope="module")
def ports() -> PortSet:
    return full_port_set()


def test_there_is_a_factory_for_each_of_the_15_agent_task_types() -> None:
    assert set(FACTORIES) == set(worker_specs())
    assert len(FACTORIES) == 15
    assert all(spec.factory is not None for spec in worker_specs(FACTORIES).values())


def test_the_default_wiring_carries_the_production_factories() -> None:
    assert all(spec.factory is not None for spec in ProductionWiring()._specs.values())


def test_the_double_set_covers_every_remaining_port_and_nothing_is_unmet(ports: PortSet) -> None:
    assert unmet_ports(worker_specs(FACTORIES), ports) == []


@pytest.mark.parametrize("task_type", sorted(FACTORIES))
def test_every_factory_builds_its_worker_from_provider_doubles(
    task_type: str, ports: PortSet
) -> None:
    ti = type("TI", (), {"org_id": "org_x"})()
    worker = FACTORIES[task_type](ports, ti)
    assert callable(worker.run)
    assert type(worker).__name__ == ENTRY_POINTS[task_type]


@pytest.mark.parametrize("task_type", sorted(FACTORIES))
def test_a_missing_port_is_a_typed_refusal_naming_it_never_a_fallback(
    task_type: str, ports: PortSet
) -> None:
    own = sorted(p for p in EXPECTED_UNMET_PORTS if p.startswith(task_type + ":"))
    assert own, task_type
    ti = type("TI", (), {"org_id": "org_x"})()
    spec = {task_type: worker_specs(FACTORIES)[task_type]}
    for victim in own:
        reduced = PortSet({k: v for k, v in ports.ports.items() if k != victim})
        assert unmet_ports(spec, reduced) == [victim]  # the refusal names exactly this port
        with contextlib.suppress(MissingDependencyError):
            FACTORIES[task_type](reduced, ti)  # a direct read of the port is typed too


def test_the_registry_has_every_worker_once_all_ports_exist(ports: PortSet) -> None:
    wiring = ProductionWiring()
    approval = Inert("approval")
    registry = wiring.build_registry(ports, approval)  # type: ignore[arg-type]
    names = set(registry.workers)  # type: ignore[attr-defined]
    assert names == {*FACTORIES, APPROVAL_TASK_TYPE, DELIVERY_TASK_TYPE}
    assert registry.workers[APPROVAL_TASK_TYPE] is approval  # type: ignore[attr-defined]
    # the delivery worker is the real agent_13 stage over the job's storage (a typed worker)
    assert registry.workers[DELIVERY_TASK_TYPE].__class__.__name__ == "DeliveryStage"  # type: ignore[attr-defined]


def test_the_registry_refuses_with_every_remaining_port_when_the_set_is_the_real_one() -> None:
    shared = PortSet({**{name: Inert(name) for name in SHARED}, "prompts": _prompts()})
    with pytest.raises(MissingDependencyError) as exc:
        ProductionWiring().build_registry(shared, Inert("approval"))  # type: ignore[arg-type]
    assert set(exc.value.details["unmet"]) == EXPECTED_UNMET_PORTS


def test_the_prompt_store_is_pinned_to_the_released_files() -> None:
    store = _prompts()
    store.verify_all()
    assert set(store.registry) == {
        "agent_04/research_pack_notes.v1", "agent_04/research_pack_plan.v1",
        "agent_05/script_draft.v1", "agent_05/script_draft_section.v1",
        "agent_05/shorts_adaptation.v1", "agent_06/claim_extraction.v1",
        "agent_06/claim_verification.v1", "agent_08/candidate_rank.v1", "agent_08/query_plan.v1",
        "agent_09/shot_direction.v1", "agent_11/thumbnail_concepts.v1",
        "agent_16/compliance_gate.v1", "agent_16/compliance_gate_frames.v1",
        "agent_16/compliance_gate_paraphrase.v1", "agent_16/quality_score.v1",
    }  # fmt: skip


def test_the_pins_equal_the_files_in_the_repository() -> None:
    from amw_orchestrator.prompt_store import compute_registry

    root = resolve_prompts_dir("docs/v4/prompts")
    assert root is not None
    assert compute_registry(root) == dict(load_prompt_registry())


def test_a_changed_prompt_file_is_refused_before_any_call(tmp_path: Path) -> None:
    src = resolve_prompts_dir("docs/v4/prompts")
    assert src is not None
    for file in src.glob("agent_*/*.md"):
        target = tmp_path / file.parent.name / file.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(file.read_bytes())
    store = PinnedPrompts(tmp_path, load_prompt_registry())
    store.verify_all()
    victim = tmp_path / "agent_06_fact_checker" / "claim_extraction.v1.md"
    victim.write_bytes(victim.read_bytes() + b" ")
    with pytest.raises(ConfigInvalidError):
        store.text("agent_06/claim_extraction.v1")
    with pytest.raises(ConfigInvalidError):
        store.verify_all()
    victim.unlink()
    with pytest.raises(ConfigInvalidError):
        store.text("agent_06/claim_extraction.v1")


def test_an_unknown_or_malformed_prompt_id_is_refused() -> None:
    store = _prompts()
    for bad in ("agent_06/nope.v1", "claim_extraction", "../x", "agent_99/claim_extraction.v1"):
        with pytest.raises(ConfigInvalidError):
            store.text(bad)


def test_a_missing_prompt_directory_leaves_the_port_unwired_not_guessed(tmp_path: Path) -> None:
    assert resolve_prompts_dir(str(tmp_path / "absent")) is None


def test_a_broken_registry_file_is_config_invalid(tmp_path: Path) -> None:
    bad = tmp_path / "r.json"
    bad.write_text('{"prompts": {"agent_06/x.v1": "not-a-hash"}}', encoding="utf-8")
    with pytest.raises(ConfigInvalidError):
        load_prompt_registry(bad)
    with pytest.raises(ConfigInvalidError):
        load_prompt_registry(tmp_path / "absent.json")


def test_the_job_documents_stay_refused_until_the_inputs_lane_lands() -> None:
    """Brand kit, compliance profile and the other job documents have no production reader (the
    brand kit reader belongs to the inputs lane, CCR-290): fail closed, named."""
    wiring: Any = ProductionWiring()
    with pytest.raises(MissingDependencyError) as exc:
        wiring.job_documents(None, None)
    assert exc.value.details["unmet"] == ["job_documents"]
