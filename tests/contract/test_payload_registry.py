# ruff: noqa: PT018
"""Payload schema registry (CCR-130, P4-17): lookup by major, typed errors, no values leaked."""

from collections.abc import Callable
from types import ModuleType

import pytest
from pydantic import BaseModel, ConfigDict

from amw_core.contracts.payloads import (
    PAYLOAD_PLUGIN_PACKAGES,
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


# --- the real allow-list: every agent package registers its own schemas (ticket "agent payload
# registration"); the names are pinned so a dropped or extra schema is a visible diff -------------
REGISTERED = frozenset(
    {
        "agent_04.research_pack.input", "agent_04.research_pack.output",
        "agent_05.script_draft.input", "agent_05.script_draft.output",
        "agent_05.shorts_adaptation.input", "agent_05.shorts_adaptation.output",
        "agent_06.claim_extraction.input", "agent_06.claim_extraction.output",
        "agent_06.claim_verification.input", "agent_06.claim_verification.output",
        "agent_07.voice_synthesis.input", "agent_07.voice_synthesis.output",
        "agent_07.audio_master.input", "agent_07.audio_master.output",
        "agent_08.asset_sourcing.input", "agent_08.asset_sourcing.output",
        "agent_09.shot_plan.input", "agent_09.shot_plan.output",
        "agent_10.render.input", "agent_10.render.output",
        "agent_10.subtitles.input", "agent_10.subtitles.output",
        "agent_10.technical_qc.input", "agent_10.technical_qc.output",
        "agent_11.thumbnail_variants.input", "agent_11.thumbnail_variants.output",
        "agent_13.file_delivery.input", "agent_13.file_delivery.output",
        "agent_16.compliance_gate.input", "agent_16.compliance_gate.output",
        "agent_16.quality_score.input", "agent_16.quality_score.output",
        "agent_16.publication_authorisation.input", "agent_16.publication_authorisation.output",
        "svc_s02.uniqueness_check.input", "svc_s02.uniqueness_check.output",
        "svc_s07.request_approval.input", "svc_s07.request_approval.output",
    }
)  # fmt: skip
NOT_REGISTERED = (  # no model pairs the name with a payload yet: the executor refuses them
    "agent_12.metadata.input",
    "agent_12.metadata.output",
)


def test_default_allow_list_loads_every_agent_package_and_pins_the_schema_names() -> None:
    reg = PayloadSchemaRegistry()
    loaded = load_payload_schema_plugins(reg)
    assert loaded == tuple(sorted(PAYLOAD_PLUGIN_PACKAGES))
    assert len(loaded) == 12
    assert reg.names() == REGISTERED


def test_allow_list_namespaces_match_the_package_and_are_read_only() -> None:
    for package, namespace in PAYLOAD_PLUGIN_PACKAGES.items():
        assert namespace.startswith(("agent_", "svc_s")) and not namespace.endswith(".")
        if namespace == "svc_s02":  # CCR-282 provisional default: S2 is hosted by Agent 16
            assert package == "agent_16_compliance_qa.svc_s02"
        elif namespace == "svc_s07":  # CCR-282 clause 1 / CCR-283: the ApprovalWorker's package
            assert package == "amw_orchestrator"
        else:
            assert package.startswith((namespace, "amw_delivery"))  # agent_13: amw_delivery
    with pytest.raises(TypeError):
        PAYLOAD_PLUGIN_PACKAGES["evil_pkg"] = "agent_07"  # type: ignore[index]


@pytest.mark.parametrize("name", NOT_REGISTERED)
def test_a_schema_without_a_model_is_refused_not_waved_through(name: str) -> None:
    reg = PayloadSchemaRegistry()
    load_payload_schema_plugins(reg)
    with pytest.raises(SchemaInvalidError):
        reg.validate(name, "1.0.0", {})


def test_a_real_plugin_registering_outside_its_namespace_is_refused() -> None:
    """agent_05's real ``register`` bound to agent_07's namespace: refused, nothing registered."""
    reg = PayloadSchemaRegistry()
    with pytest.raises(ConfigInvalidError) as err:
        load_payload_schema_plugins(reg, {"agent_05_scriptwriter": "agent_07"})
    assert err.value.details["namespace"] == "agent_07"
    assert reg.names() == frozenset()


def test_a_real_plugin_cannot_take_over_another_packages_schema() -> None:
    """Both real plugins loaded, then agent_05's ``register`` run again under agent_04's
    namespace: the name check fires before the registry is touched."""
    reg = PayloadSchemaRegistry()
    load_payload_schema_plugins(reg)
    before = reg.names()
    with pytest.raises(ConfigInvalidError):
        load_payload_schema_plugins(reg, {"agent_05_scriptwriter": "agent_04"})
    assert reg.names() == before


def test_a_real_plugin_registering_a_schema_twice_is_refused() -> None:
    from agent_07_voice_production.payloads import register

    registrar = PayloadRegistrar(PayloadSchemaRegistry(), "agent_07")
    register(registrar)
    with pytest.raises(ConfigInvalidError):
        register(registrar)  # the same registrar sees every name a second time


def test_loading_twice_into_one_registry_is_idempotent() -> None:
    reg = PayloadSchemaRegistry()
    load_payload_schema_plugins(reg)
    load_payload_schema_plugins(reg)  # a second executor in the same process
    assert reg.names() == REGISTERED


# --- the shared-service namespace (CCR-282 provisional default) -------------------------------
def test_agent_16_cannot_register_into_the_svc_s02_namespace_nor_s02_into_agent_16() -> None:
    reg = PayloadSchemaRegistry()
    with pytest.raises(ConfigInvalidError):
        load_payload_schema_plugins(reg, {"agent_16_compliance_qa": "svc_s02"})
    with pytest.raises(ConfigInvalidError):
        load_payload_schema_plugins(reg, {"agent_16_compliance_qa.svc_s02": "agent_16"})
    with pytest.raises(ConfigInvalidError):  # another namespace of the shared services
        load_payload_schema_plugins(reg, {"agent_16_compliance_qa.svc_s02": "svc_s07"})
    assert reg.names() == frozenset()


def test_svc_s07_is_owned_by_the_orchestrator_and_only_by_it() -> None:
    """CCR-282 clause 1 + CCR-283 (PROVISIONAL): ``amw_orchestrator`` registers ``svc_s07.*``; no
    other package may, and the orchestrator may register nothing outside its namespace."""
    assert {p for p, n in PAYLOAD_PLUGIN_PACKAGES.items() if n == "svc_s07"} == {"amw_orchestrator"}
    reg = PayloadSchemaRegistry()
    with pytest.raises(ConfigInvalidError):
        load_payload_schema_plugins(reg, {"amw_orchestrator": "agent_16"})
    with pytest.raises(ConfigInvalidError):
        load_payload_schema_plugins(reg, {"agent_16_compliance_qa": "svc_s07"})
    assert reg.names() == frozenset()
    load_payload_schema_plugins(reg)
    assert {n for n in reg.names() if n.startswith("svc_s07.")} == {
        "svc_s07.request_approval.input",
        "svc_s07.request_approval.output",
    }
