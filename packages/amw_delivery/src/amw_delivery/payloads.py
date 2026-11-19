"""Payload schemas of Agent 13 (``file_delivery``) for the registry (03 section 5.3 rule 2a)."""

from amw_core.contracts.payloads import PayloadRegistrar
from amw_delivery.models import BundleInputs, BundleManifest
from amw_delivery.stage import INPUT_SCHEMA, OUTPUT_SCHEMA, SCHEMA_VERSION


def register(registrar: PayloadRegistrar) -> None:
    registrar.register(INPUT_SCHEMA, SCHEMA_VERSION, BundleInputs)
    registrar.register(OUTPUT_SCHEMA, SCHEMA_VERSION, BundleManifest)
