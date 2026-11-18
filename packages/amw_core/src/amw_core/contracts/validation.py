"""Validate-before-processing helpers (03 section 7.1 steps 1 and 5).

Each ``validate_*`` checks a document against the exact JSON Schema version, then builds the
Pydantic model (which adds the rules the schema cannot express, e.g. 03 section 6 rule 1).
Failures raise typed errors with ``details.violations`` (03 section 7.2):
``PERMANENT.SCHEMA_INVALID``, ``PERMANENT.SCHEMA_VERSION_UNSUPPORTED`` or, for a reference to
another tenant, ``PERMANENT.CROSS_TENANT_REF``.
"""

import re
from collections.abc import Mapping
from typing import Any

from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticError

from amw_core.contracts import registry
from amw_core.contracts.control import ControlCommand
from amw_core.contracts.envelope import Envelope
from amw_core.contracts.error import ErrorObject
from amw_core.contracts.owner_topic import OwnerTopic
from amw_core.contracts.production_type import ProductionType
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.errors import SchemaInvalidError, SchemaVersionUnsupportedError

MAX_VIOLATIONS = 200
DEFAULT_VERSION = "1.0.0"
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _pointer(parts: Any) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def schema_violations(name: str, version: str, doc: Any) -> list[dict[str, str]]:
    """Every JSON Schema violation of ``doc`` (empty list = valid)."""
    errors: list[JsonSchemaError] = sorted(
        registry.validator(name, version).iter_errors(doc), key=lambda e: list(e.absolute_path)
    )
    return [
        {"path": _pointer(e.absolute_path), "keyword": str(e.validator), "message": e.message[:500]}
        for e in errors[:MAX_VIOLATIONS]
    ]


def _resolve_version(name: str, doc: Any, version: str | None) -> str:
    requested = version
    if requested is None and isinstance(doc, Mapping):
        candidate = doc.get("schema_version")
        requested = candidate if isinstance(candidate, str) else None
    if requested is None:
        return DEFAULT_VERSION
    if requested in registry.versions(name):
        return requested
    if _SEMVER.fullmatch(requested):
        raise SchemaVersionUnsupportedError(
            f"{name} {requested} is not supported", details={"supported": registry.versions(name)}
        )
    return DEFAULT_VERSION  # malformed version: the schema pattern reports it


def _validate[M: BaseModel](name: str, model: type[M], doc: Any, version: str | None) -> M:
    resolved = _resolve_version(name, doc, version)
    violations = schema_violations(name, resolved, doc)
    if violations:
        raise SchemaInvalidError(
            f"{name} {resolved}: {len(violations)} schema violation(s)",
            details={"violations": violations},
        )
    try:
        return model.model_validate(doc)
    except PydanticError as exc:
        model_violations = [
            {
                "path": _pointer(err["loc"]),
                "keyword": "model",
                "message": str(err["msg"])[:500],
            }
            for err in exc.errors()[:MAX_VIOLATIONS]
        ]
        raise SchemaInvalidError(
            f"{name} {resolved}: contract rule violated", details={"violations": model_violations}
        ) from exc


def validate_task_input(doc: Any, *, version: str | None = None) -> TaskInput:
    return _validate("amw.task_input", TaskInput, doc, version)


def validate_task_output(doc: Any, *, version: str | None = None) -> TaskOutput:
    """The output carries no ``schema_version``: pass ``payload_ref.schema_version`` (03 5.1)."""
    return _validate("amw.task_output", TaskOutput, doc, version)


def validate_envelope(doc: Any, *, version: str | None = None) -> Envelope:
    return _validate("amw.envelope", Envelope, doc, version)


def validate_control(doc: Any, *, version: str | None = None) -> ControlCommand:
    return _validate("amw.control", ControlCommand, doc, version)


def validate_error(doc: Any, *, version: str | None = None) -> ErrorObject:
    return _validate("amw.error", ErrorObject, doc, version)


def validate_owner_topic(doc: Any, *, version: str | None = None) -> OwnerTopic:
    """``amw.owner_topic`` has no ``schema_version`` field: pass the registered version."""
    return _validate("amw.owner_topic", OwnerTopic, doc, version)


def validate_production_type(doc: Any, *, version: str | None = None) -> ProductionType:
    """Schema plus the graph rules of 24 section 2 (see ``ProductionType``)."""
    return _validate("amw.production_type", ProductionType, doc, version)
