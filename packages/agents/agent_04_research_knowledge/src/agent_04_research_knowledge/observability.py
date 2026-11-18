"""Structured logs and audit rows without content (blueprint 22; NFR-6, 27 section 7.3.6).

``EventLogger.emit`` accepts only identifiers, counts, booleans and short code strings as field
values, so a chunk, a passage or a note cannot be passed to a log line by accident; every line
carries ``org_id`` and ``actor = agent_04``. ``AuditSink`` is the narrow writer the package uses;
``CoreAuditSink`` adapts ``amw_core`` ``AuditLog`` inside a tenant transaction.
"""

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from amw_core.enums import ActorKind
from amw_core.ids import ActorRef, JobId
from amw_core.interfaces import AuditLog, Clock, NewAuditEntry, TenancyContext, TenantContext

LOGGER_NAME = "amw.agent_04"
ACTOR = "agent_04"
_SAFE_STR = re.compile(r"^[A-Za-z0-9_.:/#=-]{0,96}$")
MAX_LIST = 64


def _check(value: Any) -> Any:
    if isinstance(value, bool | int) or value is None:
        return value
    if isinstance(value, str):
        if not _SAFE_STR.fullmatch(value):
            raise ValueError("log fields hold identifiers and codes only, never free text")
        return value
    if isinstance(value, list | tuple):
        if len(value) > MAX_LIST:
            raise ValueError("log list fields are bounded")
        return [_check(v) for v in value]
    raise ValueError(f"unsupported log field type {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class LogContext:
    org_id: str
    correlation_id: str | None = None
    job_id: str | None = None
    task_id: str | None = None
    attempt_id: str | None = None


class EventLogger:
    def __init__(self, context: LogContext, logger: logging.Logger | None = None) -> None:
        self._ctx = context
        self._logger = logger or logging.getLogger(LOGGER_NAME)

    def emit(self, level: int, event: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "event": event,
            "org_id": self._ctx.org_id,
            "correlation_id": self._ctx.correlation_id,
            "job_id": self._ctx.job_id,
            "task_id": self._ctx.task_id,
            "attempt_id": self._ctx.attempt_id,
            "actor": ACTOR,
        }
        record.update({k: _check(v) for k, v in fields.items()})
        self._logger.log(level, json.dumps(record, sort_keys=True), extra={"amw_event": record})

    def info(self, event: str, **fields: Any) -> None:
        self.emit(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self.emit(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self.emit(logging.ERROR, event, **fields)


class AuditSink(Protocol):
    """One audit row per retrieval, gate decision, release lookup, snapshot, ingestion (22.3)."""

    def record(
        self, action: str, target_kind: str, target_id: str | None, details: Mapping[str, Any]
    ) -> None: ...


class CoreAuditSink:
    """Writes through ``amw_core`` ``AuditLog`` in its own tenant transaction (never direct DML)."""

    def __init__(
        self,
        audit: AuditLog,
        tenancy: TenancyContext,
        clock: Clock,
        context: TenantContext,
        job_id: JobId | None = None,
    ) -> None:
        self._audit, self._tenancy, self._clock = audit, tenancy, clock
        self._context, self._job_id = context, job_id

    def record(
        self, action: str, target_kind: str, target_id: str | None, details: Mapping[str, Any]
    ) -> None:
        safe = {k: _check(v) for k, v in details.items()}
        entry = NewAuditEntry(
            actor_kind=ActorKind.AGENT,
            actor_ref=ActorRef(ACTOR),
            authority="agent_04.research",
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            occurred_at=self._clock.now(),
            job_id=self._job_id,
            correlation_id=self._context.correlation_id,
            details=safe,
        )
        with self._tenancy.transaction(self._context) as tx:
            self._audit.append(tx, entry)


class NullAuditSink:
    def record(
        self, action: str, target_kind: str, target_id: str | None, details: Mapping[str, Any]
    ) -> None:
        return None
