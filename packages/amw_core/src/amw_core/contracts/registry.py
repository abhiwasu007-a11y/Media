"""Schema registry (03 section 2.1): immutable JSON Schema files shipped in this package.

Layout ``schemas/<schema name>/<semver>.json``; each ``$id`` is ``urn:amw:schema:<name>:<semver>``.
``$ref`` resolves only from this registry (no network fetch).
"""

import json
from collections.abc import Mapping
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from amw_core.contracts.common import is_rfc3339_utc

CONTRACT_SCHEMAS = (
    "amw.common",
    "amw.task_input",
    "amw.task_output",
    "amw.envelope",
    "amw.error",
    "amw.control",
)


def schema_id(name: str, version: str) -> str:
    return f"urn:amw:schema:{name}:{version}"


@cache
def _load() -> Mapping[tuple[str, str], Mapping[str, Any]]:
    root = files("amw_core.contracts").joinpath("schemas")
    found: dict[tuple[str, str], Mapping[str, Any]] = {}
    for name_dir in root.iterdir():
        if not name_dir.is_dir():
            continue
        for item in name_dir.iterdir():
            if item.name.endswith(".json"):
                version = item.name.removesuffix(".json")
                doc = json.loads(item.read_text(encoding="utf-8"))
                if doc.get("$id") != schema_id(name_dir.name, version):
                    raise RuntimeError(f"schema file {name_dir.name}/{item.name} has a wrong $id")
                found[(name_dir.name, version)] = doc
    return MappingProxyType(found)


def all_schemas() -> Mapping[tuple[str, str], Mapping[str, Any]]:
    """Every shipped schema keyed by ``(name, version)``."""
    return _load()


def versions(name: str) -> tuple[str, ...]:
    return tuple(sorted(v for (n, v) in _load() if n == name))


def get_schema(name: str, version: str) -> Mapping[str, Any]:
    return _load()[(name, version)]


@cache
def _registry() -> Registry[Any]:
    resources = [
        (schema_id(n, v), DRAFT202012.create_resource(dict(doc))) for (n, v), doc in _load().items()
    ]
    registry: Registry[Any] = Registry().with_resources(resources)
    return registry


def _date_time(instance: object) -> bool:
    # Non-strings are the "type" keyword's concern; strings must be strict RFC 3339 UTC.
    return not isinstance(instance, str) or is_rfc3339_utc(instance)


def format_checker() -> FormatChecker:
    """Enforces ``format: date-time`` (implemented here; no optional jsonschema extra needed)."""
    checker = FormatChecker(formats=())
    checker.checks("date-time")(_date_time)
    return checker


@cache
def validator(name: str, version: str) -> Draft202012Validator:
    """Validator for one exact schema version (03 section 2.3 rule 1)."""
    return Draft202012Validator(
        dict(get_schema(name, version)), registry=_registry(), format_checker=format_checker()
    )
