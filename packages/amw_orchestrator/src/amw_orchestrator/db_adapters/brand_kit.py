"""``BrandKitReader`` of agent_08: no database object exists to read (CCR-299).

04 section 5.12 describes ``brand_kits`` and ``channels.brand_kit_id`` is a TFK to it, but no
migration creates the table, and the brand-kit document has no registered schema (CCR-290; three
readers use three shapes). Building a reader would mean inventing either the table or the
document format, which is a contract (rule 2 of the lane rules). This adapter is therefore the
fail-closed default the production wiring uses until CCR-299 is decided: it always refuses with a
typed ``MissingDependencyError``; it never returns a made-up kit and never reads a blob.
"""

from agent_08_visual_assets.stage import BrandKit
from amw_core.errors import MissingDependencyError
from amw_core.interfaces.tenancy_context import TenantTransaction


class UnavailableBrandKitReader:
    def brand_kit(self, tx: TenantTransaction, uri: str, sha256: str | None) -> BrandKit | None:
        raise MissingDependencyError(
            "brand kits are not stored yet (CCR-299): no brand_kits table and no document schema",
            details={"class": "brand_kit"},
        )
