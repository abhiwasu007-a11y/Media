"""``amw.error`` 1.0.0 (03 section 6) and the bridge from typed exceptions to the Error object."""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, ClassVar, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from amw_core.contracts.common import ActorRefStr, AmwModel, CorrelationIdStr, UtcTimestamp
from amw_core.enums import FailureClass
from amw_core.errors import CATALOGUE, AmwError

ErrorCode = Annotated[
    str,
    StringConstraints(
        pattern=r"^(TEMPORARY|PERMANENT|RESOURCE|AGENT|INFRASTRUCTURE|PUBLISHING)\.[A-Z][A-Z0-9_]{2,63}$"
    ),
]


class Violation(AmwModel):
    path: str
    keyword: str
    message: Annotated[str, StringConstraints(max_length=500)]


class ErrorDetails(AmwModel):
    """``details`` is an open object in the schema; only ``violations`` is typed."""

    model_config = ConfigDict(extra="allow")
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"violations"})

    violations: Annotated[tuple[Violation, ...], Field(max_length=200)] | None = None


class ErrorObject(AmwModel):
    code: ErrorCode
    error_class: FailureClass
    message: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    retryable: bool
    retry_after_ms: Annotated[int, Field(ge=0, strict=True)] | None
    details: ErrorDetails
    actor: ActorRefStr
    provider: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,32}$")] | None
    upstream_status: Annotated[int, Field(ge=100, le=599, strict=True)] | None
    upstream_code: Annotated[str, StringConstraints(max_length=128)] | None
    attempt_no: Annotated[int, Field(ge=0, strict=True)]
    occurred_at: UtcTimestamp
    correlation_id: CorrelationIdStr

    @model_validator(mode="after")
    def _code_rules(self) -> Self:
        # 03 section 6 rule 1: class equals the code prefix; codes only from the 07 catalogue.
        if self.code.split(".", 1)[0] != self.error_class.value:
            raise ValueError("error_class must equal the prefix of code")
        if self.code not in CATALOGUE:
            raise ValueError(f"code {self.code} is not in the 07 section 2 catalogue")
        return self


def error_object_from_exception(
    exc: AmwError,
    *,
    actor: str,
    attempt_no: int,
    occurred_at: datetime,
    correlation_id: str,
    extra_details: Mapping[str, Any] | None = None,
) -> ErrorObject:
    """Build the wire Error object from a typed exception (``retryable`` = catalogue default)."""
    details: dict[str, Any] = {**exc.details, **(extra_details or {})}
    return ErrorObject(
        code=exc.code,
        error_class=exc.error_class,
        message=exc.message[:2000] or exc.code,
        retryable=exc.retryable,
        retry_after_ms=exc.retry_after_ms,
        details=ErrorDetails.model_validate(details),
        actor=actor,
        provider=exc.provider,
        upstream_status=exc.upstream_status,
        upstream_code=exc.upstream_code,
        attempt_no=attempt_no,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
    )
