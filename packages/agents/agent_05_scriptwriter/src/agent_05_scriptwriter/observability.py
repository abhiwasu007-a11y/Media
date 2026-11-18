"""Content-free structured logging (blueprint 10 common rules, 22.1, 27 section 7.3.6).

Only whitelisted field names with scalar IDs, codes, hashes or counts are written. A string that is
not an identifier-shaped token is replaced, so narration, brief text, feedback or topic text cannot
reach a log line even by mistake.
"""

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger("agent_05")

_TOKEN = re.compile(r"^[A-Za-z0-9_.:\-/]{1,128}$")
ALLOWED_FIELDS = frozenset(
    {
        "org_id",
        "channel_id",
        "job_id",
        "task_id",
        "attempt_id",
        "correlation_id",
        "actor",
        "step",
        "step_key",
        "section_id",
        "code",
        "reason",
        "rule_ids",
        "check_ids",
        "count",
        "segments",
        "scenes",
        "characters",
        "repair",
        "script_id",
        "version",
        "sha256",
        "hook_id",
        "calls",
        "checkpoint_step",
        "status",
        "input_class",
    }
)


def _clean(value: Any) -> Any:
    if isinstance(value, bool | int) or value is None:
        return value
    if isinstance(value, str):
        return value if _TOKEN.match(value) else "[redacted]"
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value][:50]
    return "[redacted]"


def safe_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {k: _clean(v) for k, v in fields.items() if k in ALLOWED_FIELDS}


def log_event(event: str, **fields: Any) -> None:
    """One JSON line; ``event`` is a fixed name such as ``script_draft.plan_done``."""
    payload = {"event": event, **safe_fields(fields)}
    logger.info(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def log_security_event(event: str, org_id: str) -> None:
    """``security.cross_tenant_ref`` carries the caller's org only, never the foreign one."""
    logger.warning(json.dumps({"event": event, "org_id": _clean(org_id)}, sort_keys=True))
