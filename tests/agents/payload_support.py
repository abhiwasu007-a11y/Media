"""Shared helper of the agent payload-registration tests (``<agent>/test_payloads.py``).

The registry is the one the orchestrator executor fills at start-up (the allow-listed loader), so
a test fails when an agent's ``payloads.py`` is not on the list. Payloads under test are emitted by
each agent's own test fakes (a real stage run), never written by hand.
"""

from functools import cache
from typing import Any

from pydantic import BaseModel

from amw_core.contracts.common import PayloadObject
from amw_core.contracts.payloads import PayloadSchemaRegistry, load_payload_schema_plugins


@cache
def loaded_registry() -> PayloadSchemaRegistry:
    registry = PayloadSchemaRegistry()
    load_payload_schema_plugins(registry)
    return registry


def round_trip(payload: PayloadObject, *, exact: bool = True) -> BaseModel:
    """Validate an emitted payload through the loaded registry, re-emit it and validate again.

    ``exact``: the re-emitted JSON document equals the emitted one (nothing dropped, added or
    renamed by the registered model)."""
    registry = loaded_registry()
    assert payload.data is not None, "a payload with inline data is needed"
    model = registry.validate(payload.payload_schema, payload.payload_schema_version, payload.data)
    again: dict[str, Any] = model.model_dump(mode="json", by_alias=True)
    if exact:
        assert again == payload.data
    assert registry.validate(payload.payload_schema, payload.payload_schema_version, again) == model
    return model
