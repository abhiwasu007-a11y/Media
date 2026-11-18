"""File delivery adapter Protocol (3A slice spec section 4; capability ``file_delivery``;
task type ``agent_13.file_delivery``; idempotency scope ``delivery.file``: job, deliverable
preset, file SHA-256).

Delivers already-stored, verified blobs of one tenant; every file URI must belong to the
request's ``org_id`` (``CrossTenantRefError`` otherwise, 03 section 8.3). The storage area
``jobs/<job>/deliveries/<publication>/`` is pending CCR-3A-3, so the delivered location is an
opaque ``delivered_ref`` chosen by the adapter. Usage is recorded with ``amount_micros = 0``.
"""

from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field

from amw_adapters.common import AdapterModel, AdapterResult
from amw_core.contracts.common import JobIdStr, OrgIdStr, Sha256Hex, StorageUri


class DeliveryFile(AdapterModel):
    name: Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")]
    uri: StorageUri
    sha256: Sha256Hex
    size_bytes: Annotated[int, Field(ge=0)]
    media_type: str


class DeliveryRequest(AdapterModel):
    org_id: OrgIdStr
    job_id: JobIdStr
    deliverable_preset: Annotated[str, Field(min_length=1)]
    files: Annotated[tuple[DeliveryFile, ...], Field(min_length=1)]


class DeliveredFile(AdapterModel):
    name: str
    delivered_ref: str
    sha256: str
    size_bytes: int


class DeliveryReceipt(AdapterResult):
    files: tuple[DeliveredFile, ...]
    manifest_sha256: str


@runtime_checkable
class FileDeliveryAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    def deliver(self, request: DeliveryRequest, *, idempotency_key: str) -> DeliveryReceipt: ...
