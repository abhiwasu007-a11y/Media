"""Payload schemas of Agent 06 for the registry (03 section 5.3 rule 2a; ``agent_06.*``)."""

from agent_06_fact_checker import extraction_step, verification_step
from agent_06_fact_checker.models import (
    ExtractionInput,
    ExtractionOutput,
    VerificationInput,
    VerificationOutput,
)
from amw_core.contracts.payloads import PayloadRegistrar

SCHEMA_VERSION = "1.0.0"
EXTRACTION_INPUT_VERSION = "1.1.0"
"""The extraction input model is the twin of the 1.1.0 schema (``models.py`` header)."""


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(extraction_step.INPUT_SCHEMA, EXTRACTION_INPUT_VERSION, ExtractionInput)
    registrar.register(extraction_step.OUTPUT_SCHEMA, SCHEMA_VERSION, ExtractionOutput)
    registrar.register(verification_step.INPUT_SCHEMA, SCHEMA_VERSION, VerificationInput)
    registrar.register(verification_step.OUTPUT_SCHEMA, SCHEMA_VERSION, VerificationOutput)
