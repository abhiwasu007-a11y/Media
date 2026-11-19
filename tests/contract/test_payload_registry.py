"""Payload schema registry (CCR-130, P4-17): lookup by major, typed errors, no values leaked."""

from collections.abc import Callable
from types import ModuleType

import pytest
from pydantic import BaseModel, ConfigDict

from amw_core.contracts.payloads import (
    PAYLOAD_SCHEMAS,
    PayloadRegistrar,
    PayloadSchemaRegistry,
    load_payload_schema_plugins,
)
from amw_core.errors import ConfigInvalidError, SchemaInvalidError, SchemaVersionUnsupportedError

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


def _plugin_module(register: object) -> ModuleType:
    module = ModuleType("fake")
    module.register = register  # type: ignore[attr-defined]
    return module


def _loader(modules: dict[str, object]) -> Callable[[str], ModuleType]:
    def load(name: str) -> ModuleType:
        mod = modules[name]
        if isinstance(mod, Exception):
            raise mod
        return _plugin_module(mod)

    return load


def test_plugin_registers_only_inside_its_own_namespace() -> None:
    r = PayloadSchemaRegistry()

    def plugin(registrar: PayloadRegistrar) -> None:
        registrar.register(NAME, "1.0.0", Thing)

    out = load_payload_schema_plugins(
        r, {"agent_99_pkg": "agent_99"}, _loader({"agent_99_pkg.payloads": plugin})
    )
    assert out == ("agent_99_pkg",)
    assert r.validate(NAME, "1.0.0", {"topic": "t"})


def test_malicious_plugin_cannot_take_over_another_namespace() -> None:
    """A package bound to ``agent_66`` registering ``agent_07.*`` (or a schema that already
    exists) is refused, and what it did register before is not left half-applied silently."""
    r = PayloadSchemaRegistry()
    r.register("agent_07.voice_synthesis.input", "1.0.0", OtherThing)

    def evil(registrar: PayloadRegistrar) -> None:
        registrar.register("agent_07.voice_synthesis.input", "1.0.0", Thing)

    with pytest.raises(ConfigInvalidError):
        load_payload_schema_plugins(
            r, {"agent_66_pkg": "agent_66"}, _loader({"agent_66_pkg.payloads": evil})
        )
    assert r.resolve("agent_07.voice_synthesis.input", "1.0.0").model is OtherThing


def test_plugin_cannot_register_twice_or_prefix_spoof() -> None:
    def twice(registrar: PayloadRegistrar) -> None:
        registrar.register(NAME, "1.0.0", Thing)
        registrar.register(NAME, "1.1.0", Thing)

    def spoof(registrar: PayloadRegistrar) -> None:
        registrar.register("agent_990.thing.input", "1.0.0", Thing)  # prefix of the namespace text

    for plugin in (twice, spoof):
        with pytest.raises(ConfigInvalidError):
            load_payload_schema_plugins(
                PayloadSchemaRegistry(),
                {"agent_99_pkg": "agent_99"},
                _loader({"agent_99_pkg.payloads": plugin}),
            )


def test_only_allow_listed_packages_are_imported() -> None:
    imported: list[str] = []

    def load(name: str) -> ModuleType:
        imported.append(name)
        return _plugin_module(lambda registrar: None)

    load_payload_schema_plugins(PayloadSchemaRegistry(), {"agent_99_pkg": "agent_99"}, load)
    assert imported == ["agent_99_pkg.payloads"]
    assert "malicious_pkg.payloads" not in imported
    assert load_payload_schema_plugins(PayloadSchemaRegistry(), {}, load) == ()


@pytest.mark.parametrize("failure", [ImportError("x"), AttributeError("no register"), "raises"])
def test_failing_or_missing_plugin_is_a_startup_error(failure: object) -> None:
    def broken(registrar: PayloadRegistrar) -> None:
        raise RuntimeError("boom")

    entry: object = broken if failure == "raises" else failure
    with pytest.raises(ConfigInvalidError):
        load_payload_schema_plugins(
            PayloadSchemaRegistry(),
            {"agent_99_pkg": "agent_99"},
            _loader({"agent_99_pkg.payloads": entry}),
        )


def test_default_allow_list_loads_with_this_pr() -> None:
    assert load_payload_schema_plugins(PayloadSchemaRegistry()) == ()
