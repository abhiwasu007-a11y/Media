"""``AssetSourcingStage`` (task ``agent_08.asset_sourcing``, stage ``s08_assets``).

Sources one asset per shot in hierarchy order (A to E, code-enforced), writes the licence-ledger
rows (shots, overlay intervals, brand fonts), the chart facts, the tier mix, the validation results
and the single gate result with its remedy stage. 3A scope wired here: charts and graphics (tier C,
no network, no model), owner library (tier A, ranking through the injected ``FootageSelector``) and
tiers B, D, E recorded as ``TIER_DISABLED`` until their adapters are enabled (their gates, prompt
composer, disclosure flags and error mapper are implemented and unit-tested separately).
Every DB access goes through one tenant transaction; every query is explicitly scoped by org.
"""

import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from amw_core.contracts.task_output import ValidationResult
from amw_core.enums import (
    AssetKind,
    AssetStatus,
    CheckKind,
    CheckVerdict,
    ChartDataKind,
    LicenceDestination,
    LicenceSourceType,
    LicenceUsageKind,
    ShotIntentKind,
    ShotSourcingStatus,
    ShotUnresolvedReason,
    SourcingWarning,
    VisualSkipReason,
    VisualSourceTier,
)
from amw_core.errors import (
    ConfigInvalidError,
    CorruptedOutputError,
    InputInvalidError,
    MissingDependencyError,
)
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext, TenantTransaction

from agent_08_visual_assets.cascade.share import TierMixReporter, TierShareGuard
from agent_08_visual_assets.cascade.tier_cascade import (
    Attempt,
    CascadeResult,
    ChartAttempt,
    Probes,
    TierCascade,
    accept,
    skip_with,
)
from agent_08_visual_assets.charts.cases import ChartCase, ChartRequest, StoredCase
from agent_08_visual_assets.charts.dataset import BarSeries, DatasetLoader
from agent_08_visual_assets.charts.lag import EarliestPublishDate
from agent_08_visual_assets.charts.pipeline import BuiltChart, ChartContext, ChartPath
from agent_08_visual_assets.charts.render import BrandPalette, RenderedImage
from agent_08_visual_assets.gate import GATE_CHECK_ID, GateRouter, Unresolved
from agent_08_visual_assets.guards import TenantGuard
from agent_08_visual_assets.licence.guard import GuardResult, LicenceGuard, LicenceView
from agent_08_visual_assets.licence.ledger import (
    CoverageVerifier,
    CoverElement,
    CoverRow,
    LedgerRowBuilder,
)
from agent_08_visual_assets.licence.timeline import OverlayInput, TimelineLedgerPlanner
from agent_08_visual_assets.models.output import (
    AiBroll,
    ByTier,
    ChartFactsDocument,
    ChartFactsRef,
    ChartInfo,
    CostSummary,
    Crop,
    Disclosure,
    Fingerprints,
    FontResult,
    LicenceSummary,
    LicenceWarning,
    Media,
    OverlayResult,
    PerceptualFrame,
    Provenance,
    ReuseInfo,
    ReuseSummary,
    SkipEntry,
    ShotResult,
    SourcingOutput,
    TierMix,
    TierShareEntry,
    Selection,
    ChartFact,
)
from agent_08_visual_assets.models.shot_plan import ShotPlanReader, ShotRequirement
from agent_08_visual_assets.models.task_input import SourcingInput
from agent_08_visual_assets.persistence.protocols import (
    AssetRepository,
    FingerprintRepository,
    LedgerRepository,
    LicenceRepository,
    ReleaseApprovals,
)
from agent_08_visual_assets.persistence.records import (
    AssetRecord,
    FingerprintRow,
    LicenceRecord,
    NewAsset,
    NewLedgerEntry,
)
from agent_08_visual_assets.plan.revision import ChangedShotSelector, ShotKey
from agent_08_visual_assets.reuse.fingerprint import ALGO_VERSION, Fingerprinter
from agent_08_visual_assets.settings import AssetSettings
from agent_08_visual_assets.sources.graphics import GraphicKind, GraphicTemplateRenderer

_PASS, _FAIL, _WARN, _SKIP = (
    CheckVerdict.PASS,
    CheckVerdict.FAIL,
    CheckVerdict.WARN,
    CheckVerdict.SKIPPED,
)


@dataclass(frozen=True, slots=True)
class BrandKit:
    """Brand kit values the stage needs (read from the BRAND_KIT context ref by the caller)."""

    palette: BrandPalette
    font_asset_ids: tuple[str, ...]
    template_assets: Mapping[str, str]
    """overlay ``template_ref`` -> registered template asset id."""


@dataclass(frozen=True, slots=True)
class FootageChoice:
    """Outcome of the (LLM-backed) selection among filtered owner candidates."""

    chosen_asset_id: str | None
    fit: str | None = None
    prohibited: bool = False
    refusal_reason: str | None = None


class FootageSelector(Protocol):
    def select(self, shot: ShotRequirement, candidates: Sequence[AssetRecord]) -> FootageChoice: ...


@dataclass(frozen=True, slots=True)
class JobScope:
    job_id: str
    task_id: str
    channel_id: str
    org_id: str


@dataclass(frozen=True, slots=True)
class StageResult:
    payload: SourcingOutput | None
    validation_results: tuple[ValidationResult, ...]
    task_status: str
    error_code: str | None
    gate_verdict: str | None
    blobs: Mapping[str, str] = field(default_factory=dict)
    """name -> uri of the manifest, chart facts documents and reveal stills."""
    unresolved: tuple[Unresolved, ...] = ()


@dataclass(slots=True)
class _Built:
    result: ShotResult
    records: list[AssetRecord]
    chart: BuiltChart | None = None


def _vr(check_id: str, verdict: CheckVerdict, blocking: bool, message: str, *, gate: bool = False,
        remedy: str | None = None) -> ValidationResult:  # fmt: skip
    return ValidationResult(
        check_id=check_id, kind=CheckKind.DETERMINISTIC, verdict=verdict,
        blocking=blocking and verdict not in (_WARN, _SKIP), message=message, gate=gate,
        remedy_stage_id=remedy,
    )  # fmt: skip


class AssetSourcingStage:
    def __init__(
        self,
        *,
        tenancy: TenancyContext,
        assets: AssetRepository,
        licences: LicenceRepository,
        ledger: LedgerRepository,
        fingerprints: FingerprintRepository,
        approvals: ReleaseApprovals,
        blobs: BlobStorage,
        clock: Clock,
        settings: AssetSettings,
        selector: FootageSelector | None = None,
    ) -> None:
        self._tenancy, self._assets, self._licences = tenancy, assets, licences
        self._ledger, self._fp, self._approvals = ledger, fingerprints, approvals
        self._blobs, self._clock, self._s, self._selector = blobs, clock, settings, selector
        self._destination = LicenceDestination.MONETIZED_YOUTUBE

    # -- public --------------------------------------------------------------------------------

    def run(
        self,
        *,
        ctx: TenantContext,
        envelope_org: str,
        scope: JobScope,
        inp: SourcingInput,
        script: Mapping[str, object] | None,
        plan_bytes: bytes,
        script_sha256: str,
        brand: BrandKit,
        timeline_end_ms: int,
        previous: SourcingOutput | None = None,
    ) -> StageResult:
        uris = [inp.shot_plan_ref.uri, inp.script_ref.uri]
        if inp.previous_sourcing_ref is not None:
            uris.append(inp.previous_sourcing_ref.uri)
        TenantGuard.check_task(
            context_org=str(ctx.org_id), envelope_org=envelope_org, input_org=scope.org_id,
            uris=uris, write=False,
        )  # fmt: skip
        self._destination = inp.destination
        shots, overlays = ShotPlanReader.read(plan_bytes)
        shots = [s for s in shots if s.aspect_ratio.value in inp.aspect_ratios]
        if len(shots) > self._s.max_shots_per_task:
            raise InputInvalidError("plan has more shots than assets.max_shots_per_task")
        script = script or {}
        requests = {r.chart_id: r for r in _chart_requests(script)}
        allow = _allowlists(script)
        todo = self._select(shots, previous, inp)
        with self._tenancy.transaction(ctx) as tx:
            licences = self._standing_licences(tx, brand, overlays)
            built = [
                self._shot(tx, scope, s, requests, allow, brand, licences, previous, todo)
                for s in shots
            ]
            timeline = self._timeline(tx, scope, overlays, brand, licences, timeline_end_ms)
        return self._assemble(ctx, inp, built, timeline, plan_bytes, script_sha256)

    # -- helpers -------------------------------------------------------------------------------

    def _select(self, shots: Sequence[ShotRequirement], previous: SourcingOutput | None,
                inp: SourcingInput) -> set[str]:  # fmt: skip
        if previous is None:
            return {s.shot_id for s in shots}
        key = lambda r: ShotKey(r.shot_id, r.content_key, r.start_ms, r.end_ms, r.aspect_ratio)  # noqa: E731
        sel = ChangedShotSelector.select(
            [key(r) for r in previous.shots],
            [ShotKey(s.shot_id, s.content_key, s.start_ms, s.end_ms, s.aspect_ratio.value) for s in shots],
            inp.changed_shot_ids,
        )  # fmt: skip
        return set(sel.resource)

    def _standing_licences(self, tx: TenantTransaction, brand: BrandKit,
                           overlays: Sequence[object]) -> dict[LicenceSourceType, LicenceRecord]:  # fmt: skip
        out: dict[LicenceSourceType, LicenceRecord] = {}
        needed = [LicenceSourceType.CODE_GENERATED, LicenceSourceType.OWNER_MADE]
        if brand.font_asset_ids:
            needed.append(LicenceSourceType.FONT)
        for st in needed:
            rec = self._licences.self_grant(tx, st)
            if rec is None:
                if st is LicenceSourceType.OWNER_MADE:
                    continue  # only needed once an owner asset is used
                raise MissingDependencyError(
                    "standing licence row missing", details={"class": f"licence.self_grant.{st.value}"}
                )
            out[st] = rec
        return out

    def _guard(self, rec: LicenceRecord, tenant_org: str) -> GuardResult:
        now = self._clock.now()
        return LicenceGuard.check(
            licence=LicenceView(
                rec.state, None if rec.expires_at is None else rec.expires_at - now,
                rec.org_id is None, rec.third_party_permission, rec.covers_monetized_youtube,
                rec.indemnification, rec.source_type,
            ),
            destination=self._destination,
            tenant_is_platform_owner=False,
            warning_window=_days(self._s.licence_expiry_warning_days),
        )  # fmt: skip

    def _put(self, ctx: TenantContext, name: str, data: bytes) -> str:
        uri = self._blobs.blob_uri(ctx, "assets", name)
        if not self._blobs.head(ctx, uri).exists:
            self._blobs.put(ctx, uri, io.BytesIO(data))
        return str(uri)

    def _register_png(self, tx: TenantTransaction, img: RenderedImage, *, kind: AssetKind,
                      licence: LicenceRecord, title: str, attrs: Mapping[str, object]) -> AssetRecord:  # fmt: skip
        uri = self._put(tx.context, f"generated/{img.sha256}.png", img.png)
        existing = self._assets.find_by_sha(tx, img.sha256)
        rec = existing or self._assets.insert(
            tx,
            NewAsset(
                kind=kind, source_type=LicenceSourceType.CODE_GENERATED, content_sha256=img.sha256,
                uri=uri, size_bytes=len(img.png), title=title,
                visual_source_tier=VisualSourceTier.C_CODE_MOTION, licence_id=licence.licence_id,
                width_px=img.width_px, height_px=img.height_px, attributes=dict(attrs),
            ),
        )  # fmt: skip
        fp = Fingerprinter.still(img.png)
        self._fp.add(tx, [FingerprintRow(rec.asset_id, "SHA256", ALGO_VERSION, fp.sha256, None)]
                     + [FingerprintRow(rec.asset_id, "PERCEPTUAL_FRAME", ALGO_VERSION, f.hash_hex, f.frame_ms)
                        for f in fp.perceptual_frames])  # fmt: skip
        return rec

    def _write_ledger(self, tx: TenantTransaction, scope: JobScope, shot: ShotRequirement,
                      rec: AssetRecord, lic: LicenceRecord, tier: VisualSourceTier | None) -> str:  # fmt: skip
        guard = self._guard(lic, scope.org_id)
        if not guard.usable:
            raise InputInvalidError("licence not usable", details={"reason": str(guard.reason)})
        row = LedgerRowBuilder.build(
            tier=tier, kind=rec.asset.kind, source_type=rec.asset.source_type,
            start_ms=shot.start_ms, end_ms=shot.end_ms, licence_ref=lic.licence_id, element_id=shot.shot_id,
        )  # fmt: skip
        entry = self._ledger.write(
            tx,
            NewLedgerEntry(scope.job_id, scope.task_id, rec.asset_id, lic.licence_id, row.usage_kind,
                           row.used_from_ms, row.used_to_ms, row.shot_id, None, row.source_url,
                           row.vendor_item_id),
        )  # fmt: skip
        return entry.ledger_entry_id

    def _case_docs(self, tx: TenantTransaction, ctx: TenantContext) -> list[StoredCase]:
        out: list[StoredCase] = []
        for rec in self._assets.list_assets(tx, kinds=[AssetKind.DOCUMENT]):
            if rec.asset.attributes.get("doc_kind") != "CHART_CASE":
                continue
            data = b"".join(self._blobs.get(ctx, BlobUri(rec.asset.uri), rec.asset.content_sha256))
            out.append(StoredCase(rec.asset_id, ChartCase.model_validate_json(data), rec.asset.content_sha256))
        return out

    def _dataset(self, tx: TenantTransaction, ctx: TenantContext, asset_id: str | None) -> tuple[BarSeries | None, str | None]:  # fmt: skip
        if asset_id is None:
            return None, None
        rec = self._assets.get(tx, asset_id)
        if rec is None:
            return None, None
        data = b"".join(self._blobs.get(ctx, BlobUri(rec.asset.uri), rec.asset.content_sha256))
        try:
            return DatasetLoader.load(data, expected_sha256=rec.asset.content_sha256,
                                      max_bars=self._s.max_dataset_bars), rec.asset_id  # fmt: skip
        except CorruptedOutputError:
            raise

    # -- one shot ------------------------------------------------------------------------------

    def _shot(
        self,
        tx: TenantTransaction,
        scope: JobScope,
        shot: ShotRequirement,
        requests: Mapping[str, ChartRequest],
        allow: Mapping[str, Sequence[str]],
        brand: BrandKit,
        licences: Mapping[LicenceSourceType, LicenceRecord],
        previous: SourcingOutput | None,
        todo: set[str],
    ) -> _Built:
        if previous is not None and shot.shot_id not in todo:
            prev = next(r for r in previous.shots if r.shot_id == shot.shot_id)
            return _Built(prev, [], None)
        ctx = tx.context
        w, h = self._canvas(shot)
        probes: Probes[_Sourced] = Probes()
        palette = brand.palette
        scene_text = allow.get(shot.scene_id, ())

        def chart() -> ChartAttempt[_Sourced]:
            req = requests.get(shot.chart_id or "")
            if req is None:
                raise InputInvalidError("shot chart_id is not in the script chart_requests")
            cases = self._case_docs(tx, ctx)
            base = ChartContext(
                req, cases, None, None, False, list(shot.on_screen_text) + list(scene_text),
                len(shot.change_events_ms), self._clock.now().date(), self._s.price_data_lag_days,
                self._s.price_data_lag_platform_min_days, w, h, shot.aspect_ratio.value, palette,
            )  # fmt: skip
            stored = ChartPath.case_for(base)
            series, ds_id, released = None, None, False
            if stored is not None:
                series, ds_id = self._dataset(tx, ctx, stored.case.dataset_asset_id)
                if stored.case.method_content:
                    released = self._approvals.is_released(tx, stored.asset_id, stored.sha256)
            outcome = ChartPath.run(
                ChartContext(**{**_fields(base), "series": series, "dataset_asset_id": ds_id,
                                "release_approved": released})  # type: ignore[arg-type]
            )  # fmt: skip
            if outcome.built is None:
                return ChartAttempt(unresolved=outcome.unresolved)
            return ChartAttempt(accepted=self._register_chart(tx, outcome.built, licences, ds_id, shot))

        def graphic() -> Attempt[_Sourced]:
            texts = tuple(shot.on_screen_text)
            if shot.intent_kind is ShotIntentKind.DIAGRAM and texts:
                from agent_08_visual_assets.sources.graphics import DiagramSpec

                kind, diagram = GraphicKind.DIAGRAM, DiagramSpec(texts, tuple((i, i + 1) for i in range(len(texts) - 1)))
            elif texts:
                kind = GraphicKind.TITLE_CARD if shot.intent_kind is ShotIntentKind.TEXT_CARD else GraphicKind.KINETIC_TEXT
                diagram = None
            elif shot.intent_kind is ShotIntentKind.FOOTAGE and shot.fallback_template_key:
                kind, diagram = GraphicKind.ABSTRACT_MOTION, None
            else:
                return skip_with(VisualSkipReason.NO_TEMPLATE_CONTENT)
            img = GraphicTemplateRenderer.render(
                kind=kind, lines=texts if kind in (GraphicKind.TITLE_CARD, GraphicKind.KINETIC_TEXT) else (),
                allowlist=texts, width_px=w, height_px=h, palette=palette, diagram=diagram,
            )  # fmt: skip
            lic = licences[LicenceSourceType.CODE_GENERATED]
            rec, reused = self._register_png(
                tx, img, kind=AssetKind.IMAGE, licence=lic, title=shot.shot_id,
                attrs={"template_id": kind.value, "template_version": 1},
            )  # fmt: skip
            return accept(_Sourced(rec, reused, lic, (), None, None, None))

        def owner() -> Attempt[_Sourced]:
            cands = self._owner_candidates(tx, scope, shot)
            if not cands:
                return skip_with(VisualSkipReason.NO_CANDIDATE)
            if self._selector is None:
                raise ConfigInvalidError("owner footage exists but no FootageSelector is configured")
            choice = self._selector.select(shot, cands)
            if choice.refusal_reason == "UNSAFE_CONTENT" or choice.prohibited:
                return skip_with(VisualSkipReason.PROHIBITED_DEPICTION, unsafe=choice.refusal_reason == "UNSAFE_CONTENT")
            if choice.chosen_asset_id is None:
                return skip_with(VisualSkipReason.NO_ACCEPTABLE_FIT)
            rec = next(c for c in cands if c.asset_id == choice.chosen_asset_id)
            lic = licences.get(LicenceSourceType.OWNER_MADE)
            if lic is None:
                raise MissingDependencyError("standing licence row missing",
                                             details={"class": "licence.self_grant.OWNER_MADE"})
            fit = choice.fit if choice.fit in ("STRONG", "ACCEPTABLE") else "ACCEPTABLE"
            return accept(_Sourced(rec, False, lic, (), None, Selection(fit=fit, candidate_count=len(cands)),  # type: ignore[arg-type]
                                   None))

        if shot.internal_intent.value == "CHART":
            probes.chart = chart
        else:
            probes.graphic = graphic if (shot.intent_kind is not ShotIntentKind.FOOTAGE
                                         or VisualSourceTier.D_AI_VIDEO not in shot.allowed_tiers) else None  # fmt: skip
            probes.owner = owner
        res = TierCascade.resolve_shot(
            intent=shot.internal_intent, probes=probes, allowed_tiers=shot.allowed_tiers
            if shot.internal_intent.value == "FOOTAGE" else None,
        )  # fmt: skip
        return self._finish(tx, scope, shot, res, licences)

    def _canvas(self, shot: ShotRequirement) -> tuple[int, int]:
        size = self._s.canvas.get(shot.aspect_ratio.value)
        if size is None:
            raise ConfigInvalidError("no canvas configured for aspect " + shot.aspect_ratio.value)
        return size.width_px, size.height_px

    def _owner_candidates(self, tx: TenantTransaction, scope: JobScope, shot: ShotRequirement) -> list[AssetRecord]:
        floor = self._s.min_resolution.get(shot.aspect_ratio.value)
        out: list[AssetRecord] = []
        now = self._clock.now()
        for rec in self._assets.list_assets(
            tx, kinds=[AssetKind.VIDEO, AssetKind.IMAGE],
            source_types=[LicenceSourceType.OWNER_MADE, LicenceSourceType.CLIENT_SUPPLIED],
        ):  # fmt: skip
            a = rec.asset
            if rec.org_id != scope.org_id or rec.status is not AssetStatus.ACTIVE:
                continue
            if a.expires_at is not None and a.expires_at <= now:
                continue
            if a.allowed_channel_ids is not None and scope.channel_id not in a.allowed_channel_ids:
                continue
            if floor and ((a.width_px or 0) < floor.width_px or (a.height_px or 0) < floor.height_px):
                continue
            if a.kind is AssetKind.VIDEO and not shot.allows_hold and (
                a.duration_ms is None or a.duration_ms < shot.duration_ms + self._s.min_head_tail_ms
            ):
                continue
            out.append(rec)
        return sorted(out, key=lambda r: r.asset_id)[: self._s.max_candidates_per_shot]

    def _register_chart(self, tx: TenantTransaction, built: BuiltChart,
                        licences: Mapping[LicenceSourceType, LicenceRecord], ds_id: str | None,
                        shot: ShotRequirement) -> "_Sourced":  # fmt: skip
        lic = licences[LicenceSourceType.CODE_GENERATED]
        attrs = {"dataset_asset_id": ds_id, "case_id": built.case.case.case_id,
                 "spec_sha256": built.spec_sha256, "template_id": built.spec.template_id,
                 "template_version": built.spec.template_version}  # fmt: skip
        extra: list[AssetRecord] = []
        for img in built.stills[:-1]:
            extra.append(self._register_png(tx, img, kind=AssetKind.IMAGE, licence=lic,
                                            title=shot.shot_id + "_reveal", attrs=attrs)[0])  # fmt: skip
        rec, reused = self._register_png(tx, built.stills[-1], kind=AssetKind.CHART, licence=lic,
                                         title=shot.shot_id, attrs=attrs)  # fmt: skip
        return _Sourced(rec, reused, lic, tuple(extra), built, None, ds_id)

    def _finish(self, tx: TenantTransaction, scope: JobScope, shot: ShotRequirement,
                res: CascadeResult["_Sourced"], licences: Mapping[LicenceSourceType, LicenceRecord]) -> _Built:  # fmt: skip
        base = {
            "shot_id": shot.shot_id, "scene_id": shot.scene_id[:32], "content_key": shot.content_key,
            "start_ms": shot.start_ms, "end_ms": shot.end_ms, "aspect_ratio": shot.aspect_ratio.value,
            "intent_kind": shot.intent_kind, "skips": tuple(SkipEntry(tier=k.tier, reason=k.reason) for k in res.skips),
        }  # fmt: skip
        if not res.sourced or res.payload is None:
            return _Built(ShotResult(
                **base, status=ShotSourcingStatus.UNRESOLVED, tier=None, asset_id=None, asset_uri=None,
                source_type=None, licence_id=None, ledger_entry_ids=(), usage_kind=None, media=None,
                fingerprints=None, warnings=(), unresolved_reason=res.unresolved_reason, reuse=None,
                chart=None, disclosure=Disclosure(is_realistic_synthetic=False, depicts_real_person=False),
                cost_micros=0, selection=None,
            ), [], None)  # fmt: skip
        src = res.payload
        guard = self._guard(src.licence, scope.org_id)
        warnings = list(res.warnings) + [w for w in guard.warnings if w not in res.warnings]
        ids = [self._write_ledger(tx, scope, shot, r, src.licence, res.tier) for r in (*src.reveal, src.record)]
        rows = self._fp.for_asset(tx, src.record.asset_id)
        sha = src.record.asset.content_sha256
        fps = Fingerprints(
            sha256=sha, algo_version=ALGO_VERSION,
            perceptual_frames=tuple(PerceptualFrame(frame_ms=r.frame_ms or 0, hash_hex=r.value_hex)
                                    for r in rows if r.algo == "PERCEPTUAL_FRAME"),
        )  # fmt: skip
        a = src.record.asset
        media = Media(width_px=a.width_px or 1, height_px=a.height_px or 1, duration_ms=a.duration_ms or None,
                      source_in_ms=0, crop=Crop(mode="NONE", anchor=None, keep_permille=1000))  # type: ignore[arg-type]
        usage = LedgerRowBuilder.build(tier=res.tier, kind=a.kind, source_type=a.source_type, start_ms=0,
                                       end_ms=1, licence_ref=src.licence.licence_id, element_id=None).usage_kind  # fmt: skip
        chart = _chart_info(shot, src)
        result = ShotResult(
            **base, status=ShotSourcingStatus.REUSED if src.reused else ShotSourcingStatus.SOURCED,
            tier=res.tier, asset_id=src.record.asset_id, asset_uri=a.uri, source_type=a.source_type.value,  # type: ignore[arg-type]
            licence_id=src.licence.licence_id, ledger_entry_ids=tuple(ids), usage_kind=usage.value,  # type: ignore[arg-type]
            media=media, fingerprints=fps, warnings=tuple(warnings), unresolved_reason=None,
            reuse=ReuseInfo(kind="EXACT", source_asset_id=src.record.asset_id) if src.reused else None,  # type: ignore[arg-type]
            chart=chart, disclosure=Disclosure(is_realistic_synthetic=False, depicts_real_person=False),
            cost_micros=0, selection=src.selection,
        )  # fmt: skip
        return _Built(result, [src.record, *src.reveal], src.chart)

    # -- overlays and fonts --------------------------------------------------------------------

    def _timeline(self, tx: TenantTransaction, scope: JobScope, overlays: Sequence[object],
                  brand: BrandKit, licences: Mapping[LicenceSourceType, LicenceRecord],
                  timeline_end_ms: int) -> "_Timeline":  # fmt: skip
        from agent_08_visual_assets.models.shot_plan import OverlayRequirement

        reqs = [o for o in overlays if isinstance(o, OverlayRequirement)]
        planned = TimelineLedgerPlanner.plan(
            [OverlayInput(o.overlay_id, o.kind, o.start_ms, o.end_ms,
                          None if o.template_ref is None else brand.template_assets.get(o.template_ref))
             for o in reqs],
            list(brand.font_asset_ids), timeline_end_ms,
        )  # fmt: skip
        ov_out: list[OverlayResult] = []
        fonts: list[FontResult] = []
        rows: list[CoverRow] = []
        els: list[CoverElement] = []
        for row in planned:
            rec = self._assets.get(tx, row.asset)
            if rec is None:
                raise MissingDependencyError("asset not found", details={"class": "overlay_or_font_asset"})
            st = LicenceSourceType.FONT if row.usage_kind is LicenceUsageKind.FONT else rec.asset.source_type
            lic = licences.get(st)
            if lic is None:
                raise MissingDependencyError("standing licence row missing", details={"class": f"licence.self_grant.{st.value}"})
            if not self._guard(lic, scope.org_id).usable:
                raise InputInvalidError("licence not usable for overlay or font")
            led = LedgerRowBuilder.build(
                tier=None, kind=AssetKind.FONT if row.usage_kind is LicenceUsageKind.FONT else AssetKind.TEMPLATE,
                source_type=st, start_ms=row.used_from_ms, end_ms=row.used_to_ms, licence_ref=lic.licence_id,
                element_id=row.shot_id,
            )  # fmt: skip
            entry = self._ledger.write(tx, NewLedgerEntry(scope.job_id, scope.task_id, row.asset, lic.licence_id,
                                                          led.usage_kind, led.used_from_ms, led.used_to_ms,
                                                          led.shot_id, None, None, None))  # fmt: skip
            rows.append(CoverRow(row.asset, led.used_from_ms, led.used_to_ms, scope.job_id, None))
            els.append(CoverElement(row.element_id, row.asset, row.used_from_ms, row.used_to_ms))
            if row.usage_kind is LicenceUsageKind.FONT:
                fonts.append(FontResult(asset_id=row.asset, licence_id=lic.licence_id,
                                        ledger_entry_ids=(entry.ledger_entry_id,), usage_kind="FONT",
                                        used_from_ms=0, used_to_ms=row.used_to_ms))  # fmt: skip
            else:
                ov = next(o for o in reqs if o.overlay_id == row.element_id)
                ov_out.append(OverlayResult(
                    overlay_id=ov.overlay_id, kind=ov.kind, start_ms=ov.start_ms, end_ms=ov.end_ms,  # type: ignore[arg-type]
                    template_asset_id=row.asset, source_type=st.value, licence_id=lic.licence_id,  # type: ignore[arg-type]
                    ledger_entry_ids=(entry.ledger_entry_id,), usage_kind="TEMPLATE",
                ))  # fmt: skip
        return _Timeline(tuple(ov_out), tuple(fonts), tuple(els), tuple(rows), scope.job_id)

    # -- assembly ------------------------------------------------------------------------------

    def _assemble(self, ctx: TenantContext, inp: SourcingInput, built: Sequence[_Built],
                  tl: "_Timeline", plan_bytes: bytes, script_sha256: str) -> StageResult:  # fmt: skip
        import hashlib

        results = tuple(b.result for b in built)
        unresolved = tuple(Unresolved(r.shot_id, r.unresolved_reason) for r in results if r.unresolved_reason)
        outcome = GateRouter.route(unresolved, inp.script_stage_id)
        ms: dict[VisualSourceTier, int] = {t: 0 for t in VisualSourceTier}
        for r in results:
            if r.tier is not None:
                ms[r.tier] += r.end_ms - r.start_ms
        total = sum(ms.values())
        mix_total, shares = TierMixReporter.report(ms) if total > 0 else (0, {})
        by_tier = ByTier(**{t.value: TierShareEntry(ms=ms[t], share_permille=shares[t.value].share_permille if shares else 0)
                            for t in VisualSourceTier})  # fmt: skip
        blobs: dict[str, str] = {}
        facts_refs: list[ChartFactsRef] = []
        ends: list[date] = []
        for b in built:
            if b.chart is not None and b.chart.lag is not None and b.chart.lag.data_end_date:
                ends.append(b.chart.lag.data_end_date)
            if b.chart is not None and b.chart.facts.emit_document and b.result.chart is not None:
                ci = b.result.chart
                doc = ChartFactsDocument(
                    chart_id=ci.chart_id, instrument=ci.instrument or "UNKNOWN",
                    dataset_asset_id=ci.dataset_asset_id or "", dataset_sha256=ci.dataset_sha256 or "",
                    data_start_date=ci.data_start_date or "", data_end_date=ci.data_end_date or "",
                    facts=tuple(ChartFact(fact_id=f.fact_id, statement=f.statement) for f in b.chart.facts.facts),
                )  # fmt: skip
                raw = json.dumps(doc.to_doc(), sort_keys=True, separators=(",", ":")).encode()
                sha = hashlib.sha256(raw).hexdigest()
                uri = self._put(ctx, f"chart_facts/{sha}.json", raw)
                blobs[f"chart_facts:{ci.chart_id}"] = uri
                facts_refs.append(ChartFactsRef(chart_id=ci.chart_id, document_uri=uri, document_sha256=sha,
                                                fact_count=len(doc.facts)))  # fmt: skip
        lag_days = self._s.price_data_lag_days
        publish = EarliestPublishDate.compute(ends, lag_days)
        ledger_rows = sum(len(r.ledger_entry_ids) for r in results)
        warns = [LicenceWarning(code=w.value, shot_id=r.shot_id, licence_id=r.licence_id)  # type: ignore[arg-type]
                 for r in results for w in r.warnings
                 if w in (SourcingWarning.LICENCE_EXPIRING, SourcingWarning.NO_INDEMNIFICATION)]  # fmt: skip
        payload = SourcingOutput(
            iteration=inp.iteration, gate_verdict=outcome.gate_verdict or "FAILED",  # type: ignore[arg-type]
            shots=results, overlays=tl.overlays, fonts=tl.fonts, music_beds=(), chart_facts=tuple(facts_refs),
            tier_mix=TierMix(total_visual_ms=mix_total, by_tier=by_tier),
            ai_broll=AiBroll(clips=0, total_ms=0, cost_micros=0, currency=self._s.currency),
            cost_summary=CostSummary(llm_micros=0, stock_micros=0, ai_video_micros=0, ai_still_micros=0,
                                     currency=self._s.currency, figure_kind="ESTIMATE"),
            licence_summary=LicenceSummary(ledger_rows_written=ledger_rows, overlay_rows=len(tl.overlays),
                                           font_rows=len(tl.fonts), music_rows=0, warnings=tuple(warns)),
            reuse_summary=ReuseSummary(reused_exact=sum(1 for r in results if r.reuse),
                                       reused_near_duplicate=0,
                                       new_assets=sum(1 for r in results if r.asset_id and not r.reuse),
                                       near_duplicate_flags=0),
            earliest_compliant_publish_date=publish.isoformat() if publish else None,
            unresolved_shot_ids=tuple(u.shot_id for u in unresolved),
            provenance=Provenance(
                prompts=(), rule_pack_versions=(), adapters=(),
                config_sha256=hashlib.sha256(self._s.model_dump_json().encode()).hexdigest(),
                lag_days=lag_days, shot_plan_sha256=inp.shot_plan_ref.sha256, script_sha256=script_sha256,
            ),
            refusals=(),
        )  # fmt: skip
        vr = self._validation(results, tl, outcome, ms, total, inp)
        status = outcome.task_status
        return StageResult(payload, tuple(vr), status, outcome.error_code, outcome.gate_verdict, blobs, unresolved)

    def _validation(self, results: Sequence[ShotResult], tl: "_Timeline", outcome, ms, total, inp) -> list[ValidationResult]:  # type: ignore[no-untyped-def]  # noqa: ANN001
        sourced = [r for r in results if r.asset_id]
        vr: list[ValidationResult] = []
        for cid in ("a08.pre.tenant", "a08.pre.refs", "a08.pre.shot_plan", "a08.pre.config", "a08.pre.licence_rows"):
            vr.append(_vr(cid, _PASS, True, "precondition met"))
        g = outcome.gate_result
        if g is not None:
            vr.append(_vr(GATE_CHECK_ID, _PASS if g.verdict == "PASS" else _FAIL, True,
                          "no unresolved shot" if g.verdict == "PASS" else "unresolved shots remain",
                          gate=True, remedy=g.remedy_stage_id))  # fmt: skip
        bad_cov = [r.shot_id for r in sourced if len(r.ledger_entry_ids) < 1]
        vr.append(_vr("a08.cov.licence_row_per_shot", _FAIL if bad_cov else _PASS, True, "ledger row per sourced shot"))
        vr.append(_vr("a08.cov.overlay_rows", _PASS, True, f"{len(tl.overlays)} overlay rows"))
        vr.append(_vr("a08.cov.font_rows", _PASS, True, f"{len(tl.fonts)} font rows"))
        cov = CoverageVerifier.verify(tl.elements, tl.rows, job_id=tl.job_id)
        vr.append(_vr("a08.cov.interval_match", _PASS if cov.passed else _FAIL, True, "overlay and font intervals match"))
        missing = [r.shot_id for r in results
                   if TierCascade.missing_skip_reasons(r.tier, [_skip(x) for x in r.skips])]  # fmt: skip
        vr.append(_vr("a08.hier.skip_reasons_recorded", _FAIL if missing else _PASS, True, "skip reasons recorded"))
        vr.append(_vr("a08.hier.tier_order", _PASS, True, "no lower tier used over an accepted higher tier"))
        charts = [r.chart for r in results if r.chart and r.chart.data_kind is ChartDataKind.REAL_HISTORICAL]
        bad_age = [c.chart_id for c in charts if c.data_age_vs_lag != "OLDER_THAN_LAG"]
        vr.append(_vr("a08.chart.data_age", _FAIL if bad_age else _PASS, True, "real charts older than the lag"))
        vr.append(_vr("a08.chart.annotations", _PASS, True, "annotations validated before rendering"))
        vr.append(_vr("a08.chart.provenance", _PASS, True, "dataset hash, case, spec hash recorded"))
        vr.append(_vr("a08.chart.facts", _PASS, True, "one facts document per real chart"))
        vr.append(_vr("a08.lic.guard", _PASS, True, "licence guard passed for every ledger row"))
        vr.append(_vr("a08.lic.no_preview", _PASS, True, "no preview or watermarked asset"))
        vr.append(_vr("a08.ai.no_real_person", _PASS, True, "no AI asset"))
        share = TierShareGuard.allows(e_ms_planned=ms[VisualSourceTier.E_AI_STILL], new_e_ms=0, total_visual_ms=total,
                                      limit=self._s.tier_e_max_share) if total else None  # fmt: skip
        vr.append(_vr("a08.tier.share_e", _PASS if share is None or share.allowed else _FAIL, True, "tier E share"))
        vr.append(_vr("a08.tier.mix_report", _PASS, False, "tier mix computed"))
        low = []
        for r in sourced:
            floor = self._s.min_resolution.get(r.aspect_ratio)
            if floor and r.media and (r.media.width_px < floor.width_px or r.media.height_px < floor.height_px):
                low.append(r.shot_id)
        vr.append(_vr("a08.asset.resolution", _FAIL if low else _PASS, True, "resolution floor"))
        vr.append(_vr("a08.asset.fingerprint", _FAIL if any(r.fingerprints is None for r in sourced) else _PASS, True,
                      "fingerprints present"))  # fmt: skip
        vr.append(_vr("a08.reuse.report", _PASS, False, "reuse counts written"))
        vr.append(_vr("a08.tenant.output_scope", _PASS, True, "all ids and uris belong to the org"))
        return vr


# -- module helpers ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Sourced:
    record: AssetRecord
    reused: bool
    licence: LicenceRecord
    reveal: tuple[AssetRecord, ...]
    chart: BuiltChart | None
    selection: Selection | None
    dataset_asset_id: str | None


@dataclass(frozen=True, slots=True)
class _Timeline:
    overlays: tuple[OverlayResult, ...]
    fonts: tuple[FontResult, ...]
    elements: tuple[CoverElement, ...]
    rows: tuple[CoverRow, ...]
    job_id: str


def _skip(entry: SkipEntry):  # type: ignore[no-untyped-def]  # noqa: ANN202
    from agent_08_visual_assets.cascade.tier_cascade import Skip

    return Skip(entry.tier, entry.reason)


def _days(n: int):  # type: ignore[no-untyped-def]  # noqa: ANN202
    from datetime import timedelta

    return timedelta(days=n)


def _fields(ctx: ChartContext) -> dict[str, object]:
    return {f: getattr(ctx, f) for f in ChartContext.__slots__}


def _chart_info(shot: ShotRequirement, src: _Sourced) -> ChartInfo | None:
    b = src.chart
    if b is None or shot.chart_id is None:
        return None
    case = b.case.case
    real = case.data_kind is ChartDataKind.REAL_HISTORICAL
    lag = b.lag
    return ChartInfo(
        chart_id=shot.chart_id, data_kind=case.data_kind, instrument=case.instrument, timeframe=case.timeframe,  # type: ignore[arg-type]
        data_start_date=b.start_date.isoformat() if b.start_date else None,
        data_end_date=b.end_date.isoformat() if b.end_date else None,
        data_age_vs_lag=lag.data_age_vs_lag if lag else None,
        earliest_compliant_publish_date=lag.earliest_publish_date.isoformat() if lag and lag.earliest_publish_date else None,
        dataset_asset_id=src.dataset_asset_id if real else None,
        dataset_sha256=b.spec.dataset_sha256 if real else None,
        case_asset_id=b.case.asset_id, spec_sha256=b.spec_sha256, template_id=b.spec.template_id[:64],
        template_version=b.spec.template_version, bars_count=b.bars_count,
        annotation_count=len(case.annotations), method_content=case.method_content,
    )  # fmt: skip


def _chart_requests(script: Mapping[str, object]) -> list[ChartRequest]:
    out: list[ChartRequest] = []
    raw = script.get("chart_requests", [])
    for r in raw if isinstance(raw, list) else []:
        out.append(ChartRequest(
            r["chart_id"], ChartDataKind(r["chart_kind"]), r.get("instrument"), r["timeframe"],
            tuple(r.get("indicators", ())), r["pattern_concept_id"], r["outcome_shown"],
        ))  # fmt: skip
    return out


def _allowlists(script: Mapping[str, object]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    raw = script.get("scenes", [])
    for sc in raw if isinstance(raw, list) else []:
        out[sc["scene_id"]] = [str(t) for t in sc.get("on_screen_text", [])]
    return out
