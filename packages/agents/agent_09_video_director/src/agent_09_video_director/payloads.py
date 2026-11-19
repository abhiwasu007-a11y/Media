"""Payload schemas of Agent 09 for the registry (03 section 5.3 rule 2a; ``agent_09.*``)."""

from agent_09_video_director.contracts import ShotPlanInput
from agent_09_video_director.output import SCHEMA, SCHEMA_VERSION, ShotPlanPayload
from agent_09_video_director.protocol import INPUT_SCHEMA
from amw_core.contracts.payloads import PayloadRegistrar


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(INPUT_SCHEMA, SCHEMA_VERSION, ShotPlanInput)
    registrar.register(SCHEMA, SCHEMA_VERSION, ShotPlanPayload)
