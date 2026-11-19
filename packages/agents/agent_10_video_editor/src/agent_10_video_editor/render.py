"""``agent_10.render``: resumable, content-addressed, checkpointed FFmpeg render (section 4.1).

Flow: tenant scope -> upstream gate -> heavy-work guard (armed self-drain timer) -> timeline
compile -> segment plan -> resume verification -> per-segment encode (guard before each, atomic
content-addressed store, checkpoint) -> mux -> probe -> register. A drain, a closed guard or the
self-drain timer ends the run with ``SUSPENDED`` (``CHECKPOINTED / DRAIN``); nothing is killed
while a final blob is being written (atomic put); a running FFmpeg process is stopped only when it
cannot finish before ``act_by``, its scratch ``.part`` is discarded.
"""

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from agent_10_video_editor.audit import record as audit_record
from agent_10_video_editor.canonical import canonical_json, sha256_hex
from agent_10_video_editor.checkpointing import CheckpointIO
from agent_10_video_editor.config import Placement
from agent_10_video_editor.contracts import (
    BlobRef,
    BlobRefSized,
    ColourOut,
    EncoderOut,
    FpsOut,
    GopOut,
    GuardsOut,
    ProbeOut,
    ProvenanceOut,
    QualityMetricOut,
    RateControlOut,
    RenderInput,
    RenderOutput,
    SegmentsOut,
)
from agent_10_video_editor.deps import StageDeps
from agent_10_video_editor.errors import MeasurementUnavailable, config_invalid, input_invalid
from agent_10_video_editor.ffmpeg import (
    ArgvBuilder,
    RunLimits,
    SegmentCommand,
    ffmpeg_build_id,
)
from agent_10_video_editor.frames import FrameQuantiser
from agent_10_video_editor.guard import (
    DrainSignal,
    GuardReason,
    HeavyTaskGuard,
)
from agent_10_video_editor.inputs import (
    AssetManifest,
    AssetRecord,
    AudioMaster,
    NarrationTimeline,
    ScriptStrings,
    ShotPlan,
)
from agent_10_video_editor.media import ProbeService, StopRequested, run_checked
from agent_10_video_editor.observability import LogContext, emit, labels
from agent_10_video_editor.ports import RenderRow
from agent_10_video_editor.probe import PacketParser, ProbeResult, SsimParser, X264SeiParser
from agent_10_video_editor.qc.checks import (
    a10_q_colour_tags,
    a10_q_gop_settings,
    sei_mismatches,
    x264_expected,
)
from agent_10_video_editor.qc.result import CheckResult, passed, skipped
from agent_10_video_editor.scope import ScratchDir, TenantScope, one_ref_per_schema
from agent_10_video_editor.segments import (
    BlobFacts,
    RenderState,
    ResumeVerifier,
    Segment,
    SegmentKey,
    SegmentRecord,
    plan_segments,
    segments_index,
    slice_for,
    target_frames_of,
)
from agent_10_video_editor.taskio import (
    ACTOR,
    build_output,
    continue_action,
    drain_action,
    ffmpeg_cost_entry,
    output_ref,
    to_validation_result,
    usage,
    validate_budget,
)
from agent_10_video_editor.timeline import (
    FontCoverage,
    TextBinder,
    Timeline,
    TimelineCompiler,
    TimelineHasher,
    UpstreamGate,
)
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import (
    CheckVerdict,
    OutputRefKind,
    OutputStatus,
    RenderKind,
    RenderStatus,
)
from amw_core.errors import (
    AmwError,
    CorruptedOutputError,
    DeadlineExceededError,
    IdempotencyConflictError,
    LockConflictError,
    RenderCrashError,
    SchemaInvalidError,
)
from amw_core.ids import (
    RENDER,
    ActorRef,
    IdempotencyKey,
    IdempotencyScope,
    TaskId,
    make_idempotency_key,
)
from amw_core.interfaces.idempotency_store import BeginAction
from amw_core.interfaces.tenancy_context import TenantContext

RENDER_SCHEMAS = (
    "agent_09.shot_plan.output",
    "agent_08.asset_sourcing.output",
    "agent_07.audio_master.output",
    "agent_07.voice_synthesis.output",
    "agent_05.script_document",
)
_PRESET_ASPECT = {"yt_master_1080p": "16:9", "yt_master_1440p": "16:9", "shorts_9x16": "9:16"}
_SEGMENT_STEP = "render.seg_"


@dataclass(frozen=True, slots=True)
class LoadedInputs:
    plan: ShotPlan
    manifest: AssetManifest
    audio: AudioMaster
    narration: NarrationTimeline
    script: ScriptStrings
    script_sha256: str


def load_inputs(task_input: TaskInput, scope: TenantScope) -> LoadedInputs:
    """Read every upstream blob (SHA-256 verified on read) into typed models (F-02)."""
    refs = one_ref_per_schema(task_input, RENDER_SCHEMAS)

    def blob(schema: str) -> bytes:
        uri, sha = refs[schema]
        return scope.read_bytes(uri, sha)

    try:
        return LoadedInputs(
            plan=ShotPlan.model_validate_json(blob("agent_09.shot_plan.output")),
            manifest=AssetManifest.model_validate_json(blob("agent_08.asset_sourcing.output")),
            audio=AudioMaster.model_validate_json(blob("agent_07.audio_master.output")),
            narration=NarrationTimeline.model_validate_json(
                blob("agent_07.voice_synthesis.output")
            ),
            script=ScriptStrings.model_validate_json(blob("agent_05.script_document")),
            script_sha256=refs["agent_05.script_document"][1],
        )
    except ValidationError as exc:
        raise SchemaInvalidError("upstream document failed its schema") from exc


def parse_render_input(task_input: TaskInput) -> RenderInput:
    """Payload schema plus the 7.4 rules that need no storage."""
    validate_budget(task_input)
    if task_input.payload.data is None:
        raise input_invalid("PAYLOAD_NOT_INLINE")
    try:
        payload = RenderInput.model_validate(task_input.payload.data)
    except ValidationError as exc:
        raise SchemaInvalidError("render input failed its schema") from exc
    if _PRESET_ASPECT[payload.preset_key] != payload.aspect_ratio:
        raise input_invalid("PRESET_ASPECT_MISMATCH")
    return payload


def _tenant_context(task_input: TaskInput) -> TenantContext:
    from amw_core.ids import OrgId

    return TenantContext(
        org_id=OrgId(task_input.org_id),
        actor=ActorRef(ACTOR),
        correlation_id=None,
    )


VmafStatus = Literal["LIBVMAF_NOT_IN_BUILD", "LIBVMAF_IN_BUILD_NOT_USED"]
_SSIM_Q = Decimal("0.000001")


def quality_metric(
    records: Iterable[SegmentRecord], total_frames: int, vmaf_status: VmafStatus
) -> QualityMetricOut:
    """Frame-weighted mean of the per-segment SSIM ``All`` values (the mean over all frames up
    to the filter's 6-decimal rounding, as ``All`` is a per-frame mean) and the lowest segment."""
    measured = [(Decimal(r.ssim_all), r.ssim_frames) for r in records if r.ssim_all is not None]
    frames = sum(n for _, n in measured)
    if frames == 0:
        mean = low = None
    else:
        weighted = sum((v * n for v, n in measured), Decimal(0)) / frames
        mean = str(weighted.quantize(_SSIM_Q, rounding=ROUND_HALF_UP))
        low = str(min(v for v, _ in measured).quantize(_SSIM_Q, rounding=ROUND_HALF_UP))
    return QualityMetricOut(
        metric="SSIM",
        reference="FFV1_LOSSLESS_SEGMENT",
        ssim_all=mean,
        ssim_min_segment=low,
        frames_measured=frames,
        frames_total=total_frames,
        vmaf_status=vmaf_status,
    )


def _progress(done_frames: int, total_frames: int) -> Decimal:
    return (Decimal(done_frames) / Decimal(total_frames)).quantize(Decimal("0.001"))


class RenderStage:
    """Typed implementation of task type ``agent_10.render`` (``s10_render``)."""

    def __init__(self, deps: StageDeps) -> None:
        self._d = deps

    # -- public --------------------------------------------------------------------------------

    def run(
        self, task_input: TaskInput, attempt_id: str, envelope_org: str | None = None
    ) -> TaskOutput:
        """``envelope_org``: organisation of the received envelope (compared with the input)."""
        run = _RenderRun(self._d, task_input, attempt_id, envelope_org)
        try:
            return run.execute()
        finally:
            run.close()


class _RenderRun:
    def __init__(
        self,
        deps: StageDeps,
        task_input: TaskInput,
        attempt_id: str,
        envelope_org: str | None = None,
    ) -> None:
        self.envelope_org = envelope_org
        self.d = deps
        self.ti = task_input
        self.attempt_id = attempt_id
        self.ctx = _tenant_context(task_input)
        self.scope = TenantScope(self.ctx, deps.storage)
        self.signal = DrainSignal()
        self.guard = HeavyTaskGuard(deps.cfg.guard, deps.admission, self.signal, deps.timers)
        self.scratch = ScratchDir(deps.scratch_root, task_input.org_id, task_input.task_id)
        self.argv = ArgvBuilder(deps.cfg.render, deps.ffmpeg_bin, deps.ffprobe_bin)
        self.started_ms = deps.clock.monotonic_ms()
        self.ckpt = CheckpointIO(
            scope=self.scope,
            tenancy=deps.tenancy,
            store=deps.checkpoints,
            clock=deps.clock,
            context=self.ctx,
            job_id=task_input.job_id,
            task_id=task_input.task_id,
            attempt_id=attempt_id,
        )
        self.log = LogContext(
            task_input.org_id,
            task_input.job_id,
            task_input.task_id,
            attempt_id,
            task_input.correlation_id,
        )
        self.warnings: list[str] = []
        self._scopes: dict[str, str] = {}
        self.encoded = 0
        self.reused = 0
        self.resumed = False
        self._audio_bps = 0
        self._vmaf_status: VmafStatus = "LIBVMAF_NOT_IN_BUILD"
        self._settings_sha256: str | None = None

    def close(self) -> None:
        self.guard.disarm()
        self.scratch.clean()

    # -- orchestration -----------------------------------------------------------------------

    def execute(self) -> TaskOutput:
        d, ti = self.d, self.ti
        self._note("render.start")
        with d.tenancy.transaction(self.ctx) as tx:
            audit_record(
                d.audit, tx, d.clock, action="render.started", target_kind="task",
                target_id=ti.task_id, job_id=ti.job_id, correlation_id=ti.correlation_id,
                details={"attempt_id": self.attempt_id},
            )  # fmt: skip
        if self.envelope_org is not None:
            TenantScope.assert_consistent(self.envelope_org, ti)
        else:
            TenantScope.assert_refs_owned(ti)
        self._note("render.tenant_ok")
        payload = parse_render_input(ti)
        loaded = load_inputs(ti, self.scope)
        UpstreamGate.check_models(
            plan=loaded.plan,
            manifest=loaded.manifest,
            audio=loaded.audio,
            narration=loaded.narration,
            script_sha256=loaded.script_sha256,
            verified_script_sha256=payload.verified_script_sha256,
            aspect_ratio=payload.aspect_ratio,
        )
        self._note("render.upstream_ok")
        if loaded.plan.language != payload.language or (
            loaded.narration.language not in (None, payload.language)
        ):
            raise input_invalid("LANGUAGE_MISMATCH")
        if payload.preset_key != d.cfg.render.preset_key:
            raise input_invalid("PRESET_CONFIG_MISMATCH")
        if payload.music_bed is not None and not d.cfg.qc.music_enabled:
            raise input_invalid("MUSIC_BED_DISABLED")
        self._audio_bps = loaded.audio.codec_profile.bitrate_bps
        self.guard.arm()  # fails closed without a calendar
        work = self.scratch.open()
        probe = ProbeService(d.runner, self.argv, work)
        version = d.runner.run(self.argv.version(), cwd=work, limits=RunLimits())
        build_id = ffmpeg_build_id(version.stdout)
        listing = d.runner.run(self.argv.filters(), cwd=work, limits=RunLimits())
        self._vmaf_status = (
            "LIBVMAF_IN_BUILD_NOT_USED"
            if re.search(r"^\s*\S+\s+libvmaf\s", listing.stdout, flags=re.M)
            else "LIBVMAF_NOT_IN_BUILD"
        )

        restored = self.ckpt.latest(RenderState, "render.")
        state = restored[0] if restored else None
        self.resumed = state is not None
        if state is None:
            render_id = str(RENDER.new())
            state = RenderState(
                render_id=render_id,
                final_uri=self.scope.uri("jobs", f"{ti.job_id}/renders/{render_id}.mp4"),
            )
            self.ckpt.write("render.gated", state)

        assets = self._asset_records(loaded)
        timeline = TimelineCompiler.compile(
            loaded.plan, loaded.manifest, assets, loaded.audio, d.cfg, payload.aspect_ratio
        )
        timeline_sha = TimelineHasher.timeline_sha256(timeline)
        if state.timeline_sha256 not in (None, timeline_sha):
            raise input_invalid("PLAN_CHANGED")
        self._bind_text(timeline, loaded, assets)
        timeline_blob = self.scope.put_bytes(
            self.scope.uri("jobs", f"{ti.job_id}/renders/timelines/{timeline_sha}.json"),
            canonical_json(timeline.canonical()),
        )
        state = state.model_copy(
            update={"timeline_sha256": timeline_sha, "timeline_uri": timeline_blob.uri}
        )
        self._note(
            "render.timeline", timeline_sha256=timeline_sha, total_frames=timeline.total_frames
        )
        existing = self._existing_render(timeline_sha, payload.preset_key)
        if existing is not None:
            return self._replay_output(state, existing, timeline, timeline_sha, build_id, probe)
        self.ckpt.write("render.timeline", state)

        target = target_frames_of(
            d.cfg.render.segment_target_ms, timeline.fps.num, timeline.fps.den
        )
        segments = plan_segments(timeline, target)
        plans = [self._plan_segment(timeline, s, build_id) for s in segments]
        if state.args_sha256 is None:
            state = state.model_copy(
                update={
                    "gop": dict(plans[0].command.gop),
                    "args_sha256": sha256_hex(
                        canonical_json([p.command.args_sha256 for p in plans])
                    ),
                }
            )
        self._note("render.segment_plan", segments=len(segments), target_frames=target)
        resume = ResumeVerifier.verify(
            [(s, p.key, p.uri) for s, p in zip(segments, plans, strict=True)],
            state,
            lambda uri: self._facts(uri, work),
            lambda uri: self._probe_frames(uri, probe, work),
        )
        records: dict[int, SegmentRecord] = {r.ordinal: r for r in resume.reusable}
        for adopted in resume.adopted:
            state = state.with_segment(adopted)
            self.ckpt.write(
                f"{_SEGMENT_STEP}{adopted.ordinal}",
                state,
                [self._effect_key(adopted.key)],
                _progress(adopted.frames, timeline.total_frames),
            )
        self.reused = len(resume.reusable)
        if self.resumed:
            self._note("render.resume", reused=self.reused, to_encode=len(resume.to_encode))
        for _ in resume.reusable:
            self._count("a10_segments_total", outcome="reused")
        state = state.model_copy(update={"segments": {**state.segments, **records}})
        for ordinal in resume.to_encode:
            segment, plan = segments[ordinal], plans[ordinal]
            est = self._estimate_ms(segment.frames, timeline)
            verdict = self.guard.check(est)
            self._guard_note(verdict.allowed, verdict.reason)
            if not verdict.allowed:
                return self._suspended(state, verdict.reason, timeline, records, plans)
            try:
                record = self._encode_segment(segment, plan, work, probe, est)
            except StopRequested:
                return self._suspended(state, GuardReason.MARKET_HOURS, timeline, records, plans)
            records[ordinal] = record
            state = state.with_segment(record).model_copy(
                update={
                    "market_hours_checks": self.guard.market_hours_checks,
                    "night_window_checks": self.guard.night_window_checks,
                }
            )
            done = sum(r.frames for r in records.values())
            self.ckpt.write(
                f"{_SEGMENT_STEP}{ordinal}",
                state,
                [self._effect_key(plan.key)],
                _progress(done, timeline.total_frames),
            )
            self.encoded += 1
            self._count("a10_segments_total", outcome="encoded")
            self._note("render.segment_done", ordinal=ordinal, key=plan.key)

        mux_est = self._estimate_ms(min(timeline.total_frames, target), timeline)
        verdict = self.guard.check(mux_est)
        self._guard_note(verdict.allowed, verdict.reason)
        if not verdict.allowed:
            return self._suspended(state, verdict.reason, timeline, records, plans)
        try:
            final_info, final_probe, packet_count = self._mux(
                segments_index(records), loaded, timeline, work, probe, state, mux_est
            )
        except StopRequested:
            return self._suspended(state, GuardReason.MARKET_HOURS, timeline, records, plans)
        self._note("render.mux", size_bytes=final_info.size_bytes)
        self.ckpt.write("render.mux", state)
        row = self._register(state, timeline, timeline_sha, payload, final_info, final_probe)
        state = state.model_copy(update={"registered": True})
        self.ckpt.write("render.registered", state, [self._master_key(timeline_sha)])
        self._note("render.registered", render_id=row.render_id, content_sha256=row.content_sha256)
        return self._output(
            row,
            timeline,
            timeline_sha,
            state,
            build_id,
            final_probe,
            packet_count,
            drained=False,
            plans=plans,
            segments_total=len(segments),
        )

    # -- helpers -----------------------------------------------------------------------------

    def _note(self, event: str, **fields: int | bool | str | None) -> None:
        emit(event, self.log, **fields)

    def _count(self, name: str, **extra: str) -> None:
        if self.d.metrics is not None:
            self.d.metrics.count(name, labels(self.ti.org_id, **extra))

    def _guard_note(self, allowed: bool, reason: GuardReason | None) -> None:
        if not allowed:
            with self.d.tenancy.transaction(self.ctx) as tx:
                audit_record(
                    self.d.audit, tx, self.d.clock, action="render.guard_refused",
                    target_kind="task", target_id=self.ti.task_id, job_id=self.ti.job_id,
                    correlation_id=self.ti.correlation_id,
                    details={"reason": str(reason) if reason else "SELF_DRAIN"},
                )  # fmt: skip
        self._note("render.guard", allowed=allowed, reason=str(reason) if reason else None)
        self._count(
            "a10_guard_checks_total",
            task="render",
            result="allowed" if allowed else "denied",
            reason=str(reason) if reason else "",
        )

    def _asset_records(self, loaded: LoadedInputs) -> dict[str, AssetRecord]:
        ids = {o.template_asset_id for o in loaded.manifest.overlays}
        ids |= {s.asset_id for s in loaded.manifest.shots if s.asset_id}
        ids |= {f.asset_id for f in loaded.manifest.fonts}
        with self.d.tenancy.transaction(self.ctx) as tx:
            return dict(self.d.assets.lookup(tx, sorted(ids)))

    def _bind_text(
        self, timeline: Timeline, loaded: LoadedInputs, assets: dict[str, AssetRecord]
    ) -> None:
        """F-09, F-10: every on-screen text is a script string by SHA-256 and the brand font
        covers every code point (fail closed when text exists and no font reader is wired)."""
        bound = TextBinder.bind(timeline.overlays, loaded.script)
        if not bound:
            return
        reader = self.d.font_reader
        fonts = [assets[f.asset_id] for f in loaded.manifest.fonts if f.asset_id in assets]
        if reader is None or not fonts:
            raise config_invalid("FONT_COVERAGE_UNAVAILABLE")
        # Brand font first, then the fallback fonts of the manifest: a code point is covered when
        # any listed font has it (per-glyph fallback; owner decision WS-06). Each font is read
        # by its recorded SHA-256, so only registered, hash-checked bytes are consulted.
        covered: set[int] = set()
        for font in fonts:
            covered |= reader(self.scope.read_bytes(font.uri, font.sha256))
        FontCoverage.check(covered, list(bound.values()))

    def _existing_render(self, timeline_sha: str, preset_key: str) -> RenderRow | None:
        with self.d.tenancy.transaction(self.ctx) as tx:
            return self.d.renders.find_master(tx, self.ti.job_id, timeline_sha, preset_key)

    def _effect_key(self, segment_key: str) -> str:
        key = str(
            make_idempotency_key(
                self.ti.org_id, IdempotencyScope.RENDER_SEGMENT, [self.ti.job_id, segment_key]
            )
        )
        self._scopes[key] = IdempotencyScope.RENDER_SEGMENT.value
        return key

    def _idem_begin(self, key: str, request_sha256: str) -> BeginAction:
        """03 section 9.1 rule 3: ``begin`` in its own committed transaction before the effect."""
        with self.d.tenancy.transaction(self.ctx) as tx:
            decision = self.d.idempotency.begin(
                tx, IdempotencyKey(key), self._scope_of(key), request_sha256,
                TaskId(self.ti.task_id), self.d.clock.now(), self.d.cfg.render.effect_lock_ms,
            )  # fmt: skip
        return decision.action

    def _idem_complete(self, key: str, result_ref: str) -> None:
        with self.d.tenancy.transaction(self.ctx) as tx:
            self.d.idempotency.complete(tx, IdempotencyKey(key), result_ref, self.d.clock.now())

    def _idem_fail(self, key: str) -> None:
        with self.d.tenancy.transaction(self.ctx) as tx:
            self.d.idempotency.fail(tx, IdempotencyKey(key), self.d.clock.now())

    def _scope_of(self, key: str) -> str:
        return self._scopes[key]

    def _master_key(self, timeline_sha: str) -> str:
        key = str(
            make_idempotency_key(
                self.ti.org_id,
                IdempotencyScope.RENDER_MASTER,
                [self.ti.job_id, timeline_sha, self.d.cfg.render.preset_key],
            )
        )
        self._scopes[key] = IdempotencyScope.RENDER_MASTER.value
        return key

    def _estimate_ms(self, frames: int, timeline: Timeline) -> int:
        output_ms = FrameQuantiser.frames_to_ms(frames, timeline.fps.num, timeline.fps.den)
        eta = self.d.cfg.render.eta_ms_per_output_s
        if eta is None:
            if self.d.admission.placement() is Placement.VPS:
                raise config_invalid("ETA_NOT_SET")
            return output_ms
        return math.ceil(output_ms * eta / 1000)

    # -- segments ----------------------------------------------------------------------------

    @dataclass(frozen=True, slots=True)
    class _Plan:
        key: str
        uri: str
        command: SegmentCommand

    def _plan_segment(
        self, timeline: Timeline, segment: Segment, build_id: str
    ) -> _RenderRun._Plan:
        sl = slice_for(timeline, segment)
        command = self.argv.segment_command(sl)
        self.warnings.extend(command.warnings)
        key = SegmentKey.compute(sl.slice_sha256, sl.asset_sha256s(), command.args_sha256, build_id)
        uri = self.scope.uri("jobs", f"{self.ti.job_id}/renders/segments/{key}.mp4")
        return _RenderRun._Plan(key, uri, command)

    def _facts(self, uri: str, work: Path) -> BlobFacts:
        """Verifying head: a blob is only 'present' when its stream matches its recorded hash."""
        info = self.scope.head(uri)
        if info is None:
            return BlobFacts(False, None, None)
        try:
            digest = sha256_hex(self.scope.read_bytes(uri, info.sha256))
        except CorruptedOutputError:
            return BlobFacts(False, None, None)
        return BlobFacts(digest == info.sha256, info.sha256, info.size_bytes)

    def _probe_frames(self, uri: str, probe: ProbeService, work: Path) -> int | None:
        info = self.scope.head(uri)
        if info is None:
            return None
        target = work / "resume_check.mp4"
        try:
            self.scope.read_to(uri, info.sha256, target)
            return probe.frame_count(target.name)
        except CorruptedOutputError, MeasurementUnavailable:
            return None
        finally:
            target.unlink(missing_ok=True)

    def _free_uri(self, plan: _RenderRun._Plan) -> str:
        """A corrupt blob at the content-addressed path cannot be overwritten (write-once)."""
        uri, n = plan.uri, 0
        while self.scope.head(uri) is not None:
            n += 1
            uri = plan.uri.replace(".mp4", f".r{n}.mp4")
        return uri

    def _encode_segment(
        self,
        segment: Segment,
        plan: _RenderRun._Plan,
        work: Path,
        probe: ProbeService,
        est_ms: int,
    ) -> SegmentRecord:
        """Scope ``render.segment``: the effect key is begun before and completed after the put."""
        key = self._effect_key(plan.key)
        action = self._idem_begin(key, plan.key)
        if action is BeginAction.IN_FLIGHT:
            raise LockConflictError("another attempt holds this segment")
        try:
            record = self._encode_segment_inner(segment, plan, work, probe, est_ms)
        except BaseException:
            if action is not BeginAction.RETURN_STORED:
                self._idem_fail(key)
            raise
        if action is not BeginAction.RETURN_STORED:
            self._idem_complete(key, record.uri)
        return record

    def _encode_segment_inner(
        self,
        segment: Segment,
        plan: _RenderRun._Plan,
        work: Path,
        probe: ProbeService,
        est_ms: int,
    ) -> SegmentRecord:
        cmd = plan.command
        for staged in cmd.inputs:
            self.scope.read_to(staged.uri, staged.sha256, work / staged.name)
        self._check_sources_long_enough(cmd, probe)
        part = work / cmd.output_name
        part.unlink(missing_ok=True)

        def stop() -> bool:
            drain = self.signal.drain_requested or self.d.admission.drain_flag()
            return self.signal.hard_stop_requested or (
                drain and self.guard.estimate_overruns(est_ms)
            )

        limits = RunLimits(threads=self.d.cfg.render.threads)
        reference = work / cmd.reference_name
        try:  # the FFV1 reference is scratch only: deleted on every path (ADR-014)
            try:
                run_checked(self.d.runner, list(cmd.argv), cwd=work, limits=limits, stop=stop)
            except AmwError as exc:
                part.unlink(missing_ok=True)
                if isinstance(exc, RenderCrashError):
                    self._raise_unreadable_asset(cmd, probe)
                raise
            except StopRequested:
                part.unlink(missing_ok=True)
                raise
            try:
                self._verify_segment(part, segment, probe)
                ssim_all, ssim_frames = self._ssim(part, reference, segment, limits)
            except MeasurementUnavailable, RenderCrashError:
                part.unlink(missing_ok=True)
                raise
        finally:
            reference.unlink(missing_ok=True)
        info = self.scope.put_file(self._free_uri(plan), part)
        part.unlink(missing_ok=True)
        for staged in cmd.inputs:
            (work / staged.name).unlink(missing_ok=True)
        return SegmentRecord(
            ordinal=segment.ordinal,
            key=plan.key,
            uri=info.uri,
            sha256=info.sha256,
            size_bytes=info.size_bytes,
            frames=segment.frames,
            ssim_all=ssim_all,
            ssim_frames=ssim_frames,
        )

    def _ssim(
        self, part: Path, reference: Path, segment: Segment, limits: RunLimits
    ) -> tuple[str | None, int]:
        """SSIM of one segment and the number of frame pairs it covers. A pair count that is
        not the number of sampled frames is reported as not measured (never a wrong value)."""
        every = self.d.cfg.render.quality_sample_every
        result = run_checked(
            self.d.runner,
            self.argv.ssim(part.name, reference.name, every),
            cwd=part.parent,
            limits=limits,
        )
        pairs = sum(1 for line in result.stdout.splitlines() if line.startswith("n:"))
        expected = -(-segment.frames // every)
        if pairs != expected:
            self.warnings.append(f"SSIM_PAIR_COUNT:{segment.ordinal}:{pairs}/{expected}")
            return None, 0
        return SsimParser.parse(result.stderr), pairs

    def _check_sources_long_enough(self, cmd: SegmentCommand, probe: ProbeService) -> None:
        """A moving source shorter than the shot would be frozen by ``tpad=clone``: refuse it."""
        cfg = self.d.cfg.render
        one_frame_ms = FrameQuantiser.frames_to_ms(1, cfg.fps_num, cfg.fps_den)
        for name, shot_id, needs_ms in cmd.video_needs:
            if probe.full(name).duration_ms + one_frame_ms < needs_ms:
                raise input_invalid(f"SOURCE_TOO_SHORT:{shot_id}")

    def _raise_unreadable_asset(self, cmd: SegmentCommand, probe: ProbeService) -> None:
        for staged in cmd.inputs:
            if not probe.readable(staged.name):
                raise input_invalid(f"ASSET_UNREADABLE:{staged.sha256[:12]}")

    def _verify_segment(self, part: Path, segment: Segment, probe: ProbeService) -> None:
        """Frame count, CFR, first frame IDR and colour tags (section 18: verification failure
        is ``RESOURCE.RENDER_CRASH``)."""
        cfg = self.d.cfg.render
        frames = probe.frame_count(part.name)
        if frames != segment.frames or not probe.first_frame_is_idr(part.name):
            raise RenderCrashError(
                "segment verification failed", details={"ordinal": segment.ordinal}
            )
        full = probe.full(part.name)
        from fractions import Fraction

        if (
            full.video.r_frame_rate != full.video.avg_frame_rate
            or full.video.r_frame_rate != Fraction(cfg.fps_num, cfg.fps_den)
        ):
            raise RenderCrashError("segment is not constant frame rate")
        if (
            a10_q_colour_tags(probed=full.video.colour, configured=cfg.colour.model_dump()).verdict
            is CheckVerdict.FAIL
        ):
            raise RenderCrashError("segment colour tags differ from configuration")

    # -- mux and register ---------------------------------------------------------------------

    def _mux(
        self,
        records: list[SegmentRecord],
        loaded: LoadedInputs,
        timeline: Timeline,
        work: Path,
        probe: ProbeService,
        state: RenderState,
        est_ms: int,
    ) -> tuple[Any, ProbeResult, int]:
        names: list[str] = []
        sei_hashes: list[str] = []
        enc = self.d.cfg.render.encode
        want = x264_expected(
            gop_frames=enc.gop_frames,
            bframes=enc.bframes,
            cabac=enc.cabac,
            target_bps=enc.target_bps,
            maxrate_bps=enc.maxrate_bps,
            bufsize_bps=enc.bufsize_bps,
        )
        for record in records:
            name = f"seg_{record.ordinal}.mp4"
            self.scope.read_to(record.uri, record.sha256, work / name)  # CorruptedOutput -> retry
            names.append(name)
            # every segment (encoded now, reused or adopted) carries the configured settings
            texts = X264SeiParser.texts_in_file(work / name)
            if len(texts) != 1 or sei_mismatches(X264SeiParser.parse_text(texts[0]), want):
                raise RenderCrashError(
                    "segment encoder settings differ", details={"ordinal": record.ordinal}
                )
            sei_hashes.append(sha256_hex(texts[0].encode()))
        self._settings_sha256 = sha256_hex(canonical_json(sei_hashes))
        self.scope.read_to(
            loaded.audio.master.master_uri, loaded.audio.master.sha256, work / "master.wav"
        )
        duration_ms = timeline.expected_render_duration_ms
        argv, listing = self.argv.mux_argv(
            names, "master.wav", loaded.audio.codec_profile, duration_ms
        )
        (work / "concat.txt").write_text(listing, encoding="utf-8")
        final = work / "final.part"
        final.unlink(missing_ok=True)
        try:
            run_checked(
                self.d.runner,
                argv,
                cwd=work,
                limits=RunLimits(threads=self.d.cfg.render.threads),
                stop=lambda: self.signal.hard_stop_requested,
            )
        except StopRequested:
            final.unlink(missing_ok=True)
            raise
        result = probe.full(final.name)
        packet_count = probe.packet_count(final.name)
        self._verify_final(result, timeline, loaded)
        info = self.scope.put_file(state.final_uri, final)
        final.unlink(missing_ok=True)
        return info, result, packet_count

    def _verify_final(self, result: ProbeResult, timeline: Timeline, loaded: LoadedInputs) -> None:
        cfg = self.d.cfg.render
        delta = abs(result.duration_ms * cfg.fps_num - timeline.total_frames * 1000 * cfg.fps_den)
        profile = loaded.audio.codec_profile
        audio = result.audio
        if (
            delta > 1000 * cfg.fps_den
            or audio is None
            or audio.sample_rate != profile.sample_rate_hz
            or audio.channels != profile.channels
        ):
            raise RenderCrashError("final file verification failed")
        if (
            a10_q_colour_tags(
                probed=result.video.colour, configured=cfg.colour.model_dump()
            ).verdict
            is CheckVerdict.FAIL
        ):
            raise RenderCrashError("final colour tags differ from configuration")

    def _register(
        self,
        state: RenderState,
        timeline: Timeline,
        timeline_sha: str,
        payload: RenderInput,
        info: Any,
        result: ProbeResult,
    ) -> RenderRow:
        width, height = self.d.cfg.render.geometry
        master_key = self._master_key(timeline_sha)
        action = self._idem_begin(master_key, info.sha256)  # same key, other content: conflict
        with self.d.tenancy.transaction(self.ctx) as tx:
            existing = self.d.renders.find_by_content(tx, info.sha256)
            if existing is not None:
                if existing.timeline_sha256 != timeline_sha:
                    raise IdempotencyConflictError("same content, different timeline")
                stored = existing  # replay: no second row and no second cost row
            else:
                stored = self.d.renders.insert(
                    tx,
                    self._row(state, timeline, timeline_sha, payload, info, result, width, height),
                )
                audit_record(
                    self.d.audit, tx, self.d.clock, action="render.completed",
                    target_kind="render", target_id=stored.render_id, job_id=self.ti.job_id,
                    correlation_id=self.ti.correlation_id,
                    details={
                        "content_sha256": stored.content_sha256,
                        "duration_ms": stored.duration_ms,
                    },
                )  # fmt: skip
                self.d.cost_ledger.record(
                    tx,
                    ffmpeg_cost_entry(
                        self.ti,
                        self.attempt_id,
                        task_type="agent_10.render",
                        occurred_at=self.d.clock.now(),
                        units_ms=self._render_ms(),
                    ),
                )
        if action is not BeginAction.RETURN_STORED:
            self._idem_complete(master_key, stored.storage_ref)
        return stored

    def _row(
        self, state: RenderState, timeline: Timeline, timeline_sha: str, payload: RenderInput,
        info: Any, result: ProbeResult, width: int, height: int,
    ) -> RenderRow:  # fmt: skip
        return RenderRow(
            render_id=state.render_id,
            job_id=self.ti.job_id,
            kind=str(RenderKind.MASTER),
            preset_key=payload.preset_key,
            version=1,
            timeline_sha256=timeline_sha,
            width_px=result.video.width or width,
            height_px=result.video.height or height,
            fps_num=timeline.fps.num,
            fps_den=timeline.fps.den,
            video_codec=result.video.codec_name,
            audio_codec=result.audio.codec_name if result.audio else "",
            video_bitrate_bps=result.video_bitrate_bps,
            audio_bitrate_bps=self._audio_bps,
            audio_sample_rate_hz=result.audio.sample_rate if result.audio else 0,
            duration_ms=result.duration_ms,
            size_bytes=info.size_bytes,
            storage_ref=info.uri,
            content_sha256=info.sha256,
            status=RenderStatus.COMPLETE,
            worker_id=self.d.worker_id,
        )

    def _render_ms(self) -> int:
        return max(self.d.clock.monotonic_ms() - self.started_ms, 0)

    # -- outputs -----------------------------------------------------------------------------

    def _suspended(
        self,
        state: RenderState,
        reason: GuardReason | None,
        timeline: Timeline,
        records: dict[int, SegmentRecord],
        plans: list[_RenderRun._Plan],
    ) -> TaskOutput:
        state = state.model_copy(
            update={
                "segments": {**state.segments, **records},
                "market_hours_checks": self.guard.market_hours_checks,
                "night_window_checks": self.guard.night_window_checks,
            }
        )
        done = sum(r.frames for r in records.values())
        self.ckpt.write("render.drain", state, progress=_progress(done, timeline.total_frames))
        self._note(
            "render.self_drain" if self.signal.self_drained else "render.drain", done_frames=done
        )
        text = f"CHECKPOINTED / DRAIN ({reason or 'SELF_DRAIN'})"
        return build_output(
            status=OutputStatus.SUSPENDED,
            schema="agent_10.render.output",
            data=None,
            refs=[],
            results=[],
            duration_ms=self._render_ms(),
            resource_usage=usage(self._render_ms(), self.ti.resource_budget.currency),
            next_action=drain_action(text),
            now=self.d.clock.now(),
        )

    def _process_results(
        self,
        timeline: Timeline,
        packet_count: int,
        probe: ProbeResult,
        gop: Mapping[str, object],
        segments_ok: bool,
        hash_ok: bool,
    ) -> list[CheckResult]:
        cfg = self.d.cfg.render
        results = [
            passed("a10.q.schema", gate=False),
            passed("a10.q.tenant", gate=False)
            if self.envelope_org is not None
            else skipped("a10.q.tenant", "ENVELOPE_ORG_NOT_SUPPLIED", gate=False),
            passed("a10.q.upstream", gate=False),
            CheckResult(
                "a10.q.timeline_frames",
                CheckVerdict.PASS if packet_count == timeline.total_frames else CheckVerdict.FAIL,
                True,
                gate=False,
                measured=packet_count,
                threshold=timeline.total_frames,
            ),
            CheckResult(
                "a10.q.segments_verified",
                CheckVerdict.PASS if segments_ok else CheckVerdict.FAIL,
                True,
                gate=False,
            ),
            passed("a10.q.no_provider_call", gate=False, measured=0, threshold=0),
            CheckResult(
                "a10.q.hash_chain",
                CheckVerdict.PASS if hash_ok else CheckVerdict.FAIL,
                True,
                gate=False,
            ),
            a10_q_colour_tags(probed=probe.video.colour, configured=cfg.colour.model_dump()),
            a10_q_gop_settings(recorded=gop, configured_gop_frames=cfg.effective_gop_frames),
        ]
        return results

    def _output(
        self,
        row: RenderRow,
        timeline: Timeline,
        timeline_sha: str,
        state: RenderState,
        build_id: str,
        probe: ProbeResult,
        packet_count: int,
        *,
        drained: bool,
        plans: list[_RenderRun._Plan],
        segments_total: int,
    ) -> TaskOutput:
        cfg = self.d.cfg.render
        gop = state.gop
        args_sha = state.args_sha256 or sha256_hex(b"")
        nominal = self._audio_bps or (probe.audio.bit_rate or 0 if probe.audio else 0)
        hash_ok = self._hash_ok(row)
        results = self._process_results(timeline, packet_count, probe, gop, True, hash_ok)
        output = RenderOutput(
            render_id=row.render_id,
            render_ref=BlobRefSized(
                uri=row.storage_ref, sha256=row.content_sha256, size_bytes=row.size_bytes
            ),
            timeline_ref=BlobRef(uri=state.timeline_uri or "", sha256=timeline_sha),
            fps=FpsOut(num=timeline.fps.num, den=timeline.fps.den),
            frame_count=timeline.total_frames,
            duration_ms=row.duration_ms,
            segments=SegmentsOut(
                planned=segments_total,
                encoded=self.encoded,
                reused=self.reused,
                resumed_from_checkpoint=self.resumed,
            ),
            encoder=EncoderOut(
                ffmpeg_build_id=build_id,
                video_encoder=cfg.video_encoder,
                args_sha256=args_sha,
                preset_key=cfg.preset_key,
                gop=GopOut(
                    gop_frames=int(gop.get("gop_frames", cfg.effective_gop_frames)),
                    closed_gop=bool(gop.get("closed_gop", True)),
                    idr_at_segment_start=bool(gop.get("idr_at_segment_start", True)),
                ),
                colour=ColourOut(**cfg.colour.model_dump()),
                audio_bitrate_nominal_bps=max(nominal, 1),
                rate_control=RateControlOut(**cfg.encode.recorded()),
                quality_metric=quality_metric(
                    state.segments.values(), timeline.total_frames, self._vmaf_status
                ),
                settings_sha256=self._settings_sha256,
            ),
            probe=ProbeOut(
                width_px=probe.video.width,
                height_px=probe.video.height,
                video_codec=probe.video.codec_name,
                audio_codec=probe.audio.codec_name if probe.audio else "",
                video_bitrate_bps=probe.video_bitrate_bps,
                audio_bitrate_avg_bps=(probe.audio.bit_rate or 0) if probe.audio else 0,
                audio_sample_rate_hz=probe.audio.sample_rate if probe.audio else 0,
                channels=probe.audio.channels if probe.audio else 0,
            ),
            render_ms=self._render_ms(),
            guards=GuardsOut(
                market_hours_checks=self.guard.market_hours_checks,
                night_window_checks=self.guard.night_window_checks,
                drained=drained,
            ),
            provenance=ProvenanceOut(
                config_keys_family="agent_10.*",
                ffmpeg_version_string_sha256=sha256_hex(build_id.encode()),
            ),
        )
        refs = [
            output_ref(
                row.storage_ref,
                OutputRefKind.VIDEO,
                row.content_sha256,
                row.size_bytes,
                "video/mp4",
            ),
            output_ref(
                state.timeline_uri or "", OutputRefKind.DATA, timeline_sha, 1, "application/json"
            ),
        ]
        failing = [r for r in results if r.verdict is CheckVerdict.FAIL]
        if failing:
            from amw_core.errors import IncompleteOutputError

            raise IncompleteOutputError(
                "process-integrity check failed", details={"checks": [r.check_id for r in failing]}
            )
        return build_output(
            status=OutputStatus.SUCCEEDED,
            schema="agent_10.render.output",
            data=output.model_dump(mode="json"),
            refs=refs,
            results=[to_validation_result(r) for r in results],
            duration_ms=self._render_ms(),
            resource_usage=usage(self._render_ms(), self.ti.resource_budget.currency),
            next_action=continue_action("render complete"),
            now=self.d.clock.now(),
        )

    def _hash_ok(self, row: RenderRow) -> bool:
        info = self.scope.head(row.storage_ref)
        return (
            info is not None
            and info.sha256 == row.content_sha256
            and info.size_bytes == row.size_bytes
        )

    def _replay_output(
        self,
        state: RenderState,
        row: RenderRow,
        timeline: Timeline,
        timeline_sha: str,
        build_id: str,
        probe_service: ProbeService,
    ) -> TaskOutput:
        """Replay of a completed render: no second row, no second final blob, no second cost row."""
        work = self.scratch.open()
        final = work / "replay.mp4"
        self.scope.read_to(row.storage_ref, row.content_sha256, final)
        result = probe_service.full(final.name)
        count = probe_service.packet_count(final.name)
        # the final blob is bound to the renders row by its SHA-256 (registered after the
        # per-segment settings checks of the original render)
        self._settings_sha256 = sha256_hex(
            canonical_json([sha256_hex(t.encode()) for t in X264SeiParser.texts_in_file(final)])
        )
        target = target_frames_of(
            self.d.cfg.render.segment_target_ms, timeline.fps.num, timeline.fps.den
        )
        segments = plan_segments(timeline, target)
        plans = [self._plan_segment(timeline, seg, build_id) for seg in segments]
        planned = len(segments)
        self.reused, self.encoded = planned, 0  # nothing is encoded again
        self._audio_bps = self._audio_bps or row.audio_bitrate_bps
        if state.args_sha256 is None:
            state = state.model_copy(
                update={
                    "gop": dict(plans[0].command.gop),
                    "args_sha256": sha256_hex(
                        canonical_json([p.command.args_sha256 for p in plans])
                    ),
                }
            )
        return self._output(
            row,
            timeline,
            timeline_sha,
            state,
            build_id,
            result,
            count,
            drained=False,
            plans=plans,
            segments_total=planned,
        )


__all__ = [
    "DeadlineExceededError",
    "PacketParser",
    "RenderStage",
    "load_inputs",
    "parse_render_input",
]
