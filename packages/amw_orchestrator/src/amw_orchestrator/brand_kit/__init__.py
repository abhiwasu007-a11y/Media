"""Channel brand kit as config data and its real reader for agent_08 (CCR-306)."""

from amw_orchestrator.brand_kit.fonts import FontManifest, check_kit_fonts, packaged_manifest_path
from amw_orchestrator.brand_kit.model import BrandKitDocument
from amw_orchestrator.brand_kit.packaged import packaged_brand_kit, seed_brand_kit
from amw_orchestrator.brand_kit.reader import ManifestBrandKitReader

__all__ = [
    "BrandKitDocument",
    "FontManifest",
    "ManifestBrandKitReader",
    "check_kit_fonts",
    "packaged_brand_kit",
    "packaged_manifest_path",
    "seed_brand_kit",
]
