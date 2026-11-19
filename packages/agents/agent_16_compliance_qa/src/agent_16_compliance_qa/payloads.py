"""Payload schemas of Agent 16 for the registry (03 section 5.3 rule 2a; ``agent_16.*``).

The three input schemas and the three output schemas (sections 8.2, 8.4, 8.5; hand-written
models of ``payload_models`` compared with the document blocks by the contract tests) are
registered. The ``svc_s02.*`` schemas are registered from ``agent_16_compliance_qa.svc_s02``
(CCR-282): one allow-list entry binds one package to one namespace.
"""

from agent_16_compliance_qa.assembler import INPUT_SCHEMA, ComplianceGateInput
from agent_16_compliance_qa.authorisation.stage import AUTH_INPUT, AuthorisationInput
from agent_16_compliance_qa.output import SCHEMA_VERSION
from agent_16_compliance_qa.payload_models import (
    ComplianceGateOutput,
    PublicationAuthorisationOutput,
    QualityScoreOutput,
)
from agent_16_compliance_qa.scoring.stage import QUALITY_INPUT, QualityScoreInput
from amw_core.contracts.payloads import PayloadRegistrar

GATE_OUTPUT = "agent_16.compliance_gate.output"
QUALITY_OUTPUT = "agent_16.quality_score.output"
AUTH_OUTPUT = "agent_16.publication_authorisation.output"


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(INPUT_SCHEMA, SCHEMA_VERSION, ComplianceGateInput)
    registrar.register(GATE_OUTPUT, SCHEMA_VERSION, ComplianceGateOutput)
    registrar.register(QUALITY_INPUT, SCHEMA_VERSION, QualityScoreInput)
    registrar.register(QUALITY_OUTPUT, SCHEMA_VERSION, QualityScoreOutput)
    registrar.register(AUTH_INPUT, SCHEMA_VERSION, AuthorisationInput)
    registrar.register(AUTH_OUTPUT, SCHEMA_VERSION, PublicationAuthorisationOutput)
