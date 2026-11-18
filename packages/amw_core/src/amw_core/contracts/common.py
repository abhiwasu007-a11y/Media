"""``amw.common`` 1.0.0 as Pydantic v2 models and constrained types (03 section 3.2).

Strict: booleans are JSON booleans only, numbers never come from strings or booleans, integers
never from floats, timestamps only as RFC 3339 UTC (``Z``).

Conventions (GLOSSARY section 3, 27 section 7.3): money is integer micros/minor units, durations are
integer milliseconds, timestamps are aware ``datetime`` normalised to UTC and serialised with ``Z``.
Optional schema properties that are not nullable are omitted from ``to_doc()`` output when ``None``.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

from amw_core.enums import ContextRefPurpose
from amw_core.ids import ACTOR_REF_PATTERN, EXECUTOR_ID_PATTERN, IDEMPOTENCY_KEY_PATTERN, UUID7_BODY


def _wire(prefix: str) -> str:
    return rf"^{prefix}_{UUID7_BODY}$"


OrgIdStr = Annotated[str, StringConstraints(pattern=_wire("org"))]
JobIdStr = Annotated[str, StringConstraints(pattern=_wire("job"))]
TaskIdStr = Annotated[str, StringConstraints(pattern=_wire("tsk"))]
ProjectIdStr = Annotated[str, StringConstraints(pattern=_wire("prj"))]
ChannelIdStr = Annotated[str, StringConstraints(pattern=_wire("chn"))]
MessageIdStr = Annotated[str, StringConstraints(pattern=_wire("msg"))]
CorrelationIdStr = Annotated[str, StringConstraints(pattern=_wire("cor"))]
CostEntryIdStr = Annotated[str, StringConstraints(pattern=_wire("cst"))]
IdempotencyKeyStr = Annotated[str, StringConstraints(pattern=IDEMPOTENCY_KEY_PATTERN)]
ExecutorIdStr = Annotated[str, StringConstraints(pattern=EXECUTOR_ID_PATTERN)]
ActorRefStr = Annotated[str, StringConstraints(pattern=ACTOR_REF_PATTERN)]
SEMVER_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
V1_PATTERN = r"^1\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
Semver = Annotated[str, StringConstraints(pattern=SEMVER_PATTERN)]
SchemaVersionV1 = Annotated[str, StringConstraints(pattern=V1_PATTERN)]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
SchemaName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")]
STORAGE_URI_PATTERN = (
    r"^(amw-blob://(org_[0-9a-f-]{36}|platform)/[A-Za-z0-9._/-]+"
    r"|amw-entity://(org_[0-9a-f-]{36}|platform)/[a-z_]+/[a-z]{3}_[0-9a-f-]{36})$"
)
StorageUri = Annotated[str, StringConstraints(pattern=STORAGE_URI_PATTERN, max_length=1024)]
NonNegInt = Annotated[int, Field(ge=0, strict=True)]


RFC3339_UTC_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$"
_RFC3339_UTC = re.compile(RFC3339_UTC_PATTERN)


def is_rfc3339_utc(value: str) -> bool:
    """Strict ``utc_timestamp`` wire form: RFC 3339 date-time in UTC with ``Z`` (GLOSSARY 4)."""
    if _RFC3339_UTC.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _strict_utc(value: object) -> datetime:
    # Accept only an aware UTC datetime or the RFC 3339 "Z" string; never unix numbers, dates,
    # naive datetimes or non-UTC offsets (03 section 3.2 utc_timestamp; 27 section 7.3 rule 8).
    if isinstance(value, datetime):
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)
    if isinstance(value, str) and is_rfc3339_utc(value):
        return datetime.fromisoformat(value).astimezone(UTC)
    raise ValueError("timestamp must be an RFC 3339 UTC string ending in Z")


UtcTimestamp = Annotated[datetime, BeforeValidator(_strict_utc)]
"""Aware UTC datetime (``utc_timestamp``); see ``_strict_utc`` for what is refused."""
StrictNumber = Annotated[float, Field(strict=True)]
"""JSON number: int or float, never a bool or a numeric string."""


def storage_uri_owner(uri: str) -> str:
    """Owner segment of a storage URI (03 section 8): an org wire ID or ``platform``."""
    rest = uri.split("://", 1)[1]
    return rest.split("/", 1)[0]


class AmwModel(BaseModel):
    """Base of every contract model: ``extra=forbid``, frozen, alias-aware."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )
    omit_if_none: ClassVar[frozenset[str]] = frozenset()
    """Optional, non-nullable schema properties (by wire name): omitted when ``None`` on output,
    and an explicit ``null`` on input is refused, as the JSON Schema does."""

    @model_validator(mode="before")
    @classmethod
    def _refuse_null_for_optional(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in cls.omit_if_none:
                if key in data and data[key] is None:
                    raise ValueError(f"{key} may be omitted but must not be null")
        return data

    @model_serializer(mode="wrap")
    def _omit_optional_nones(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        if isinstance(data, dict):
            for key in self.omit_if_none:
                if key in data and data[key] is None:
                    del data[key]
        return data

    def to_doc(self) -> dict[str, Any]:
        """JSON-compatible document that validates against the model's JSON Schema."""
        result: dict[str, Any] = self.model_dump(mode="json")
        return result


class ContextRef(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"sha256", "schema", "schema_version"})

    uri: StorageUri
    purpose: ContextRefPurpose
    sha256: Sha256Hex | None = None
    schema_: SchemaName | None = Field(default=None, alias="schema")
    schema_version: Semver | None = None


class PayloadObject(AmwModel):
    """``payload_object``: inline ``data`` XOR stored ``data_ref`` + ``data_sha256``."""

    omit_if_none: ClassVar[frozenset[str]] = frozenset({"data", "data_ref", "data_sha256"})

    payload_schema: SchemaName
    payload_schema_version: Semver
    data: dict[str, Any] | None = None
    data_ref: StorageUri | None = None
    data_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def _one_of(self) -> Self:
        inline = self.data is not None and self.data_ref is None
        stored = self.data is None and self.data_ref is not None and self.data_sha256 is not None
        if not (inline or stored):
            raise ValueError("payload needs exactly one of data, or data_ref + data_sha256")
        return self


class ResourceBudget(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset(
        {"max_tokens_in", "max_tokens_out", "max_llm_calls", "max_render_ms"}
    )

    max_cost_micros: NonNegInt
    currency: Currency
    max_wall_ms: Annotated[int, Field(ge=1, strict=True)]
    max_tokens_in: NonNegInt | None = None
    max_tokens_out: NonNegInt | None = None
    max_llm_calls: NonNegInt | None = None
    max_render_ms: NonNegInt | None = None
