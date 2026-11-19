"""``AssetSourcingStage`` (task ``agent_08.asset_sourcing``, stage ``s08_assets``).

Sources one asset per shot in hierarchy order (A to E, code-enforced), writes the licence-ledger
rows (shots, overlay intervals, brand fonts), the chart facts, the tier mix, the validation results
and the single gate result with its remedy stage. 3A scope wired here: charts and graphics (tier C,
no network, no model), owner library (tier A, ranking through the injected ``FootageSelector``) and
tiers B, D, E recorded as ``TIER_DISABLED`` until their adapters are enabled (their gates, prompt
composer, disclosure flags and error mapper are implemented and unit-tested separately).
Every DB access goes through one tenant transaction; every query is explicitly scoped by org.
"""

import hashlib
import io
import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from agent_08_visual_assets.cascade.selection import (
    Assessment,
    Fit,
    RankedCandidate,
    SafetyFloor,
    TieBreaker,
)
from agent_08_visual_assets.cascade.share import TierMixReporter, TierShareGuard
from agent_08_visual_assets.cascade.tier_cascade import (
    Attempt,
    CascadeResult,
    ChartAttempt,
    Probes,
    Skip,
    TierCascade,
    accept,
    skip_with,
)
from agent_08_visual_assets.charts.cases import ChartCase, ChartRequest, StoredCase
from agent_08_visual_assets.charts.datapack_builder import (
    DataPackChartBuilder,
    DataPackChartRequest,
    RegisteredDataset,
    is_data_within_lag,
)
from agent_08_visual_assets.charts.dataset import BarSeries, DatasetLoader
from agent_08_visual_assets.charts.lag import EarliestPublishDate
from agent_08_visual_assets.charts.pipeline import BuiltChart, ChartContext, ChartPath
from agent_08_visual_assets.charts.render import BrandPalette, RenderedImage
from agent_08_visual_assets.gate import GATE_CHECK_ID, GateOutcome, GateRouter, Unresolved
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
    ChartFact,
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
    RevealStill,
    Selection,
    ShotResult,
    SkipEntry,
    SourcingOutput,
    TierMix,
    TierShareEntry,
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
    LedgerEntry,
    LicenceRecord,
    NewAsset,
    NewLedgerEntry,
)
from agent_08_visual_assets.plan.revision import ChangedShotSelector, ShotKey
from agent_08_visual_assets.registrar import APPROVED_SOURCE_CLASS
from agent_08_visual_assets.reuse.engine import (
    ReuseCandidate,
    ReuseDecisionKind,
    ReuseEngine,
    ReuseRequest,
)
from agent_08_visual_assets.reuse.fingerprint import ALGO_VERSION, Fingerprinter
from agent_08_visual_assets.settings import AssetSettings
from agent_08_visual_assets.sources.graphics import GraphicKind, GraphicTemplateRenderer
from agent_08_visual_assets.templates import TemplateResolver
from amw_core.contracts.common import PayloadObject
from amw_core.contracts.error import error_object_from_exception
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import (
    NextAction,
    OutputRef,
    ResourceUsage,
    TaskOutput,
    ValidationResult,
)
from amw_core.enums import (
    AssetKind,
    AssetStatus,
    ChartDataKind,
    CheckKind,
    CheckVerdict,
    ContextRefPurpose,
    LicenceDestination,
    LicenceSourceType,
    LicenceUsageKind,
    NextActionType,
    OutputRefKind,
    OutputStatus,
    ShotIntentKind,
    ShotSourcingStatus,
    ShotUnresolvedReason,
    SourcingWarning,
    VisualSkipReason,
    VisualSourceTier,
)
from amw_core.errors import (
    AgentError,
    AmwError,
    BudgetExhaustedError,
    ConfigInvalidError,
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    PermanentError,
    QualityRepeatedFailureError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    TenantInactiveError,
    TenantMismatchError,
)
from amw_core.exec_context import ExecContext
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenancyContext, TenantContext, TenantTransaction
from amw_core.tenancy.storage_paths import task_artifact_uri

AGENT_ID = "agent_08"

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


@dataclass(frozen=True, slots=True)
class FootageChoice:
    """Outcome of the (LLM-backed) assessment of the filtered owner candidates.

    The model's fits are advisory: the stage applies ``SafetyFloor`` and ``TieBreaker``."""

    assessments: tuple[Assessment, ...] = ()
    order: tuple[str, ...] = ()
    prohibited: bool = False
    refusal_reason: str | None = None


class BrandKitReader(Protocol):
    """Reads the ``BRAND_KIT`` context ref of the Task Input (04 section 5.12) inside the tenant
    transaction; ``None`` for a ref that does not resolve to the tenant's brand kit."""

    def brand_kit(self, tx: TenantTransaction, uri: str, sha256: str | None) -> BrandKit | None: ...


class JobDestinationReader(Protocol):
    """Reads ``jobs.monetized_destination`` (CCR-028) of the task's job inside the tenant
    transaction; ``None`` when the row or the value is not readable."""

    def monetized_destination(self, tx: TenantTransaction, job_id: str) -> bool | None: ...


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
    chart_checked: bool = True


def _vr(
    check_id: str,
    verdict: CheckVerdict,
    blocking: bool,
    message: str,
    *,
    gate: bool = False,
    remedy: str | None = None,
) -> ValidationResult:
    return ValidationResult(
        check_id=check_id,
        kind=CheckKind.DETERMINISTIC,
        verdict=verdict,
        blocking=blocking and verdict not in (_WARN, _SKIP),
        message=message,
        gate=gate,
        remedy_stage_id=remedy,
    )


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
        brand_kits: BrandKitReader | None = None,
        job_destinations: JobDestinationReader | None = None,
    ) -> None:
        self._tenancy, self._assets, self._licences = tenancy, assets, licences
        self._ledger, self._fp, self._approvals = ledger, fingerprints, approvals
        self._blobs, self._clock, self._s, self._selector = blobs, clock, settings, selector
        self._brand_kits, self._templates = brand_kits, TemplateResolver(assets)
        self._job_destinations = job_destinations
        self._destination = LicenceDestination.MONETIZED_YOUTUBE
        self._reset(JobScope("", "", "", ""))

    # -- public --------------------------------------------------------------------------------

    def run(self, task_input: TaskInput, ctx: ExecContext) -> TaskOutput:
        """``TaskWorker`` entry point (03 section 1 rule 5, CCR-203). Reads ``shot_plan_ref`` and
        ``script_ref`` itself, runs the stage and returns ``amw.task_output``; ``StageResult``
        never crosses. Typed permanent failures are returned, never raised."""
        started = self._clock.monotonic_ms()
        validated = False
        try:
            check_ctx(task_input, ctx)
            call = self._prepare(task_input, ctx)
            validated = True
            result = self.source(**call)
            return self._task_output(task_input, ctx, result, started)
        except (PermanentError, AgentError, BudgetExhaustedError) as exc:
            return error_output(
                exc,
                task=task_input,
                clock=self._clock,
                started_ms=started,
                attempt_no=task_input.retry_count,
                validated=validated,
            )

    def _prepare(self, task: TaskInput, ctx: ExecContext) -> dict[str, Any]:
        """E0: payload, tenant guard, the two blobs (hash-verified), brand kit, previous output."""
        if task.agent_id != AGENT_ID:
            raise InputInvalidError("task is not addressed to agent_08")
        data = task.payload.data
        if data is None:
            raise SchemaInvalidError("payload must carry inline data")
        try:
            inp = SourcingInput.model_validate(data)
        except ValidationError:
            raise SchemaInvalidError("payload is not agent_08.asset_sourcing.input") from None
        tenant = ctx.tenant
        uris = [inp.shot_plan_ref.uri, inp.script_ref.uri]
        if inp.previous_sourcing_ref is not None:
            uris.append(inp.previous_sourcing_ref.uri)
        uris.extend(r.uri for r in task.context_refs)
        TenantGuard.check_task(
            context_org=str(tenant.org_id),
            envelope_org=task.org_id,
            input_org=task.org_id,
            uris=uris,
            write=False,
        )
        plan_bytes = self._read(
            tenant, inp.shot_plan_ref.uri, inp.shot_plan_ref.sha256, "shot plan"
        )
        script_bytes = self._read(tenant, inp.script_ref.uri, inp.script_ref.sha256, "script")
        previous: SourcingOutput | None = None
        if inp.previous_sourcing_ref is not None:
            prev = inp.previous_sourcing_ref
            raw = self._read(tenant, prev.uri, prev.sha256, "previous sourcing manifest")
            try:
                previous = SourcingOutput.model_validate(json.loads(raw))
            except ValueError:
                raise InputInvalidError("previous sourcing manifest is not valid") from None
        total = ShotPlanReader.total_duration_ms(plan_bytes)
        return {
            "ctx": tenant,
            "envelope_org": task.org_id,
            "scope": JobScope(
                task.job_id, task.task_id, str(ctx.channel_id or task.channel_id or ""), task.org_id
            ),
            "inp": inp,
            "script_bytes": script_bytes,
            "plan_bytes": plan_bytes,
            "brand": self._brand(task, tenant),
            "job_destination": self._job_destination(task, tenant),
            "timeline_end_ms": total,
            "previous": previous,
        }

    def _read(self, tenant: TenantContext, uri: str, sha256: str, what: str) -> bytes:
        try:
            return b"".join(self._blobs.get(tenant, BlobUri(uri), sha256))
        except CorruptedOutputError:
            raise InputInvalidError(f"{what} hash does not match its reference") from None

    def _brand(self, task: TaskInput, tenant: TenantContext) -> BrandKit:
        if self._brand_kits is None:
            raise ConfigInvalidError("no brand kit reader is configured")
        refs = [r for r in task.context_refs if r.purpose is ContextRefPurpose.BRAND_KIT]
        if len(refs) != 1:
            raise MissingDependencyError(
                "the task needs exactly one BRAND_KIT context ref", details={"class": "brand_kit"}
            )
        with self._tenancy.transaction(tenant) as tx:
            kit = self._brand_kits.brand_kit(tx, refs[0].uri, refs[0].sha256)
        if kit is None:
            raise MissingDependencyError("brand kit not found", details={"class": "brand_kit"})
        return kit

    def _job_destination(self, task: TaskInput, tenant: TenantContext) -> LicenceDestination:
        """The job's own destination; the payload value is never trusted here. Fails CLOSED: an
        unreadable destination refuses the task instead of falling back to the payload."""
        if self._job_destinations is None:
            raise ConfigInvalidError("no job destination reader is configured")
        with self._tenancy.transaction(tenant) as tx:
            monetized = self._job_destinations.monetized_destination(tx, task.job_id)
        if monetized is None:
            raise MissingDependencyError(
                "the job's monetized destination is not readable", details={"class": "job"}
            )
        return (
            LicenceDestination.MONETIZED_YOUTUBE if monetized else LicenceDestination.NON_MONETIZED
        )

    def _task_output(
        self, task: TaskInput, ctx: ExecContext, result: StageResult, started: int
    ) -> TaskOutput:
        if result.payload is None or result.task_status != "SUCCEEDED":
            code = result.error_code or QualityRepeatedFailureError.code
            cls = AmwError.registry.get(code, QualityRepeatedFailureError)
            raise cls("asset sourcing failed", details={"stage_result": result.task_status})
        doc = result.payload.to_doc()
        body = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
        tenant = ctx.tenant
        name = "sourcing_manifest.json"
        uri = task_artifact_uri(ctx.org_id, ctx.job_id, ctx.task_id, ctx.attempt_id, name)
        blob = BlobUri(uri)
        head = self._blobs.head(tenant, blob)
        if not head.exists:
            self._blobs.put(tenant, blob, io.BytesIO(body))
        elif head.sha256 != hashlib.sha256(body).hexdigest():
            raise InputInvalidError("a manifest of this attempt exists with different content")
        refs = [
            OutputRef(
                uri=uri,
                kind=OutputRefKind.DATA,
                sha256=hashlib.sha256(body).hexdigest(),
                size_bytes=len(body),
                media_type="application/json",
            )
        ]
        for extra in result.blobs.values():
            h = self._blobs.head(tenant, BlobUri(extra))
            if h.sha256 is None or h.size_bytes is None:
                raise CorruptedOutputError("an output blob is missing")
            refs.append(
                OutputRef(
                    uri=extra,
                    kind=OutputRefKind.DATA,
                    sha256=h.sha256,
                    size_bytes=h.size_bytes,
                    media_type="application/json",
                )
            )
        failed = result.gate_verdict == "FAILED"
        now = self._clock.now()
        return TaskOutput(
            status=OutputStatus.SUCCEEDED,
            payload=PayloadObject(
                payload_schema="agent_08.asset_sourcing.output",
                payload_schema_version="1.0.0",
                data=doc,
            ),
            output_refs=tuple(refs),
            quality_score=None,
            confidence=None,
            validation_results=result.validation_results,
            duration=max(0, self._clock.monotonic_ms() - started),
            resource_usage=zero_usage(task.resource_budget.currency),
            error=None,
            next_action=NextAction(
                type=NextActionType.CONTINUE,
                wait_reason=None,
                escalation_level=None,
                reason=f"gate FAILED: {GATE_CHECK_ID}" if failed else "gate PASSED",
            ),
            downstream_agent=None,
            timestamp=now,
        )

    def source(
        self,
        *,
        ctx: TenantContext,
        envelope_org: str,
        scope: JobScope,
        inp: SourcingInput,
        script_bytes: bytes,
        plan_bytes: bytes,
        brand: BrandKit,
        timeline_end_ms: int,
        previous: SourcingOutput | None = None,
        job_destination: LicenceDestination | None = None,
    ) -> StageResult:
        self._reset(scope)
        uris = [inp.shot_plan_ref.uri, inp.script_ref.uri]
        if inp.previous_sourcing_ref is not None:
            uris.append(inp.previous_sourcing_ref.uri)
        TenantGuard.check_task(
            context_org=str(ctx.org_id),
            envelope_org=envelope_org,
            input_org=scope.org_id,
            uris=uris,
            write=False,
        )
        self._pre["a08.pre.tenant"] = True
        # 7.4: both inputs are verified against the hashes of their refs (03 section 8.4)
        if hashlib.sha256(plan_bytes).hexdigest() != inp.shot_plan_ref.sha256:
            raise InputInvalidError("shot plan hash does not match its reference")
        if hashlib.sha256(script_bytes).hexdigest() != inp.script_ref.sha256:
            raise InputInvalidError("script hash does not match its reference")
        if job_destination is not None and job_destination is not inp.destination:
            raise InputInvalidError("destination disagrees with the job's monetized destination")
        self._pre["a08.pre.refs"] = True
        self._destination = inp.destination
        shots, overlays = ShotPlanReader.read(plan_bytes)
        shots = [s for s in shots if s.aspect_ratio.value in inp.aspect_ratios]
        self._pre["a08.pre.shot_plan"] = True
        if len(shots) > self._s.max_shots_per_task:
            raise InputInvalidError("plan has more shots than assets.max_shots_per_task")
        self._pre["a08.pre.batch_size"] = True
        self._plan_shots.extend(shots)
        self._pre["a08.pre.config"] = True  # AssetSettings validated at construction
        script = json.loads(script_bytes)
        requests = {r.chart_id: r for r in _chart_requests(script)}
        allow = _allowlists(script)
        todo = self._select(shots, previous, inp)
        with (
            tempfile.TemporaryDirectory(prefix="a08_font_") as tmp,
            self._tenancy.transaction(ctx) as tx,
        ):
            self._own_assets.update(
                e.entry.asset_id
                for e in self._ledger.for_job(tx, scope.job_id)
                if e.entry.task_id == scope.task_id
            )
            licences = self._standing_licences(tx, brand, overlays)
            self._pre["a08.pre.licence_rows"] = True
            brand = self._with_font(tx, brand, Path(tmp))
            built = [
                self._shot(tx, scope, s, requests, allow, brand, licences, previous, todo)
                for s in shots
            ]
            timeline = self._timeline(tx, scope, overlays, brand, licences, timeline_end_ms)
            rows = tuple(self._ledger.for_job(tx, scope.job_id))
        return self._assemble(ctx, inp, built, timeline, rows, previous, script)

    def _reset(self, scope: JobScope) -> None:
        self._pre: dict[str, bool] = {}
        self._guards: list[GuardResult] = []
        self._own_assets: set[str] = set()
        self._channel = scope.channel_id
        self._plan_shots: list[ShotRequirement] = []

    def _with_font(self, tx: TenantTransaction, brand: BrandKit, tmp: Path) -> BrandKit:
        """The font that renders is the first brand-kit font asset, read through tenant storage;
        its asset is the one that carries the FONT ledger row."""
        if not brand.font_asset_ids:
            return brand
        rec = self._assets.get(tx, brand.font_asset_ids[0])
        if rec is None or rec.asset.kind is not AssetKind.FONT:
            raise MissingDependencyError(
                "brand font asset missing", details={"class": "brand_font"}
            )
        data = b"".join(
            self._blobs.get(tx.context, BlobUri(rec.asset.uri), rec.asset.content_sha256)
        )
        path = tmp / f"{rec.asset.content_sha256}.ttf"
        path.write_bytes(data)
        palette = replace(brand.palette, font_path=str(path), font_sha256=rec.asset.content_sha256)
        return replace(brand, palette=palette)

    # -- helpers -------------------------------------------------------------------------------

    def _select(
        self, shots: Sequence[ShotRequirement], previous: SourcingOutput | None, inp: SourcingInput
    ) -> set[str]:
        if previous is None:
            return {s.shot_id for s in shots}

        def key(r: ShotResult) -> ShotKey:
            return ShotKey(r.shot_id, r.content_key, r.start_ms, r.end_ms, r.aspect_ratio)

        sel = ChangedShotSelector.select(
            [key(r) for r in previous.shots],
            [
                ShotKey(s.shot_id, s.content_key, s.start_ms, s.end_ms, s.aspect_ratio.value)
                for s in shots
            ],
            inp.changed_shot_ids,
        )
        return set(sel.resource)

    def _standing_licences(
        self, tx: TenantTransaction, brand: BrandKit, overlays: Sequence[object]
    ) -> dict[LicenceSourceType, LicenceRecord]:
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
                    "standing licence row missing",
                    details={"class": f"licence.self_grant.{st.value}"},
                )
            out[st] = rec
        return out

    def _licence_for(
        self,
        tx: TenantTransaction,
        licences: Mapping[LicenceSourceType, LicenceRecord],
        source_type: LicenceSourceType,
    ) -> LicenceRecord:
        """Standing self-grant row of the asset's own source type: an owner asset is never
        ledgered under another class (a client asset needs its own client licence row)."""
        rec = licences.get(source_type) or self._licences.self_grant(tx, source_type)
        if rec is None:
            raise MissingDependencyError(
                "standing licence row missing",
                details={"class": f"licence.self_grant.{source_type.value}"},
            )
        return rec

    def _guard(self, rec: LicenceRecord, tenant_org: str) -> GuardResult:
        now = self._clock.now()
        return LicenceGuard.check(
            licence=LicenceView(
                rec.state,
                None if rec.expires_at is None else rec.expires_at - now,
                rec.org_id is None,
                rec.third_party_permission,
                rec.covers_monetized_youtube,
                rec.indemnification,
                rec.source_type,
            ),
            destination=self._destination,
            tenant_is_platform_owner=False,
            warning_window=_days(self._s.licence_expiry_warning_days),
        )

    def _put(self, ctx: TenantContext, name: str, data: bytes) -> str:
        uri = self._blobs.blob_uri(ctx, "assets", name)
        if not self._blobs.head(ctx, uri).exists:
            self._blobs.put(ctx, uri, io.BytesIO(data))
        return str(uri)

    def _register_png(
        self,
        tx: TenantTransaction,
        img: RenderedImage,
        *,
        kind: AssetKind,
        licence: LicenceRecord,
        title: str,
        attrs: Mapping[str, object],
    ) -> tuple[AssetRecord, bool]:
        uri = self._put(tx.context, f"generated/{img.sha256}.png", img.png)
        existing = self._assets.find_by_sha(tx, img.sha256)
        if existing is not None:
            now = self._clock.now()
            decision = ReuseEngine.decide(
                asset=ReuseCandidate(
                    existing.org_id,
                    existing.status.value,
                    None if existing.asset.expires_at is None else existing.asset.expires_at - now,
                    existing.asset.allowed_channel_ids,
                    0,
                    existing.asset.content_sha256,
                ),
                request=ReuseRequest(str(tx.context.org_id), self._channel, img.sha256),
                distance=None,
                max_uses=None,
                hamming_threshold=None,
            )
            if decision.decision is not ReuseDecisionKind.REUSE_EXACT:
                raise InputInvalidError(
                    "an identical asset exists but is not reusable",
                    details={"reason": str(decision.reason)},
                )
        rec = existing or self._assets.insert(
            tx,
            NewAsset(
                kind=kind,
                source_type=LicenceSourceType.CODE_GENERATED,
                content_sha256=img.sha256,
                uri=uri,
                size_bytes=len(img.png),
                title=title,
                visual_source_tier=VisualSourceTier.C_CODE_MOTION,
                licence_id=licence.licence_id,
                width_px=img.width_px,
                height_px=img.height_px,
                attributes=dict(attrs),
            ),
        )
        fp = Fingerprinter.still(img.png)
        self._fp.add(
            tx,
            [FingerprintRow(rec.asset_id, "SHA256", ALGO_VERSION, fp.sha256, None)]
            + [
                FingerprintRow(
                    rec.asset_id, "PERCEPTUAL_FRAME", ALGO_VERSION, f.hash_hex, f.frame_ms
                )
                for f in fp.perceptual_frames
            ],
        )
        return rec, existing is not None and existing.asset_id not in self._own_assets

    def _write_ledger(
        self,
        tx: TenantTransaction,
        scope: JobScope,
        shot: ShotRequirement,
        rec: AssetRecord,
        lic: LicenceRecord,
        tier: VisualSourceTier | None,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> str:
        guard = self._guard(lic, scope.org_id)
        self._guards.append(guard)
        if not guard.usable:
            raise InputInvalidError("licence not usable", details={"reason": str(guard.reason)})
        row = LedgerRowBuilder.build(
            tier=tier,
            kind=rec.asset.kind,
            source_type=rec.asset.source_type,
            start_ms=shot.start_ms if start_ms is None else start_ms,
            end_ms=shot.end_ms if end_ms is None else end_ms,
            licence_ref=lic.licence_id,
            element_id=shot.shot_id,
        )
        entry = self._write_row(
            tx,
            NewLedgerEntry(
                scope.job_id,
                scope.task_id,
                rec.asset_id,
                lic.licence_id,
                row.usage_kind,
                row.used_from_ms,
                row.used_to_ms,
                row.shot_id,
                None,
                row.source_url,
                row.vendor_item_id,
            ),
        )
        return entry.ledger_entry_id

    def _write_row(self, tx: TenantTransaction, new: NewLedgerEntry) -> LedgerEntry:
        """Append the row unless this job already holds the same covering row (a revision writes
        new rows only for shots whose asset or interval changed, FR-20)."""
        for e in self._ledger.for_job(tx, new.job_id):
            x = e.entry
            if (x.asset_id, x.usage_kind, x.shot_id, x.used_from_ms, x.used_to_ms, x.render_id) == (
                new.asset_id,
                new.usage_kind,
                new.shot_id,
                new.used_from_ms,
                new.used_to_ms,
                None,
            ):
                return e
        return self._ledger.write(tx, new)

    def _case_docs(self, tx: TenantTransaction, ctx: TenantContext) -> list[StoredCase]:
        out: list[StoredCase] = []
        for rec in self._assets.list_assets(tx, kinds=[AssetKind.DOCUMENT]):
            if rec.asset.attributes.get("doc_kind") != "CHART_CASE":
                continue
            _require_intake(rec)
            data = b"".join(self._blobs.get(ctx, BlobUri(rec.asset.uri), rec.asset.content_sha256))
            out.append(
                StoredCase(
                    rec.asset_id, ChartCase.model_validate_json(data), rec.asset.content_sha256
                )
            )
        return out

    def _dataset(
        self, tx: TenantTransaction, ctx: TenantContext, asset_id: str | None
    ) -> tuple[BarSeries | None, str | None]:
        if asset_id is None:
            return None, None
        rec = self._assets.get(tx, asset_id)
        if rec is None:
            return None, None
        if rec.asset.attributes.get("doc_kind") != "DATASET":
            raise InputInvalidError("dataset asset is not a registered dataset")
        _require_intake(rec)
        data = b"".join(self._blobs.get(ctx, BlobUri(rec.asset.uri), rec.asset.content_sha256))
        try:
            return DatasetLoader.load(
                data, expected_sha256=rec.asset.content_sha256, max_bars=self._s.max_dataset_bars
            ), rec.asset_id
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
                req,
                cases,
                None,
                None,
                False,
                list(shot.on_screen_text) + list(scene_text),
                len(shot.change_events_ms),
                self._clock.now().date(),
                self._s.price_data_lag_days,
                self._s.price_data_lag_platform_min_days,
                w,
                h,
                shot.aspect_ratio.value,
                palette,
            )
            stored = ChartPath.case_for(base)
            if stored is not None and stored.case.window_dates is not None:
                return self._datapack_chart(tx, stored, base, licences, shot)
            series, ds_id, released = None, None, False
            if stored is not None:
                series, ds_id = self._dataset(tx, ctx, stored.case.dataset_asset_id)
                if stored.case.method_content:
                    released = self._approvals.is_released(tx, stored.asset_id, stored.sha256)
            outcome = ChartPath.run(
                replace(base, series=series, dataset_asset_id=ds_id, release_approved=released)
            )
            if outcome.built is None:
                return ChartAttempt(unresolved=outcome.unresolved)
            return ChartAttempt(
                accepted=self._register_chart(tx, outcome.built, licences, ds_id, shot)
            )

        def graphic() -> Attempt[_Sourced]:
            texts = tuple(shot.on_screen_text)
            if shot.intent_kind is ShotIntentKind.DIAGRAM and texts:
                from agent_08_visual_assets.sources.graphics import DiagramSpec

                kind, diagram = (
                    GraphicKind.DIAGRAM,
                    DiagramSpec(texts, tuple((i, i + 1) for i in range(len(texts) - 1))),
                )
            elif texts:
                kind = (
                    GraphicKind.TITLE_CARD
                    if shot.intent_kind is ShotIntentKind.TEXT_CARD
                    else GraphicKind.KINETIC_TEXT
                )
                diagram = None
            elif shot.intent_kind is ShotIntentKind.FOOTAGE and shot.fallback_template_key:
                kind, diagram = GraphicKind.ABSTRACT_MOTION, None
            else:
                return skip_with(VisualSkipReason.NO_TEMPLATE_CONTENT)
            img = GraphicTemplateRenderer.render(
                kind=kind,
                lines=texts if kind in (GraphicKind.TITLE_CARD, GraphicKind.KINETIC_TEXT) else (),
                allowlist=texts,
                width_px=w,
                height_px=h,
                palette=palette,
                diagram=diagram,
            )
            lic = licences[LicenceSourceType.CODE_GENERATED]
            rec, reused = self._register_png(
                tx,
                img,
                kind=AssetKind.IMAGE,
                licence=lic,
                title=shot.shot_id,
                attrs={"template_id": kind.value, "template_version": 1},
            )
            return accept(_Sourced(rec, reused, lic, (), None, None, None))

        def owner() -> Attempt[_Sourced]:
            cands = self._owner_candidates(tx, scope, shot)
            if not cands:
                return skip_with(VisualSkipReason.NO_CANDIDATE)
            if self._selector is None:
                raise ConfigInvalidError(
                    "owner footage exists but no FootageSelector is configured"
                )
            choice = self._selector.select(shot, cands)
            if choice.refusal_reason == "UNSAFE_CONTENT" or choice.prohibited:
                return skip_with(
                    VisualSkipReason.PROHIBITED_DEPICTION,
                    unsafe=choice.refusal_reason == "UNSAFE_CONTENT",
                )
            by_id = {c.asset_id: c for c in cands}
            known = tuple(a for a in choice.assessments if a.candidate_id in by_id)
            floor = SafetyFloor.apply(known, [i for i in choice.order if i in by_id])
            fits = dict(floor.fits)
            ranked = [
                RankedCandidate(
                    i, f, VisualSourceTier.A_OWNER_REAL, False, by_id[i].asset.duration_ms
                )
                for i, f in fits.items()
            ]
            order = TieBreaker.order(ranked, shot.duration_ms)
            if not order:
                return skip_with(VisualSkipReason.NO_ACCEPTABLE_FIT)
            rec = by_id[order[0]]
            lic = self._licence_for(tx, licences, rec.asset.source_type)
            fit = "STRONG" if fits[rec.asset_id] is Fit.STRONG else "ACCEPTABLE"
            return accept(
                _Sourced(
                    rec,
                    False,
                    lic,
                    (),
                    None,
                    Selection(fit=fit, candidate_count=len(cands)),
                    None,
                )
            )

        if shot.internal_intent.value == "CHART":
            probes.chart = chart
        else:
            probes.graphic = (
                graphic
                if (
                    shot.intent_kind is not ShotIntentKind.FOOTAGE
                    or VisualSourceTier.D_AI_VIDEO not in shot.allowed_tiers
                )
                else None
            )
            probes.owner = owner
        res = TierCascade.resolve_shot(
            intent=shot.internal_intent,
            probes=probes,
            allowed_tiers=shot.allowed_tiers if shot.internal_intent.value == "FOOTAGE" else None,
        )
        return self._finish(tx, scope, shot, res, licences)

    def _canvas(self, shot: ShotRequirement) -> tuple[int, int]:
        size = self._s.canvas.get(shot.aspect_ratio.value)
        if size is None:
            raise ConfigInvalidError("no canvas configured for aspect " + shot.aspect_ratio.value)
        return size.width_px, size.height_px

    def _owner_candidates(
        self, tx: TenantTransaction, scope: JobScope, shot: ShotRequirement
    ) -> list[AssetRecord]:
        floor = self._s.min_resolution.get(shot.aspect_ratio.value)
        out: list[AssetRecord] = []
        now = self._clock.now()
        for rec in self._assets.list_assets(
            tx,
            kinds=[AssetKind.VIDEO, AssetKind.IMAGE],
            source_types=[LicenceSourceType.OWNER_MADE, LicenceSourceType.CLIENT_SUPPLIED],
        ):
            a = rec.asset
            if rec.org_id != scope.org_id or rec.status is not AssetStatus.ACTIVE:
                continue
            if a.expires_at is not None and a.expires_at <= now:
                continue
            if a.allowed_channel_ids is not None and scope.channel_id not in a.allowed_channel_ids:
                continue
            if floor and (
                (a.width_px or 0) < floor.width_px or (a.height_px or 0) < floor.height_px
            ):
                continue
            if (
                a.kind is AssetKind.VIDEO
                and not shot.allows_hold
                and (
                    a.duration_ms is None
                    or a.duration_ms < shot.duration_ms + self._s.min_head_tail_ms
                )
            ):
                continue
            out.append(rec)
        return sorted(out, key=lambda r: r.asset_id)[: self._s.max_candidates_per_shot]

    def _datapack_chart(
        self,
        tx: TenantTransaction,
        stored: StoredCase,
        base: ChartContext,
        licences: Mapping[LicenceSourceType, LicenceRecord],
        shot: ShotRequirement,
    ) -> ChartAttempt[_Sourced]:
        """Tier C data_pack chart scene: an owner case with a date window (CCR-259) over a
        registered data_pack dataset, drawn by ``DataPackChartBuilder`` with the stage's clock as
        the only as-of source; registered like every other chart."""
        case = stored.case
        series, ds_id = self._dataset(tx, tx.context, case.dataset_asset_id)
        rec = self._assets.get(tx, ds_id) if ds_id is not None else None
        if series is None or rec is None or case.window_dates is None or case.instrument is None:
            return ChartAttempt(unresolved=ShotUnresolvedReason.NO_DATASET)
        if case.method_content and not self._approvals.is_released(
            tx, stored.asset_id, stored.sha256
        ):
            return ChartAttempt(unresolved=ShotUnresolvedReason.METHOD_NOT_RELEASED)
        request = DataPackChartRequest(
            chart_id=base.request.chart_id,
            instrument=case.instrument,
            timeframe=case.timeframe,
            window_start=case.window_dates.start_date,
            window_end=case.window_dates.end_date,
            indicators=case.indicators,
            annotations=case.annotations,
            connectors=case.connectors,
            on_screen_text_allowlist=tuple(base.on_screen_text_allowlist),
            rsi_guides=case.rsi_guides,
            reveal_steps=base.change_events + 1,
            aspect_ratio=base.aspect_ratio,
        )
        builder = DataPackChartBuilder(
            palette=base.palette,
            clock=self._clock,
            lag_days=self._s.price_data_lag_days,
            platform_min_lag_days=self._s.price_data_lag_platform_min_days,
            width_px=base.width_px,
            height_px=base.height_px,
        )
        dataset = RegisteredDataset(
            rec.asset_id, rec.asset.content_sha256, rec.asset.attributes, series
        )
        try:
            chart = builder.build(request, dataset)
        except InputInvalidError as exc:
            if is_data_within_lag(exc):
                return ChartAttempt(unresolved=ShotUnresolvedReason.DATA_WITHIN_LAG)
            raise
        return ChartAttempt(
            accepted=self._register_chart(tx, chart.as_built(stored), licences, ds_id, shot)
        )

    def _register_chart(
        self,
        tx: TenantTransaction,
        built: BuiltChart,
        licences: Mapping[LicenceSourceType, LicenceRecord],
        ds_id: str | None,
        shot: ShotRequirement,
    ) -> _Sourced:
        lic = licences[LicenceSourceType.CODE_GENERATED]
        attrs = {
            **built.extra_attributes,
            "dataset_asset_id": ds_id,
            "case_id": built.case.case.case_id,
            "spec_sha256": built.spec_sha256,
            "template_id": built.spec.template_id,
            "template_version": built.spec.template_version,
        }
        rec, reused = self._register_png(
            tx, built.stills[-1], kind=AssetKind.CHART, licence=lic, title=shot.shot_id, attrs=attrs
        )
        steps: list[AssetRecord] = []
        for img in built.stills[:-1]:
            steps.append(
                self._register_png(
                    tx,
                    img,
                    kind=AssetKind.IMAGE,
                    licence=lic,
                    title=shot.shot_id + "_reveal",
                    attrs=attrs,
                )[0]
            )
        steps.append(rec)  # the full-window still is both the chart asset and the last step
        return _Sourced(rec, reused, lic, tuple(steps), built, None, ds_id)

    def _finish(
        self,
        tx: TenantTransaction,
        scope: JobScope,
        shot: ShotRequirement,
        res: CascadeResult[_Sourced],
        licences: Mapping[LicenceSourceType, LicenceRecord],
    ) -> _Built:
        base = {
            "shot_id": shot.shot_id,
            "scene_id": shot.scene_id[:32],
            "content_key": shot.content_key,
            "start_ms": shot.start_ms,
            "end_ms": shot.end_ms,
            "aspect_ratio": shot.aspect_ratio.value,
            "intent_kind": shot.intent_kind,
            "skips": tuple(SkipEntry(tier=k.tier, reason=k.reason) for k in res.skips),
        }
        if not res.sourced or res.payload is None:
            return _Built(
                ShotResult(
                    **base,
                    status=ShotSourcingStatus.UNRESOLVED,
                    tier=None,
                    asset_id=None,
                    asset_uri=None,
                    source_type=None,
                    licence_id=None,
                    ledger_entry_ids=(),
                    usage_kind=None,
                    media=None,
                    fingerprints=None,
                    warnings=(),
                    unresolved_reason=res.unresolved_reason,
                    reuse=None,
                    chart=None,
                    reveal_stills=(),
                    disclosure=Disclosure(is_realistic_synthetic=False, depicts_real_person=False),
                    cost_micros=0,
                    selection=None,
                ),
                [],
                None,
            )
        src = res.payload
        guard = self._guard(src.licence, scope.org_id)
        warnings = list(res.warnings) + [w for w in guard.warnings if w not in res.warnings]
        ids = [self._write_ledger(tx, scope, shot, src.record, src.licence, res.tier)]
        starts = [shot.start_ms, *shot.change_events_ms]
        ends = [*shot.change_events_ms, shot.end_ms]
        reveal: list[RevealStill] = []
        for k, rec in enumerate(src.reveal):
            if rec.asset_id == src.record.asset_id:
                rid = ids[0]  # the full-window still is the chart asset: its shot row covers it
            else:
                rid = self._write_ledger(
                    tx, scope, shot, rec, src.licence, res.tier, starts[k], ends[k]
                )
            reveal.append(
                RevealStill(
                    k=k,
                    asset_id=rec.asset_id,
                    asset_uri=rec.asset.uri,
                    sha256=rec.asset.content_sha256,
                    start_ms=starts[k],
                    end_ms=ends[k],
                    licence_id=src.licence.licence_id,
                    ledger_entry_ids=(rid,),
                )
            )
        rows = self._fp.for_asset(tx, src.record.asset_id)
        sha = src.record.asset.content_sha256
        fps = Fingerprints(
            sha256=sha,
            algo_version=ALGO_VERSION,
            perceptual_frames=tuple(
                PerceptualFrame(frame_ms=r.frame_ms or 0, hash_hex=r.value_hex)
                for r in rows
                if r.algo == "PERCEPTUAL_FRAME"
            ),
        )
        a = src.record.asset
        media = Media(
            width_px=a.width_px or 1,
            height_px=a.height_px or 1,
            duration_ms=a.duration_ms or None,
            source_in_ms=0,
            crop=Crop(mode="NONE", anchor=None, keep_permille=1000),
        )
        usage = LedgerRowBuilder.build(
            tier=res.tier,
            kind=a.kind,
            source_type=a.source_type,
            start_ms=0,
            end_ms=1,
            licence_ref=src.licence.licence_id,
            element_id=None,
        ).usage_kind
        chart = _chart_info(shot, src)
        result = ShotResult(
            **base,
            status=ShotSourcingStatus.REUSED if src.reused else ShotSourcingStatus.SOURCED,
            tier=res.tier,
            asset_id=src.record.asset_id,
            asset_uri=a.uri,
            source_type=a.source_type.value,
            licence_id=src.licence.licence_id,
            ledger_entry_ids=tuple(ids),
            usage_kind=usage.value,
            media=media,
            fingerprints=fps,
            warnings=tuple(warnings),
            unresolved_reason=None,
            reuse=ReuseInfo(kind="EXACT", source_asset_id=src.record.asset_id)
            if src.reused
            else None,
            chart=chart,
            reveal_stills=tuple(reveal),
            disclosure=Disclosure(is_realistic_synthetic=False, depicts_real_person=False),
            cost_micros=0,
            selection=src.selection,
        )
        return _Built(result, [src.record, *src.reveal], src.chart)

    # -- overlays and fonts --------------------------------------------------------------------

    def _timeline(
        self,
        tx: TenantTransaction,
        scope: JobScope,
        overlays: Sequence[object],
        brand: BrandKit,
        licences: Mapping[LicenceSourceType, LicenceRecord],
        timeline_end_ms: int,
    ) -> _Timeline:
        from agent_08_visual_assets.models.shot_plan import OverlayRequirement

        reqs = [o for o in overlays if isinstance(o, OverlayRequirement)]
        resolved = self._templates.resolve(tx, (o.template_ref for o in reqs if o.template_ref))
        planned = TimelineLedgerPlanner.plan(
            [
                OverlayInput(
                    o.overlay_id,
                    o.kind,
                    o.start_ms,
                    o.end_ms,
                    None if o.template_ref is None else resolved[o.template_ref],
                    o.template_ref,
                )
                for o in reqs
            ],
            list(brand.font_asset_ids),
            timeline_end_ms,
        )
        ov_out: list[OverlayResult] = []
        fonts: list[FontResult] = []
        rows: list[CoverRow] = []
        els: list[CoverElement] = []
        for row in planned:
            rec = self._assets.get(tx, row.asset)
            if rec is None:
                raise MissingDependencyError(
                    "asset not found", details={"class": "overlay_or_font_asset"}
                )
            st = (
                LicenceSourceType.FONT
                if row.usage_kind is LicenceUsageKind.FONT
                else rec.asset.source_type
            )
            lic = licences.get(st)
            if lic is None:
                raise MissingDependencyError(
                    "standing licence row missing",
                    details={"class": f"licence.self_grant.{st.value}"},
                )
            if not self._guard(lic, scope.org_id).usable:
                raise InputInvalidError("licence not usable for overlay or font")
            led = LedgerRowBuilder.build(
                tier=None,
                kind=AssetKind.FONT
                if row.usage_kind is LicenceUsageKind.FONT
                else AssetKind.TEMPLATE,
                source_type=st,
                start_ms=row.used_from_ms,
                end_ms=row.used_to_ms,
                licence_ref=lic.licence_id,
                element_id=row.shot_id,
            )
            entry = self._write_row(
                tx,
                NewLedgerEntry(
                    scope.job_id,
                    scope.task_id,
                    row.asset,
                    lic.licence_id,
                    led.usage_kind,
                    led.used_from_ms,
                    led.used_to_ms,
                    led.shot_id,
                    None,
                    None,
                    None,
                ),
            )
            rows.append(CoverRow(row.asset, led.used_from_ms, led.used_to_ms, scope.job_id, None))
            els.append(CoverElement(row.element_id, row.asset, row.used_from_ms, row.used_to_ms))
            if row.usage_kind is LicenceUsageKind.FONT:
                fonts.append(
                    FontResult(
                        asset_id=row.asset,
                        licence_id=lic.licence_id,
                        ledger_entry_ids=(entry.ledger_entry_id,),
                        usage_kind="FONT",
                        used_from_ms=0,
                        used_to_ms=row.used_to_ms,
                    )
                )
            else:
                ov = next(o for o in reqs if o.overlay_id == row.element_id)
                ov_out.append(
                    OverlayResult(
                        overlay_id=ov.overlay_id,
                        kind=ov.kind,
                        start_ms=ov.start_ms,
                        end_ms=ov.end_ms,
                        template_asset_id=row.asset,
                        source_type=st.value,
                        licence_id=lic.licence_id,
                        ledger_entry_ids=(entry.ledger_entry_id,),
                        usage_kind="TEMPLATE",
                    )
                )
        return _Timeline(tuple(ov_out), tuple(fonts), tuple(els), tuple(rows), scope.job_id)

    # -- assembly ------------------------------------------------------------------------------

    def _assemble(
        self,
        ctx: TenantContext,
        inp: SourcingInput,
        built: Sequence[_Built],
        tl: _Timeline,
        rows: Sequence[LedgerEntry],
        previous: SourcingOutput | None,
        script: Mapping[str, object],
    ) -> StageResult:
        script_sha256 = inp.script_ref.sha256
        results = tuple(b.result for b in built)
        unresolved = tuple(
            Unresolved(r.shot_id, r.unresolved_reason) for r in results if r.unresolved_reason
        )
        outcome = GateRouter.route(unresolved, inp.script_stage_id)
        ms: dict[VisualSourceTier, int] = dict.fromkeys(VisualSourceTier, 0)
        for r in results:
            if r.tier is not None:
                ms[r.tier] += r.end_ms - r.start_ms
        total = sum(ms.values())
        mix_total, shares = TierMixReporter.report(ms) if total > 0 else (0, {})
        by_tier = ByTier(
            **{
                t.value: TierShareEntry(
                    ms=ms[t], share_permille=shares[t.value].share_permille if shares else 0
                )
                for t in VisualSourceTier
            }
        )
        blobs: dict[str, str] = {}
        facts_refs: list[ChartFactsRef] = []
        ends: list[date] = []
        for b in built:
            if b.chart is not None and b.chart.lag is not None and b.chart.lag.data_end_date:
                ends.append(b.chart.lag.data_end_date)
            if b.chart is not None and b.chart.facts.emit_document and b.result.chart is not None:
                ci = b.result.chart
                doc = ChartFactsDocument(
                    chart_id=ci.chart_id,
                    instrument=ci.instrument or "UNKNOWN",
                    dataset_asset_id=ci.dataset_asset_id or "",
                    dataset_sha256=ci.dataset_sha256 or "",
                    data_start_date=ci.data_start_date or "",
                    data_end_date=ci.data_end_date or "",
                    facts=tuple(
                        ChartFact(fact_id=f.fact_id, statement=f.statement)
                        for f in b.chart.facts.facts
                    ),
                )
                raw = json.dumps(doc.to_doc(), sort_keys=True, separators=(",", ":")).encode()
                sha = hashlib.sha256(raw).hexdigest()
                uri = self._put(ctx, f"chart_facts/{sha}.json", raw)
                blobs[f"chart_facts:{ci.chart_id}"] = uri
                facts_refs.append(
                    ChartFactsRef(
                        chart_id=ci.chart_id,
                        document_uri=uri,
                        document_sha256=sha,
                        fact_count=len(doc.facts),
                    )
                )
        if previous is not None:
            have = {f.chart_id for f in facts_refs}
            carried = {
                r.chart.chart_id for b in built if b.chart is None for r in [b.result] if r.chart
            }
            facts_refs.extend(f for f in previous.chart_facts if f.chart_id in carried - have)
        lag_days = self._s.price_data_lag_days
        publish = EarliestPublishDate.compute(ends, lag_days)
        ledger_rows = len(
            {
                i
                for r in results
                for i in (
                    *r.ledger_entry_ids,
                    *(x for rs in r.reveal_stills for x in rs.ledger_entry_ids),
                )
            }
        )
        warns = [
            LicenceWarning(code=w.value, shot_id=r.shot_id, licence_id=r.licence_id)
            for r in results
            for w in r.warnings
            if w in (SourcingWarning.LICENCE_EXPIRING, SourcingWarning.NO_INDEMNIFICATION)
        ]
        payload = SourcingOutput(
            iteration=inp.iteration,
            gate_verdict=outcome.gate_verdict or "FAILED",
            shots=results,
            overlays=tl.overlays,
            fonts=tl.fonts,
            music_beds=(),
            chart_facts=tuple(facts_refs),
            tier_mix=TierMix(total_visual_ms=mix_total, by_tier=by_tier),
            ai_broll=AiBroll(clips=0, total_ms=0, cost_micros=0, currency=self._s.currency),
            cost_summary=CostSummary(
                llm_micros=0,
                stock_micros=0,
                ai_video_micros=0,
                ai_still_micros=0,
                currency=self._s.currency,
                figure_kind="ESTIMATE",
            ),
            licence_summary=LicenceSummary(
                ledger_rows_written=ledger_rows,
                overlay_rows=len(tl.overlays),
                font_rows=len(tl.fonts),
                music_rows=0,
                warnings=tuple(warns),
            ),
            reuse_summary=ReuseSummary(
                reused_exact=sum(1 for r in results if r.reuse),
                reused_near_duplicate=0,
                new_assets=sum(1 for r in results if r.asset_id and not r.reuse),
                near_duplicate_flags=0,
            ),
            earliest_compliant_publish_date=publish.isoformat() if publish else None,
            unresolved_shot_ids=tuple(u.shot_id for u in unresolved),
            provenance=Provenance(
                prompts=(),
                rule_pack_versions=(),
                adapters=(),
                config_sha256=hashlib.sha256(self._s.model_dump_json().encode()).hexdigest(),
                lag_days=lag_days,
                shot_plan_sha256=inp.shot_plan_ref.sha256,
                script_sha256=script_sha256,
            ),
            refusals=(),
        )
        vr = self._validation(ctx, results, tl, outcome, ms, total, rows, payload, built)
        status, error = outcome.task_status, outcome.error_code
        if error is None and any(v.blocking and not v.gate and v.verdict is _FAIL for v in vr):
            status, error = "FAILED", QualityRepeatedFailureError.code
        return StageResult(
            payload, tuple(vr), status, error, outcome.gate_verdict, blobs, unresolved
        )

    def _validation(
        self,
        ctx: TenantContext,
        results: Sequence[ShotResult],
        tl: _Timeline,
        outcome: GateOutcome,
        ms: Mapping[VisualSourceTier, int],
        total: int,
        rows: Sequence[LedgerEntry],
        payload: SourcingOutput,
        built: Sequence[_Built],
    ) -> list[ValidationResult]:
        """Every row is measured here; a measurement that cannot be made is SKIPPED (never PASS)."""
        sourced = [r for r in results if r.asset_id]
        vr: list[ValidationResult] = []

        def add(cid: str, ok: bool | None, msg: str, *, warn: bool = False) -> None:
            if ok is None:
                vr.append(_vr(cid, _SKIP, False, msg))
            elif ok:
                vr.append(_vr(cid, _PASS, True, msg))
            else:
                vr.append(_vr(cid, _WARN if warn else _FAIL, True, msg))

        for cid in (
            "a08.pre.tenant",
            "a08.pre.refs",
            "a08.pre.shot_plan",
            "a08.pre.config",
            "a08.pre.licence_rows",
            "a08.pre.batch_size",
        ):
            add(cid, self._pre.get(cid, False), "recorded when the precondition step ran")
        add("a08.pre.budget", None, "no paid or LLM effect is wired in this stage")
        g = outcome.gate_result
        if g is not None:
            vr.append(
                _vr(
                    GATE_CHECK_ID,
                    _PASS if g.verdict == "PASS" else _FAIL,
                    True,
                    "no unresolved shot" if g.verdict == "PASS" else "unresolved shots remain",
                    gate=True,
                    remedy=g.remedy_stage_id,
                )
            )
        # coverage: exactly one covering ledger row per sourced shot and per reveal still
        job = tl.job_id
        cover_rows = [
            CoverRow(
                e.entry.asset_id,
                e.entry.used_from_ms,
                e.entry.used_to_ms,
                e.entry.job_id,
                e.entry.render_id,
            )
            for e in rows
        ]
        els = [CoverElement(r.shot_id, r.asset_id or "", r.start_ms, r.end_ms) for r in sourced]
        els += [
            CoverElement(f"{r.shot_id}:rs{x.k}", x.asset_id, x.start_ms, x.end_ms)
            for r in sourced
            for x in r.reveal_stills
        ]
        cov = CoverageVerifier.verify(els, cover_rows, job_id=job)
        add(
            "a08.cov.licence_row_per_shot",
            cov.passed,
            f"gaps={list(cov.gaps)} duplicates={list(cov.duplicates)}",
        )
        ov_els = tuple(e for e in tl.elements if not e.element.startswith("font:"))
        font_els = tuple(e for e in tl.elements if e.element.startswith("font:"))
        ov_cov = CoverageVerifier.verify(ov_els, cover_rows, job_id=job)
        font_cov = CoverageVerifier.verify(font_els, cover_rows, job_id=job)
        add("a08.cov.overlay_rows", ov_cov.passed, f"{len(ov_els)} overlays checked")
        add("a08.cov.font_rows", font_cov.passed, f"{len(font_els)} fonts checked")
        exact = {(r.asset, r.from_ms, r.to_ms) for r in cover_rows}
        interval_ok = all(
            (e.asset, e.start_ms, e.end_ms) in exact
            for e in (*(x for x in els if ":rs" not in x.element), *tl.elements)
        )
        add("a08.cov.interval_match", interval_ok, "shot, overlay and font row intervals match")
        allowed = {s.shot_id: s for s in self._plan_shots}
        missing = [
            r.shot_id
            for r in results
            if [
                t
                for t in TierCascade.missing_skip_reasons(r.tier, [_skip(x) for x in r.skips])
                # a chart is served by tier C only: C is the attempt, never a skipped tier
                if not (
                    r.intent_kind is ShotIntentKind.CHART and t is VisualSourceTier.C_CODE_MOTION
                )
            ]
        ]
        add("a08.hier.skip_reasons_recorded", not missing, f"missing for {missing}")
        order_bad = [
            r.shot_id
            for r in sourced
            if r.shot_id in allowed
            and r.tier is not None
            and r.tier not in allowed[r.shot_id].allowed_tiers
        ]
        add("a08.hier.tier_order", not order_bad, f"violations: {order_bad}")
        charts = [r.chart for r in results if r.chart]
        real = [c for c in charts if c.data_kind is ChartDataKind.REAL_HISTORICAL]
        add(
            "a08.chart.data_age",
            None if not real else all(c.data_age_vs_lag == "OLDER_THAN_LAG" for c in real),
            "real charts older than the lag",
        )
        add(
            "a08.chart.annotations",
            None if not charts else all(b.chart_checked for b in built if b.chart is not None),
            "annotations validated before rendering (rejection aborts the task)",
        )
        add(
            "a08.chart.provenance",
            None
            if not charts
            else all(
                c.spec_sha256
                and c.case_asset_id
                and c.template_version >= 1
                and (
                    c.data_kind is ChartDataKind.SCHEMATIC
                    or (c.dataset_sha256 and c.dataset_asset_id)
                )
                for c in charts
            ),
            "dataset hash, case, spec hash and template version recorded",
        )
        facts_ids = {f.chart_id for f in payload.chart_facts}
        add(
            "a08.chart.facts",
            None if not charts else {c.chart_id for c in real} == facts_ids,
            "one facts document per real chart, none for schematic",
        )
        add(
            "a08.lic.guard",
            None if not self._guards else all(g.usable for g in self._guards),
            f"{len(self._guards)} guard checks",
        )
        add("a08.lic.no_preview", None, "no stock path is wired in this stage")
        add("a08.lic.third_party", None, "no platform-held licence is used in this stage")
        expiring = [w for w in payload.licence_summary.warnings if w.code == "LICENCE_EXPIRING"]
        add("a08.lic.expiry_window", not expiring, f"{len(expiring)} expiring", warn=True)
        add("a08.ai.budget", None, "no AI asset in this stage")
        add("a08.ai.no_real_person", not any(r.disclosure.depicts_real_person for r in results),
            "no result depicts a real person")  # fmt: skip
        add("a08.ai.disclosure_flags", None, "no AI asset in this stage")
        share = (
            TierShareGuard.allows(
                e_ms_planned=ms[VisualSourceTier.E_AI_STILL],
                new_e_ms=0,
                total_visual_ms=total,
                limit=self._s.tier_e_max_share,
            )
            if total
            else None
        )
        add("a08.tier.share_e", None if share is None else share.allowed, "tier E share")
        add("a08.tier.mix_report", total > 0 or not sourced, "tier mix computed")
        low = []
        for r in sourced:
            floor = self._s.min_resolution.get(r.aspect_ratio)
            if (
                floor
                and r.media
                and (r.media.width_px < floor.width_px or r.media.height_px < floor.height_px)
            ):
                low.append(r.shot_id)
        add("a08.asset.resolution", None if not sourced else not low, f"below floor: {low}")
        footage = [r for r in sourced if r.tier is VisualSourceTier.A_OWNER_REAL and r.media]
        short = [
            r.shot_id
            for r in footage
            if r.media
            and r.media.duration_ms is not None
            and r.media.duration_ms < (r.end_ms - r.start_ms)
        ]
        add("a08.asset.duration_cover", None if not footage else not short, f"short: {short}")
        add("a08.asset.crop", None if not sourced else all(
            r.media is None or r.media.crop.mode.value == "NONE" for r in sourced),
            "only uncropped assets are produced")  # fmt: skip
        add(
            "a08.asset.fingerprint",
            None if not sourced else all(r.fingerprints is not None for r in sourced),
            "fingerprints present",
        )
        reused = [r for r in results if r.reuse]
        add("a08.reuse.channel_permission", None if not reused else True,
            "reuse passed ReuseEngine (status, expiry, channel)")  # fmt: skip
        add("a08.reuse.report", True, "reuse counts written")
        add("a08.cost.within_budget", None, "no paid effect is wired in this stage")
        ref_ok = all(
            self._blobs.head(ctx, BlobUri(f.document_uri)).sha256 == f.document_sha256
            for f in payload.chart_facts
        )
        add("a08.output.refs", None if not payload.chart_facts else ref_ok, "facts blobs exist")
        uris = [r.asset_uri for r in results if r.asset_uri] + [
            x.asset_uri for r in results for x in r.reveal_stills
        ]
        scope_ok = all(
            u.startswith(f"amw-blob://{ctx.org_id}/") or u.startswith("amw-blob://platform/")
            for u in uris
        )
        add("a08.tenant.output_scope", scope_ok, "every uri belongs to the org")
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


def _require_intake(rec: AssetRecord) -> None:
    """Fail closed (R20, Q22): chart data is read only if it entered through the registrar from
    the owner-approved class as an owner-made document."""
    a = rec.asset
    if (
        a.kind is not AssetKind.DOCUMENT
        or a.source_type is not LicenceSourceType.OWNER_MADE
        or a.attributes.get("source_path_class") != APPROVED_SOURCE_CLASS
    ):
        raise InputInvalidError(
            "chart data did not come through the approved intake class",
            details={"asset_id": rec.asset_id},
        )


def _skip(entry: SkipEntry) -> Skip:
    return Skip(entry.tier, entry.reason)


def _days(n: int) -> timedelta:
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
        chart_id=shot.chart_id,
        data_kind=case.data_kind,
        instrument=case.instrument,
        timeframe=case.timeframe,
        data_start_date=b.start_date.isoformat() if b.start_date else None,
        data_end_date=b.end_date.isoformat() if b.end_date else None,
        data_age_vs_lag=lag.data_age_vs_lag if lag else None,
        earliest_compliant_publish_date=lag.earliest_publish_date.isoformat()
        if lag and lag.earliest_publish_date
        else None,
        dataset_asset_id=src.dataset_asset_id if real else None,
        dataset_sha256=b.spec.dataset_sha256 if real else None,
        case_asset_id=b.case.asset_id,
        spec_sha256=b.spec_sha256,
        template_id=b.spec.template_id[:64],
        template_version=b.spec.template_version,
        bars_count=b.bars_count,
        annotation_count=len(case.annotations),
        method_content=case.method_content,
    )


def _chart_requests(script: Mapping[str, object]) -> list[ChartRequest]:
    out: list[ChartRequest] = []
    raw = script.get("chart_requests", [])
    for r in raw if isinstance(raw, list) else []:
        out.append(
            ChartRequest(
                r["chart_id"],
                ChartDataKind(r["chart_kind"]),
                r.get("instrument"),
                r["timeframe"],
                tuple(r.get("indicators", ())),
                r["pattern_concept_id"],
                r["outcome_shown"],
            )
        )
    return out


def _allowlists(script: Mapping[str, object]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    raw = script.get("scenes", [])
    for sc in raw if isinstance(raw, list) else []:
        out[sc["scene_id"]] = [str(t) for t in sc.get("on_screen_text", [])]
    return out


_REJECTED = (
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
    InputInvalidError,
    TenantMismatchError,
    CrossTenantRefError,
    TenantInactiveError,
    MissingDependencyError,
)


def check_ctx(task: TaskInput, ctx: ExecContext) -> None:
    """The context and the Task Input must name the same org, job and task (19.1 layer 1)."""
    if (
        str(ctx.org_id) != task.org_id
        or str(ctx.job_id) != task.job_id
        or str(ctx.task_id) != task.task_id
    ):
        raise TenantMismatchError("execution context does not match the Task Input")


def zero_usage(currency: str) -> ResourceUsage:
    """3A runs no paid call here; ``cpu_ms`` and ``peak_rss_bytes`` are the worker's to measure."""
    return ResourceUsage(
        cpu_ms=0,
        peak_rss_bytes=0,
        tokens_in=0,
        tokens_out=0,
        tokens_cached_in=0,
        llm_calls=0,
        provider_calls=0,
        cost_estimate_micros=0,
        currency=currency,
        cost_entry_ids=(),
    )


def error_output(
    exc: AmwError,
    *,
    task: TaskInput,
    clock: Clock,
    started_ms: int,
    attempt_no: int,
    validated: bool,
) -> TaskOutput:
    """``REJECTED`` for an input never accepted, ``SUSPENDED`` for a budget wait, else ``FAILED``
    (blueprint 18); retryable infrastructure errors propagate to the worker, which owns retry."""
    suspended = isinstance(exc, BudgetExhaustedError)
    rejected = isinstance(exc, _REJECTED) and not validated
    status = (
        OutputStatus.SUSPENDED
        if suspended
        else OutputStatus.REJECTED
        if rejected
        else OutputStatus.FAILED
    )
    now = clock.now()
    error = error_object_from_exception(
        exc,
        actor=AGENT_ID,
        attempt_no=0 if rejected else attempt_no,
        occurred_at=now,
        correlation_id=task.correlation_id,
    )
    if suspended:
        action = NextAction(
            type=NextActionType.WAIT,
            wait_reason=exc.spec.wait_reason,
            escalation_level=None,
            reason=exc.code,
        )
    else:
        action = NextAction(
            type=NextActionType.RETRY if exc.retryable else NextActionType.STOP,
            wait_reason=None,
            escalation_level=None,
            reason=exc.code,
        )
    return TaskOutput(
        status=status,
        payload=None,
        output_refs=(),
        quality_score=None,
        confidence=None,
        validation_results=(),
        duration=max(0, clock.monotonic_ms() - started_ms),
        resource_usage=zero_usage(task.resource_budget.currency),
        error=error,
        next_action=action,
        downstream_agent=None,
        timestamp=now,
    )
