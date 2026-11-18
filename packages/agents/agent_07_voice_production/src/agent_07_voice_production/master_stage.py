"""``agent_07.audio_master`` (stage ``s07_master``, blocking gate): M1 to M9 of blueprint 4.2.

Domain-quality results carry ``gate: true`` and, when they fail, ``remedy_stage_id = s07_voice``;
the task still SUCCEEDS and the orchestrator routes REVISE (03 5.3 rule 4). Process-integrity
results keep ``gate: false``. Music mixing is 3B (D6): ``music_stem`` is an optional input that is
null in 3A; a non-null value is refused while ``music_enabled`` is false and needs a ``MusicMixer``
once enabled.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_07_voice_production import contracts as c
from agent_07_voice_production.blobs import put_once, read_verified
from agent_07_voice_production.config import AgentSevenConfig
from agent_07_voice_production.context import ExecContext, scratch_dir
from agent_07_voice_production.ffmpeg import require_working_format
from agent_07_voice_production.master import (
    CodecFacts,
    MasteringBackend,
    MasterRun,
    PassState,
    loudness_in_tolerance,
    run_passes,
)
from agent_07_voice_production.outputs import (
    classify,
    failed,
    log_event,
    output_ref,
    result,
    success,
    suspended,
    usage,
)
from agent_07_voice_production.ports import (
    AudioAnalysis,
    AudioTools,
    ControlPort,
    FactsReader,
    SilenceSpan,
)
from amw_core.contracts.common import storage_uri_owner
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import TaskOutput, ValidationResult
from amw_core.enums import CheckVerdict, OutputRefKind, WaitReason
from amw_core.errors import (
    ConfigInvalidError,
    CrossTenantRefError,
    IncompleteOutputError,
    InputInvalidError,
    PermissionDeniedError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
)
from amw_core.interfaces.checkpoint_store import CheckpointStore, NewCheckpoint
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenancyContext

PASS, FAIL, WARN, SKIPPED = (
    CheckVerdict.PASS,
    CheckVerdict.FAIL,
    CheckVerdict.WARN,
    CheckVerdict.SKIPPED,
)
REMEDY = "s07_voice"


@runtime_checkable
class MusicMixer(Protocol):
    """3B hook (D6, CCR-007): gains a licensed music stem 15 to 20 dB under the narration and
    returns the leveled stem and the measured offset. Not implemented in 3A."""

    def mix(
        self, narration: Path, music: Path, spans: Sequence[SilenceSpan]
    ) -> tuple[Path, float]: ...


@dataclass(frozen=True, slots=True)
class MasterDeps:
    config: AgentSevenConfig
    storage: BlobStorage
    tenancy: TenancyContext
    checkpoints: CheckpointStore
    facts: FactsReader
    tools: AudioTools
    backend: MasteringBackend
    clock: Clock
    control: ControlPort
    scratch_root: Path
    music_mixer: MusicMixer | None = None


class _Drained(Exception):  # noqa: N818 - control flow
    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


def gate_result(
    check_id: str,
    ok: bool | None,
    message: str,
    *,
    measured: bool | int | float | str | None = None,
    threshold: bool | int | float | str | None = None,
    unit: str | None = None,
) -> ValidationResult:
    """A calibrated gate check is PASS/FAIL blocking; ``ok = None`` means "not calibrated yet":
    WARN with the measured value (18 7.0.4)."""
    if ok is None:
        return result(check_id, WARN, message, measured=measured, unit=unit, gate=True)
    return result(
        check_id,
        PASS if ok else FAIL,
        message,
        blocking=True,
        measured=measured,
        threshold=threshold,
        unit=unit,
        gate=True,
        remedy_stage_id=REMEDY,
    )


def silence_findings(
    runs: Sequence[SilenceSpan], pauses: Sequence[c.PauseSpan], tolerance_ms: int
) -> tuple[list[c.MasterSilenceRun], int]:
    """Mark each run that lies inside a deliberate-pause span; return the longest run that does
    not (dead air, ``a07.silence.max_run``)."""
    marked: list[c.MasterSilenceRun] = []
    longest = 0
    for run in runs:
        inside = any(
            p.start_ms - tolerance_ms <= run.start_ms and run.end_ms <= p.end_ms + tolerance_ms
            for p in pauses
        )
        marked.append(
            c.MasterSilenceRun(start_ms=run.start_ms, end_ms=run.end_ms, in_deliberate_pause=inside)
        )
        if not inside:
            longest = max(longest, run.duration_ms)
    return marked, longest


def evaluate_master(
    *,
    cfg: AgentSevenConfig,
    pre: AudioAnalysis,
    run: MasterRun,
    pauses: Sequence[c.PauseSpan],
    duration_delta_samples: int,
    music_offset: float | None,
    music_active: bool,
) -> tuple[tuple[ValidationResult, ...], tuple[c.MasterSilenceRun, ...]]:
    """F-25: gate results (``gate: true``) and process-integrity results (``gate: false``)."""
    codec: CodecFacts = run.codec
    out: list[ValidationResult] = []
    tp = codec.post_codec.true_peak_dbtp
    loud = codec.post_codec.integrated_lufs
    out.append(
        gate_result(
            "qc.audio.true_peak",
            tp is not None and tp <= cfg.true_peak_max_dbtp,
            "post-codec true peak at or below the ceiling",
            measured=tp,
            threshold=cfg.true_peak_max_dbtp,
            unit="dBTP",
        )
    )
    out.append(
        gate_result(
            "qc.audio.integrated_lufs",
            loudness_in_tolerance(loud, cfg),
            "integrated loudness against the target (tolerance calibrated in 3B)",
            measured=loud,
            threshold=cfg.tolerance_lu if cfg.tolerance_lu is None else cfg.target_lufs,
            unit="LUFS",
        )
    )
    rate_ok = run.master_stream.sample_rate_hz == cfg.sample_rate_hz == codec.sample_rate_hz
    out.append(
        gate_result(
            "qc.audio.sample_rate",
            rate_ok,
            "48 kHz in the master and the encode",
            measured=codec.sample_rate_hz,
            threshold=cfg.sample_rate_hz,
            unit="Hz",
        )
    )
    out.append(
        gate_result(
            "qc.audio.codec",
            codec.codec == "aac" and codec.profile == "LC",
            "AAC-LC verification encode",
            measured=f"{codec.codec}/{codec.profile}",
            threshold="aac/LC",
        )
    )
    out.append(
        gate_result(
            "qc.audio.channels",
            codec.channels == 2 == run.master_stream.channels,
            "stereo master and encode",
            measured=codec.channels,
            threshold=2,
        )
    )
    out.append(
        gate_result(
            "qc.audio.bitrate",
            codec.bitrate_bps >= cfg.min_bitrate_bps,
            "nominal encode rate at or above the spec (CCR-055: the measured average is in the report)",
            measured=codec.bitrate_bps,
            threshold=cfg.min_bitrate_bps,
            unit="bps",
        )
    )
    out.append(
        result(
            "qc.audio.lra_report",
            PASS,
            "loudness range recorded for information",
            measured=codec.post_codec.lra_lu,
            unit="LU",
        )
    )
    out.append(
        gate_result(
            "qc.voice.clipping",
            pre.clipping_samples == 0,
            "no stem sample at full scale",
            measured=pre.clipping_samples,
            threshold=0,
        )
    )
    assert cfg.pause_span_tolerance_ms is not None  # noqa: S101 - require_master()
    out.append(
        gate_result(
            "qc.audio.clipping",
            run.master_clipping_samples == 0,
            "no master sample at full scale",
            measured=run.master_clipping_samples,
            threshold=0,
        )
    )
    marked, longest = silence_findings(pre.silence_runs, pauses, cfg.pause_span_tolerance_ms)
    limit = cfg.max_silence_ms
    out.append(
        gate_result(
            "a07.silence.max_run",
            None if limit is None else longest < limit,
            "no silence run at or above the limit outside deliberate pauses",
            measured=longest,
            threshold=limit,
            unit="ms",
        )
    )
    reduction_limit = cfg.max_limiter_reduction_db
    out.append(
        gate_result(
            "a07.master.limiter_reduction",
            None if reduction_limit is None else run.limiter_gain_reduction_db <= reduction_limit,
            "limiter gain reduction needed to reach the loudness target",
            measured=run.limiter_gain_reduction_db,
            threshold=reduction_limit,
            unit="dB",
        )
    )
    if music_offset is None or not music_active:
        out.append(
            result(
                "qc.audio.music_bed_offset",
                SKIPPED,
                "no music stem (3A technical runs, ADR-009) or no active span",
                gate=True,
            )
        )
    else:
        out.append(
            gate_result(
                "qc.audio.music_bed_offset",
                cfg.music_band_min_db <= music_offset <= cfg.music_band_max_db,
                "music 15 to 20 dB under the narration",
                measured=music_offset,
                threshold=f"{cfg.music_band_min_db}..{cfg.music_band_max_db}",
                unit="dB",
            )
        )
    floor, floor_limit = pre.noise_floor_dbfs, cfg.noise_floor_max_dbfs
    if floor is None:
        out.append(
            result("a07.noise.floor", SKIPPED, "no silence run to measure the noise floor in")
        )
    elif floor_limit is None:
        out.append(
            result(
                "a07.noise.floor",
                WARN,
                "noise limit not calibrated: value recorded",
                measured=floor,
                unit="dBFS",
            )
        )
    else:
        out.append(
            result(
                "a07.noise.floor",
                PASS if floor <= floor_limit else FAIL,
                "noise floor against the limit",
                measured=floor,
                threshold=floor_limit,
                unit="dBFS",
            )
        )
    out.append(
        result(
            "a07.master.duration_preserved",
            PASS if duration_delta_samples == 0 else FAIL,
            "master has exactly the stem's sample count",
            blocking=True,
            measured=duration_delta_samples,
            threshold=0,
        )
    )
    out.append(
        result("a07.tenant.scope", PASS, "every reference belongs to the task's org", blocking=True)
    )
    out.append(
        result(
            "a07.caps",
            PASS if run.passes <= cfg.max_passes else FAIL,
            "mastering passes within the cap",
            blocking=True,
            measured=run.passes,
            threshold=cfg.max_passes,
        )
    )
    return tuple(out), tuple(marked)


class AudioMasterStage:
    def __init__(self, deps: MasterDeps) -> None:
        self._d = deps

    def run(self, task_input: TaskInput, attempt_id: str) -> TaskOutput:
        d = self._d
        started = d.clock.monotonic_ms()
        ctx: ExecContext | None = None
        resource = usage(
            provider_calls=0, cost_micros=0, currency=d.config.currency, cost_entry_ids=()
        )
        try:
            ctx = ExecContext.from_task_input(task_input, attempt_id)
            return self._run(ctx, task_input, started, resource)
        except _Drained:
            return suspended(
                wait_reason=WaitReason.DRAIN,
                resource=resource,
                duration_ms=d.clock.monotonic_ms() - started,
                now=d.clock.now(),
            )
        except Exception as raw:
            return failed(
                classify(raw),
                ctx=ctx,
                correlation_id=task_input.correlation_id,
                resource=resource,
                duration_ms=d.clock.monotonic_ms() - started,
                now=d.clock.now(),
                attempt_no=task_input.retry_count + 1,
            )

    def _payload(self, ctx: ExecContext, task_input: TaskInput) -> c.AudioMasterInput:
        env = task_input.payload
        if env.payload_schema != c.SCHEMA_MASTER_INPUT:
            raise SchemaInvalidError("payload schema is not agent_07.audio_master.input")
        if env.payload_schema_version != c.SCHEMA_VERSION:
            raise SchemaVersionUnsupportedError("unsupported payload schema version")
        if env.data is not None:
            raw: object = env.data
        else:
            if env.data_ref is None or env.data_sha256 is None:
                raise SchemaInvalidError("payload has neither inline data nor a stored reference")
            raw = json.loads(
                read_verified(self._d.storage, ctx.tenant, BlobUri(env.data_ref), env.data_sha256)
            )
        payload = c.AudioMasterInput.model_validate(raw)
        uris = [payload.narration_ref, payload.timeline_ref]
        if payload.music_stem is not None:
            uris.append(payload.music_stem.stem_ref)
        for uri in uris:
            if storage_uri_owner(uri) != str(ctx.org_id):
                raise CrossTenantRefError("a payload reference belongs to another tenant")
        return payload

    def _run(
        self, ctx: ExecContext, task_input: TaskInput, started: int, resource: object
    ) -> TaskOutput:
        d, cfg = self._d, self._d.config
        cfg.require_master()
        payload = self._payload(ctx, task_input)
        # M1: load the stem and the timeline by hash (a mismatch is CORRUPTED_OUTPUT, AM-23).
        stem_bytes = read_verified(
            d.storage, ctx.tenant, BlobUri(payload.narration_ref), payload.narration_sha256
        )
        timeline_bytes = read_verified(
            d.storage, ctx.tenant, BlobUri(payload.timeline_ref), payload.timeline_sha256
        )
        try:
            timeline = c.NarrationTimeline.model_validate(json.loads(timeline_bytes))
        except ValueError as exc:
            raise InputInvalidError("the timeline document is not readable") from exc
        if timeline.purpose is not c.Purpose.PRODUCTION:
            raise InputInvalidError("a voice sample is never mastered")
        music = self._music_hook(ctx, payload)

        with scratch_dir(d.scratch_root, ctx) as scratch:
            stem = scratch / "narration.wav"
            stem.write_bytes(stem_bytes)
            pre = d.tools.analyse(
                stem, silence_noise_db=cfg.silence_noise_db, silence_min_s=cfg.silence_detect_min_s
            )
            require_working_format(pre.stream, cfg)
            if pre.stream.duration_ms != timeline.total_duration_ms:
                raise InputInvalidError(
                    "the timeline total differs from the stem duration",
                    details={
                        "timeline_ms": timeline.total_duration_ms,
                        "stem_ms": pre.stream.duration_ms,
                    },
                )
            resume = self._resume(ctx)
            run = run_passes(
                d.backend,
                stem=stem,
                pre=pre,
                cfg=cfg,
                workdir=scratch,
                resume=resume,
                after_pass=lambda state: self._after_pass(ctx, state),
            )
            master_bytes = run.master_path.read_bytes()
        delta = run.master_stream.duration_samples - pre.stream.duration_samples
        results, silence_runs = evaluate_master(
            cfg=cfg,
            pre=pre,
            run=run,
            pauses=payload.deliberate_pause_spans,
            duration_delta_samples=delta,
            music_offset=music,
            music_active=music is not None,
        )
        _require_delivery_encode(run, cfg)
        integrity = [r for r in results if r.blocking and not r.gate and r.verdict is not PASS]
        if integrity:
            raise IncompleteOutputError(
                "a blocking integrity check of s07_master did not pass",
                details={"check_ids": [r.check_id for r in integrity]},
            )
        failing = [r for r in results if r.gate and r.blocking and r.verdict is FAIL]
        base = f"{ctx.job_id}/s07_master/{ctx.task_id}"
        master_uri = d.storage.blob_uri(ctx.tenant, "jobs", f"{base}/master.wav")
        info = put_once(d.storage, ctx.tenant, master_uri, master_bytes)
        report = {
            "gate": [r.check_id for r in failing],
            "pre": _loud(pre.loudness),
            "post": _loud(run.codec.post_codec),
            "passes": run.passes,
            "codec": {
                "codec": run.codec.codec,
                "profile": run.codec.profile,
                "sample_rate_hz": run.codec.sample_rate_hz,
                "channels": run.codec.channels,
                "nominal_bitrate_bps": run.codec.bitrate_bps,
                "measured_bitrate_bps": run.codec.measured_bitrate_bps,
            },
            "master_clipping_samples": run.master_clipping_samples,
        }
        report_uri = d.storage.blob_uri(ctx.tenant, "jobs", f"{base}/report.json")
        report_info = put_once(
            d.storage, ctx.tenant, report_uri, json.dumps(report, sort_keys=True).encode()
        )
        out = c.AudioMasterOutput(
            gate_verdict="FAILED" if failing else "PASSED",
            gate_reasons=tuple(
                c.GateReason(
                    check_id=r.check_id,
                    measured=_scalar(r.measured),
                    threshold=_scalar(r.threshold),
                    remedy_stage_id="s07_voice",
                )
                for r in failing
            ),
            iteration=payload.iteration,
            master=c.MasterFileBlock(
                master_uri=str(master_uri),
                sha256=info.sha256,
                duration_ms=run.master_stream.duration_ms,
                sample_rate_hz=48000,  # verified against the measured stream, see the guard
                channels=2,
            ),
            measurements=c.MasterMeasurements(
                pre=_block(pre.loudness),
                post=_block(run.codec.post_codec),
                clipping_samples=pre.clipping_samples,
                silence_runs=silence_runs,
                noise_floor_dbfs=pre.noise_floor_dbfs,
                duration_delta_samples=delta,
            ),
            mastering=c.MasteringBlock(
                passes=run.passes,
                gain_db=run.gain_db,
                limiter_ceiling_dbtp=run.ceiling_dbtp,
                limiter_gain_reduction_db=run.limiter_gain_reduction_db,
                denoise_mode=c.DenoiseOut(cfg.denoise_mode.value),
            ),
            codec_verification=c.CodecVerificationBlock(
                codec="aac",  # equal to the measured values: _require_delivery_encode
                profile="LC",
                sample_rate_hz=48000,
                channels=2,
                bitrate_bps=run.codec.bitrate_bps,  # nominal rate, the gated value (CCR-055)
                post_codec=_block(run.codec.post_codec),
            ),
            codec_profile=c.CodecProfileBlock(
                codec="aac",
                profile="LC",
                sample_rate_hz=48000,
                channels=2,
                bitrate_bps=cfg.min_bitrate_bps,
                encoder=f"{cfg.aac_encoder} ({d.backend.build()})"[:64],
                rate_mode=cfg.aac_rate_mode,
            ),
            music=None,
            provenance=c.MasterProvenance(
                ffmpeg_build=d.backend.build()[:128],
                config_version=cfg.config_version,
                narration_sha256=payload.narration_sha256,
                timeline_sha256=payload.timeline_sha256,
            ),
        )
        log_event("master.gate", ctx, verdict=out.gate_verdict, passes=run.passes)
        refs = [
            output_ref(
                str(master_uri), OutputRefKind.AUDIO, info.sha256, info.size_bytes, "audio/wav"
            ),
            output_ref(
                str(report_uri),
                OutputRefKind.REPORT,
                report_info.sha256,
                report_info.size_bytes,
                "application/json",
            ),
        ]
        reason = f"gate FAILED: {', '.join(r.check_id for r in failing)}" if failing else ""
        return success(
            payload_schema=c.SCHEMA_MASTER_OUTPUT,
            payload=out,
            refs=refs,
            results=results,
            resource=usage(
                provider_calls=0, cost_micros=0, currency=cfg.currency, cost_entry_ids=()
            ),
            duration_ms=d.clock.monotonic_ms() - started,
            now=d.clock.now(),
            reason=reason,
            downstream="agent_10",
        )

    # -- 3B hook ------------------------------------------------------------------------

    def _music_hook(self, ctx: ExecContext, payload: c.AudioMasterInput) -> float | None:
        """Optional input, null in 3A (CCR-007): refused while music is disabled; with music
        enabled every asset needs a ``MUSIC_BED`` licence-ledger row and a mixer must be wired."""
        music = payload.music_stem
        if music is None:
            return None
        if not self._d.config.music_enabled:
            raise InputInvalidError("a music stem is refused while agent_07.music_enabled is false")
        with self._d.tenancy.transaction(ctx.tenant) as tx:
            licensed = self._d.facts.music_licence_rows_exist(tx, tuple(music.asset_ids))
        if not licensed:
            raise PermissionDeniedError(
                "a music asset has no licence-ledger row", details={"reason": "music_unlicensed"}
            )
        if self._d.music_mixer is None:
            raise ConfigInvalidError("music mixing is a 3B feature: no MusicMixer is configured")
        raise ConfigInvalidError("music mixing is not implemented in 3A")  # pragma: no cover

    # -- checkpoints and drain ----------------------------------------------------------

    def _after_pass(self, ctx: ExecContext, state: PassState) -> None:
        d = self._d
        step = f"master.pass_{state.pass_no}"
        doc = json.dumps(
            {
                "pass": state.pass_no,
                "gain": state.gain_db,
                "ceiling": state.ceiling_dbtp,
                "next_gain": state.next_gain_db,
                "next_ceiling": state.next_ceiling_dbtp,
                "satisfied": state.satisfied,
            },
            sort_keys=True,
        ).encode()
        uri = d.storage.blob_uri(
            ctx.tenant, "jobs", f"{ctx.job_id}/s07_master/{ctx.task_id}/{step}.json"
        )
        info = put_once(d.storage, ctx.tenant, uri, doc)
        with d.tenancy.transaction(ctx.tenant) as tx:
            d.checkpoints.write(
                tx,
                NewCheckpoint(
                    task_id=ctx.task_id,
                    attempt_id=ctx.attempt_id,
                    step_key=step,
                    state_ref=str(uri),
                    state_sha256=info.sha256,
                    completed_effects=(),
                ),
                d.clock.now(),
            )
        log_event("master.pass", ctx, pass_no=state.pass_no, satisfied=state.satisfied)
        if d.control.drain_requested():
            raise _Drained(step)

    def _resume(self, ctx: ExecContext) -> PassState | None:
        d = self._d
        with d.tenancy.transaction(ctx.tenant) as tx:
            latest = d.checkpoints.latest(tx, ctx.task_id)
        if latest is None or not latest.checkpoint.step_key.startswith("master.pass_"):
            return None
        raw = read_verified(
            d.storage,
            ctx.tenant,
            BlobUri(latest.checkpoint.state_ref),
            latest.checkpoint.state_sha256,
        )
        s = json.loads(raw)
        return PassState(
            int(s["pass"]),
            float(s["gain"]),
            float(s["ceiling"]),
            float(s["next_gain"]),
            float(s["next_ceiling"]),
            bool(s["satisfied"]),
        )


def _require_delivery_encode(run: MasterRun, cfg: AgentSevenConfig) -> None:
    """The payload reports measured codec facts; a verification encode that is not AAC-LC at the
    delivery rate, stereo and at or above the minimum bitrate is a process-integrity failure (a
    typed error, no payload) and is never papered over with the spec constants. The bitrate gate
    is on the nominal rate (CCR-055); the measured average goes to the report."""
    codec, master = run.codec, run.master_stream
    wrong = [
        name
        for name, ok in (
            ("qc.audio.codec", codec.codec == "aac" and codec.profile == "LC"),
            (
                "qc.audio.sample_rate",
                master.sample_rate_hz == codec.sample_rate_hz == cfg.sample_rate_hz,
            ),
            ("qc.audio.channels", codec.channels == 2 == master.channels),
            ("qc.audio.bitrate", codec.bitrate_bps >= cfg.min_bitrate_bps),
        )
        if not ok
    ]
    if wrong:
        raise IncompleteOutputError(
            "the verification encode is not the delivery profile",
            details={
                "check_ids": wrong,
                "codec": f"{codec.codec}/{codec.profile}",
                "sample_rate_hz": codec.sample_rate_hz,
                "channels": codec.channels,
                "bitrate_bps": codec.bitrate_bps,
            },
        )


def _block(loudness: object) -> c.LoudnessBlock:
    return c.LoudnessBlock(
        integrated_lufs=getattr(loudness, "integrated_lufs", None),
        true_peak_dbtp=getattr(loudness, "true_peak_dbtp", None),
        lra_lu=getattr(loudness, "lra_lu", None),
    )


def _loud(loudness: object) -> dict[str, float | None]:
    return _block(loudness).model_dump()


def _scalar(value: object) -> float | str | None:
    if isinstance(value, bool):
        return str(value)
    return value if isinstance(value, float | str) or value is None else float(value)  # type: ignore[arg-type]


__all__ = ["AudioMasterStage", "MasterDeps", "MusicMixer", "evaluate_master"]
