"""JSON log formatter and context binding (contextvars, so async and threads stay separate)."""

import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

from amw_core.observability.redaction import RedactionFilter, Redactor

CONTEXT_FIELDS: tuple[str, ...] = (
    "org_id",
    "correlation_id",
    "job_id",
    "task_id",
    "attempt_id",
    "actor",
)
"""27 section 7.3 rule 6 / 03 section 10.2: the fields every line carries when known."""

FAILURE_FIELDS: tuple[str, ...] = ("error_code", "error_class")
"""07 section 12: every failure line also carries these."""

PLATFORM_ORG = "platform"

_context: ContextVar[Mapping[str, str]] = ContextVar("amw_log_context", default={})  # noqa: B039

_STD_ATTRS = frozenset(
    logging.LogRecord("x", 0, "x", 0, "x", None, None).__dict__.keys() | {"message", "asctime"}
)


def current_log_context() -> Mapping[str, str]:
    return dict(_context.get())


@contextmanager
def log_context(**fields: str | None) -> Iterator[None]:
    """Bind context fields for the enclosed block (nested blocks add or override fields)."""
    unknown = set(fields) - set(CONTEXT_FIELDS) - set(FAILURE_FIELDS)
    if unknown:
        raise ValueError(f"unknown log context fields: {sorted(unknown)}")
    merged = dict(_context.get())
    merged.update({k: v for k, v in fields.items() if v is not None})
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


def bind_log_context(**fields: str | None) -> None:
    """Bind fields for the rest of the current context (worker loops); prefer ``log_context``."""
    merged = dict(_context.get())
    merged.update({k: v for k, v in fields.items() if v is not None})
    _context.set(merged)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ``ts``, ``level``, ``logger``, ``message``, the context fields
    (``org_id`` defaults to ``"platform"``), failure fields and remaining ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = dict(_context.get())
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in CONTEXT_FIELDS + FAILURE_FIELDS:
            value = record.__dict__.get(name, ctx.get(name))
            if value is not None:
                out[name] = value
        out.setdefault("org_id", PLATFORM_ORG)
        for key, value in record.__dict__.items():
            if key in _STD_ATTRS or key in out or key.startswith("_"):
                continue
            out[key] = value
        if record.exc_text:
            out["exception"] = record.exc_text
        elif record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, default=_json_default, ensure_ascii=False, sort_keys=True)


def configure_logging(
    redactor: Redactor | None = None,
    level: int = logging.INFO,
    stream: TextIO | None = None,
    logger_name: str = "amw",
) -> logging.Handler:
    """Install one JSON handler with the redaction filter on the ``amw`` logger tree.

    Returns the handler (tests attach their own stream). Repeated calls replace the handler.
    """
    logger = logging.getLogger(logger_name)
    for existing in list(logger.handlers):
        if getattr(existing, "_amw_handler", False):
            logger.removeHandler(existing)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter(redactor))
    handler._amw_handler = True  # type: ignore[attr-defined]  # marker for replacement
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return handler


def get_logger(name: str) -> logging.Logger:
    """A logger under the ``amw`` tree (``amw.<name>``)."""
    return logging.getLogger(name if name.startswith("amw") else f"amw.{name}")
