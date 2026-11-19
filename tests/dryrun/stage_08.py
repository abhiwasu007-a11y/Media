# ruff: noqa: E501, B007
# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated,index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""``s08_assets`` -> ``agent_08.asset_sourcing`` (code-made graphics, tier C).

Integration findings handled here (input builder / worker wrapper, see the dry-run report):
* Agent 08 has no ``TaskInput`` entry point and returns a ``StageResult``, not an
  ``amw.task_output``: the wrapper below builds the task output.
* Agent 08 reads ``plan_bytes`` as ``{"views": {"agent_08_shots": [...]}, "overlays": [...]}``,
  while Agent 09 stores the ``ShotPlan`` model in its blob and the views in its payload; the
  builder writes that hand-off document and points ``shot_plan_ref`` at it.
* No stock or AI-image adapter is wired into Agent 08 (tiers B / D / E are skipped by design
  in this build), so the fake stock / image adapters are not exercised.
"""

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_08_visual_assets.charts.render import BrandPalette
from agent_08_visual_assets.models.task_input import SourcingInput
from agent_08_visual_assets.persistence.records import NewAsset
from agent_08_visual_assets.settings import AssetSettings, CanvasSize
from agent_08_visual_assets.stage import AssetSourcingStage, BrandKit, JobScope
from agent_08_visual_assets.testing.memory import (
    MemoryAssetRepository,
    MemoryAuditLog,
    MemoryFingerprintRepository,
    MemoryLedgerRepository,
    MemoryLicenceRepository,
    MemoryReleaseApprovals,
)
from amw_core.contracts import NextAction, OutputRef, ResourceUsage, TaskOutput
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.error import ErrorObject
from amw_core.enums import (
    AssetKind,
    EscalationLevel,
    LicenceDestination,
    LicenceSourceType,
    NextActionType,
    OutputRefKind,
    OutputStatus,
)
from amw_core.interfaces import BlobUri, TenantContext
from amw_core.testing.memory import MemoryTransaction
from amw_orchestrator.executor import StageCall
from tests.agents.agent_08_visual_assets.fixtures import FakeTenancy, lic
from tests.dryrun.base import World, upstream, upstream_data
from tests.dryrun.kit import banner_png, ref_ending, sha256_hex

BRAND_FONT = Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf")
"""System font with Devanagari glyphs (dry run only; the brand font is an owner decision, WS-06)."""
PALETTE = BrandPalette("#101820", "#f2f2f2", "#2a3540", "#2ecc71", "#e74c3c", "#f1c40f", "#3498db")


def settings(width: int, height: int) -> AssetSettings:
    return AssetSettings(
        price_data_lag_days=30,
        price_data_lag_platform_min_days=30,
        tier_e_max_share=__import__("decimal").Decimal("0.5"),
        licence_expiry_warning_days=14,
        min_resolution={
            "16:9": CanvasSize(width_px=width, height_px=height),
            "9:16": CanvasSize(width_px=height, height_px=width),
        },
        canvas={
            "16:9": CanvasSize(width_px=width, height_px=height),
            "9:16": CanvasSize(width_px=height, height_px=width),
        },
        max_shots_per_task=80,
        max_candidates_per_shot=12,
        max_search_requests_per_shot=3,
        min_head_tail_ms=500,
        max_dataset_bars=5000,
        fingerprint_frames_per_clip=3,
    )


class AssetsExecutor:
    def __init__(self, world: World, width: int, height: int) -> None:
        self.w = world
        self.size = (width, height)
        self.assets = MemoryAssetRepository()
        self.licences = MemoryLicenceRepository()
        self.ledger = MemoryLedgerRepository()
        self.fps = MemoryFingerprintRepository()
        self.approvals = MemoryReleaseApprovals()
        self.audit = MemoryAuditLog()
        self.font_id: str | None = None
        self.render_size = (width, height)
        self.tpl_id: str | None = None

    def _setup(self, org: str) -> TenantContext:
        ctx = TenantContext(org, "sys_operator")  # type: ignore[arg-type]
        if self.font_id is not None:
            return ctx
        tx = MemoryTransaction(ctx)
        for st in (
            LicenceSourceType.CODE_GENERATED,
            LicenceSourceType.OWNER_MADE,
            LicenceSourceType.FONT,
        ):
            self.licences.add(lic(org, st))
        data = BRAND_FONT.read_bytes()
        sha = sha256_hex(data)
        uri = self.w.blobs.storage.blob_uri(ctx, "assets", f"fonts/{sha}.ttf")
        if not self.w.blobs.storage.head(ctx, uri).exists:
            self.w.blobs.storage.put(ctx, uri, io.BytesIO(data))
        self.font_id = self.assets.insert(
            tx,
            NewAsset(
                kind=AssetKind.FONT,
                source_type=LicenceSourceType.FONT,
                content_sha256=sha,
                uri=str(uri),
                size_bytes=len(data),
                title="GNU FreeSans (system package, Devanagari coverage; licence REQUIRES REVIEW, WS-06)",
            ),
        ).asset_id
        self.w.extras.setdefault("templates", {})[self.font_id] = (str(uri), sha)
        return ctx

    def execute(self, call: StageCall) -> TaskOutput:
        org = call.job.org_id
        ctx = self._setup(org)
        shorts = call.job.production_type_key.value == "SHORTS"
        aspect = "9:16" if shorts else "16:9"
        script_stage = "s05_shorts" if shorts else "s05_script"
        sref = ref_ending(upstream(call, script_stage), ".json")
        sdata = upstream_data(call, script_stage)
        script_bytes = self.w.blobs.read(sref.uri, sref.sha256)
        plan_data = upstream_data(call, "s09_plan")
        plan_ref = plan_data["plan_ref"]
        plan_model = self.w.blobs.read_json(plan_ref["uri"], plan_ref["sha256"])
        overlays = [
            {**o, "template_ref": o.get("template_ref") or f"tpl.code_card.{o['kind'].lower()}"}
            for o in plan_model.get("overlays", [])
        ]
        plan_model["overlays"] = overlays
        handoff = json.dumps(
            {"views": plan_data["views"], "overlays": overlays},
            ensure_ascii=False,
        ).encode()
        h_uri, h_sha = self.w.blobs.put_bytes(
            "jobs", f"{call.job.job_id}/tasks/{call.task_id}/agent08_plan_view.json", handoff
        )
        data: dict[str, Any] = {
            "shot_plan_ref": {
                "uri": h_uri,
                "sha256": h_sha,
                "schema": "agent_09.shot_plan.output",
                "schema_version": "1.0.0",
            },
            "script_ref": {"uri": sref.uri, "sha256": sref.sha256, "script_id": sdata["script_id"]},
            "aspect_ratios": [aspect],
            "destination": "MONETIZED_YOUTUBE",
            "script_stage_id": script_stage,
            "channel_category": "finance",
            "active_rule_packs": ["rp.youtube_general", "rp.finance_sebi_in"],
            "ai_video_allowed": False,
            "stills_allowed": False,
            "iteration": call.iteration,
            "previous_sourcing_ref": None,
            "changed_shot_ids": [],
        }
        if call.prior_output is not None and call.prior_output.payload is not None:
            prev_ref = next(
                (r for r in call.prior_output.output_refs if r.uri.endswith("sourcing.json")), None
            )
            if prev_ref is not None:
                data["previous_sourcing_ref"] = {"uri": prev_ref.uri, "sha256": prev_ref.sha256}
        templates = self._templates(ctx, plan_model.get("overlays", []))
        w, h = self.size
        if shorts:
            w, h = h, w
        stage = AssetSourcingStage(
            tenancy=FakeTenancy(),
            assets=self.assets,
            licences=self.licences,
            ledger=self.ledger,
            fingerprints=self.fps,
            approvals=self.approvals,
            blobs=self.w.blobs.storage,
            clock=self.w.clock,
            settings=settings(*self.size),
        )
        res = stage.run(
            ctx=ctx,
            envelope_org=org,
            scope=JobScope(call.job.job_id, call.task_id, call.job.channel_id, org),
            inp=SourcingInput.model_validate(data),
            script_bytes=script_bytes,
            plan_bytes=handoff,
            brand=BrandKit(PALETTE, (self.font_id or "",), templates),
            timeline_end_ms=plan_data["total_duration_ms"],
            previous=None,
            job_destination=LicenceDestination.MONETIZED_YOUTUBE,
        )
        return self._task_output(call, ctx, res)

    def _templates(self, ctx: TenantContext, overlays: list[dict[str, Any]]) -> dict[str, str]:
        """Every overlay template the plan names, registered as a code-made template asset."""
        tx = MemoryTransaction(ctx)
        out: dict[str, str] = {}
        for ov in overlays:
            ref = ov.get("template_ref")
            if not ref or ref in out:
                continue
            w, h = self.render_size
            png = banner_png(w, h, ref.split(".")[-1].upper().replace("_", " "))
            uri, sha = self.w.blobs.put_bytes("assets", f"templates/{sha256_hex(png)}.png", png)
            out[ref] = self.assets.insert(
                tx,
                NewAsset(
                    kind=AssetKind.TEMPLATE,
                    source_type=LicenceSourceType.CODE_GENERATED,
                    content_sha256=sha,
                    uri=uri,
                    size_bytes=len(png),
                    title=f"PLUMBING {ref}",
                ),
            ).asset_id
            self.w.extras.setdefault("templates", {})[out[ref]] = (uri, sha)
            self.w.extras.setdefault("template_keys", {})[ref] = uri
        return out

    def _task_output(self, call: StageCall, ctx: TenantContext, res: Any) -> TaskOutput:
        refs: list[OutputRef] = []
        payload = None
        if res.payload is not None:
            doc = res.payload.to_doc()
            uri, sha = self.w.blobs.put_json(
                "jobs", f"{call.job.job_id}/tasks/{call.task_id}/sourcing.json", doc
            )
            body = self.w.blobs.read(uri, sha)
            refs.append(
                OutputRef(
                    uri=uri,
                    kind=OutputRefKind.DATA,
                    sha256=sha,
                    size_bytes=len(body),
                    media_type="application/json",
                )
            )
            for name, buri in sorted(res.blobs.items()):
                head = self.w.blobs.storage.head(ctx, BlobUri(buri))
                media = "image/png" if buri.endswith(".png") else "application/json"
                refs.append(
                    OutputRef(
                        uri=buri,
                        kind=OutputRefKind.IMAGE if media == "image/png" else OutputRefKind.DATA,
                        sha256=head.sha256 or "0" * 64,
                        size_bytes=head.size_bytes or 0,
                        media_type=media,
                    )
                )
            payload = PayloadObject(
                payload_schema="agent_08.asset_sourcing.output",
                payload_schema_version="1.0.0",
                data=doc,
            )
        ok = res.task_status == "SUCCEEDED"
        error = None
        if not ok:
            error = ErrorObject.model_validate(
                {
                    "code": res.error_code or "AGENT.INCOMPLETE_OUTPUT",
                    "error_class": (res.error_code or "AGENT.X").split(".")[0],
                    "message": "agent_08 stage did not succeed",
                    "retryable": False,
                    "retry_after_ms": None,
                    "details": {},
                    "actor": "agent_08",
                    "provider": None,
                    "upstream_status": None,
                    "upstream_code": None,
                    "attempt_no": call.attempt_no,
                    "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "correlation_id": call.job.correlation_id,
                }
            )
        return TaskOutput(
            status=OutputStatus.SUCCEEDED if ok else OutputStatus.FAILED,
            payload=payload if ok else None,
            output_refs=tuple(refs) if ok else (),
            quality_score=None,
            confidence=None,
            validation_results=tuple(res.validation_results),
            duration=1,
            resource_usage=ResourceUsage(
                cpu_ms=0,
                peak_rss_bytes=0,
                tokens_in=0,
                tokens_out=0,
                tokens_cached_in=0,
                llm_calls=0,
                provider_calls=0,
                cost_estimate_micros=0,
                currency="USD",
                cost_entry_ids=(),
            ),
            error=error,
            next_action=NextAction(
                type=NextActionType.CONTINUE if ok else NextActionType.ESCALATE,
                wait_reason=None,
                escalation_level=None if ok else EscalationLevel.L3,
                reason="assets sourced" if ok else "asset sourcing failed",
            ),
            downstream_agent="agent_10" if ok else None,
            timestamp=datetime.now(UTC),
        )
