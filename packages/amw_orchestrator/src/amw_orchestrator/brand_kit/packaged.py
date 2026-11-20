"""Packaged brand-kit config documents and their seeding into a tenant's storage.

The documents are config data under ``amw_orchestrator/data/brand_kits``. ``seed_brand_kit`` stores
one write-once, content-addressed in the tenant's ``assets`` area and returns the reference the
job documents (``BRAND_KIT`` context ref) carry. It is run by the operator seed step, not by a
worker."""

import hashlib
import io
import re
from importlib import resources
from typing import Final

from amw_core.errors import MissingDependencyError
from amw_core.ids import OrgId
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.tenancy.storage_paths import blob_uri
from amw_orchestrator.brand_kit.model import BrandKitDocument
from amw_orchestrator.executor import DocRef

_NAME: Final = r"^[a-z][a-z0-9_]{0,63}$"


def packaged_brand_kit_bytes(name: str) -> bytes:
    if re.fullmatch(_NAME, name) is None:
        raise MissingDependencyError(
            "no packaged brand kit of this name", details={"class": "brand_kit"}
        )
    try:
        return (
            resources.files("amw_orchestrator")
            .joinpath(f"data/brand_kits/{name}.json")
            .read_bytes()
        )
    except OSError:
        raise MissingDependencyError(
            "no packaged brand kit of this name", details={"class": "brand_kit"}
        ) from None


def packaged_brand_kit(name: str) -> BrandKitDocument:
    return BrandKitDocument.model_validate_json(packaged_brand_kit_bytes(name))


def seed_brand_kit(
    storage: BlobStorage, org_id: OrgId, name: str, actor: str = "agent_01"
) -> DocRef:
    """Store the packaged kit ``name`` for the tenant (idempotent: same bytes, same reference)."""
    data = packaged_brand_kit_bytes(name)
    packaged_brand_kit(name)  # a packaged document that fails its schema is never seeded
    sha = hashlib.sha256(data).hexdigest()
    uri = blob_uri(org_id, "assets", f"brand_kits/{name}/{sha}.json")
    context = TenantContext(org_id, actor, None)  # type: ignore[arg-type]
    if not storage.head(context, BlobUri(uri)).exists:
        storage.put(context, BlobUri(uri), io.BytesIO(data))
    return DocRef(uri, sha)
