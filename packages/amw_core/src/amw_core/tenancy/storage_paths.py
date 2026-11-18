"""Tenant-scoped storage references (03 section 8): build and check ``amw-blob://`` and
``amw-entity://`` URIs. Resolving a URI to a backend path is ``amw_core.storage`` (ADR-005)."""

import re

from amw_core.errors import CrossTenantRefError, InputInvalidError
from amw_core.ids import OrgId, Prefix, prefix_of
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
