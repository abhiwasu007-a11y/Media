"""``TenantGuard`` (blueprint 10.1, D-PRE-1; 08 section 8 layer 1).

Pure decision over facts the worker has read through ``amw_core.tenancy``. Order matters: the three
org IDs must agree, the tenant must be active, the channel must belong to the org (an unknown or
foreign channel is ``MISSING_DEPENDENCY``, no existence oracle), every reference must belong to the
task's org and channel (a foreign one is ``CROSS_TENANT_REF`` plus a security event naming only the
caller's org) and its SHA-256 must verify.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agent_05_scriptwriter.errors import (
    CrossTenantRef,
    InputInvalid,
    MissingDependency,
    TenantInactive,
    TenantMismatch,
)


@dataclass(frozen=True, slots=True)
class RefFact:
    purpose: str
    org: str
    channel: str | None
    sha_ok: bool


@dataclass(frozen=True, slots=True)
class TenantFacts:
    envelope_org: str
    input_org: str
    db_org: str
    channel_org: str | None
    tenant_status: str
    refs: Sequence[RefFact]
    task_channel: str


SecurityEvent = Callable[[str, dict[str, str]], None]


def check_tenant(facts: TenantFacts, on_security_event: SecurityEvent) -> None:
    if not (facts.envelope_org == facts.input_org == facts.db_org):
        raise TenantMismatch("org id differs across envelope, input and database context")
    if facts.tenant_status != "ACTIVE":
        raise TenantInactive("tenant is not active")
    if facts.channel_org != facts.db_org:
        raise MissingDependency("channel not found")
    for ref in facts.refs:
        if ref.org != facts.db_org or (
            ref.channel is not None and ref.channel != facts.task_channel
        ):
            on_security_event("security.cross_tenant_ref", {"org_id": facts.db_org})
            raise CrossTenantRef("a context reference belongs to another tenant or channel")
        if not ref.sha_ok:
            raise InputInvalid("a context reference failed its SHA-256 check")
