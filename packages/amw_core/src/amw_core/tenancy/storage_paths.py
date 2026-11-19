"""Tenant-scoped storage references (03 section 8): build and check ``amw-blob://`` and
``amw-entity://`` URIs. Resolving a URI to a backend path is ``amw_core.storage`` (ADR-005)."""

import re

from amw_core.errors import CrossTenantRefError, InputInvalidError
from amw_core.ids import (
    ATTEMPT,
    JOB,
    PUBLICATION,
    TASK,
    AttemptId,
    JobId,
    OrgId,
    Prefix,
    PublicationId,
    TaskId,
    is_valid_id,
    prefix_of,
)
from amw_core.interfaces.tenancy_context import TenantTransaction

PLATFORM = "platform"
_URI = re.compile(r"^amw-(?P<scheme>blob|entity)://(?P<owner>[^/]+)/(?P<rest>.+)$")
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _check_path(parts: list[str]) -> None:
    for part in parts:
        if part in ("", ".", "..") or not _SEGMENT.fullmatch(part):
            raise InputInvalidError("storage path segment not allowed", details={"segment": part})


def blob_uri(org_id: OrgId, area: str, path: str) -> str:
    """``amw-blob://<org wire id>/<area>/<path>`` (no ``..``, no empty segments)."""
    if prefix_of(org_id) is not Prefix.ORGANISATION:
        raise InputInvalidError("blob URI needs an organisation ID")
    _check_path([*area.split("/"), *path.split("/")])
    return f"amw-blob://{org_id}/{area}/{path}"


_AGENT_ID = re.compile(r"^agent_(0[1-9]|1[0-7])$")
_TASK_FILES = frozenset({"input.json", "output.json"})


def _name_parts(name: str) -> list[str]:
    parts = name.split("/")
    _check_path(parts)
    return parts


def task_artifact_uri(
    org_id: OrgId, job_id: JobId, task_id: TaskId, attempt_id: AttemptId, name: str
) -> str:
    """``jobs/<job>/tasks/<task>/attempts/<att>/artifacts/<name>``: every write-once task file
    (03 section 8 rule 5, CCR-208). ``name`` may have several segments."""
    JOB.validate(job_id)
    TASK.validate(task_id)
    ATTEMPT.validate(attempt_id)
    return blob_uri(
        org_id,
        "jobs",
        f"{job_id}/tasks/{task_id}/attempts/{attempt_id}/artifacts/{'/'.join(_name_parts(name))}",
    )


def task_io_uri(
    org_id: OrgId, job_id: JobId, task_id: TaskId, attempt_id: AttemptId, filename: str
) -> str:
    """``.../attempts/<att>/input.json`` or ``output.json`` (the only two non-artifact files)."""
    if filename not in _TASK_FILES:
        raise InputInvalidError("task file must be input.json or output.json")
    JOB.validate(job_id)
    TASK.validate(task_id)
    ATTEMPT.validate(attempt_id)
    return blob_uri(org_id, "jobs", f"{job_id}/tasks/{task_id}/attempts/{attempt_id}/{filename}")


def checkpoint_uri(org_id: OrgId, job_id: JobId, task_id: TaskId, name: str) -> str:
    """``jobs/<job>/checkpoints/<task>/<name>``: the one checkpoint location (CCR-208)."""
    JOB.validate(job_id)
    TASK.validate(task_id)
    return blob_uri(org_id, "jobs", f"{job_id}/checkpoints/{task_id}/{'/'.join(_name_parts(name))}")


def job_cache_uri(org_id: OrgId, job_id: JobId, agent_id: str, name: str) -> str:
    """``jobs/<job>/cache/<agent_id>/<name>``: content-addressed blobs reusable by later tasks."""
    JOB.validate(job_id)
    if not _AGENT_ID.fullmatch(agent_id):
        raise InputInvalidError("agent id not allowed in a cache path", details={"agent": agent_id})
    return blob_uri(org_id, "jobs", f"{job_id}/cache/{agent_id}/{'/'.join(_name_parts(name))}")


def render_uri(org_id: OrgId, job_id: JobId, name: str) -> str:
    """``jobs/<job>/renders/<name>``."""
    JOB.validate(job_id)
    return blob_uri(org_id, "jobs", f"{job_id}/renders/{'/'.join(_name_parts(name))}")


def delivery_uri(org_id: OrgId, job_id: JobId, publication_id: PublicationId, name: str) -> str:
    """``jobs/<job>/deliveries/<pub>/<name>``."""
    JOB.validate(job_id)
    PUBLICATION.validate(publication_id)
    return blob_uri(
        org_id, "jobs", f"{job_id}/deliveries/{publication_id}/{'/'.join(_name_parts(name))}"
    )


def check_jobs_subpath(path: str) -> None:
    """03 section 8 rule 5: ``path`` (after the ``jobs`` area) must be one of the listed
    sub-paths under a job wire ID, else ``PERMANENT.INPUT_INVALID``."""
    parts = path.split("/")
    if _jobs_subpath_ok(parts):
        return
    raise InputInvalidError("storage path is not a 03 section 8 'jobs' sub-path")


def _jobs_subpath_ok(parts: list[str]) -> bool:
    if len(parts) < 3 or not is_valid_id(parts[0], Prefix.JOB):
        return False
    kind, rest = parts[1], parts[2:]
    match kind:
        case "tasks":
            if len(rest) < 4 or not is_valid_id(rest[0], Prefix.TASK) or rest[1] != "attempts":
                return False
            if not is_valid_id(rest[2], Prefix.TASK_ATTEMPT):
                return False
            tail = rest[3:]
            return (len(tail) == 1 and tail[0] in _TASK_FILES) or (
                tail[0] == "artifacts" and len(tail) >= 2
            )
        case "checkpoints":
            return len(rest) >= 2 and is_valid_id(rest[0], Prefix.TASK)
        case "cache":
            return len(rest) >= 2 and _AGENT_ID.fullmatch(rest[0]) is not None
        case "renders":
            return len(rest) >= 1
        case "deliveries":
            return len(rest) >= 2 and is_valid_id(rest[0], Prefix.PUBLICATION)
    return False


def uri_owner(uri: str) -> str:
    """The org wire ID (or ``platform``) a storage URI belongs to."""
    match = _URI.fullmatch(uri)
    if match is None:
        raise InputInvalidError("not an amw storage URI", details={"value": uri[:120]})
    owner = match["owner"]
    if owner != PLATFORM and prefix_of(owner) is not Prefix.ORGANISATION:
        raise InputInvalidError("storage URI owner is not an organisation")
    _check_path(match["rest"].split("/"))
    return owner


def require_uri_tenant(tx: TenantTransaction, uri: str, *, allow_platform: bool = False) -> None:
    """03 section 8 rule 3: the URI's org must be the transaction's org (or ``platform`` for
    read-only access). Mismatch = ``PERMANENT.CROSS_TENANT_REF``."""
    owner = uri_owner(uri)
    if owner == tx.context.org_id or (allow_platform and owner == PLATFORM):
        return
    raise CrossTenantRefError(
        "storage reference of another tenant", details={"tx_org_id": tx.context.org_id}
    )
