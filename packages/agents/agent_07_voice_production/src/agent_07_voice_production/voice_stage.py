"""``agent_07.voice_synthesis`` (stage ``s07_voice``): V1 to V10 of blueprint 4.1.

Order: tenant scope, payload, script gate, voice policy (voice, language, brand kit, licence,
consent), dictionary, plan, fail-closed gates, one call per sentence (or owner-recording intake),
stem and measured timeline, measurements, registration, checks, output. Every denial happens
before the first paid call. The task never edits the script and sends only sanitised sentence
text and the voice reference to the provider.
"""

import io
import json
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from agent_07_voice_production import contracts as c
from agent_07_voice_production.blobs import put_once, read_actual, read_verified
from agent_07_voice_production.config import AgentSevenConfig
from agent_07_voice_production.context import ExecContext, scratch_dir
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
from agent_07_voice_production.policy import (
    ResolvedVoice,
    check_consent,
    check_licence,
    check_script_gate,
    resolve_voice,
)
from agent_07_voice_production.ports import (
    AudioAnalysis,
    AudioTools,
    CircuitBreaker,
    ControlPort,
    FactsReader,
    NarrationRegistration,
    NarrationRegistry,
    TtsCapabilities,
    TtsSynthesizer,
)
from agent_07_voice_production.style import (
    StyleDecision,
    applied_ratio,
    distinct_variation,
    map_style,
)
from agent_07_voice_production.synthesis import (
    ClipResult,
    SegmentSynthesizer,
    SynthesisSettings,
    estimate_micros,
)
from agent_07_voice_production.text import (
    PreparedSegment,
    PronunciationDictionary,
    prepare_segment,
    scan_unknown_terms,
)
from agent_07_voice_production.timeline import (
    PlacedClip,
    assemble,
    timeline_from_marks,
    timeline_problems,
    validate_marks,
)
from amw_core.contracts.common import storage_uri_owner
from amw_core.contracts.task_input import TaskInput
from amw_core.contracts.task_output import OutputRef, TaskOutput, ValidationResult
from amw_core.enums import (
    AssetKind,
    CheckKind,
    CheckVerdict,
    OutputRefKind,
    VoiceKind,
    WaitReason,
)
from amw_core.errors import (
    BudgetExhaustedError,
    ConfigInvalidError,
    CrossTenantRefError,
    IncompleteOutputError,
    InputInvalidError,
    LoopCapExceededError,
    MissingDependencyError,
    PermissionDeniedError,
    SchemaInvalidError,
    SchemaVersionUnsupportedError,
)
from amw_core.ids import IdempotencyKey
from amw_core.interfaces.budget_guard import BudgetGuard
from amw_core.interfaces.checkpoint_store import CheckpointStore, NewCheckpoint
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostLedger
from amw_core.interfaces.idempotency_store import IdempotencyStore
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenancyContext

PASS, FAIL, WARN, SKIPPED = (
    CheckVerdict.PASS,
    CheckVerdict.FAIL,
    CheckVerdict.WARN,
    CheckVerdict.SKIPPED,
)
WORKING_RATE = 48_000


@dataclass(frozen=True, slots=True)
class VoiceDeps:
    config: AgentSevenConfig
    tts: TtsSynthesizer
    storage: BlobStorage
    tenancy: TenancyContext
    idempotency: IdempotencyStore
    ledger: CostLedger
    budget: BudgetGuard
    breaker: CircuitBreaker
    checkpoints: CheckpointStore
    facts: FactsReader
    registry: NarrationRegistry
    tools: AudioTools
    clock: Clock
    control: ControlPort
    scratch_root: Path
    sleep: Callable[[float], None] | None = None


@dataclass(slots=True)
class _Run:
    """Mutable state of one attempt."""

    ctx: ExecContext
    payload: c.VoiceSynthesisInput
    script: c.ScriptDocument
    segments: tuple[c.ScriptSegment, ...]
    resolved: ResolvedVoice
    caps: TtsCapabilities
    dictionary: PronunciationDictionary
    dictionary_asset_id: str
    org_wire: str
    calls: int = 0
    reused: int = 0
    characters: int = 0
    cost_entry_ids: tuple[str, ...] = ()
    cost_micros: int = 0
    clip_refs: tuple[OutputRef, ...] = ()


class VoiceSynthesisStage:
    def __init__(self, deps: VoiceDeps) -> None:
        self._d = deps
        self._partial: _Partial | None = None

    # ---------------------------------------------------------------- entry point

    def run(self, task_input: TaskInput, attempt_id: str) -> TaskOutput:
        d = self._d
        started = d.clock.monotonic_ms()
        ctx: ExecContext | None = None
        self._partial = None
        try:
            ctx = ExecContext.from_task_input(task_input, attempt_id)
            return self._run(ctx, task_input, started)
        except _Drained as drained:
            return suspended(
                wait_reason=WaitReason.DRAIN,
                resource=usage(
                    provider_calls=drained.calls,
                    cost_micros=drained.cost,
                    currency=d.config.currency,
                    cost_entry_ids=drained.entries,
                ),
                duration_ms=d.clock.monotonic_ms() - started,
                now=d.clock.now(),
                refs=drained.refs,
            )
        except Exception as raw:
            exc = classify(raw)
            now = d.clock.now()
            elapsed = d.clock.monotonic_ms() - started
            partial = self._partial or _Partial(0, 0, ())
            resource = usage(
                provider_calls=partial.calls,
                cost_micros=partial.cost,
                currency=d.config.currency,
                cost_entry_ids=partial.entries,
            )
            if isinstance(exc, BudgetExhaustedError) and ctx is not None:
                return suspended(
                    wait_reason=WaitReason.AWAITING_BUDGET,
                    resource=resource,
                    duration_ms=elapsed,
                    now=now,
                    exc=exc,
                    ctx=ctx,
                )
            if isinstance(exc, PermissionDeniedError) and ctx is not None:
                log_event("voice.denied", ctx, reason=str(exc.details.get("reason")))
            return failed(
                exc,
                ctx=ctx,
                correlation_id=task_input.correlation_id,
                resource=resource,
                duration_ms=elapsed,
                now=now,
                attempt_no=task_input.retry_count + 1,
            )

    # ---------------------------------------------------------------- V1 to V10

    def _run(self, ctx: ExecContext, task_input: TaskInput, started: int) -> TaskOutput:
        d = self._d
        cfg = d.config
        cfg.require_voice()
        payload = self._payload(ctx, task_input)
        caps = d.tts.capabilities()
        production = payload.purpose is c.Purpose.PRODUCTION

        script, verification, row_sha = self._read_script(ctx, payload)
        with d.tenancy.transaction(ctx.tenant) as tx:
            row = d.facts.script_row(tx, payload.script_id, payload.script_version)
            approval = (
                d.facts.approval(tx, payload.verification_approval_id)
                if payload.verification_approval_id is not None
                else None
            )
            bundle = d.facts.voice_bundle(tx, payload.voice_id)
            brand_kit = (
                d.facts.brand_kit_voice_id(tx, ctx.channel_id)
                if ctx.channel_id is not None
                else None
            )
            job = d.facts.job(tx, ctx.job_id)
            platform_owner = d.facts.org_is_platform_owner(tx)
        check_script_gate(
            payload, blob_sha256=row_sha, row=row, verification=verification, approval=approval
        )
        if job is None:
            raise MissingDependencyError("job not found")
        resolved = resolve_voice(
            bundle,
            language=payload.language,
            caps=caps,
            brand_kit_voice_id=brand_kit,
            production=production,
        )
        now = d.clock.now()
        licence = check_licence(
            resolved,
            monetized_destination=job.monetized_destination,
            org_is_platform_owner=platform_owner,
            now=now,
        )
        check_consent(resolved, channel_id=ctx.channel_id, now=now)
        human = resolved.kind is VoiceKind.HUMAN_RECORDED
        if human != (payload.human_narration is not None):
            raise InputInvalidError(
                "human_narration is required for a HUMAN_RECORDED voice and refused otherwise"
            )
        if human and not production:
            raise InputInvalidError("a voice sample is never an owner recording")
        if len(script.segments) > cfg.max_segments:
            raise LoopCapExceededError("the script has more sentences than agent_07.max_segments")

        segments = script.segments
        if not production:
            if cfg.sample_max_segments is None:
                raise ConfigInvalidError("agent_07.sample.max_segments is unset")
            segments = segments[: cfg.sample_max_segments]
        dictionary, dict_asset_id = self._dictionary(ctx, payload)
        run = _Run(
            ctx,
            payload,
            script,
            segments,
            resolved,
            caps,
            dictionary,
            dict_asset_id,
            str(ctx.org_id),
        )
        log_event("voice.plan", ctx, segments=len(segments), kind=resolved.kind.value)

        if human:
            return self._finish_human(run, licence.licence_id, started)
        return self._finish_provider(run, licence.licence_id, started)

    # ---------------------------------------------------------------- inputs

    def _payload(self, ctx: ExecContext, task_input: TaskInput) -> c.VoiceSynthesisInput:
        env = task_input.payload
        if env.payload_schema != c.SCHEMA_VOICE_INPUT:
            raise SchemaInvalidError("payload schema is not agent_07.voice_synthesis.input")
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
        payload = c.VoiceSynthesisInput.model_validate(raw)
        uris = [payload.script_ref, payload.verification_ref, payload.dictionary_ref]
        if payload.human_narration is not None:
            uris.append(payload.human_narration.asset_ref)
        for uri in uris:
            if storage_uri_owner(uri) != str(ctx.org_id):
                raise CrossTenantRefError("a payload reference belongs to another tenant")
        return payload

    def _read_script(
        self, ctx: ExecContext, payload: c.VoiceSynthesisInput
    ) -> tuple[c.ScriptDocument, c.VerificationOutput, str]:
        d = self._d
        raw, actual = read_actual(d.storage, ctx.tenant, BlobUri(payload.script_ref))
        verification_raw, _ = read_actual(d.storage, ctx.tenant, BlobUri(payload.verification_ref))
        try:
            script = c.ScriptDocument.model_validate(json.loads(raw))
            verification = c.VerificationOutput.model_validate(
                _unwrap(json.loads(verification_raw))
            )
        except ValueError as exc:
            raise InputInvalidError("script or verification document is not readable") from exc
        return script, verification, actual

    def _dictionary(
        self, ctx: ExecContext, payload: c.VoiceSynthesisInput
    ) -> tuple[PronunciationDictionary, str]:
        d = self._d
        with d.tenancy.transaction(ctx.tenant) as tx:
            asset = d.facts.asset_by_ref(tx, payload.dictionary_ref)
        if asset is None:
            raise MissingDependencyError("pronunciation dictionary asset not found")
        if str(asset.org_id) != str(ctx.org_id):
            raise CrossTenantRefError("the dictionary belongs to another tenant")
        if (
            asset.allowed_channel_ids is not None
            and ctx.channel_id not in asset.allowed_channel_ids
        ):
            raise InputInvalidError("the dictionary is not permitted for this channel")
        expected = payload.dictionary_sha256 or asset.content_sha256
        data = read_verified(d.storage, ctx.tenant, BlobUri(payload.dictionary_ref), expected)
        return PronunciationDictionary.from_bytes(data, expected, payload.language), str(
            asset.asset_id
        )

    # ---------------------------------------------------------------- provider path

    def _finish_provider(self, run: _Run, licence_id: str, started: int) -> TaskOutput:
        d, cfg, ctx, payload = self._d, self._d.config, run.ctx, run.payload
        caps = run.caps
        voice = run.resolved.bundle.voice
        if voice.provider is None or voice.provider_voice_ref is None:
            raise MissingDependencyError("voice has no provider reference")
        model_ref = cfg.model_ref
        if model_ref is None:
            raise ConfigInvalidError("agent_07.tts.model_ref is unset")

        prepared = [
            prepare_segment(
                s,
                run.dictionary,
                phoneme_support=caps.phoneme_support,
                max_chars_per_request=caps.max_chars_per_request or cfg.max_chars_per_request,
                extra_delimiters=caps.markup_delimiters,
            )
            for s in run.segments
        ]
        styles = {s.segment_id: map_style(s.pace, s.emotion, caps) for s in run.segments}
        # Unknown terms are scanned on the text after substitution and before escaping.
        substituted = {
            s.segment_id: _unescape_for_scan(p.spoken_text)
            for s, p in zip(run.segments, prepared, strict=True)
        }
        unknown = scan_unknown_terms(
            org_wire_id=run.org_wire,
            segments=run.segments,
            scenes=run.script.scenes,
            original_texts={s.segment_id: s.text for s in run.segments},
            substituted_texts=substituted,
        )
        assert cfg.price_micros_per_1k_chars is not None  # noqa: S101
        total_estimate = estimate_micros(
            sum(p.characters for p in prepared), cfg.price_micros_per_1k_chars
        )
        synth = SegmentSynthesizer(
            tts=d.tts,
            idempotency=d.idempotency,
            ledger=d.ledger,
            budget=d.budget,
            breaker=d.breaker,
            storage=d.storage,
            tenancy=d.tenancy,
            clock=d.clock,
            config=cfg,
            tools=d.tools,
            **({"sleep": d.sleep} if d.sleep is not None else {}),
        )
        # Fail-closed gate for the whole plan before the first call (NFR-3, FI-08...FI-10).
        synth.guard(ctx, voice.provider, total_estimate)
        settings = SynthesisSettings(
            voice_id=str(voice.id),
            voice_ref=voice.provider_voice_ref,
            model_ref=model_ref,
            language=payload.language,
            provider=voice.provider,
        )

        clips: list[PlacedClip] = []
        done: list[IdempotencyKey] = []
        for index, prep in enumerate(prepared, start=1):
            try:
                clip = synth.synthesize(ctx, prep, settings)
            except BaseException:
                self._partial = self._with_unreturned(run, synth)
                raise
            self._account(run, clip)
            done.append(clip.idempotency_key)
            clips.append(
                PlacedClip(
                    prep.segment_id,
                    clip.samples,
                    prep.spoken_text_sha256,
                    str(clip.idempotency_key),
                    False,
                )
            )
            if index % cfg.checkpoint_every_n == 0 or d.control.drain_requested():
                self._checkpoint(run, f"voice.clips_{index}", done)
                self._recheck_consent(run)
            if d.control.drain_requested() and index < len(prepared):
                self._checkpoint(run, "voice.drain", done)
                raise _Drained(run.calls, run.cost_micros, run.cost_entry_ids, ())

        asm = assemble(
            clips,
            c.ScriptDocument(segments=run.segments, scenes=run.script.scenes),
            styles,
            gap_ms=cfg.gap_ms or 0,
            sample_rate_hz=cfg.sample_rate_hz,
        )
        stem_bytes = _wav_bytes(asm.samples, cfg.sample_rate_hz)
        timeline = c.NarrationTimeline(
            script_id=payload.script_id,
            script_version=payload.script_version,
            iteration=payload.iteration,
            purpose=payload.purpose,
            source=c.TimelineSource.PROVIDER_CLIPS,
            total_duration_ms=len(asm.samples) * 1000 // cfg.sample_rate_hz,
            segments=asm.segments,
            pauses=asm.pauses,
        )
        return self._publish(
            run,
            licence_id,
            started,
            stem_bytes,
            timeline,
            prepared=prepared,
            styles=styles,
            unknown=unknown,
            intake=None,
            model_ref=model_ref,
            provider=voice.provider,
        )

    # ---------------------------------------------------------------- owner recording

    def _finish_human(self, run: _Run, licence_id: str, started: int) -> TaskOutput:
        d, cfg, ctx, payload = self._d, self._d.config, run.ctx, run.payload
        narration = payload.human_narration
        assert narration is not None  # noqa: S101
        with d.tenancy.transaction(ctx.tenant) as tx:
            asset = d.facts.asset_by_ref(tx, narration.asset_ref)
        if asset is None:
            raise MissingDependencyError("owner recording asset not found")
        if str(asset.org_id) != str(ctx.org_id):
            raise CrossTenantRefError("the recording belongs to another tenant")
        if asset.kind != AssetKind.AUDIO_VOICE.value or not asset.active:
            raise PermissionDeniedError("the recording asset is not an active voice asset")
        if (
            asset.allowed_channel_ids is not None
            and ctx.channel_id not in asset.allowed_channel_ids
        ):
            raise PermissionDeniedError("the recording is not permitted for this channel")
        if not narration.attests_follows_verified_script:
            raise InputInvalidError(
                "the owner's attestation that the recording follows the script is missing"
            )
        data = read_verified(
            d.storage, ctx.tenant, BlobUri(narration.asset_ref), narration.asset_sha256
        )
        with scratch_dir(d.scratch_root, ctx) as scratch:
            src, work = scratch / "recording.src", scratch / "narration.wav"
            src.write_bytes(data)
            source = d.tools.probe(src)
            if source.duration_samples <= 0:
                raise InputInvalidError("the recording is empty")
            d.tools.to_working_format(src, work)
            analysis = d.tools.analyse(
                work, silence_noise_db=cfg.silence_noise_db, silence_min_s=cfg.silence_detect_min_s
            )
            if analysis.clipping_samples > 0:
                raise InputInvalidError(
                    "the recording has clipped samples; re-record it",
                    details={
                        "clipping_samples": analysis.clipping_samples,
                        "violations": [
                            {"path": "", "keyword": "clipping", "message": "clipped samples"}
                        ],
                    },
                )
            stem_duration = analysis.stream.duration_ms
            validate_marks(
                narration.segment_marks,
                run.script,
                duration_ms=stem_duration,
                max_gap_ms=cfg.max_mark_gap_ms,
            )
            stem_bytes = work.read_bytes()
        segments, pauses = timeline_from_marks(narration.segment_marks, run.script)
        timeline = c.NarrationTimeline(
            script_id=payload.script_id,
            script_version=payload.script_version,
            iteration=payload.iteration,
            purpose=payload.purpose,
            source=c.TimelineSource.OWNER_MARKS,
            total_duration_ms=stem_duration,
            segments=segments,
            pauses=pauses,
        )
        intake = c.IntakeBlock(
            source_sha256=narration.asset_sha256,
            source_sample_rate_hz=source.sample_rate_hz,
            source_channels=source.channels,
            source_duration_ms=max(1, source.duration_ms),
            attestation_recorded=True,
            marks_count=len(narration.segment_marks),
        )
        return self._publish(
            run,
            licence_id,
            started,
            stem_bytes,
            timeline,
            prepared=[],
            styles={},
            unknown=(),
            intake=intake,
            model_ref=None,
            provider=None,
            analysis=analysis,
        )

    # ---------------------------------------------------------------- shared tail

    def _publish(
        self,
        run: _Run,
        licence_id: str,
        started: int,
        stem_bytes: bytes,
        timeline: c.NarrationTimeline,
        *,
        prepared: Sequence[PreparedSegment],
        styles: dict[str, StyleDecision],
        unknown: Sequence[c.UnknownTerm],
        intake: c.IntakeBlock | None,
        model_ref: str | None,
        provider: str | None,
        analysis: AudioAnalysis | None = None,
    ) -> TaskOutput:
        d, cfg, ctx, payload = self._d, self._d.config, run.ctx, run.payload
        production = payload.purpose is c.Purpose.PRODUCTION
        base = f"{ctx.job_id}/s07_voice/{ctx.task_id}"
        stem_uri = d.storage.blob_uri(ctx.tenant, "jobs", f"{base}/narration.wav")
        stem_info = put_once(d.storage, ctx.tenant, stem_uri, stem_bytes)
        timeline_doc = timeline.model_dump_json().encode("utf-8")
        timeline_uri = d.storage.blob_uri(ctx.tenant, "jobs", f"{base}/timeline.json")
        timeline_info = put_once(d.storage, ctx.tenant, timeline_uri, timeline_doc)

        if analysis is None:
            with scratch_dir(d.scratch_root, ctx) as scratch:
                path = scratch / "stem.wav"
                path.write_bytes(stem_bytes)
                analysis = d.tools.analyse(
                    path,
                    silence_noise_db=cfg.silence_noise_db,
                    silence_min_s=cfg.silence_detect_min_s,
                )
        scoped = c.ScriptDocument(segments=run.segments, scenes=run.script.scenes)
        problems = timeline_problems(timeline, scoped, timeline.total_duration_ms)

        asset_id: str | None = None
        voice = run.resolved.bundle.voice
        licence = run.resolved.bundle.licence
        assert licence is not None  # noqa: S101 - check_licence
        if production:
            with d.tenancy.transaction(ctx.tenant) as tx:
                registered = d.registry.register(
                    tx,
                    NarrationRegistration(
                        content_sha256=stem_info.sha256,
                        stem_uri=str(stem_uri),
                        voice=voice,
                        licence_id=licence.licence_id,
                        source_type=licence.source_type,
                        job_id=str(ctx.job_id),
                        task_id=str(ctx.task_id),
                        is_realistic_synthetic=voice.kind is not VoiceKind.HUMAN_RECORDED,
                    ),
                )
            asset_id = str(registered.asset_id)
            log_event("voice.registered", ctx, row_created=registered.created)

        dictionary_block = c.DictionaryBlock(
            asset_id=run.dictionary_asset_id,
            version=run.dictionary.document.version,
            dictionary_sha256=run.dictionary.sha256,
            hits_total=sum(h.count for p in prepared for h in p.hits),
            hits=tuple(h for p in prepared for h in p.hits),
            unknown_terms=tuple(unknown),
        )
        payload_out = c.VoiceSynthesisOutput(
            purpose=payload.purpose,
            script_id=payload.script_id,
            script_version=payload.script_version,
            iteration=payload.iteration,
            language=payload.language,
            voice=c.VoiceBlock(
                voice_id=str(voice.id),
                voice_kind=voice.kind,
                licence_id=licence_id,
                provider=provider,
                model_ref=model_ref,
                consent_id=str(voice.consent_id) if voice.consent_id is not None else None,
                presenter_kind=run.resolved.presenter_kind,
            ),
            narration=c.NarrationBlock(
                stem_uri=str(stem_uri),
                sha256=stem_info.sha256,
                duration_ms=timeline.total_duration_ms,
                sample_rate_hz=48000,
                channels=1,
                asset_id=asset_id,
            ),
            timeline=c.TimelineBlock(
                source=timeline.source,
                timeline_uri=str(timeline_uri),
                timeline_sha256=timeline_info.sha256,
                segments=timeline.segments,
                pauses=timeline.pauses,
            ),
            dictionary=dictionary_block,
            voice_measurements=c.VoiceMeasurements(
                clipping_samples=analysis.clipping_samples,
                peak_dbfs=analysis.peak_dbfs,
                noise_floor_dbfs=analysis.noise_floor_dbfs,
                integrated_lufs=analysis.loudness.integrated_lufs,
                silence_runs=tuple(
                    c.SilenceRun(start_ms=s.start_ms, end_ms=s.end_ms)
                    for s in analysis.silence_runs
                ),
            ),
            intake=intake,
            cost=c.CostBlock(
                calls=run.calls,
                reused_clips=run.reused,
                characters=run.characters,
                unit_kind="characters",
                figure_kind="ESTIMATE",
                cost_entry_ids=run.cost_entry_ids,
            ),
            provenance=c.VoiceProvenance(
                adapter=d.tts.provider if provider is not None else "human_recording",
                adapter_capabilities=c.AdapterCapabilitiesOut(
                    pace_control=run.caps.pace_control,
                    emotion_control=run.caps.emotion_control,
                    phoneme_support=run.caps.phoneme_support,
                    languages=run.caps.languages,
                    max_chars_per_request=run.caps.max_chars_per_request,
                ),
                config_version=cfg.config_version,
                script_sha256=payload.script_sha256,
                dictionary_sha256=run.dictionary.sha256,
            ),
        )
        results = self._checks(
            run, prepared, styles, unknown, analysis, problems, intake, production
        )
        failing = [r for r in results if r.blocking and r.verdict is not PASS]
        if failing:
            raise IncompleteOutputError(
                "a blocking check of s07_voice did not pass",
                details={"check_ids": [r.check_id for r in failing]},
            )
        refs = [
            output_ref(
                str(stem_uri),
                OutputRefKind.AUDIO,
                stem_info.sha256,
                stem_info.size_bytes,
                "audio/wav",
            ),
            output_ref(
                str(timeline_uri),
                OutputRefKind.DATA,
                timeline_info.sha256,
                timeline_info.size_bytes,
                "application/json",
            ),
            *run.clip_refs,
        ]
        log_event("voice.completed", ctx, calls=run.calls, characters=run.characters)
        return success(
            payload_schema=c.SCHEMA_VOICE_OUTPUT,
            payload=payload_out,
            refs=refs,
            results=results,
            resource=usage(
                provider_calls=run.calls,
                cost_micros=run.cost_micros,
                currency=cfg.currency,
                cost_entry_ids=run.cost_entry_ids,
            ),
            duration_ms=d.clock.monotonic_ms() - started,
            now=d.clock.now(),
            downstream="agent_09" if production else None,
        )

    # ---------------------------------------------------------------- checks

    def _checks(
        self,
        run: _Run,
        prepared: Sequence[PreparedSegment],
        styles: dict[str, StyleDecision],
        unknown: Sequence[c.UnknownTerm],
        analysis: AudioAnalysis,
        problems: list[str],
        intake: c.IntakeBlock | None,
        production: bool,
    ) -> tuple[ValidationResult, ...]:
        cfg = self._d.config
        out: list[ValidationResult] = []
        human = intake is not None
        out.append(
            result(
                "a07.tenant.scope",
                PASS,
                "every reference and row belongs to the task's org",
                blocking=True,
            )
        )
        out.append(
            result(
                "a07.caps",
                PASS,
                "segment and pass caps respected",
                blocking=True,
                measured=len(run.segments),
                threshold=cfg.max_segments,
            )
        )
        out.append(
            result(
                "a07.voice.kind_recorded",
                PASS,
                "voice kind and presenter kind echoed for Agent 16",
                blocking=True,
                measured=run.resolved.presenter_kind.value,
            )
        )
        out.append(result("a07.licence.active", PASS, "the voice licence is active", blocking=True))
        out.append(
            result(
                "a07.licence.recorded",
                PASS if production else SKIPPED,
                "asset and licence-ledger rows written once"
                if production
                else "a voice sample is not licensed into a video",
                blocking=True,
            )
        )
        if human:
            out.append(
                result("a07.lang.supported", SKIPPED, "no provider is called", blocking=True)
            )
            out.append(
                result(
                    "a07.intake.attestation",
                    PASS,
                    "the owner's attestation is recorded",
                    blocking=True,
                    kind=CheckKind.HUMAN,
                )
            )
            out.append(
                result(
                    "a07.intake.clipping",
                    PASS,
                    "no clipped sample in the recording",
                    blocking=True,
                    measured=0,
                    threshold=0,
                )
            )
        else:
            out.append(
                result(
                    "a07.lang.supported", PASS, "the adapter declares the language", blocking=True
                )
            )
            expected = sum(p.expected_matches for p in prepared)
            applied = sum(h.count for p in prepared for h in p.hits)
            out.append(
                result(
                    "qc.voice.dictionary_applied",
                    PASS if expected == applied else FAIL,
                    "every dictionary term of the script went through its entry",
                    blocking=True,
                    measured=applied,
                    threshold=expected,
                )
            )
            skipped = sum(p.skipped_phoneme_entries for p in prepared)
            if skipped:
                out.append(
                    result(
                        "a07.dict.phoneme_unsupported",
                        WARN,
                        "PHONEME entries skipped: the adapter has no phoneme support",
                        measured=skipped,
                    )
                )
            out.append(
                result(
                    "a07.dict.unknown_terms",
                    WARN if unknown else PASS,
                    "unknown terms listed for the owner (never auto-added)",
                    measured=len(unknown),
                )
            )
            variation = distinct_variation(run.segments)
            out.append(
                result(
                    "qc.voice.variation",
                    PASS if variation else WARN,
                    "pace/emotion variation across sentences",
                    measured=variation,
                )
            )
            ok, asked = applied_ratio(run.segments, [styles[s.segment_id] for s in run.segments])
            out.append(
                result(
                    "a07.style.applied_ratio",
                    SKIPPED if asked == 0 else (PASS if ok == asked else WARN),
                    "share of requested non-default styles the adapter applied",
                    measured=f"{ok}/{asked}",
                )
            )
            out.append(
                result(
                    "a07.cost.recorded",
                    PASS if len(run.cost_entry_ids) == run.calls else FAIL,
                    "every paid call has a ledger row",
                    blocking=True,
                    measured=len(run.cost_entry_ids),
                    threshold=run.calls,
                )
            )
        out.append(
            result(
                "qc.voice.consent_verified",
                PASS if run.resolved.kind is VoiceKind.CONSENTED_CLONE else SKIPPED,
                "clone consent is VERIFIED, current and the owner's",
                blocking=True,
            )
        )
        out.append(
            result(
                "a07.timeline.complete",
                FAIL if problems else PASS,
                "; ".join(problems) or "an aligned entry for every sentence",
                blocking=True,
                measured=len(problems),
                threshold=0,
            )
        )
        out.append(
            result(
                "qc.voice.clipping",
                PASS if analysis.clipping_samples == 0 else WARN,
                "raw-voice clipping is reported; the master decides",
                measured=analysis.clipping_samples,
                threshold=0,
            )
        )
        limit = cfg.noise_floor_max_dbfs
        floor = analysis.noise_floor_dbfs
        if floor is None:
            out.append(
                result("a07.noise.floor", SKIPPED, "no silence run to measure the noise floor in")
            )
        elif limit is None:
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
                    PASS if floor <= limit else FAIL,
                    "raw-voice noise floor against the limit",
                    measured=floor,
                    threshold=limit,
                    unit="dBFS",
                )
            )
        return tuple(out)

    # ---------------------------------------------------------------- bookkeeping

    @staticmethod
    def _with_unreturned(run: _Run, synth: SegmentSynthesizer) -> _Partial:
        """Usage so far, including a billed call whose audio was refused (FR-9, Q-23)."""
        calls, cost, entries = run.calls, run.cost_micros, run.cost_entry_ids
        if synth.unreturned is not None:
            entry_id, _chars, micros = synth.unreturned
            calls, cost, entries = calls + 1, cost + micros, (*entries, str(entry_id))
        return _Partial(calls, cost, entries)

    def _account(self, run: _Run, clip: ClipResult) -> None:
        """``calls`` counts the task's billed calls (also on a replay: the output of a replay equals
        the first run's); the harness counts adapter invocations separately."""
        if clip.cost_entry_id is not None:
            run.calls += 1
            run.characters += clip.characters
            run.cost_micros += clip.amount_micros
            run.cost_entry_ids += (str(clip.cost_entry_id),)
        info = self._d.storage.head(run.ctx.tenant, BlobUri(clip.clip_uri))
        run.clip_refs += (
            output_ref(
                clip.clip_uri,
                OutputRefKind.AUDIO,
                clip.clip_sha256,
                info.size_bytes or 0,
                "audio/wav",
            ),
        )

    def _checkpoint(self, run: _Run, step_key: str, done: Sequence[IdempotencyKey]) -> None:
        d, ctx = self._d, run.ctx
        state = json.dumps(
            {
                "step": step_key,
                "completed": [str(k) for k in done],
                "clips": [r.sha256 for r in run.clip_refs],
            },
            sort_keys=True,
        ).encode()
        uri = d.storage.blob_uri(
            ctx.tenant,
            "jobs",
            f"{ctx.job_id}/s07_voice/{ctx.task_id}/{ctx.attempt_id}/{step_key}.json",
        )
        info = put_once(d.storage, ctx.tenant, uri, state)
        with d.tenancy.transaction(ctx.tenant) as tx:
            d.checkpoints.write(
                tx,
                NewCheckpoint(
                    task_id=ctx.task_id,
                    attempt_id=ctx.attempt_id,
                    step_key=step_key,
                    state_ref=str(uri),
                    state_sha256=info.sha256,
                    completed_effects=tuple(done),
                    progress_ratio=Decimal(len(done)) / Decimal(max(1, len(run.segments))),
                ),
                d.clock.now(),
            )
        log_event("voice.checkpoint", ctx, step=step_key, clips=len(done))

    def _recheck_consent(self, run: _Run) -> None:
        """A withdrawal between batches stops further calls (F-04)."""
        d, ctx = self._d, run.ctx
        with d.tenancy.transaction(ctx.tenant) as tx:
            bundle = d.facts.voice_bundle(tx, run.payload.voice_id)
        if bundle is None:
            raise MissingDependencyError("voice not found")
        check_consent(
            ResolvedVoice(bundle, run.resolved.kind, run.resolved.presenter_kind),
            channel_id=ctx.channel_id,
            now=d.clock.now(),
        )


@dataclass(frozen=True, slots=True)
class _Partial:
    calls: int
    cost: int
    entries: tuple[str, ...]


class _Drained(Exception):  # noqa: N818 - control flow, not an error
    def __init__(
        self, calls: int, cost: int, entries: tuple[str, ...], refs: tuple[OutputRef, ...]
    ) -> None:
        super().__init__("drain")
        self.calls, self.cost, self.entries, self.refs = calls, cost, entries, refs


def _unwrap(doc: object) -> object:
    """Agent 06's output may be the bare payload or ``{"overall": {...}, "script_id": ...}``."""
    if isinstance(doc, dict) and "overall" in doc:
        flat = {k: v for k, v in doc.items() if k in ("script_id", "script_version")}
        flat["verification_verdict"] = doc["overall"]["verification_verdict"]
        return flat
    return doc


def _unescape_for_scan(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _wav_bytes(samples: object, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())  # type: ignore[attr-defined]
    return buffer.getvalue()


__all__ = ["VoiceDeps", "VoiceSynthesisStage"]
