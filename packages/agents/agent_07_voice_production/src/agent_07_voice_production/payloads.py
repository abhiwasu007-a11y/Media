"""Payload schemas of Agent 07 for the registry (03 section 5.3 rule 2a; ``agent_07.*``)."""

from agent_07_voice_production import contracts as c
from amw_core.contracts.payloads import PayloadRegistrar


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(c.SCHEMA_VOICE_INPUT, c.SCHEMA_VERSION, c.VoiceSynthesisInput)
    registrar.register(c.SCHEMA_VOICE_OUTPUT, c.SCHEMA_VERSION, c.VoiceSynthesisOutput)
    registrar.register(c.SCHEMA_MASTER_INPUT, c.SCHEMA_VERSION, c.AudioMasterInput)
    registrar.register(c.SCHEMA_MASTER_OUTPUT, c.SCHEMA_VERSION, c.AudioMasterOutput)
