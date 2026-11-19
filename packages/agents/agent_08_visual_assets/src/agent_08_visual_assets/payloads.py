"""Payload schemas of Agent 08 for the registry (03 section 5.3 rule 2a; ``agent_08.*``)."""

from agent_08_visual_assets.models.output import SourcingOutput
from agent_08_visual_assets.models.task_input import SourcingInput
from amw_core.contracts.payloads import PayloadRegistrar

INPUT_SCHEMA = "agent_08.asset_sourcing.input"
OUTPUT_SCHEMA = "agent_08.asset_sourcing.output"
SCHEMA_VERSION = "1.0.0"


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(INPUT_SCHEMA, SCHEMA_VERSION, SourcingInput)
    registrar.register(OUTPUT_SCHEMA, SCHEMA_VERSION, SourcingOutput)
