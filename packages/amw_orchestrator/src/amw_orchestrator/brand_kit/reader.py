"""``ManifestBrandKitReader``: the real ``BrandKitReader`` of agent_08 (CCR-306, PROPOSED).

The ``BRAND_KIT`` context ref names a tenant-scoped, write-once JSON document (seeded from the
packaged config data, ``packaged.py``). The reader: refuses a ref of another tenant, reads it
hash-verified through ``BlobStorage``, parses ``BrandKitDocument`` (no logo / trademark fields),
checks the fonts against the pinned manifest and the glyph coverage, resolves each font to the
tenant's registered ``FONT`` asset by content hash (that asset carries the FONT licence-ledger
row) and returns agent_08's ``BrandKit``. A missing document, font or asset REFUSES; there is no
default kit (fail closed)."""

import json

from pydantic import ValidationError

from agent_08_visual_assets.charts.render import BrandPalette
from agent_08_visual_assets.persistence.protocols import AssetRepository
from agent_08_visual_assets.stage import BrandKit
from amw_core.contracts.error import violation
from amw_core.enums import AssetKind
from amw_core.errors import (
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    SchemaInvalidError,
)
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.tenancy.storage_paths import uri_owner
from amw_orchestrator.brand_kit.fonts import FontManifest, check_kit_fonts
from amw_orchestrator.brand_kit.model import BrandKitDocument

_MAX_DOC_BYTES = 64 * 1024
"""A brand-kit document is a few hundred bytes of config; a larger blob is not one."""


class ManifestBrandKitReader:
    def __init__(
        self, storage: BlobStorage, assets: AssetRepository, manifest: FontManifest
    ) -> None:
        self._storage, self._assets, self._manifest = storage, assets, manifest

    def _document(self, tx: TenantTransaction, uri: str, sha256: str | None) -> BrandKitDocument:
        if not sha256:
            raise InputInvalidError("the brand kit reference has no SHA-256")
        if uri_owner(uri) != str(tx.context.org_id):
            raise CrossTenantRefError("the brand kit belongs to another tenant")
        data = b"".join(self._storage.get(tx.context, BlobUri(uri), sha256))
        if len(data) > _MAX_DOC_BYTES:
            raise InputInvalidError("the brand kit document is too large")
        try:
            return BrandKitDocument.model_validate(json.loads(data))
        except ValidationError as exc:
            raise SchemaInvalidError(
                "the brand kit fails its schema",
                details={
                    "violations": [
                        violation(str(e["type"]), "/brand_kit/" + "/".join(map(str, e["loc"])))
                        for e in exc.errors()[:20]
                    ]
                },
            ) from None
        except ValueError, RecursionError:
            raise SchemaInvalidError(
                "the brand kit is not valid JSON",
                details={"violations": [violation("BRAND_KIT_NOT_JSON", "/brand_kit")]},
            ) from None

    def brand_kit(self, tx: TenantTransaction, uri: str, sha256: str | None) -> BrandKit:
        doc = self._document(tx, uri, sha256)
        kit = check_kit_fonts(doc, self._manifest)
        ids: list[str] = []
        for key in dict.fromkeys((doc.fonts.primary, doc.fonts.fallback)):
            found = self._assets.find_by_sha(tx, kit.fonts[key].sha256)
            if (
                found is None
                or found.asset.kind is not AssetKind.FONT
                or found.org_id != str(tx.context.org_id)
            ):
                raise MissingDependencyError(
                    "a brand-kit font is not registered as a tenant FONT asset",
                    details={"class": "brand_font"},
                )
            ids.append(found.asset_id)
        palette = BrandPalette(**doc.palette.model_dump())
        return BrandKit(palette, tuple(ids))
