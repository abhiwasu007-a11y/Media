"""``amw.error`` 1.0.0 (03 section 6) and the bridge from typed exceptions to the Error object."""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Annotated, Any, ClassVar, Self

from pydantic import ConfigDict, Field, StrictBool, StringConstraints, model_validator

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


MAX_VIOLATIONS = 200
MAX_VIOLATION_MESSAGE = 500


def violation(code: str, path: str = "", message: str | None = None) -> Violation:
    """The one builder of a ``details.violations[]`` item (03 section 6 rule 6, CCR-210).

    ``code`` is the payload-local reason code (``keyword``), ``path`` the JSON Pointer of the
    failing location or ``""``; ``message`` is a short text without content
    (default: the code itself).
    """
    text = code if message is None else message
    return Violation(path=path, keyword=code, message=text[:MAX_VIOLATION_MESSAGE])


def _violation_item(item: object) -> Violation | dict[str, Any]:
    """Normalise one ``violations`` item; a bare string becomes ``{"", s, s}`` (CCR-210)."""
    if isinstance(item, Violation):
        return item
    if isinstance(item, Mapping):
        keyword = str(item.get("keyword", ""))
        return {
            "path": str(item.get("path", "")),
            "keyword": keyword,
            "message": str(item.get("message", keyword))[:MAX_VIOLATION_MESSAGE],
        }
    return violation(str(item))


def _normalised_details(details: dict[str, Any]) -> dict[str, Any]:
    raw = details.get("violations")
    if raw is None:
        return {k: v for k, v in details.items() if k != "violations"}
    if isinstance(raw, str | bytes | Mapping | Violation) or not isinstance(raw, Iterable):
        items: list[object] = [raw]
    else:
        items = list(raw)
    return {**details, "violations": [_violation_item(i) for i in items[:MAX_VIOLATIONS]]}


class ErrorDetails(AmwModel):
    """``details`` is an open object in the schema; only ``violations`` is typed."""

    model_config = ConfigDict(extra="allow")
    omit_if_none: ClassVar[frozenset[str]] = frozenset({"violations"})

    violations: Annotated[tuple[Violation, ...], Field(max_length=200)] | None = None


class ErrorObject(AmwModel):
    code: ErrorCode
    error_class: FailureClass
    message: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    retryable: StrictBool
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
    """Build the wire Error object from a typed exception (``retryable`` = catalogue default).

    Never fails because of ``details``: bare-string violations are converted (03 section 6 rule 6).
    """
    details = _normalised_details({**exc.details, **(extra_details or {})})
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
