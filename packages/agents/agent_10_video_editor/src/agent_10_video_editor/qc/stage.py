"""``agent_10.technical_qc``: blocking QC gate on the final MP4 (sections 4.2, 6.5, 8.3, 20).

The guard runs at task start and before every check group and evidence pass; the self-drain timer
stops a running pass at ``act_by`` (its ``.part`` output is scratch and discarded). A failed gate is
NOT a failed task: the task is ``SUCCEEDED`` with ``gate: true`` results and ``gate_verdict =
FAILED``. A missing or unparseable measurement is never ``PASS``: it raises and the task is retried.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from agent_10_video_editor.audit import record as audit_record
from agent_10_video_editor.canonical import canonical_json, sha256_hex
from agent_10_video_editor.checkpointing import CheckpointIO
from agent_10_video_editor.contracts import (
    BlobRef,
    CountsOut,
    EvidenceOut,
    FailureOut,
    MeasurementsOut,
    SelftestOut,
    TechnicalQcInput,
    TechnicalQcOutput,
    TierMixOut,
)
from agent_10_video_editor.deps import StageDeps
from agent_10_video_editor.errors import (
    MeasurementUnavailable,
    config_invalid,
    input_invalid,
    map_measurement_error,
    missing_dependency,
)
from agent_10_video_editor.ffmpeg import ArgvBuilder, RunLimits, ffmpeg_build_id
from agent_10_video_editor.frames import FrameQuantiser
from agent_10_video_editor.guard import DrainSignal, GuardReason, HeavyTaskGuard
from agent_10_video_editor.inputs import (
    AssetManifest,
    AudioMaster,
    NarrationTimeline,
    ScriptStrings,
    ShotPlan,
)
from agent_10_video_editor.media import ProbeService, StopRequested, run_checked
from agent_10_video_editor.observability import LogContext, emit, labels
from agent_10_video_editor.ports import LicenceSnapshot, QcRow
from agent_10_video_editor.probe import (
    AtomOrderChecker,
    BlackdetectParser,
    Ebur128Parser,
    FreezedetectParser,
    PacketParser,
    ProbeResult,
    SceneParser,
    SilencedetectParser,
    parse_stream_times,
)
from agent_10_video_editor.qc import checks as C  # noqa: N812
from agent_10_video_editor.qc.evidence import EvidenceWriter
from agent_10_video_editor.qc.gate import SHORTS_SKIPPED, GateAggregator, QcPlan, profile_check_ids
from agent_10_video_editor.qc.result import CheckResult, failed, passed, skipped
from agent_10_video_editor.qc.selftest import SelfTestRecord
from agent_10_video_editor.scope import ScratchDir, TenantScope, one_ref_per_schema
from agent_10_video_editor.subtitles import SrtParser, SrtValidator
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
from agent_10_video_editor.timeline import Timeline
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput
from amw_core.enums import (
    CheckKind,
    CheckVerdict,
    GateVerdict,
    OutputRefKind,
    OutputStatus,
    RenderStatus,
)
from amw_core.errors import (
    AgentCrashError,
    IncompleteOutputError,
    InputInvalidError,
    RenderCrashError,
    SchemaInvalidError,
)
from amw_core.ids import ActorRef
from amw_core.interfaces.tenancy_context import TenantContext

QC_SCHEMAS = (
    "agent_10.render.output",
    "agent_10.subtitles.output",
    "agent_10.timeline",
    "agent_09.shot_plan.output",
    "agent_08.asset_sourcing.output",
    "agent_07.audio_master.output",
    "agent_07.voice_synthesis.output",
    "agent_05.script_document",
)


class SelfTestProvider(Protocol):
    """Readiness-owned record of the QC self-test for a build ID (18 section 7.11)."""

    def record_for(self, build_id: str) -> SelfTestRecord: ...


@dataclass
class _Measured:
    probe: ProbeResult | None = None
    histogram: dict[str, int] = field(default_factory=dict)
    packet_count: int = 0
    moov_first: bool = False
    stream_times: dict[str, tuple[str, str]] = field(default_factory=dict)
    ebur: dict[str, float] = field(default_factory=dict)
    silences: list[tuple[int, int]] = field(default_factory=list)
    blacks: list[tuple[int, int]] = field(default_factory=list)
    freezes: list[tuple[int, int]] = field(default_factory=list)
    scenes: list[int] = field(default_factory=list)


def _spans_to_shots(
    timeline_shots: list[tuple[str, int, int]], runs: list[tuple[int, int]]
) -> tuple[str, ...]:
    return tuple(sid for sid, a, b in timeline_shots if any(r[0] < b and a < r[1] for r in runs))


class QcStage:
    """Typed implementation of task type ``agent_10.technical_qc`` (``s10_qc``)."""

    def __init__(self, deps: StageDeps, selftests: SelfTestProvider) -> None:
        self._d = deps
        self._selftests = selftests

    def run(
        self, task_input: TaskInput, attempt_id: str, envelope_org: str | None = None
    ) -> TaskOutput:
        """``envelope_org`` is the organisation of the Task Input envelope the worker received; when
        it is not supplied ``a10.q.tenant`` is reported ``SKIPPED`` (never a self-comparison)."""
        run = _QcRun(self._d, self._selftests, task_input, attempt_id, envelope_org)
        try:
            return run.execute()
        finally:
            run.guard.disarm()
            run.scratch.clean()


class _QcRun:
    def __init__(
        self,
        deps: StageDeps,
        selftests: SelfTestProvider,
        ti: TaskInput,
        attempt_id: str,
        envelope_org: str | None = None,
    ) -> None:
        self.d, self.ti, self.attempt_id, self.selftests = deps, ti, attempt_id, selftests
        self.envelope_org = envelope_org
        from amw_core.ids import OrgId

        self.ctx = TenantContext(org_id=OrgId(ti.org_id), actor=ActorRef(ACTOR))
        self.scope = TenantScope(self.ctx, deps.storage)
        self.signal = DrainSignal()
        self.guard = HeavyTaskGuard(deps.cfg.guard, deps.admission, self.signal, deps.timers)
        self.scratch = ScratchDir(deps.scratch_root, ti.org_id, ti.task_id)
        self.argv = ArgvBuilder(deps.cfg.render, deps.ffmpeg_bin, deps.ffprobe_bin)
        self.started = deps.clock.monotonic_ms()
        self.log = LogContext(ti.org_id, ti.job_id, ti.task_id, attempt_id, ti.correlation_id)
        self.ckpt = CheckpointIO(
            scope=self.scope,
            tenancy=deps.tenancy,
            store=deps.checkpoints,
            clock=deps.clock,
            context=self.ctx,
            job_id=ti.job_id,
            task_id=ti.task_id,
            attempt_id=attempt_id,
        )

    # -- helpers --------------------------------------------------------------------------------

    def _suspend(self, reason: GuardReason | None, group: str) -> TaskOutput:
        self.ckpt.write(f"{group}.drain", _QcState(group=group))
        return build_output(
            status=OutputStatus.SUSPENDED,
            schema="agent_10.technical_qc.output",
            data=None,
            refs=[],
            results=[],
            duration_ms=self._ms(),
            resource_usage=usage(self._ms(), self.ti.resource_budget.currency),
            next_action=drain_action(f"CHECKPOINTED / DRAIN ({reason or 'SELF_DRAIN'})"),
            now=self.d.clock.now(),
        )

    def _ms(self) -> int:
        return max(self.d.clock.monotonic_ms() - self.started, 0)

    def _est(self, frames: int, timeline: Timeline) -> int:
        output_ms = FrameQuantiser.frames_to_ms(frames, timeline.fps.num, timeline.fps.den)
        eta = self.d.cfg.render.eta_ms_per_output_s
        return output_ms if eta is None else -(-output_ms * eta // 1000)

    def _run(self, argv: list[str], work: Path) -> Any:
        return run_checked(
            self.d.runner,
            argv,
            cwd=work,
            limits=RunLimits(threads=self.d.cfg.render.threads),
            stop=lambda: self.signal.hard_stop_requested,
        )

    # -- the task ---------------------------------------------------------------------------------

    def execute(self) -> TaskOutput:
        d, ti, qcfg = self.d, self.ti, self.d.cfg.qc
        emit("qc.start", self.log)
        if self.envelope_org is not None:
            TenantScope.assert_consistent(self.envelope_org, ti)
        else:
            TenantScope.assert_refs_owned(ti)
        validate_budget(ti)
        if ti.payload.data is None:
            raise input_invalid("PAYLOAD_NOT_INLINE")
        try:
            payload = TechnicalQcInput.model_validate(ti.payload.data)
        except ValidationError as exc:
            raise SchemaInvalidError("technical_qc input failed its schema") from exc
        if payload.music_bed is not None and not qcfg.music_enabled:
            raise input_invalid("MUSIC_BED_DISABLED")
        if qcfg.single_pass:
            raise config_invalid(
                "CONFIG_KEY:agent_10.qc.single_pass"
            )  # not enabled before R-02 equality proof
        refs = one_ref_per_schema(ti, QC_SCHEMAS)
        render_out = _json(self.scope.read_bytes(*refs["agent_10.render.output"]))
        timeline = _timeline(self.scope.read_bytes(*refs["agent_10.timeline"]))
        plan = ShotPlan.model_validate_json(
            self.scope.read_bytes(*refs["agent_09.shot_plan.output"])
        )
        manifest = AssetManifest.model_validate_json(
            self.scope.read_bytes(*refs["agent_08.asset_sourcing.output"])
        )
        audio = AudioMaster.model_validate_json(
            self.scope.read_bytes(*refs["agent_07.audio_master.output"])
        )
        narration = NarrationTimeline.model_validate_json(
            self.scope.read_bytes(*refs["agent_07.voice_synthesis.output"])
        )
        script = ScriptStrings.model_validate_json(
            self.scope.read_bytes(*refs["agent_05.script_document"])
        )
        subs_out = _json(self.scope.read_bytes(*refs["agent_10.subtitles.output"]))
        with d.tenancy.transaction(self.ctx) as tx:
            row = d.renders.get(tx, payload.render_id)
        if row is None:
            raise missing_dependency(f"RENDER_NOT_FOUND:{payload.render_id}")
        render_ref = render_out["render_ref"]
        hash_ok = (
            payload.render_sha256 == render_ref["sha256"] == row.content_sha256
            and render_out["timeline_ref"]["sha256"] == refs["agent_10.timeline"][1]
        )
        if not hash_ok:
            raise IncompleteOutputError(
                "a10.q.hash_chain failed", details={"check": "a10.q.hash_chain"}
            )
        timeline_sha = render_out["timeline_ref"]["sha256"]
        if plan.language != script_language(subs_out, plan.language):
            raise input_invalid("LANGUAGE_MISMATCH")

        self.guard.arm()
        work = self.scratch.open()
        probe = ProbeService(d.runner, self.argv, work)
        version = d.runner.run(self.argv.version(), cwd=work, limits=RunLimits())
        build_id = ffmpeg_build_id(version.stdout)
        selftest = self.selftests.record_for(build_id)
        emit("selftest.result", self.log, passed=selftest.passed)
        if not selftest.passed:
            raise config_invalid("SELFTEST_FAILED")
        self.scope.read_to(row.storage_ref, row.content_sha256, work / "final.mp4")
        srt_entry = subs_out["srt"][0]
        self.scope.read_to(srt_entry["uri"], srt_entry["sha256"], work / "sub.srt")

        m = _Measured()
        results: list[CheckResult] = []
        spec = QcPlan.build(payload.qc_profile)
        groups = list(dict.fromkeys(s.group for s in spec))
        total_est = self._est(timeline.total_frames, timeline)
        try:
            for group in groups:
                est = total_est if group in ("qc.audio", "qc.video") else max(total_est // 10, 1000)
                verdict = self.guard.check(est)
                if not verdict.allowed:
                    return self._suspend(verdict.reason, group)
                try:
                    self._measure(group, m, work, probe, timeline, row.duration_ms)
                except MeasurementUnavailable as exc:
                    raise map_measurement_error(exc, process_died=False) from exc
                self.ckpt.write(group, _QcState(group=group))
                emit("qc.group_done", self.log, group=group)
            results = self._evaluate(
                payload, plan, manifest, audio, narration, script, timeline, row, m, subs_out, work
            )
            est = total_est
            verdict = self.guard.check(est)
            if not verdict.allowed:
                return self._suspend(verdict.reason, "qc.evidence")
            evidence = self._evidence(payload, row, timeline, timeline_sha, results, probe, work)
            emit("qc.evidence", self.log, frames=len(evidence.frames))
        except StopRequested:
            return self._suspend(GuardReason.MARKET_HOURS, "qc.interrupted")

        gate = GateAggregator.decide(
            [r for r in results if r.gate], profile_check_ids(payload.qc_profile)
        )
        counts = _counts(results)
        emit(
            "qc.gate", self.log, gate_verdict=str(gate.gate_verdict), failed=len(gate.failed_checks)
        )
        for r in results:
            emit("qc.check", self.log, check_id=r.check_id, verdict=str(r.verdict))
            if d.metrics is not None:
                d.metrics.count(
                    "a10_check_results_total",
                    labels(ti.org_id, check_id=r.check_id, verdict=str(r.verdict)),
                )
        if d.metrics is not None:
            d.metrics.count(
                "a10_gate_total",
                labels(
                    ti.org_id,
                    profile=payload.qc_profile,
                    gate_verdict=str(gate.gate_verdict),
                    remedy_stage_id=",".join(gate.remedy_stage_ids),
                ),
            )
        self._persist(payload, row, results, evidence)
        emit("qc.persisted", self.log, rows=len(results))
        cost_amount = self._cost(row.duration_ms)
        output = TechnicalQcOutput(
            gate_verdict=gate.gate_verdict.value,
            failures=tuple(
                self._failure(r)
                for r in results
                if r.gate and r.blocking and r.verdict is CheckVerdict.FAIL
            ),
            render_id=payload.render_id,
            render_sha256=payload.render_sha256,
            profile=payload.qc_profile,
            iteration=payload.iteration,
            counts=counts,
            measurements=_measurements(m, row, subs_out, timeline, audio),
            tier_mix=_tier_mix(timeline),
            evidence=EvidenceOut(
                manifest_ref=evidence.manifest,
                contact_sheet_ref=evidence.contact_sheet,
                sample_frames_ref=evidence.frames,
                loudness_series_ref=evidence.loudness_series,
                report_ref=evidence.report,
            ),
            selftest=SelftestOut(
                ffmpeg_build_id=build_id,
                selftest_ref=_selftest_ref(self.scope, ti.job_id, selftest),
                passed=selftest.passed,
            ),
        )
        refs_out = [
            output_ref(
                evidence.manifest.uri,
                OutputRefKind.DATA,
                evidence.manifest.sha256,
                1,
                "application/json",
            ),
            output_ref(
                evidence.contact_sheet.uri,
                OutputRefKind.IMAGE,
                evidence.contact_sheet.sha256,
                1,
                "image/png",
            ),
            output_ref(
                evidence.report.uri,
                OutputRefKind.REPORT,
                evidence.report.sha256,
                1,
                "application/json",
            ),
            *(
                output_ref(f.uri, OutputRefKind.IMAGE, f.sha256, 1, "image/png")
                for f in evidence.frames
            ),
        ]
        # computed, not asserted: the output model above validated, every ref hash matched (the read
        # path raises otherwise), the tenant check ran when the envelope org was supplied, and the
        # cost row recorded for this task carries the amount of the (zero) provider spend
        process = [
            passed("a10.q.schema", gate=False, measured=len(refs_out)),
            passed("a10.q.hash_chain", gate=False, measured=len(refs)),
            passed("a10.q.no_provider_call", gate=False, measured=cost_amount, threshold=0),
            passed("a10.q.tenant", gate=False)
            if self.envelope_org is not None
            else skipped("a10.q.tenant", "ENVELOPE_ORG_NOT_SUPPLIED", gate=False),
        ]
        failed_ids = [f.check_id for f in gate.failed_checks]
        action = continue_action(
            f"gate FAILED: {', '.join(failed_ids)}" if failed_ids else "gate PASSED"
        )
        return build_output(
            status=OutputStatus.SUCCEEDED,
            schema="agent_10.technical_qc.output",
            data=output.model_dump(mode="json", by_alias=True),
            refs=refs_out,
            results=[to_validation_result(r) for r in [*results, *process]],
            duration_ms=self._ms(),
            resource_usage=usage(self._ms(), ti.resource_budget.currency),
            next_action=action,
            now=d.clock.now(),
        )

    # -- measurement groups ---------------------------------------------------------------------

    def _measure(
        self,
        group: str,
        m: _Measured,
        work: Path,
        probe: ProbeService,
        timeline: Timeline,
        duration_ms: int,
    ) -> None:
        qc = self.d.cfg.qc
        if group == "qc.probe":
            m.probe = probe.full("final.mp4")
            csv = probe.packets_csv("final.mp4")
            m.histogram = PacketParser.histogram(csv)
            m.packet_count = PacketParser.count(csv)
            m.moov_first = AtomOrderChecker.moov_first((work / "final.mp4").read_bytes()[: 1 << 20])
            m.stream_times = parse_stream_times(probe.stream_times_csv("final.mp4"))
        elif group == "qc.audio":
            m.ebur = Ebur128Parser.parse(self._run(self.argv.ebur128("final.mp4"), work).stderr)
            m.silences = SilencedetectParser.parse(
                self._run(
                    self.argv.silencedetect("final.mp4", qc.silence_n_db, qc.silence_d_s), work
                ).stderr,
                duration_ms,
            )
        elif group == "qc.video":
            m.blacks = BlackdetectParser.parse(
                self._run(
                    self.argv.blackdetect(
                        "final.mp4", qc.black_d_s, qc.black_pic_th, qc.black_pix_th
                    ),
                    work,
                ).stderr
            )
            m.freezes = FreezedetectParser.parse(
                self._run(
                    self.argv.freezedetect("final.mp4", qc.freeze_n_db, qc.freeze_d_s), work
                ).stderr,
                duration_ms,
            )
            m.scenes = SceneParser.parse(
                self._run(self.argv.scene("final.mp4", qc.scene_threshold), work).stderr
            )

    # -- evaluation -----------------------------------------------------------------------------

    def _evaluate(
        self,
        payload: TechnicalQcInput,
        plan: ShotPlan,
        manifest: AssetManifest,
        audio: AudioMaster,
        narration: NarrationTimeline,
        script: ScriptStrings,
        timeline: Timeline,
        row: Any,
        m: _Measured,
        subs_out: dict[str, Any],
        work: Path,
    ) -> list[CheckResult]:
        cfg, qc = self.d.cfg.render, self.d.cfg.qc
        assert m.probe is not None  # noqa: S101 - set by the qc.probe group
        pr = m.probe
        total_ms = row.duration_ms
        shots_ms = [(s.shot_id, s.plan_start_ms, s.plan_end_ms) for s in timeline.shots]
        narration_end = (
            narration.end_ms
            if narration.end_ms is not None
            else max((s.end_ms for s in narration.segments), default=0)
        )
        end_screen_ms = (
            timeline.end_screen.plan_end_ms - timeline.end_screen.plan_start_ms
            if timeline.end_screen
            else 0
        )
        r: list[CheckResult] = []
        add = r.append
        add(
            C.qc_video_resolution(
                width=pr.video.width,
                height=pr.video.height,
                min_width=qc.min_width_px,
                min_height=qc.min_height_px,
                blocking=payload.qc_profile == "qc.long_form",
            )
        )
        add(
            C.qc_video_codec_profile(
                codec_name=pr.video.codec_name,
                profile=pr.video.profile,
                field_order=pr.video.field_order,
            )
        )
        add(C.qc_video_pix_fmt(pix_fmt=pr.video.pix_fmt))
        add(
            C.qc_video_bitrate(
                video_bitrate_bps=pr.video_bitrate_bps,
                min_bps=qc.video_bitrate_min_bps,
                max_bps=qc.video_bitrate_max_bps,
                floor_bps=qc.video_bitrate_floor_bps,
            )
        )
        add(
            C.CfrAnalyser.evaluate(
                interval_histogram_s=m.histogram,
                fps_num=cfg.fps_num,
                fps_den=cfg.fps_den,
                tolerance_s=qc.cfr_tolerance_s,
                r_frame_rate=pr.video.r_frame_rate,
                avg_frame_rate=pr.video.avg_frame_rate,
            )
        )
        add(
            C.qc_video_fps_matches_project(
                r_frame_rate=pr.video.r_frame_rate, fps_num=cfg.fps_num, fps_den=cfg.fps_den
            )
        )
        add(C.qc_container_faststart(moov_first=m.moov_first))
        a = pr.audio
        if a is None:
            raise MeasurementUnavailable(["audio_stream"])
        add(C.qc_audio_codec(codec_name=a.codec_name, profile=a.profile))
        add(C.qc_audio_sample_rate(sample_rate_hz=a.sample_rate, expected_hz=qc.sample_rate_hz))
        add(C.qc_audio_channels(channels=a.channels, expected=qc.channels))
        add(
            C.qc_audio_bitrate(
                nominal_bps=row.audio_bitrate_bps,
                measured_avg_bps=a.bit_rate or 0,
                min_bps=qc.audio_bitrate_min_bps,
            )
        )
        add(
            C.qc_audio_true_peak(
                true_peak_dbtp=m.ebur["true_peak_dbtp"],
                ceiling_dbtp=float(qc.true_peak_ceiling_dbtp),
            )
        )
        lufs_result = C.qc_audio_integrated_lufs(
            integrated_lufs=m.ebur["integrated_lufs"],
            target_lufs=float(qc.target_lufs),
            tolerance_lu=float(qc.lufs_tolerance_lu) if qc.lufs_tolerance_lu else None,
        )
        if m.ebur.get("silent"):
            # ebur128 reports Peak -inf: a fully silent track is a blocking FAIL (remedy s07_voice),
            # never a crash and never an unsourced WARN
            lufs_result = failed(
                "qc.audio.integrated_lufs",
                measured=m.ebur["integrated_lufs"],
                threshold=float(qc.target_lufs),
                unit="LUFS",
                message="AUDIO_SILENT",
            )
        add(lufs_result)
        add(C.qc_audio_lra_report(lra_lu=m.ebur["lra_lu"]))
        add(C.qc_audio_clipping(clipping_samples=audio.clipping_samples))
        add(
            C.qc_audio_music_bed_offset(music_lufs=None, narration_lufs=m.ebur["integrated_lufs"])
            if payload.music_bed is None
            else skipped("qc.audio.music_bed_offset", "MUSIC_MEASUREMENT_3B")
        )
        pauses = [(p.start_ms, p.end_ms) for p in plan.audio_plan.deliberate_pauses]
        add(
            C.qc_audio_silence_mix(
                runs_ms=m.silences,
                deliberate_pause_ms=pauses,
                total_ms=total_ms,
                max_ms=qc.silence_max_ms,
            )
        )
        add(C.qc_audio_speech_spans(spans_ms=None))
        add(
            C.qc_video_black_frames(
                detections_ms=m.blacks,
                deliberate_black_ms=[(i.start_ms, i.end_ms) for i in plan.deliberate_black],
                total_ms=total_ms,
                calibrated=qc.black_calibrated,
            )
        )
        add(
            C.qc_video_freeze(
                detections_ms=m.freezes,
                deliberate_hold_ms=[(h.start_ms, h.end_ms) for h in plan.deliberate_hold],
                total_ms=total_ms,
                calibrated=qc.freeze_calibrated,
            )
        )
        v_start, v_dur = m.stream_times["video"]
        a_start, a_dur = m.stream_times["audio"]
        add(
            C.qc_sync_av_container(
                start_video_s=v_start,
                start_audio_s=a_start,
                duration_video_s=v_dur,
                duration_audio_s=a_dur,
                frame_ms=FrameQuantiser.frames_to_ms(1, cfg.fps_num, cfg.fps_den),
                tol_start_ms=qc.sync_tol_start_ms,
                tol_dur_ms=qc.sync_tol_dur_ms,
            )
        )
        try:
            srt_cues = SrtParser.parse((work / "sub.srt").read_bytes())
        except InputInvalidError as exc:
            # a malformed stored SRT (BOM, CRLF, bad time line) is a gate FAIL (remedy s10_render)
            srt_cues = []
            srt_errors = [f"PARSE:{', '.join(exc.details.get('violations', ['SRT_UNPARSEABLE']))}"]
        else:
            srt_errors = SrtValidator.validate(srt_cues, total_ms)
            self._run(self.argv.srt_check("sub.srt"), work)
        add(C.qc_subtitles_format(errors=srt_errors))
        add(
            C.qc_subtitles_languages(
                present=[e["language"] for e in subs_out["srt"]], required=[plan.language]
            )
        )
        seg_dicts = [
            {"segment_id": s.segment_id, "start_ms": s.start_ms, "end_ms": s.end_ms}
            for s in narration.segments
        ]
        add(
            C.qc_subtitles_sync(
                segments=seg_dicts,
                cues=_cue_segments(srt_cues, seg_dicts),
                tol_sub_ms=qc.sub_tol_ms,
                calibrated=qc.sub_tol_ms is not None,
            )
        )
        add(
            C.qc_subtitles_accuracy(
                overlap_permille=_word_overlap_permille(
                    srt_cues, [seg.segment_id for seg in narration.segments], script
                )
            )
        )
        add(
            C.qc_duration_vs_script(
                actual_ms=total_ms,
                narration_end_ms=narration_end,
                end_screen_ms=end_screen_ms,
                tol_dur_ms=qc.duration_tol_ms,
            )
        )
        add(
            C.qc_duration_vs_timeline(
                actual_ms=total_ms,
                timeline_frames=timeline.total_frames,
                fps_num=cfg.fps_num,
                fps_den=cfg.fps_den,
            )
        )
        add(C.qc_duration_in_bounds(actual_ms=total_ms, targets_ms=qc.duration_targets_ms))
        r.extend(
            self._licence_and_visual(
                payload, plan, manifest, audio, timeline, script, row, shots_ms
            )
        )
        r.extend(self._edit(payload, plan, timeline, m, total_ms, pauses))
        # a10.q.timeline_frames: video packet count equals the compiled frame count
        r.append(
            CheckResult(
                "a10.q.timeline_frames",
                CheckVerdict.PASS if m.packet_count == timeline.total_frames else CheckVerdict.FAIL,
                True,
                gate=False,
                measured=m.packet_count,
                threshold=timeline.total_frames,
            )
        )
        out: list[CheckResult] = []
        for res in r:
            res = _with_shots(res, shots_ms, m)
            if payload.qc_profile == "qc.shorts" and res.check_id in SHORTS_SKIPPED:
                res = skipped(res.check_id, "SECTION_BASED_ITEM_NOT_IN_SHORTS")
            out.append(res)
        broken = [
            x
            for x in out
            if x.check_id == "a10.q.timeline_frames" and x.verdict is CheckVerdict.FAIL
        ]
        if broken:
            raise RenderCrashError(
                "frame count differs from the timeline", details={"measured": m.packet_count}
            )
        return [x for x in out if x.check_id != "a10.q.timeline_frames"]

    def _licence_and_visual(
        self,
        payload: TechnicalQcInput,
        plan: ShotPlan,
        manifest: AssetManifest,
        audio: AudioMaster,
        timeline: Timeline,
        script: ScriptStrings,
        row: Any,
        shots_ms: list[tuple[str, int, int]],
    ) -> list[CheckResult]:
        qc = self.d.cfg.qc
        elements: list[dict[str, Any]] = []
        for s in timeline.shots:
            elements.append(
                {
                    "element_id": s.shot_id,
                    "asset_id": s.asset_id,
                    "start_ms": s.plan_start_ms,
                    "end_ms": s.plan_end_ms,
                }
            )
            bounds = [s.plan_start_ms, *s.change_events_ms, s.plan_end_ms]
            elements.extend(
                {
                    "element_id": f"{s.shot_id}#{st.k}",
                    "asset_id": st.asset_id,
                    "start_ms": bounds[st.k],
                    "end_ms": bounds[st.k + 1],
                }
                for st in s.reveal_steps
            )
        elements.extend(
            {
                "element_id": o.overlay_id,
                "asset_id": o.template_asset_id,
                "start_ms": o.plan_start_ms,
                "end_ms": o.plan_end_ms,
            }
            for o in timeline.overlays
        )
        elements.append(
            {
                "element_id": "narration",
                "asset_id": timeline.audio.narration_asset_id,
                "start_ms": 0,
                "end_ms": timeline.audio.duration_ms,
            }
        )
        elements.extend(
            {
                "element_id": f"font:{f.asset_id}",
                "asset_id": f.asset_id,
                "start_ms": f.used_from_ms,
                "end_ms": f.used_to_ms,
            }
            for f in manifest.fonts
        )
        asset_ids = sorted({e["asset_id"] for e in elements if e["asset_id"]})
        with self.d.tenancy.transaction(self.ctx) as tx:
            snap: LicenceSnapshot = self.d.licences.snapshot(
                tx, self.ti.job_id, payload.render_id, asset_ids
            )
        out = [
            C.qc_licence_completeness(
                tenant=self.ti.org_id,
                render_id=payload.render_id,
                elements=elements,
                ledger=snap.ledger,
                licences=snap.licences,
                assets=snap.assets,
                destination=payload.destination,
            ),
            C.qc_licence_expiry_window(
                licences=[{"licence_id": k, **v} for k, v in snap.licences.items()],
                warning_window_days=qc.licence_expiry_warning_days,
            ),
            C.qc_watermark_provenance(stock_items=snap.stock_items),
            skipped("qc.watermark.visual", "CORNER_PATCH_NOT_COMPUTED_3A"),
        ]
        frames_by_tier = dict.fromkeys(
            ("A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO", "E_AI_STILL"), 0
        )
        for part in timeline.visual_parts():
            frames_by_tier[part.tier or "C_CODE_MOTION"] += part.frames
        ai_ms = sum(
            s.plan_end_ms - s.plan_start_ms for s in timeline.shots if s.tier == "D_AI_VIDEO"
        )
        out.append(
            C.qc_visual_tier_share_e(
                frames_by_tier=frames_by_tier, limit_ratio=qc.e_share_limit_ratio
            )
        )
        out.append(C.qc_visual_tier_mix_report(frames_by_tier=frames_by_tier))
        out.append(
            C.qc_visual_ai_video_budget(
                ai_video_ms=ai_ms, ai_video_limit_ms=plan.tier_budget.ai_video_limit_ms
            )
        )
        entries = {
            e.shot_id: e for e in manifest.shots if e.aspect_ratio == payload_aspect(timeline, plan)
        }
        items = []
        for s in timeline.shots:
            entry = entries.get(s.shot_id)
            if entry is None:
                continue
            record = entry.disclosure
            items.append(
                {
                    "element_id": s.shot_id,
                    "tier": s.tier,
                    # no record: the flags are unknown, so an AI asset is treated as realistic
                    # synthetic and the missing record FAILs (fail closed, YT-06/07)
                    "is_realistic_synthetic": True
                    if record is None
                    else record.is_realistic_synthetic,
                    "depicts_real_person": False if record is None else record.depicts_real_person,
                    "disclosure_recorded": record is not None,
                }
            )
        out.append(C.qc_visual_ai_disclosure_recorded(items=items))
        charts = [
            {"element_id": sid, "data_end_date": e.chart.data_end_date}
            for sid, e in entries.items()
            if e.chart is not None
        ]
        finance = self._is_finance_channel(charts)
        out.append(
            C.qc_visual_chart_data_age(
                charts=charts,
                lag_days=qc.price_data_lag_days,
                today=self.d.clock.now().date()
                if hasattr(self.d.clock.now(), "date")
                else date.today(),
                finance_channel=finance,
            )
        )
        out.append(C.qc_visual_no_synthetic_presenter(items=items, finance_channel=finance))
        return out

    def _is_finance_channel(self, charts: list[dict[str, Any]]) -> bool:
        """FIN-R9/R11 apply unless the channel is known to be non-finance (CCR-128, fail closed).

        A channel is finance when ``channels.category = 'finance'`` or ``rp.finance_sebi_in`` is
        among its active packs; an unreadable channel is finance; a chart in the manifest always
        makes the render subject to FIN-R9. No per-agent channel list exists.
        """
        if charts:
            return True
        channels = self.d.channels
        if channels is None or self.ti.channel_id is None:
            return True
        with self.d.tenancy.transaction(self.ctx) as tx:
            profile = channels.lookup(tx, str(self.ti.channel_id))
        return profile is None or profile.is_finance

    def _edit(
        self,
        payload: TechnicalQcInput,
        plan: ShotPlan,
        timeline: Timeline,
        m: _Measured,
        total_ms: int,
        pauses: list[tuple[int, int]],
    ) -> list[CheckResult]:
        qc = self.d.cfg.qc
        out: list[CheckResult] = []
        hook = plan.hook
        if hook is None:
            out.append(
                CheckResult(
                    "edit.hook.window",
                    CheckVerdict.FAIL,
                    True,
                    remedy_stage_id="s09_plan",
                    message="HOOK_MISSING",
                )
            )
            hook_end = 0
        else:
            out.append(
                C.edit_hook_window(
                    hook_end_ms=hook.end_ms,
                    first_payoff_ms=hook.first_payoff_ms,
                    window_ms=qc.hook_window_ms,
                )
            )
            hook_end = hook.end_ms
        out.append(
            C.edit_hook_no_brand_intro(
                overlays=[
                    {"overlay_id": o.overlay_id, "kind": o.kind, "start_ms": o.plan_start_ms}
                    for o in timeline.overlays
                ],
                hook_end_ms=hook_end,
            )
        )
        events = sorted(
            {s.start_ms for s in plan.shots} | {e for s in plan.shots for e in s.change_events_ms}
        )
        out.append(
            C.edit_visual_cadence(
                change_events_ms=events,
                explanatory_stretches_ms=_stretches(plan),
                max_gap_ms=qc.cadence_max_gap_ms,
                blocking=qc.cadence_blocking,
            )
        )
        out.append(
            C.edit_visual_cadence_render_crosscheck(
                timeline_events=len(events),
                scene_events=len(m.scenes),
                tolerance=qc.cadence_crosscheck_tolerance,
            )
        )
        interrupts = [s.start_ms for s in plan.shots if s.interrupt is not None]
        out.append(
            C.edit_interrupt_first_dropoff(
                interrupt_times_ms=interrupts, window_ms=qc.first_dropoff_window_ms
            )
        )
        out.append(
            C.edit_interrupt_midpoint(
                interrupt_times_ms=interrupts,
                total_ms=total_ms,
                half_window_ms=qc.midpoint_window_ms,
            )
        )
        out.append(
            C.edit_cuts_j_l(
                jl_count=sum(1 for s in plan.shots if s.jl_kind), min_count=qc.min_jl_cuts
            )
        )
        starts: list[int] = []
        seen: set[str] = set()
        for s in plan.shots:
            if s.section_id is not None and s.section_id not in seen:
                seen.add(s.section_id)
                starts.append(s.start_ms)
        out.append(
            C.edit_chapters(
                chapters_ms=[c.start_ms for c in plan.chapters],
                section_starts_ms=starts,
                tolerance_ms=1000,
            )
        )
        out.append(
            C.edit_end_screen(
                end_screen_ms=(timeline.end_screen.plan_end_ms - timeline.end_screen.plan_start_ms)
                if timeline.end_screen
                else 0,
                configured_ms=qc.end_screen_ms,
            )
        )
        out.append(
            C.edit_dead_air(
                runs_ms=m.silences,
                deliberate_pause_ms=pauses,
                total_ms=total_ms,
                max_ms=qc.silence_max_ms,
            )
        )
        return out

    # -- evidence, persistence, cost -------------------------------------------------------------

    def _evidence(
        self,
        payload: TechnicalQcInput,
        row: Any,
        timeline: Timeline,
        timeline_sha: str,
        results: list[CheckResult],
        probe: ProbeService,
        work: Path,
    ) -> Any:
        writer = EvidenceWriter(self.d.runner, self.argv, self.scope, self.d.cfg)
        frames = writer.extract_frames("final.mp4", timeline, row.duration_ms, work)
        sheet = writer.contact_sheet(len(frames), work)
        series = writer.loudness_series("final.mp4", work)
        base = f"{self.ti.job_id}/tasks/{self.ti.task_id}/attempts/{self.attempt_id}/artifacts"
        return writer.write(
            base=base,
            render_id=payload.render_id,
            render_sha256=payload.render_sha256,
            timeline=timeline,
            timeline_sha256=timeline_sha,
            frames=frames,
            sheet_name=sheet,
            series=series,
            results=results,
            work=work,
        )

    def _persist(
        self, payload: TechnicalQcInput, row: Any, results: list[CheckResult], evidence: Any
    ) -> None:
        rows = [
            QcRow(
                job_id=self.ti.job_id,
                render_id=payload.render_id,
                task_id=self.ti.task_id,
                check_id=r.check_id,
                kind=CheckKind.DETERMINISTIC,
                verdict=r.verdict,
                blocking=r.blocking,
                measured_num=float(r.measured)
                if isinstance(r.measured, int | float) and not isinstance(r.measured, bool)
                else None,
                measured_text=r.measured if isinstance(r.measured, str) else None,
                threshold_num=float(r.threshold)
                if isinstance(r.threshold, int | float) and not isinstance(r.threshold, bool)
                else None,
                threshold_text=r.threshold if isinstance(r.threshold, str) else None,
                unit=r.unit,
                rule_id=r.details.get("rule_id"),
                evidence_ref=evidence.report.uri,
                message=r.message[:2000],
            )
            for r in results
        ]
        gate_failed = any(r.gate and r.blocking and r.verdict is CheckVerdict.FAIL for r in results)
        lufs = next((r.measured for r in results if r.check_id == "qc.audio.integrated_lufs"), None)
        peak = next((r.measured for r in results if r.check_id == "qc.audio.true_peak"), None)
        with self.d.tenancy.transaction(self.ctx) as tx:
            self.d.qc_results.insert_many(tx, rows)
            audit_record(
                self.d.audit, tx, self.d.clock,
                action="qc.gate_failed" if gate_failed else "qc.completed",
                target_kind="render", target_id=payload.render_id, job_id=self.ti.job_id,
                correlation_id=self.ti.correlation_id,
                details={"profile": payload.qc_profile, "checks": len(rows)},
            )  # fmt: skip
            self.d.renders.set_qc(
                tx,
                payload.render_id,
                RenderStatus.QC_FAILED if gate_failed else RenderStatus.QC_PASSED,
                float(lufs) if isinstance(lufs, int | float) else None,
                float(peak) if isinstance(peak, int | float) else None,
            )

    def _cost(self, duration_ms: int) -> int:
        with self.d.tenancy.transaction(self.ctx) as tx:
            row = self.d.cost_ledger.record(
                tx,
                ffmpeg_cost_entry(
                    self.ti,
                    self.attempt_id,
                    task_type="agent_10.technical_qc",
                    occurred_at=self.d.clock.now(),
                    units_ms=self._ms(),
                ),
            )
        return row.entry.amount_micros

    @staticmethod
    def _failure(r: CheckResult) -> FailureOut:
        return FailureOut(
            check_id=r.check_id,
            shot_ids=r.shot_ids,
            measured=r.measured if not isinstance(r.measured, bool) else str(r.measured),
            threshold=r.threshold if not isinstance(r.threshold, bool) else str(r.threshold),
            unit=r.unit or "",
            remedy_stage=r.remedy_stage_id,
            message=(r.message or f"{r.check_id} failed")[:240],
        )


from pydantic import BaseModel, ConfigDict  # noqa: E402


class _QcState(BaseModel):
    model_config = ConfigDict(frozen=True)

    group: str


def _json(data: bytes) -> dict[str, Any]:
    import json

    value = json.loads(data)
    if not isinstance(value, dict):
        raise SchemaInvalidError("expected a JSON object")
    return value


def _timeline(data: bytes) -> Timeline:
    return Timeline.model_validate_json(data)


def _words(text: str) -> list[str]:
    return text.casefold().split()


def _word_overlap_permille(cues: list[Any], segment_ids: list[str], script: ScriptStrings) -> int:
    """Deterministic word overlap of the stored SRT text with the script (18 section 7.6).

    ``2 * |common words| / (|SRT words| + |script words|)`` over multisets, in permille: 1000 means
    the same words, anything lower (changed, added or dropped words) is reported as a WARN.
    """
    from collections import Counter

    expected = Counter(w for sid in segment_ids for w in _words(script.segments.get(sid, "")))
    actual = Counter(w for cue in cues for w in _words(cue.text))
    total = sum(expected.values()) + sum(actual.values())
    if total == 0:
        return 1000
    return 2000 * sum((expected & actual).values()) // total


def script_language(subs_out: dict[str, Any], default: str) -> str:
    entries = subs_out.get("srt") or []
    return str(entries[0]["language"]) if entries else default


def payload_aspect(timeline: Timeline, plan: ShotPlan) -> str:
    return plan.aspect_ratio


def _with_shots(
    res: CheckResult, shots_ms: list[tuple[str, int, int]], m: _Measured
) -> CheckResult:
    if res.shot_ids or not res.offending:
        return res
    runs = [tuple(o) for o in res.offending if isinstance(o, tuple) and len(o) == 2]
    if not runs:
        return res
    from dataclasses import replace

    return replace(res, shot_ids=_spans_to_shots(shots_ms, runs))


def _stretches(plan: ShotPlan) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s in plan.shots:
        if not s.explanatory:
            continue
        if out and out[-1][1] == s.start_ms:
            out[-1] = (out[-1][0], s.end_ms)
        else:
            out.append((s.start_ms, s.end_ms))
    return out


def _cue_segments(cues: list[Any], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach each cue to the narration segment that contains its midpoint."""
    out: list[dict[str, Any]] = []
    for cue in cues:
        mid = (cue.start_ms + cue.end_ms) // 2
        owner = next((s["segment_id"] for s in segments if s["start_ms"] <= mid <= s["end_ms"]), "")
        out.append({"segment_id": owner, "start_ms": cue.start_ms, "end_ms": cue.end_ms})
    return out


def _counts(results: list[CheckResult]) -> CountsOut:
    def n(v: CheckVerdict) -> int:
        return sum(1 for r in results if r.verdict is v)

    return CountsOut(
        pass_=n(CheckVerdict.PASS),
        fail=n(CheckVerdict.FAIL),
        warn=n(CheckVerdict.WARN),
        skipped=n(CheckVerdict.SKIPPED),
    )


def _measurements(
    m: _Measured, row: Any, subs_out: dict[str, Any], timeline: Timeline, audio: AudioMaster
) -> MeasurementsOut:
    assert m.probe is not None  # noqa: S101
    return MeasurementsOut(
        integrated_lufs=m.ebur["integrated_lufs"],
        true_peak_dbtp=m.ebur["true_peak_dbtp"],
        lra_lu=m.ebur["lra_lu"],
        video_bitrate_bps=m.probe.video_bitrate_bps,
        audio_bitrate_nominal_bps=row.audio_bitrate_bps,
        audio_bitrate_avg_bps=(m.probe.audio.bit_rate or 0) if m.probe.audio else 0,
        duration_ms=row.duration_ms,
        expected_ms=timeline.expected_render_duration_ms,
        black_runs=len(m.blacks),
        freeze_runs=len(m.freezes),
        silence_runs=len(m.silences),
        scene_events=len(m.scenes),
    )


def _tier_mix(timeline: Timeline) -> TierMixOut:
    frames = dict.fromkeys(
        ("A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO", "E_AI_STILL"), 0
    )
    for part in timeline.visual_parts():
        frames[part.tier or "C_CODE_MOTION"] += part.frames
    total = sum(frames.values()) or 1
    ai_ms = sum(s.plan_end_ms - s.plan_start_ms for s in timeline.shots if s.tier == "D_AI_VIDEO")
    return TierMixOut(**{k: v * 1000 // total for k, v in frames.items()}, ai_video_ms=ai_ms)


def _selftest_ref(scope: TenantScope, job_id: str, record: SelfTestRecord) -> BlobRef:
    data = canonical_json(
        {
            "ffmpeg_build_id": record.ffmpeg_build_id,
            "passed": record.passed,
            "cases": [
                {"name": c.name, "expected": c.expected, "actual": c.actual} for c in record.cases
            ],
        }
    )
    info = scope.put_bytes(
        scope.uri("jobs", f"{job_id}/qc/selftest-{sha256_hex(data)[:16]}.json"), data
    )
    return BlobRef(uri=info.uri, sha256=info.sha256)


__all__ = ["AgentCrashError", "Callable", "Fraction", "GateVerdict", "QcStage", "SelfTestProvider"]
