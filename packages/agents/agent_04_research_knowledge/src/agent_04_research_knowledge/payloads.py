"""Payload schemas of Agent 04 for the registry (03 section 5.3 rule 2a; ``agent_04.*``)."""

from agent_04_research_knowledge.models.pack_input import (
    PAYLOAD_SCHEMA,
    PAYLOAD_SCHEMA_VERSION,
    ResearchPackInput,
)
from agent_04_research_knowledge.models.pack_output import (
    PACK_OUTPUT_SCHEMA,
    PACK_OUTPUT_SCHEMA_VERSION,
    ResearchPack,
)
from amw_core.contracts.payloads import PayloadRegistrar


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(PAYLOAD_SCHEMA, PAYLOAD_SCHEMA_VERSION, ResearchPackInput)
    registrar.register(PACK_OUTPUT_SCHEMA, PACK_OUTPUT_SCHEMA_VERSION, ResearchPack)
