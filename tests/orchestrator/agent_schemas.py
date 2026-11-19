"""A TEST registry of the agents' own payload models (PASS6-B1 acceptance).

The global allow-list ``PAYLOAD_PLUGIN_PACKAGES`` is empty until the payload-registration lane
merges, and this lane does not edit it: the tests register the same models through this fixture
into a private ``PayloadSchemaRegistry`` instead. Outputs of Agent 16 stages have no registered
model yet and use a permissive stand-in (the real output is still produced by the real worker)."""

from pydantic import BaseModel, ConfigDict

from agent_04_research_knowledge.models.pack_input import ResearchPackInput
from agent_04_research_knowledge.models.pack_output import ResearchPack
from agent_05_scriptwriter.contracts import (
    ScriptDraftInput,
    ScriptDraftResult,
    ShortsAdaptationInput,
    ShortsAdaptationResult,
)
from agent_06_fact_checker.models import (
    ExtractionInput,
    ExtractionOutput,
    VerificationInput,
    VerificationOutput,
)
from agent_07_voice_production import contracts as c7
from agent_08_visual_assets.models.output import SourcingOutput
from agent_08_visual_assets.models.task_input import SourcingInput
from agent_09_video_director.contracts import ShotPlanInput
from agent_09_video_director.output import ShotPlanPayload
from agent_10_video_editor import contracts as c10
from agent_11_thumbnail_design.payload import OutputPayload, ThumbnailInput
from agent_16_compliance_qa.assembler import ComplianceGateInput
from agent_16_compliance_qa.authorisation.stage import AuthorisationInput
from agent_16_compliance_qa.scoring.stage import QualityScoreInput
from agent_16_compliance_qa.stages import UniquenessInput
from amw_core.contracts.payloads import PayloadSchemaRegistry
from amw_delivery.models import BundleInputs, BundleManifest


class Open(BaseModel):
    model_config = ConfigDict(extra="allow")


V = "1.0.0"
INPUTS: dict[str, tuple[str, type[BaseModel]]] = {
    "agent_04.research_pack.input": (V, ResearchPackInput),
    "agent_05.script_draft.input": (V, ScriptDraftInput),
    "agent_05.shorts_adaptation.input": (V, ShortsAdaptationInput),
    "agent_06.claim_extraction.input": ("1.1.0", ExtractionInput),
    "agent_06.claim_verification.input": (V, VerificationInput),
    "agent_07.voice_synthesis.input": (V, c7.VoiceSynthesisInput),
    "agent_07.audio_master.input": (V, c7.AudioMasterInput),
    "agent_08.asset_sourcing.input": (V, SourcingInput),
    "agent_09.shot_plan.input": (V, ShotPlanInput),
    "agent_10.render.input": (V, c10.RenderInput),
    "agent_10.subtitles.input": (V, c10.SubtitlesInput),
    "agent_10.technical_qc.input": (V, c10.TechnicalQcInput),
    "agent_11.thumbnail_variants.input": (V, ThumbnailInput),
    "agent_16.compliance_gate.input": (V, ComplianceGateInput),
    "agent_16.quality_score.input": (V, QualityScoreInput),
    "agent_16.publication_authorisation.input": (V, AuthorisationInput),
    "svc_s02.uniqueness_check.input": (V, UniquenessInput),
    "agent_13.file_delivery.input": (V, BundleInputs),
}
OUTPUTS: dict[str, tuple[str, type[BaseModel]]] = {
    "agent_04.research_pack.output": (V, ResearchPack),
    "agent_05.script_draft.output": (V, ScriptDraftResult),
    "agent_05.shorts_adaptation.output": (V, ShortsAdaptationResult),
    "agent_06.claim_extraction.output": (V, ExtractionOutput),
    "agent_06.claim_verification.output": (V, VerificationOutput),
    "agent_07.voice_synthesis.output": (V, c7.VoiceSynthesisOutput),
    "agent_07.audio_master.output": (V, c7.AudioMasterOutput),
    "agent_08.asset_sourcing.output": (V, SourcingOutput),
    "agent_09.shot_plan.output": (V, ShotPlanPayload),
    "agent_10.render.output": (V, c10.RenderOutput),
    "agent_10.subtitles.output": (V, c10.SubtitlesOutput),
    "agent_10.technical_qc.output": (V, c10.TechnicalQcOutput),
    "agent_11.thumbnail_variants.output": (V, OutputPayload),
    "agent_13.file_delivery.output": (V, BundleManifest),
}
OPEN_OUTPUTS = (
    "agent_16.compliance_gate.output",
    "agent_16.quality_score.output",
    "agent_16.publication_authorisation.output",
    "svc_s02.uniqueness_check.output",
    "svc_s07.request_approval.input",
    "svc_s07.request_approval.output",
)


def agent_registry(*, outputs: bool = True) -> PayloadSchemaRegistry:
    reg = PayloadSchemaRegistry()
    for name, (version, model) in INPUTS.items():
        reg.register(name, version, model)
    for name, (version, model) in OUTPUTS.items() if outputs else ():
        reg.register(name, version, model)
    for name in OPEN_OUTPUTS:
        reg.register(name, V, Open)
    return reg
