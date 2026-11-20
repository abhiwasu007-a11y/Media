"""Production worker factories of a REAL_RUN (one per agent task type of the graph).

A factory takes the ``PortSet`` the wiring built and the first Task Input and returns the agent's
own entry point (``TaskWorker.run``). It only COMPOSES: every dependency is a port of the set
(sealed real adapters, the PostgreSQL adapters, core stores, hash-pinned prompts, settings and
config objects from data files) or is built here from those ports without any I/O. Nothing is
fetched, opened or spawned at construction time (no network, no process, no database read), and no
fake is reachable: a port that does not exist is a typed ``MISSING_DEPENDENCY`` naming it.

Port ids: a shared port is named by its role (``llm``, ``storage``, ``fact_rows``, ...); a port that
belongs to one worker is ``<task_type>:<parameter>`` (the same text the REAL refusal lists). Ports
no production implementation exists for are exactly the ones ``unmet_ports`` reports: see the
PR text and ``tests/orchestrator/run_job_world.py`` for the reason of each.
"""

from collections.abc import Callable, Mapping
from typing import Any, Final

from agent_04_research_knowledge.steps.research_pack import (
    ResearchPackStep,
    ResolverFactory,
)
from agent_04_research_knowledge.steps.research_pack import StepDeps as Agent04Deps
from agent_05_scriptwriter import ScriptDraftStage, ScriptDraftStep, ScriptRepository
from agent_05_scriptwriter.protocols import Ports as Agent05Ports
from agent_05_scriptwriter.steps.common import load_prompts
from agent_06_fact_checker.extraction_step import ClaimExtractionStep
from agent_06_fact_checker.prompts import FilePromptSource
from agent_06_fact_checker.verification_step import ClaimVerificationStep
from agent_07_voice_production.master_stage import AudioMasterStage, MasterDeps
from agent_07_voice_production.voice_stage import VoiceDeps, VoiceSynthesisStage
from agent_08_visual_assets.stage import AssetSourcingStage
from agent_09_video_director.protocol import ShotPlanTask
from agent_09_video_director.step import ShotPlanStep
from agent_10_video_editor.deps import StageDeps as Agent10Deps
from agent_10_video_editor.ffmpeg import ProcessFfmpegRunner
from agent_10_video_editor.guard import ThreadTimerFactory
from agent_10_video_editor.qc.stage import QcStage
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.subtitle_stage import SubtitleStage
from agent_11_thumbnail_design.composer import PillowComposer
from agent_11_thumbnail_design.prompting import PromptBundle
from agent_11_thumbnail_design.stage import StageDeps as Agent11Deps
from agent_11_thumbnail_design.stage import ThumbnailStage
from agent_11_thumbnail_design.templates import load_templates
from agent_16_compliance_qa.inputs.extractors import DocumentUniquenessExtractor
from agent_16_compliance_qa.scoring.stage import QualityScoreStage, ScoreStageDeps
from agent_16_compliance_qa.stages import (
    ComplianceGateStage,
    GateStageDeps,
    UniquenessCheckStage,
    UniquenessStageDeps,
)
from amw_core.contracts import TaskInput
from amw_core.errors import MissingDependencyError
from amw_core.interfaces import TaskWorker
from amw_orchestrator.prompt_store import PinnedPrompts, PromptTextStore
from amw_orchestrator.real_wiring import PortSet

PROMPT_IDS: Final[Mapping[str, str]] = {
    "agent_11": "agent_11/thumbnail_concepts.v1",
    "agent_16.policy": "agent_16/compliance_gate.v1",
    "agent_16.paraphrase": "agent_16/compliance_gate_paraphrase.v1",
    "agent_16.frames": "agent_16/compliance_gate_frames.v1",
    "agent_16.score": "agent_16/quality_score.v1",
}
"""Prompt IDs (identifiers of the released files, 27 section 4); the files are hash-pinned."""

Factory = Callable[[PortSet, TaskInput], TaskWorker]


def _own(ports: PortSet, task_type: str, name: str) -> Any:
    """The port that belongs to one worker (the text the refusal lists)."""
    return ports.get(f"{task_type}:{name}")


def _prompts(ports: PortSet) -> PinnedPrompts:
    found = ports.get("prompts")
    if not isinstance(found, PinnedPrompts):
        raise MissingDependencyError(
            "the prompt store is not wired", details={"unmet": ["prompts"]}
        )
    return found


def _from(ports: PortSet, task_type: str, *names: str) -> dict[str, Any]:
    return {n: _own(ports, task_type, n) for n in names}


# ---------------------------------------------------------------------------------------------
def agent_04(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_04.research_pack"
    library, storage = _own(ports, tt, "library"), ports.get("storage")
    deps = Agent04Deps(
        llm=ports.get("llm"), library=library, tenancy=ports.get("tenancy"), storage=storage,
        checkpoints=ports.get("checkpoints"), idempotency=ports.get("idempotency"),
        budget=ports.get("budget_guard"), ledger=ports.get("cost_ledger"),
        audit=ports.get("audit"), clock=ports.get("clock"),
        resolver_factory=ResolverFactory(library, storage),
        **_from(ports, tt, "web", "directory", "settings", "prompts", "memory"),
    )  # fmt: skip
    return ResearchPackStep(deps)


def agent_05(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_05.script_draft"
    storage = ports.get("storage")
    prompts = _prompts(ports)
    prompts.verify_all()
    agent_ports = Agent05Ports(
        scripts=ScriptRepository(storage, ports.get("script_rows")),
        **_from(ports, tt, "hook_history", "checkpoints", "budget", "ledger", "control",
                "idempotency", "audit", "chunks"),
    )  # fmt: skip
    step = ScriptDraftStep(
        ports.get("llm"), agent_ports, _own(ports, tt, "settings"), load_prompts(prompts.root),
        _own(ports, tt, "scanners_for"),
    )  # fmt: skip
    return ScriptDraftStage(step, _own(ports, tt, "resolver"), storage, ports.get("clock"))


def _agent_06_shared(ports: PortSet, tt: str) -> dict[str, Any]:
    prompts = _prompts(ports)
    prompts.verify_all()
    return {
        "llm": ports.get("llm"), "budget": ports.get("budget_guard"),
        "ledger": ports.get("cost_ledger"), "tenancy": ports.get("tenancy"),
        "clock": ports.get("clock"), "blobs": ports.get("storage"),
        "checkpoints": ports.get("checkpoints"), "audit": ports.get("audit"),
        "scripts": ports.get("script_registry"), "claims": _own(ports, tt, "claims"),
        "prompts": FilePromptSource(prompts.root, prompts.registry),
        "settings": _own(ports, tt, "settings"),
    }  # fmt: skip


def agent_06_extraction(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_06.claim_extraction"
    return ClaimExtractionStep(
        **_agent_06_shared(ports, tt), **_from(ports, tt, "rule_packs", "chart_ranges")
    )


def agent_06_verification(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_06.claim_verification"
    return ClaimVerificationStep(
        **_agent_06_shared(ports, tt), **_from(ports, tt, "knowledge"),
        quotes=_own(ports, tt, "quotes"),
    )  # fmt: skip


def agent_07_voice(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_07.voice_synthesis"
    deps = VoiceDeps(
        storage=ports.get("storage"), tenancy=ports.get("tenancy"),
        idempotency=ports.get("idempotency"), ledger=ports.get("cost_ledger"),
        budget=ports.get("budget_guard"), checkpoints=ports.get("checkpoints"),
        clock=ports.get("clock"),
        **_from(ports, tt, "config", "tts", "breaker", "facts", "registry", "tools", "control",
                "scratch_root"),
    )  # fmt: skip
    return VoiceSynthesisStage(deps)


def agent_07_master(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_07.audio_master"
    deps = MasterDeps(
        storage=ports.get("storage"), tenancy=ports.get("tenancy"),
        checkpoints=ports.get("checkpoints"), clock=ports.get("clock"),
        **_from(ports, tt, "config", "facts", "tools", "backend", "control", "scratch_root"),
    )  # fmt: skip
    return AudioMasterStage(deps)


def agent_08(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_08.asset_sourcing"
    return AssetSourcingStage(
        tenancy=ports.get("tenancy"), blobs=ports.get("storage"), clock=ports.get("clock"),
        job_destinations=ports.get("job_destination"),
        brand_kits=_own(ports, tt, "brand_kits"),
        **_from(ports, tt, "assets", "licences", "ledger", "fingerprints", "approvals", "settings"),
    )  # fmt: skip


def agent_09(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_09.shot_plan"
    prompts = _prompts(ports)
    prompts.verify_all()
    step = ShotPlanStep(
        llm=ports.get("llm"), prompts=PromptTextStore(prompts),
        recorder=_own(ports, tt, "recorder"), cfg=_own(ports, tt, "cfg"),
    )  # fmt: skip
    return ShotPlanTask(
        step, ports.get("storage"), _own(ports, tt, "plan_input_ports"), ports.get("clock"),
        worst_case_call_micros=_own(ports, tt, "worst_case_call_micros"),
    )  # fmt: skip


def _agent_10_deps(ports: PortSet, tt: str) -> Agent10Deps:
    return Agent10Deps(
        storage=ports.get("storage"), tenancy=ports.get("tenancy"),
        checkpoints=ports.get("checkpoints"), cost_ledger=ports.get("cost_ledger"),
        idempotency=ports.get("idempotency"), clock=ports.get("clock"), audit=ports.get("audit"),
        runner=ProcessFfmpegRunner(), timers=ThreadTimerFactory(),
        **_from(ports, tt, "cfg", "admission", "scratch_root", "renders", "assets", "qc_results",
                "licences"),
    )  # fmt: skip


def agent_10_render(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    return RenderStage(_agent_10_deps(ports, "agent_10.render"))


def agent_10_subtitles(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    return SubtitleStage(_agent_10_deps(ports, "agent_10.subtitles"))


def agent_10_qc(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_10.technical_qc"
    return QcStage(_agent_10_deps(ports, tt), _own(ports, tt, "selftests"))


def agent_11(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_11.thumbnail_variants"
    prompts = _prompts(ports)
    pid = PROMPT_IDS["agent_11"]
    bundle = PromptBundle(pid, prompts.text(pid), prompts.sha256(pid))
    deps = Agent11Deps(
        tenancy=ports.get("tenancy"), storage=ports.get("storage"), llm=ports.get("llm"),
        budget=ports.get("budget_guard"), costs=ports.get("cost_ledger"),
        audit=ports.get("audit"), idem=ports.get("idempotency"),
        checkpoints=ports.get("checkpoints"), clock=ports.get("clock"), prompt=bundle,
        composer=PillowComposer(), templates=load_templates(),
        **_from(ports, tt, "settings", "repo", "lexicons", "packs"),
    )  # fmt: skip
    return ThumbnailStage(deps)


def agent_16_gate(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_16.compliance_gate"
    prompts = _prompts(ports)
    keys = ("policy", "paraphrase", "frames")
    ids = tuple(PROMPT_IDS[f"agent_16.{k}"] for k in keys)
    deps = GateStageDeps(
        tenancy=ports.get("tenancy"), storage=ports.get("storage"), audit=ports.get("audit"),
        budget=ports.get("budget_guard"), costs=ports.get("cost_ledger"),
        clock=ports.get("clock"), llm=ports.get("llm"),
        prompts={k: prompts.text(i) for k, i in zip(keys, ids, strict=True)}, prompt_ids=ids,
        **_from(ports, tt, "config", "breaker", "assembler", "evidence", "packs", "writer",
                "pack_texts"),
    )  # fmt: skip
    return ComplianceGateStage(deps)


def agent_16_score(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "agent_16.quality_score"
    prompts = _prompts(ports)
    pid = PROMPT_IDS["agent_16.score"]
    deps = ScoreStageDeps(
        tenancy=ports.get("tenancy"), storage=ports.get("storage"), audit=ports.get("audit"),
        budget=ports.get("budget_guard"), costs=ports.get("cost_ledger"),
        clock=ports.get("clock"), llm=ports.get("llm"), renders=ports.get("render_hash_reader"),
        rows=ports.get("fact_rows"), store=ports.get("score_store"),
        prompt=prompts.text(pid), prompt_ids=(pid,),
        **_from(ports, tt, "config", "breaker", "extractor", "groups"),
    )  # fmt: skip
    return QualityScoreStage(deps)


def svc_s02(ports: PortSet, _ti: TaskInput) -> TaskWorker:
    tt = "svc_s02.uniqueness_check"
    deps = UniquenessStageDeps(
        tenancy=ports.get("tenancy"), storage=ports.get("storage"), audit=ports.get("audit"),
        clock=ports.get("clock"), extractor=DocumentUniquenessExtractor(),
        **_from(ports, tt, "config", "store", "source"),
    )  # fmt: skip
    return UniquenessCheckStage(deps)


FACTORIES: Final[Mapping[str, Factory]] = {
    "agent_04.research_pack": agent_04,
    "agent_05.script_draft": agent_05,
    "agent_06.claim_extraction": agent_06_extraction,
    "agent_06.claim_verification": agent_06_verification,
    "agent_07.voice_synthesis": agent_07_voice,
    "agent_07.audio_master": agent_07_master,
    "agent_08.asset_sourcing": agent_08,
    "agent_09.shot_plan": agent_09,
    "agent_10.render": agent_10_render,
    "agent_10.subtitles": agent_10_subtitles,
    "agent_10.technical_qc": agent_10_qc,
    "agent_11.thumbnail_variants": agent_11,
    "agent_16.compliance_gate": agent_16_gate,
    "agent_16.quality_score": agent_16_score,
    "svc_s02.uniqueness_check": svc_s02,
}
"""The 15 production factories, keyed by task type."""

__all__ = ["FACTORIES", "PROMPT_IDS", "Factory"]
