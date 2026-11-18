"""File delivery adapter: Protocol + in-memory fake."""

from amw_adapters.file_delivery.fake import FakeFileDeliveryAdapter
from amw_adapters.file_delivery.protocol import (
    DeliveredFile,
    DeliveryFile,
    DeliveryReceipt,
    DeliveryRequest,
    FileDeliveryAdapter,
)

__all__ = [
    "DeliveredFile",
    "DeliveryFile",
    "DeliveryReceipt",
    "DeliveryRequest",
    "FakeFileDeliveryAdapter",
    "FileDeliveryAdapter",
]
