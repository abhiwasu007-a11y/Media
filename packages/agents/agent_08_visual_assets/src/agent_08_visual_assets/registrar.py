"""``SourceIntakeGuard`` and ``AssetRegistrar`` (FR-21, 3A_SLICE R20, Q22).

Owner material and datasets enter the library only through the operator tool on the owner's
instruction (D5), by a human actor, from the owner-approved course ``data_pack`` and read-only.
Any other source class (the Trade research folders included) is rejected; the factory never reads
those folders and never writes to a source. The registrar is library code called by the app, not a
task type; it never lets an agent certify its own material.
"""

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from agent_08_visual_assets.charts.cases import ChartCase
from agent_08_visual_assets.charts.dataset import DatasetLoader
from agent_08_visual_assets.persistence.protocols import AssetRepository
from agent_08_visual_assets.persistence.records import AssetRecord, NewAsset
from agent_08_visual_assets.reuse.fingerprint import Fingerprinter
from amw_core.enums import ActorKind, AssetKind, LicenceSourceType, VisualSourceTier
from amw_core.errors import InputInvalidError, PermissionDeniedError
from amw_core.ids import ActorRef
from amw_core.interfaces.audit_log import AuditLog, NewAuditEntry
from amw_core.interfaces.storage import BlobStorage
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction

APPROVED_SOURCE_CLASS = "data_pack"
AUDIT_ACCEPTED = "asset_registrar.intake_accepted"
AUDIT_REJECTED = "asset_registrar.intake_rejected"


class IntakeResult(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class IntakeDecision:
    result: IntakeResult
    attributes: dict[str, str] | None
    error_code: str | None
    audit_event: bool = True


class SourceIntakeGuard:
    @staticmethod
    def check_actor(*, actor_kind: ActorKind, via_operator_tool: bool) -> IntakeDecision:
        """Owner footage and fonts: a human through the operator tool; no source-class rule."""
        if actor_kind is not ActorKind.HUMAN or not via_operator_tool:
            return IntakeDecision(IntakeResult.REJECT, None, PermissionDeniedError.code)
        return IntakeDecision(IntakeResult.ACCEPT, {}, None)

    @staticmethod
    def check(
        *,
        actor_kind: ActorKind,
        via_operator_tool: bool,
        source_class: str,
        access: Literal["READ", "WRITE"],
    ) -> IntakeDecision:
        denied = PermissionDeniedError.code
        if actor_kind is not ActorKind.HUMAN:
            return IntakeDecision(IntakeResult.REJECT, None, denied)
        if not via_operator_tool:
            return IntakeDecision(IntakeResult.REJECT, None, denied)
        if access != "READ":
            return IntakeDecision(IntakeResult.REJECT, None, denied)
        if source_class != APPROVED_SOURCE_CLASS:
            return IntakeDecision(IntakeResult.REJECT, None, InputInvalidError.code)
        return IntakeDecision(
            IntakeResult.ACCEPT, {"source_path_class": APPROVED_SOURCE_CLASS}, None
        )


@dataclass(frozen=True, slots=True)
class Intake:
    """How the material arrived: who, through which tool, from which source, with what access."""

    actor_kind: ActorKind
    actor_ref: ActorRef
    via_operator_tool: bool
    source_class: str
    access: Literal["READ", "WRITE"] = "READ"


class AssetRegistrar:
    def __init__(
        self,
        *,
        assets: AssetRepository,
        blobs: BlobStorage,
        audit: AuditLog,
        max_dataset_bars: int,
    ) -> None:
        self._assets = assets
        self._blobs = blobs
        self._audit = audit
        self._max_bars = max_dataset_bars

    def _guard(
        self, tx: TenantTransaction, intake: Intake, target_kind: str, *, dataset: bool = True
    ) -> dict[str, str]:
        if dataset:
            decision = SourceIntakeGuard.check(
                actor_kind=intake.actor_kind,
                via_operator_tool=intake.via_operator_tool,
                source_class=intake.source_class,
                access=intake.access,
            )
        else:
            decision = SourceIntakeGuard.check_actor(
                actor_kind=intake.actor_kind, via_operator_tool=intake.via_operator_tool
            )
        self._audit.append(
            tx,
            NewAuditEntry(
                actor_kind=intake.actor_kind,
                actor_ref=intake.actor_ref,
                authority="operator_tool",
                action=AUDIT_ACCEPTED if decision.attributes is not None else AUDIT_REJECTED,
                target_kind=target_kind,
                target_id=None,
                occurred_at=datetime.now(UTC),
                details={"source_class": intake.source_class, "error_code": decision.error_code},
            ),
        )
        if decision.attributes is None:
            exc = (
                PermissionDeniedError
                if decision.error_code == PermissionDeniedError.code
                else InputInvalidError
            )
            raise exc("intake refused")
        return decision.attributes

    def _store(
        self, ctx: TenantContext, tx: TenantTransaction, area: str, name: str, content: bytes
    ) -> str:
        uri = self._blobs.blob_uri(ctx, area, name)
        if not self._blobs.head(ctx, uri).exists:
            self._blobs.put(ctx, uri, io.BytesIO(content))
        return str(uri)

    def register_dataset(
        self,
        tx: TenantTransaction,
        intake: Intake,
        *,
        content: bytes,
        instrument: str,
        timeframe: str,
        title: str,
    ) -> AssetRecord:
        attributes = self._guard(tx, intake, "dataset")
        series = DatasetLoader.parse(
            content, max_bars=self._max_bars, sha256=DatasetLoader.sha256(content)
        )
        uri = self._store(tx.context, tx, "assets", f"datasets/{series.sha256}.csv", content)
        return self._assets.insert(
            tx,
            NewAsset(
                kind=AssetKind.DOCUMENT,
                source_type=LicenceSourceType.OWNER_MADE,
                content_sha256=series.sha256,
                uri=uri,
                size_bytes=len(content),
                title=title,
                attributes={
                    **attributes,
                    "doc_kind": "DATASET",
                    "instrument": instrument,
                    "timeframe": timeframe,
                    "data_start_date": series.start_date.isoformat(),
                    "data_end_date": series.end_date.isoformat(),
                    "bars_count": len(series),
                },
            ),
        )

    def register_chart_case(
        self, tx: TenantTransaction, intake: Intake, *, document: bytes, title: str
    ) -> AssetRecord:
        attributes = self._guard(tx, intake, "chart_case")
        try:
            case = ChartCase.model_validate_json(document)
        except ValueError:
            raise InputInvalidError("chart case document is invalid") from None
        sha = Fingerprinter.sha256(document)
        uri = self._store(tx.context, tx, "assets", f"chart_cases/{sha}.json", document)
        return self._assets.insert(
            tx,
            NewAsset(
                kind=AssetKind.DOCUMENT,
                source_type=LicenceSourceType.OWNER_MADE,
                content_sha256=sha,
                uri=uri,
                size_bytes=len(document),
                title=title,
                attributes={
                    **attributes,
                    "doc_kind": "CHART_CASE",
                    "case_id": case.case_id,
                    "instrument": case.instrument,
                    "timeframe": case.timeframe,
                    "method_content": case.method_content,
                    "release_approval_id": case.release_approval_id,
                    "dataset_asset_id": case.dataset_asset_id,
                },
            ),
        )

    def register_owner_asset(
        self,
        tx: TenantTransaction,
        intake: Intake,
        *,
        content: bytes,
        kind: AssetKind,
        title: str,
        tags: tuple[str, ...] = (),
        release_ref: str | None = None,
        width_px: int | None = None,
        height_px: int | None = None,
        duration_ms: int | None = None,
    ) -> AssetRecord:
        """Owner footage or image from a human actor (``OWNER_MADE``, tier A)."""
        if kind not in (AssetKind.VIDEO, AssetKind.IMAGE, AssetKind.TEMPLATE, AssetKind.FONT):
            raise InputInvalidError("unsupported owner asset kind")
        attributes = self._guard(tx, intake, "owner_asset", dataset=False)
        sha = Fingerprinter.sha256(content)
        uri = self._store(tx.context, tx, "assets", f"owner/{sha}", content)
        tier = VisualSourceTier.A_OWNER_REAL if kind in (AssetKind.VIDEO, AssetKind.IMAGE) else None
        return self._assets.insert(
            tx,
            NewAsset(
                kind=kind,
                source_type=LicenceSourceType.OWNER_MADE,
                content_sha256=sha,
                uri=uri,
                size_bytes=len(content),
                title=title,
                visual_source_tier=tier,
                release_ref=release_ref,
                width_px=width_px,
                height_px=height_px,
                duration_ms=duration_ms,
                attributes={**attributes, "tags": list(tags)},
            ),
        )
