"""Payload schemas of Agent 11 for the registry (03 section 5.3 rule 2a; ``agent_11.*``)."""

from agent_11_thumbnail_design.payload import OutputPayload, ThumbnailInput
from agent_11_thumbnail_design.stage import INPUT_SCHEMA, OUTPUT_SCHEMA
from amw_core.contracts.payloads import PayloadRegistrar

SCHEMA_VERSION = "1.0.0"


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(INPUT_SCHEMA, SCHEMA_VERSION, ThumbnailInput)
    registrar.register(OUTPUT_SCHEMA, SCHEMA_VERSION, OutputPayload)
