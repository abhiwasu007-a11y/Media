"""Payload schemas of Agent 05 for the registry (03 section 5.3 rule 2a; ``agent_05.*``)."""

from agent_05_scriptwriter.contracts import (
    ScriptDraftInput,
    ScriptDraftResult,
    ShortsAdaptationInput,
    ShortsAdaptationResult,
)
from agent_05_scriptwriter.stage import SCHEMA_VERSION, SCRIPT_DRAFT_SCHEMA, SHORTS_SCHEMA
from amw_core.contracts.payloads import PayloadRegistrar

SCRIPT_DRAFT_OUTPUT_SCHEMA = "agent_05.script_draft.output"
SHORTS_OUTPUT_SCHEMA = "agent_05.shorts_adaptation.output"


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(SCRIPT_DRAFT_SCHEMA, SCHEMA_VERSION, ScriptDraftInput)
    registrar.register(SCRIPT_DRAFT_OUTPUT_SCHEMA, SCHEMA_VERSION, ScriptDraftResult)
    registrar.register(SHORTS_SCHEMA, SCHEMA_VERSION, ShortsAdaptationInput)
    registrar.register(SHORTS_OUTPUT_SCHEMA, SCHEMA_VERSION, ShortsAdaptationResult)
