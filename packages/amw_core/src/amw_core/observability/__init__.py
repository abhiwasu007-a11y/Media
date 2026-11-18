"""Structured JSON logging with tenant / correlation fields and secret redaction.

27 section 7.3 rule 6; 03 section 10.2; 07 section 12; 08 section 3.1 rule 3 and section 8.5.
Every line carries ``org_id`` (``"platform"`` for platform-wide work), ``correlation_id``,
``job_id``, ``task_id``, ``attempt_id`` and ``actor`` when known. A redaction filter removes values
of secret-named fields, known secret patterns and every configured secret value.
"""

from amw_core.observability.logging import (
    CONTEXT_FIELDS,
    JsonFormatter,
    bind_log_context,
    configure_logging,
    current_log_context,
    get_logger,
    log_context,
)
from amw_core.observability.redaction import (
    REDACTED,
    RedactionFilter,
    Redactor,
    contains_secret,
)

__all__ = [
    "CONTEXT_FIELDS",
    "REDACTED",
    "JsonFormatter",
    "RedactionFilter",
    "Redactor",
    "bind_log_context",
    "configure_logging",
    "contains_secret",
    "current_log_context",
    "get_logger",
    "log_context",
]
