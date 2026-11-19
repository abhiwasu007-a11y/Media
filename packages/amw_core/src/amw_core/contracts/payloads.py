"""Registry of agent payload schemas (03 section 5.3 rule 2a; CCR-130, ticket P4-17).

An agent registers the Pydantic model of each payload schema it owns (for example
``agent_07.voice_synthesis.input``); the orchestrator and the agents validate a
``payload_object`` through it. A payload is never trusted until it validated (27 section 7.3).
This module holds the mechanism only: the agents' own models and their registration live in the
agent packages, derived from their blueprint appendices, and no schema is invented here.

Semantics: lookup by ``(name, major)``. An unknown name is ``PERMANENT.SCHEMA_INVALID``; a known
name whose registered major differs, or a requested minor newer than the registered one, is
``PERMANENT.SCHEMA_VERSION_UNSUPPORTED``; a model validation failure is ``SCHEMA_INVALID`` and
carries only field locations and error types, never the offending values.
"""

import importlib.metadata
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import EntryPoint
from typing import Any

from pydantic import BaseModel, ValidationError

from amw_core.contracts.common import SchemaName, Semver
from amw_core.errors import (
    ConfigInvalidError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
)

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_NAME = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


def _split(version: str) -> tuple[int, int, int]:
    m = _SEMVER.match(version)
    if m is None:
        raise SchemaInvalidError("payload schema version is not a semantic version")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


@dataclass(frozen=True, slots=True)
class RegisteredPayloadSchema:
    name: str
    version: str
    model: type[BaseModel]


class PayloadSchemaRegistry:
    """Maps ``(schema name, major)`` to the registered model; one instance per process."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, int], RegisteredPayloadSchema] = {}

    def register(self, name: SchemaName, version: Semver, model: type[BaseModel]) -> None:
        """Idempotent for the same model; another model for the same ``(name, major)`` is a
        programming error (``ValueError``): a schema is immutable once released (03 section 2.1)."""
        if _NAME.match(name) is None:
            raise ValueError(f"bad payload schema name: {name}")
        major, _, _ = _split(version)
        key = (name, major)
        old = self._by_key.get(key)
        if old is not None and old.model is not model:
            raise ValueError(f"payload schema {name} major {major} is already registered")
        if old is None or _split(version) > _split(old.version):
            self._by_key[key] = RegisteredPayloadSchema(name, version, model)

    def names(self) -> frozenset[str]:
        return frozenset(name for name, _ in self._by_key)

    def resolve(self, name: str, version: str) -> RegisteredPayloadSchema:
        major, minor, _ = _split(version)
        known = [k for k in self._by_key if k[0] == name]
        if not known:
            raise SchemaInvalidError("unknown payload schema", details={"schema": name})
        found = self._by_key.get((name, major))
        if found is None or minor > _split(found.version)[1]:
            raise SchemaVersionUnsupportedError(
                "payload schema version is not supported",
                details={"schema": name, "version": version},
            )
        return found

    def validate(self, name: str, version: str, data: Mapping[str, Any]) -> BaseModel:
        """The validated model instance, or a typed error (see the module docstring)."""
        model = self.resolve(name, version).model
        try:
            return model.model_validate(dict(data))
        except ValidationError as exc:
            problems = [
                {"loc": ".".join(str(p) for p in e["loc"]), "type": e["type"]}
                for e in exc.errors(include_input=False, include_url=False)
            ]
            raise SchemaInvalidError(
                "payload does not match its schema",
                details={"schema": name, "version": version, "errors": problems[:20]},
            ) from exc


PAYLOAD_SCHEMAS = PayloadSchemaRegistry()
"""The process-wide registry agents register into at import time."""


def register_payload_schema(name: SchemaName, version: Semver, model: type[BaseModel]) -> None:
    PAYLOAD_SCHEMAS.register(name, version, model)


ENTRY_POINT_GROUP = "amw.payload_schemas"
"""Python entry-point group an agent package declares in its ``pyproject.toml`` to register its
payload schemas: ``[project.entry-points."amw.payload_schemas"]`` ``agent_07 =
"agent_07_voice_production.payloads:register"``, a ``register(registry)`` function that calls
``registry.register(name, version, model)`` for each schema it owns. ``amw_core`` never imports an
agent (layering); the orchestrator calls ``load_payload_schema_plugins`` once at start-up."""


def load_payload_schema_plugins(
    registry: PayloadSchemaRegistry = PAYLOAD_SCHEMAS,
    entry_points: Iterable[EntryPoint] | None = None,
) -> tuple[str, ...]:
    """Run every registered plugin against ``registry``; returns the plugin names loaded. A
    plugin that fails to load or register is a start-up error (``ConfigInvalidError``): a missing
    schema must never silently disable payload validation."""
    found = (
        tuple(entry_points)
        if entry_points is not None
        else tuple(importlib.metadata.entry_points(group=ENTRY_POINT_GROUP))
    )
    loaded: list[str] = []
    for point in sorted(found, key=lambda e: e.name):
        try:
            point.load()(registry)
        except Exception as exc:
            raise ConfigInvalidError(
                "a payload schema plugin failed", details={"plugin": point.name}
            ) from exc
        loaded.append(point.name)
    return tuple(loaded)


__all__ = [
    "ENTRY_POINT_GROUP",
    "PAYLOAD_SCHEMAS",
    "PayloadSchemaRegistry",
    "RegisteredPayloadSchema",
    "load_payload_schema_plugins",
    "register_payload_schema",
]
