"""Payload schemas of Agent 16 for the registry (03 section 5.3 rule 2a; ``agent_16.*``).

Only the three input schemas are registered: the three outputs are built as plain mappings
(``gate_payload``, ``score_payload``, ``auth_payload``) with no model, so none is registered.
"""

from agent_16_compliance_qa.assembler import INPUT_SCHEMA, ComplianceGateInput
from agent_16_compliance_qa.authorisation.stage import AUTH_INPUT, AuthorisationInput
from agent_16_compliance_qa.output import SCHEMA_VERSION
from agent_16_compliance_qa.scoring.stage import QUALITY_INPUT, QualityScoreInput
from amw_core.contracts.payloads import PayloadRegistrar


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(INPUT_SCHEMA, SCHEMA_VERSION, ComplianceGateInput)
    registrar.register(QUALITY_INPUT, SCHEMA_VERSION, QualityScoreInput)
    registrar.register(AUTH_INPUT, SCHEMA_VERSION, AuthorisationInput)
