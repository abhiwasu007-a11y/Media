"""Log event and metric names (blueprint 10 section 22) and a structural no-leak guarantee.

``amw_core.observability`` does not exist yet (core_need): this module is the package's own thin
layer. ``emit`` accepts only integers, booleans, ``None`` and short identifier-like strings (IDs,
hashes, enums, check IDs): a script string, subtitle text, asset title, path or stderr cannot be
logged because it does not fit that shape (NFR-13, S-05). A value that does not fit is a
programming error and raises.
"""

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

LOGGER = logging.getLogger("agent_10")
AGENT = "agent_10"

LOG_EVENTS = frozenset(
    {
        "render.start", "render.tenant_ok", "render.upstream_ok", "render.guard", "render.timeline",
        "render.segment_plan", "render.segment_done", "render.resume", "render.drain",
        "render.self_drain", "render.mux", "render.registered", "subs.cues", "subs.validated",
        "qc.start", "qc.group_done", "qc.check", "qc.gate", "qc.evidence", "qc.persisted",
        "selftest.result",
    }
)  # fmt: skip
_SAFE = re.compile(r"^[A-Za-z0-9_.:#<>-]{1,128}$")


@dataclass(frozen=True, slots=True)
class LogContext:
    org_id: str
    job_id: str
    task_id: str
    attempt_id: str
    correlation_id: str


def emit(event: str, ctx: LogContext, **fields: int | bool | str | None) -> None:
    if event not in LOG_EVENTS:
        raise ValueError(f"unknown log event {event!r}")
    record: dict[str, int | bool | str | None] = {
        "event": event,
        "org_id": ctx.org_id,
        "job_id": ctx.job_id,
        "task_id": ctx.task_id,
        "attempt_id": ctx.attempt_id,
        "correlation_id": ctx.correlation_id,
        "actor": AGENT,
    }
    for key, value in fields.items():
        if isinstance(value, str) and not _SAFE.fullmatch(value):
            raise ValueError(f"log field {key!r} is not identifier-like")
        record[key] = value
    LOGGER.info(json.dumps(record, sort_keys=True, separators=(",", ":")))


class MetricsSink(Protocol):
    """Counters, histograms and gauges; every call carries ``org_id`` and ``agent_id``."""

    def count(self, name: str, labels: Mapping[str, str]) -> None: ...

    def observe(self, name: str, value: int, labels: Mapping[str, str]) -> None: ...


class MemoryMetrics:
    def __init__(self) -> None:
        self.counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
        self.observations: list[tuple[str, int, tuple[tuple[str, str], ...]]] = []

    def count(self, name: str, labels: Mapping[str, str]) -> None:
        key = (name, tuple(sorted(labels.items())))
        self.counters[key] = self.counters.get(key, 0) + 1

    def observe(self, name: str, value: int, labels: Mapping[str, str]) -> None:
        self.observations.append((name, value, tuple(sorted(labels.items()))))


def labels(org_id: str, **extra: str) -> dict[str, str]:
    return {"org_id": org_id, "agent_id": AGENT, **extra}
