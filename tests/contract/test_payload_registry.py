"""Payload schema registry (CCR-130, P4-17): lookup by major, typed errors, no values leaked."""

import pytest
from pydantic import BaseModel, ConfigDict

from amw_core.contracts.payloads import PAYLOAD_SCHEMAS, PayloadSchemaRegistry
from amw_core.errors import SchemaInvalidError, SchemaVersionUnsupportedError

NAME = "agent_99.thing.input"


class Thing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str
    count: int = 1


class OtherThing(BaseModel):
    pass


def registry() -> PayloadSchemaRegistry:
    r = PayloadSchemaRegistry()
    r.register(NAME, "1.2.0", Thing)
    return r


def test_valid_payload_returns_the_model() -> None:
    out = registry().validate(NAME, "1.0.0", {"topic": "t"})
    assert isinstance(out, Thing)
    assert out.count == 1


def test_unknown_name_is_schema_invalid() -> None:
    with pytest.raises(SchemaInvalidError):
        registry().validate("agent_99.other.input", "1.0.0", {})


@pytest.mark.parametrize("version", ["2.0.0", "0.9.0", "1.3.0"])
def test_unsupported_version(version: str) -> None:
    with pytest.raises(SchemaVersionUnsupportedError):
        registry().validate(NAME, version, {"topic": "t"})


def test_bad_version_string_is_schema_invalid() -> None:
    with pytest.raises(SchemaInvalidError):
        registry().validate(NAME, "one", {"topic": "t"})


def test_failure_names_locations_never_values() -> None:
    with pytest.raises(SchemaInvalidError) as err:
        registry().validate(NAME, "1.0.0", {"topic": 5, "count": "SECRET-VALUE", "x": 1})
    text = str(err.value.details)
    assert "SECRET-VALUE" not in text
    assert "count" in text


def test_registration_is_idempotent_and_immutable_per_major() -> None:
    r = registry()
    r.register(NAME, "1.2.0", Thing)
    r.register(NAME, "1.4.0", Thing)
    assert r.validate(NAME, "1.4.0", {"topic": "t"})
    with pytest.raises(ValueError, match="already registered"):
        r.register(NAME, "1.5.0", OtherThing)
    r.register(NAME, "2.0.0", OtherThing)  # a new major may carry another model
    assert r.names() == {NAME}


def test_bad_name_is_refused() -> None:
    with pytest.raises(ValueError, match="bad payload schema name"):
        PayloadSchemaRegistry().register("NoDots", "1.0.0", Thing)


def test_process_registry_starts_without_invented_schemas() -> None:
    assert NAME not in PAYLOAD_SCHEMAS.names()


class _Point:
    """An entry point stand-in (name + load)."""

    def __init__(self, name: str, fn: object) -> None:
        self.name = name
        self._fn = fn

    def load(self) -> object:
        return self._fn


def test_plugins_register_schemas_at_startup() -> None:
    from amw_core.contracts.payloads import load_payload_schema_plugins

    r = PayloadSchemaRegistry()

    def plugin(registry: PayloadSchemaRegistry) -> None:
        registry.register(NAME, "1.0.0", Thing)

    loaded = load_payload_schema_plugins(r, [_Point("agent_99", plugin)])  # type: ignore[list-item]
    assert loaded == ("agent_99",)
    assert r.validate(NAME, "1.0.0", {"topic": "t"})


def test_failing_plugin_is_a_startup_error_not_a_silent_skip() -> None:
    from amw_core.contracts.payloads import load_payload_schema_plugins
    from amw_core.errors import ConfigInvalidError

    def broken(registry: PayloadSchemaRegistry) -> None:
        raise RuntimeError("boom")

    with pytest.raises(ConfigInvalidError):
        load_payload_schema_plugins(PayloadSchemaRegistry(), [_Point("a", broken)])  # type: ignore[list-item]


def test_no_plugins_installed_loads_nothing() -> None:
    from amw_core.contracts.payloads import load_payload_schema_plugins

    assert load_payload_schema_plugins(PayloadSchemaRegistry(), []) == ()
