"""In-memory file delivery fake (no network, no disk)."""

import hashlib
import json
from typing import Any

from amw_adapters.common import CallUsage, FailurePlan, FakeEngine, FixtureStore
from amw_adapters.file_delivery.protocol import DeliveredFile, DeliveryReceipt, DeliveryRequest
from amw_core.contracts.common import storage_uri_owner
from amw_core.enums import CostUnitKind
from amw_core.errors import CrossTenantRefError

OPERATION = "delivery.file"


class FakeFileDeliveryAdapter:
    def __init__(
        self,
        *,
        provider: str = "fake_delivery",
        currency: str = "USD",
        failures: FailurePlan | None = None,
        fixtures: FixtureStore | None = None,
    ) -> None:
        self._provider = provider
        self._currency = currency
        self.engine = FakeEngine("file_delivery", failures=failures, fixtures=fixtures)
        self.delivered: dict[str, DeliveredFile] = {}

    @property
    def provider(self) -> str:
        return self._provider

    def deliver(self, request: DeliveryRequest, *, idempotency_key: str) -> DeliveryReceipt:
        for file in request.files:
            if storage_uri_owner(file.uri) != request.org_id:
                raise CrossTenantRefError("delivery file belongs to another tenant")

        def build(_digest: str, _fixture: dict[str, Any] | None) -> DeliveryReceipt:
            files = tuple(
                DeliveredFile(
                    name=f.name,
                    delivered_ref=f"fake-delivery://{request.job_id}/{request.deliverable_preset}/{f.name}",
                    sha256=f.sha256,
                    size_bytes=f.size_bytes,
                )
                for f in request.files
            )
            manifest = json.dumps(
                [{"name": f.name, "sha256": f.sha256, "size_bytes": f.size_bytes} for f in files],
                sort_keys=True,
                separators=(",", ":"),
            )
            for f in files:
                self.delivered[f.delivered_ref] = f
            usage = CallUsage(
                provider=self._provider,
                operation=OPERATION,
                units=sum(f.size_bytes for f in files),
                unit_kind=CostUnitKind.BYTES,
                cost_micros=0,
                currency=self._currency,
                idempotency_key=idempotency_key,
            )
            return DeliveryReceipt(
                files=files,
                manifest_sha256=hashlib.sha256(manifest.encode()).hexdigest(),
                usage=usage,
            )

        return self.engine.run(OPERATION, idempotency_key, request, build, DeliveryReceipt)
