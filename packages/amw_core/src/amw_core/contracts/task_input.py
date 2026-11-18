"""``amw.task_input`` 1.0.0 (03 section 3)."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from amw_core.contracts.common import (
    ActorRefStr,
    AmwModel,
    ChannelIdStr,
    ContextRef,
    CorrelationIdStr,
    ExecutorIdStr,
    IdempotencyKeyStr,
    JobIdStr,
    OrgIdStr,
    PayloadObject,
    ProjectIdStr,
    ResourceBudget,
    SchemaVersionV1,
    TaskIdStr,
    UtcTimestamp,
    storage_uri_owner,
)
from amw_core.enums import Priority
from amw_core.errors import CrossTenantRefError


class TaskInput(AmwModel):
    """Every field of 03 section 3.1 is required; nullable ones carry ``None``."""

    org_id: OrgIdStr
    job_id: JobIdStr
    task_id: TaskIdStr
    project_id: ProjectIdStr | None
    channel_id: ChannelIdStr | None
    agent_id: ExecutorIdStr
    source_agent: ActorRefStr
    priority: Priority
    deadline: UtcTimestamp | None
    context_refs: Annotated[tuple[ContextRef, ...], Field(max_length=256)]
    resource_budget: ResourceBudget
    payload: PayloadObject
    correlation_id: CorrelationIdStr
    idempotency_key: IdempotencyKeyStr
    retry_count: Annotated[int, Field(ge=0, le=100, strict=True)]
    schema_version: SchemaVersionV1

    @model_validator(mode="after")
    def _refs_belong_to_tenant(self) -> Self:
        # 03 section 3.3 rule / 7.1 step 7: every ref belongs to org_id or to platform.
        uris = [ref.uri for ref in self.context_refs]
        if self.payload.data_ref is not None:
            uris.append(self.payload.data_ref)
        for uri in uris:
            if storage_uri_owner(uri) not in (self.org_id, "platform"):
                raise CrossTenantRefError("reference belongs to another tenant")
        return self
