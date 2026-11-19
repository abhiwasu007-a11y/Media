"""``TemplateResolver``: overlay template ID -> the tenant's current ``TEMPLATE`` asset.

CCR-204: an overlay's ``template_ref`` is a template ID (GLOSSARY "Template ID"), never a URI or
a brand key. The ID is ``attributes.template_id`` of the tenant's ``TEMPLATE`` asset that holds
the current version (registered once per tenant by the shared registry, CCR-031/032). This is the
only place that maps an ID to an asset; an unknown ID is ``MISSING_DEPENDENCY`` carrying one
``NO_TEMPLATE:<template_id>`` violation per unknown ID (and nothing partial is returned).
"""

from collections.abc import Iterable

from agent_08_visual_assets.persistence.protocols import AssetRepository
from agent_08_visual_assets.persistence.records import AssetRecord
from amw_core.contracts.error import violation
from amw_core.enums import AssetKind, AssetStatus
from amw_core.errors import MissingDependencyError
from amw_core.interfaces.tenancy_context import TenantTransaction


class TemplateResolver:
    def __init__(self, assets: AssetRepository) -> None:
        self._assets = assets

    def index(self, tx: TenantTransaction) -> dict[str, str]:
        """``template_id -> asset_id`` of the tenant's ``ACTIVE`` ``TEMPLATE`` assets. When
        several assets carry the same ID, the newest (``created_at``, then ``asset_id``) is the
        current one."""
        best: dict[str, AssetRecord] = {}
        for rec in self._assets.list_assets(tx, kinds=(AssetKind.TEMPLATE,)):
            tid = rec.asset.attributes.get("template_id")
            if rec.status is not AssetStatus.ACTIVE or not isinstance(tid, str):
                continue
            held = best.get(tid)
            if held is None or (rec.created_at, rec.asset_id) > (held.created_at, held.asset_id):
                best[tid] = rec
        return {tid: rec.asset_id for tid, rec in best.items()}

    def resolve(self, tx: TenantTransaction, template_ids: Iterable[str]) -> dict[str, str]:
        """Every ID resolved, or ``MISSING_DEPENDENCY`` listing all unknown ones."""
        wanted = sorted(set(template_ids))
        known = self.index(tx)
        missing = [t for t in wanted if t not in known]
        if missing:
            raise MissingDependencyError(
                "overlay template not registered",
                details={
                    "class": "overlay_template",
                    "violations": [violation(f"NO_TEMPLATE:{t}", "/overlays") for t in missing],
                },
            )
        return {t: known[t] for t in wanted}
