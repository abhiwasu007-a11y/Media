"""TenantGuard: S0 checks in the order of blueprint 7 (03 section 7.1), before any content read."""

import ipaddress
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from agent_04_research_knowledge.errors import (
    CrossTenantRef,
    InputInvalid,
    MissingDependency,
    TenantInactive,
    TenantMismatch,
)
from agent_04_research_knowledge.library.models import CollectionView, TenantScope
from agent_04_research_knowledge.library.protocol import KnowledgeLibrary
from agent_04_research_knowledge.models.pack_input import ResearchPackInput
from amw_core.contracts.common import storage_uri_owner
from amw_core.contracts.error import violation
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import OwnerReferenceKind, VideoKind
from amw_core.ids import Prefix, parse_id


@dataclass(frozen=True, slots=True)
class ChannelRecord:
    org_id: str
    channel_id: str
    compliance_profile_readable: bool


class TenantDirectory(Protocol):
    """Reads of the channel row, the tenant status and the project row (tenant-scoped, RLS)."""

    def tenant_active(self, org_id: str) -> bool: ...

    def channel(self, org_id: str, channel_id: str) -> ChannelRecord | None: ...

    def workspace_id(self, org_id: str, project_id: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class TenantCheck:
    scope: TenantScope
    collections: tuple[CollectionView, ...]
    workspace_id: str


def _private_literal(host: str) -> bool:
    try:
        return not ipaddress.ip_address(host.strip("[]")).is_global
    except ValueError:
        return host == "localhost" or host.endswith((".localhost", ".internal"))


class TenantGuard:
    def __init__(self, directory: TenantDirectory, library: KnowledgeLibrary) -> None:
        self._dir, self._lib = directory, library

    def check(
        self, task: TaskInput, data: ResearchPackInput, envelope_org_id: str | None = None
    ) -> TenantCheck:
        # (1) the channel is required for this task
        if task.channel_id is None:
            raise InputInvalid("channel_id is required")
        # a production job always has a project (03 section 3.1, CCR-214): no fallback to ""
        if task.project_id is None:
            raise InputInvalid(
                "project_id is required",
                details={"violations": [violation("PROJECT_MISSING", "/project_id")]},
            )
        # (2) ID prefixes
        parse_id(task.org_id, Prefix.ORGANISATION)
        parse_id(task.job_id, Prefix.JOB)
        parse_id(task.task_id, Prefix.TASK)
        parse_id(task.channel_id, Prefix.CHANNEL)
        # (3) org agreement across envelope, input and every reference
        if envelope_org_id is not None and envelope_org_id != task.org_id:
            raise TenantMismatch("envelope and input disagree on org_id")
        uris = [r.uri for r in task.context_refs]
        if task.payload.data_ref:
            uris.append(task.payload.data_ref)
        if data.revision is not None:
            uris.append(data.revision.prior_pack_ref)
        for uri in uris:
            if storage_uri_owner(uri) not in (task.org_id, "platform"):
                raise CrossTenantRef("reference belongs to another tenant")
        if (
            data.revision is not None
            and storage_uri_owner(data.revision.prior_pack_ref) != task.org_id
        ):
            raise CrossTenantRef("prior pack must belong to this tenant")
        # (4) channel belongs to the org and its compliance profile is readable
        channel = self._dir.channel(task.org_id, task.channel_id)
        if channel is None or not channel.compliance_profile_readable:
            raise MissingDependency("channel or compliance profile not readable")
        scope = TenantScope(task.org_id, task.channel_id)
        collections = tuple(self._lib.collections_for_channel(scope))
        # (5) a method topic needs a restricted collection
        if data.topic.video_kind is VideoKind.METHOD_TOPIC and not any(
            c.restricted for c in collections
        ):
            raise InputInvalid("method topic without a restricted collection")
        # (6) every collection key exists for this channel
        keys = data.library_scope.collection_keys
        if keys is not None and not set(keys) <= {c.collection_key for c in collections}:
            raise InputInvalid("unknown collection key")
        # (7) references
        for ref in data.owner_references:
            if ref.kind is OwnerReferenceKind.KNOWLEDGE_SOURCE:
                source_id = ref.knowledge_source_id
                if source_id is None or self._lib.get_source(scope, source_id) is None:
                    raise CrossTenantRef("reference not available to this tenant")
            else:
                parts = urlsplit(ref.url or "")
                if parts.scheme != "https" or not parts.hostname:
                    raise InputInvalid("references must be HTTPS URLs")
                if _private_literal(parts.hostname.lower()):
                    raise InputInvalid("private or local address refused")
        # (8) tenant active
        if not self._dir.tenant_active(task.org_id):
            raise TenantInactive("tenant is not active")
        workspace = self._dir.workspace_id(task.org_id, task.project_id)
        if workspace is None:
            raise MissingDependency("project workspace not found")
        return TenantCheck(scope, collections, workspace)
