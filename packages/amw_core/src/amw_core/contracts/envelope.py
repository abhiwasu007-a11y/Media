"""``amw.envelope`` 1.0.0 (03 section 4)."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from amw_core.contracts.common import (
    ActorRefStr,
    AmwModel,
    CorrelationIdStr,
    JobIdStr,
    MessageIdStr,
    OrgIdStr,
    SchemaVersionV1,
    Semver,
    Sha256Hex,
    StorageUri,
    TaskIdStr,
    UtcTimestamp,
    storage_uri_owner,
)
from amw_core.enums import PayloadRefSchema, Priority
from amw_core.errors import CrossTenantRefError


class PayloadRef(AmwModel):
    uri: StorageUri
    schema_: PayloadRefSchema = Field(alias="schema")
    schema_version: Semver
    sha256: Sha256Hex
    size_bytes: Annotated[int, Field(ge=2, strict=True)]
    media_type: Literal["application/json"]


class Envelope(AmwModel):
    """Message kind is ``payload_ref.schema``: task_input = dispatch, task_output = result."""

    org_id: OrgIdStr
    message_id: MessageIdStr
    sender: ActorRefStr
    receiver: ActorRefStr
    job_id: JobIdStr | None
    task_id: TaskIdStr | None
    payload_ref: PayloadRef
    priority: Priority
    timestamp: UtcTimestamp
    correlation_id: CorrelationIdStr
    schema_version: SchemaVersionV1

    @property
    def is_control(self) -> bool:
        return self.payload_ref.schema_ is PayloadRefSchema.CONTROL

    @model_validator(mode="after")
    def _rules(self) -> Self:
        # Schema allOf: dispatches and results are bound to a job and task.
        if not self.is_control and (self.job_id is None or self.task_id is None):
            raise ValueError("job_id and task_id are required unless the payload is amw.control")
        # 03 section 7.1 step 4: the payload URI belongs to the envelope's org.
        if storage_uri_owner(self.payload_ref.uri) != self.org_id:
            raise CrossTenantRefError("payload_ref.uri belongs to another tenant")
        return self
