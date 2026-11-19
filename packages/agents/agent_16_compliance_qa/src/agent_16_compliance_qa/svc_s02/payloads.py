"""Payload schemas of ``svc_s02.uniqueness_check`` for the registry (03 section 5.3 rule 2a).

Loaded through the allow-list entry ``agent_16_compliance_qa.svc_s02 -> svc_s02`` (CCR-282,
provisional default): the registrar of that entry accepts ``svc_s02.*`` names only, and the
``agent_16`` registrar of ``agent_16_compliance_qa.payloads`` accepts ``agent_16.*`` names only.
"""

from agent_16_compliance_qa.output import SCHEMA_VERSION
from agent_16_compliance_qa.payload_models import UniquenessCheckOutput
from agent_16_compliance_qa.stages import UNIQ_INPUT, UNIQ_OUTPUT, UniquenessInput
from amw_core.contracts.payloads import PayloadRegistrar


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(UNIQ_INPUT, SCHEMA_VERSION, UniquenessInput)
    registrar.register(UNIQ_OUTPUT, SCHEMA_VERSION, UniquenessCheckOutput)
