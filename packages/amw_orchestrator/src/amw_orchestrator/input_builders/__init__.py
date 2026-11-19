"""Input builders (CCR-203, ticket PASS6-B1): pure functions of ``BuildContext`` that produce the
payload of one Task Input per 3A task type. They are the ONLY code that builds a Task Input; they
import no agent package (the payload is plain data, validated by the registered model before the
worker runs) and never rewrite an upstream document: they pass references and facts.

A task type without a builder is refused (``PERMANENT.UNSUPPORTED_TASK``), never given a guess.
"""

from collections.abc import Mapping

from amw_core.errors import UnsupportedTaskError
from amw_orchestrator.executor import BuildContext, BuiltInput, InputBuilder
from amw_orchestrator.input_builders import (
    agent_04,
    agent_05,
    agent_06,
    agent_07,
    agent_08,
    agent_09,
    agent_10,
    agent_11,
    agent_13,
    agent_16,
    svc_s07,
)
from amw_orchestrator.input_builders.settings import BuilderSettings


class BuilderTable:
    """``InputBuilder`` lookup by task type."""

    def __init__(
        self,
        extra: Mapping[str, InputBuilder] | None = None,
        settings: BuilderSettings | None = None,
    ) -> None:
        cfg = settings or BuilderSettings()
        self._by_type: dict[str, InputBuilder] = {
            "agent_04.research_pack": agent_04.ResearchPackBuilder(),
            "agent_05.script_draft": agent_05.ScriptDraftBuilder(),
            "agent_05.shorts_adaptation": agent_05.ShortsAdaptationBuilder(),
            "agent_06.claim_extraction": agent_06.ClaimExtractionBuilder(),
            "agent_06.claim_verification": agent_06.ClaimVerificationBuilder(),
            "svc_s07.request_approval": svc_s07.ApprovalRequestBuilder(),
            "agent_07.voice_synthesis": agent_07.VoiceSynthesisBuilder(),
            "agent_07.audio_master": agent_07.AudioMasterBuilder(),
            "agent_09.shot_plan": agent_09.ShotPlanBuilder(),
            "agent_08.asset_sourcing": agent_08.AssetSourcingBuilder(cfg),
            "agent_10.render": agent_10.RenderBuilder(cfg),
            "agent_10.subtitles": agent_10.SubtitlesBuilder(),
            "agent_10.technical_qc": agent_10.TechnicalQcBuilder(cfg),
            "agent_11.thumbnail_variants": agent_11.ThumbnailBuilder(cfg),
            "svc_s02.uniqueness_check": agent_16.UniquenessBuilder(cfg),
            "agent_16.compliance_gate": agent_16.ComplianceGateBuilder(cfg),
            "agent_16.quality_score": agent_16.QualityScoreBuilder(cfg),
            "agent_16.publication_authorisation": agent_16.AuthorisationBuilder(cfg),
            "agent_13.file_delivery": agent_13.FileDeliveryBuilder(cfg),
            **(extra or {}),
        }

    def task_types(self) -> frozenset[str]:
        return frozenset(self._by_type)

    def build(self, ctx: BuildContext) -> BuiltInput:
        builder = self._by_type.get(ctx.stage.task_type)
        if builder is None:
            raise UnsupportedTaskError(
                "no input builder for the task type", details={"task_type": ctx.stage.task_type}
            )
        return builder.build(ctx)
