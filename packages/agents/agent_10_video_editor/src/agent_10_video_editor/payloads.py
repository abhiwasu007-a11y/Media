"""Payload schemas of Agent 10 for the registry (03 section 5.3 rule 2a; ``agent_10.*``)."""

from agent_10_video_editor.contracts import (
    RenderInput,
    RenderOutput,
    SubtitlesInput,
    SubtitlesOutput,
    TechnicalQcInput,
    TechnicalQcOutput,
)
from agent_10_video_editor.taskio import SCHEMA_VERSION
from amw_core.contracts.payloads import PayloadRegistrar


def register(registrar: PayloadRegistrar) -> None:
    registrar.register("agent_10.render.input", SCHEMA_VERSION, RenderInput)
    registrar.register("agent_10.render.output", SCHEMA_VERSION, RenderOutput)
    registrar.register("agent_10.subtitles.input", SCHEMA_VERSION, SubtitlesInput)
    registrar.register("agent_10.subtitles.output", SCHEMA_VERSION, SubtitlesOutput)
    registrar.register("agent_10.technical_qc.input", SCHEMA_VERSION, TechnicalQcInput)
    registrar.register("agent_10.technical_qc.output", SCHEMA_VERSION, TechnicalQcOutput)
