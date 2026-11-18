"""One paid TTS call per sentence (F-10, F-11, FR-9, FR-10).

Order for every call: idempotency key, then (before any I/O) breaker, provider budget gate and
call budget; the call; clip validation; clip blob; and in one transaction the ledger row and the
``COMPLETED`` key. A replay (``COMPLETED`` with the same request hash) returns the stored clip and
performs no call (NFR-2). A call whose audio fails validation is not stored and not completed
(the key returns to ``FAILED``); the orchestrator retries the task from its checkpoint.
"""

import hashlib
import io
import tempfile
import time
import wave
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from agent_07_voice_production.config import AgentSevenConfig
from agent_07_voice_production.context import AGENT_ID, ExecContext
from agent_07_voice_production.pcm import decode_s16_bytes, trim_silence
from agent_07_voice_production.ports import AudioTools, CircuitBreaker, TtsSynthesizer
from agent_07_voice_production.text import PreparedSegment
from amw_adapters.common import request_sha256
from amw_adapters.tts.protocol import OPERATION_SYNTHESIZE, TtsRequest
from amw_core.enums import CostFigureKind, CostOperation, CostUnitKind, IdempotencyStatus
from amw_core.errors import (
    CircuitOpenError,
    CorruptedOutputError,
    LockConflictError,
    TemporaryError,
)
from amw_core.ids import (
    CostEntryId,
    IdempotencyKey,
    IdempotencyScope,
    executor_id,
    make_idempotency_key,
)
from amw_core.interfaces.budget_guard import BudgetGuard, CallCheck
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostEntry, CostLedger, NewCostEntry
from amw_core.interfaces.idempotency_store import BeginAction, IdempotencyStore
from amw_core.interfaces.storage import BlobStorage, BlobUri
from amw_core.interfaces.tenancy_context import TenancyContext

CLIP_MEDIA_TYPES = ("audio/wav", "audio/x-wav", "audio/wave")


def estimate_micros(characters: int, price_micros_per_1k_chars: int) -> int:
    """F-27: ``ceil(characters x price per 1 000 characters / 1 000)`` in integer arithmetic."""
    return -(-characters * price_micros_per_1k_chars // 1000)


def tts_key(
    ctx: ExecContext, segment_id: str, spoken_text_sha256: str, voice_id: str
) -> IdempotencyKey:
    """03 section 9.2 key of scope ``tts.synthesize``: (task, segment, spoken-text hash, voice)."""
    return make_idempotency_key(
        ctx.org_id,
        IdempotencyScope.TTS_SYNTHESIZE,
        [ctx.task_id, segment_id, spoken_text_sha256, voice_id],
    )


@dataclass(frozen=True, slots=True)
class ClipResult:
    segment_id: str
    samples: array[int]
    clip_uri: str
    clip_sha256: str
    spoken_text_sha256: str
    idempotency_key: IdempotencyKey
    called_provider: bool
    characters: int
    cost_entry_id: CostEntryId | None
    amount_micros: int


@dataclass(frozen=True, slots=True)
class SynthesisSettings:
    voice_id: str
    voice_ref: str
    model_ref: str
    language: str
    provider: str


class SegmentSynthesizer:
    def __init__(
        self,
        *,
        tts: TtsSynthesizer,
        idempotency: IdempotencyStore,
        ledger: CostLedger,
        budget: BudgetGuard,
        breaker: CircuitBreaker,
        storage: BlobStorage,
        tenancy: TenancyContext,
        clock: Clock,
        config: AgentSevenConfig,
        tools: AudioTools,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._tts = tts
        self._idem = idempotency
        self._ledger = ledger
        self._budget = budget
        self._breaker = breaker
        self._storage = storage
        self._tenancy = tenancy
        self._clock = clock
        self._config = config
        self._tools = tools
        self._sleep = sleep
        self.unreturned: tuple[CostEntryId, int, int] | None = None
        """(entry id, characters, micros) of a call that was billed and recorded but whose audio was
        then refused or could not be stored; ``None`` otherwise."""

    # -- guards that run before any I/O -------------------------------------------------

    def guard(self, ctx: ExecContext, provider: str, estimated_micros: int) -> None:
        """Fail closed: breaker, provider budget row and reservation (NFR-3; zero network calls)."""
        if self._breaker.is_open(provider, OPERATION_SYNTHESIZE):
            raise CircuitOpenError("the provider circuit breaker is open", provider=provider)
        with self._tenancy.transaction(ctx.tenant) as tx:
            self._budget.check_provider_gate(tx, provider)
            self._budget.check_call(
                tx,
                CallCheck(
                    task_id=ctx.task_id,
                    job_id=ctx.job_id,
                    provider=provider,
                    estimated_cost_micros=estimated_micros,
                    currency=self._config.currency,
                ),
            )

    # -- one sentence -----------------------------------------------------------------

    def synthesize(
        self, ctx: ExecContext, prepared: PreparedSegment, settings: SynthesisSettings
    ) -> ClipResult:
        cfg = self._config
        assert cfg.price_micros_per_1k_chars is not None  # noqa: S101 - require_voice()
        assert cfg.idempotency_lock_ms is not None  # noqa: S101 - require_voice()
        self.unreturned = None
        key = tts_key(ctx, prepared.segment_id, prepared.spoken_text_sha256, settings.voice_id)
        request = TtsRequest(
            text=prepared.spoken_text,
            voice_ref=settings.voice_ref,
            model=settings.model_ref,
            language=settings.language,
            sample_rate_hz=cfg.sample_rate_hz,
        )
        request_hash = request_sha256(request)
        estimate = estimate_micros(prepared.characters, cfg.price_micros_per_1k_chars)
        with self._tenancy.transaction(ctx.tenant) as tx:
            decision = self._idem.begin(
                tx,
                key,
                IdempotencyScope.TTS_SYNTHESIZE,
                request_hash,
                ctx.task_id,
                self._clock.now(),
                cfg.idempotency_lock_ms,
            )
        if decision.action is BeginAction.RETURN_STORED:
            return self._stored(ctx, prepared, key, decision.record.result_ref)
        if decision.action is BeginAction.IN_FLIGHT:
            raise LockConflictError("another attempt holds the idempotency key")
        try:
            self.guard(ctx, settings.provider, estimate)
            result = self._call(request, key, settings.provider)
        except BaseException:
            self._fail_key(ctx, key)
            raise
        # FR-9, Q-23: every call that returned a response is recorded (ESTIMATE) and debited
        # before the audio is judged, so a garbage or unstorable return cannot escape the budget.
        entry = self._record_call(ctx, prepared, settings, key, estimate)
        self.unreturned = (entry.id, prepared.characters, estimate)
        try:
            samples = self._validate(result.audio, result.media_type, prepared)
            clip_uri, clip_sha = self._store_clip(ctx, prepared, samples)
        except BaseException:
            self._fail_key(ctx, key)
            raise
        with self._tenancy.transaction(ctx.tenant) as tx:
            self._idem.complete(tx, key, clip_uri, self._clock.now())
        self.unreturned = None
        return ClipResult(
            prepared.segment_id,
            samples,
            clip_uri,
            clip_sha,
            prepared.spoken_text_sha256,
            key,
            True,
            prepared.characters,
            entry.id,
            estimate,
        )

    def _record_call(
        self,
        ctx: ExecContext,
        prepared: PreparedSegment,
        settings: SynthesisSettings,
        key: IdempotencyKey,
        estimate: int,
    ) -> CostEntry:
        cfg = self._config
        with self._tenancy.transaction(ctx.tenant) as tx:
            entry = self._ledger.record(
                tx,
                NewCostEntry(
                    provider=settings.provider,
                    operation=CostOperation.TTS_SYNTHESIZE,
                    amount_micros=estimate,
                    currency=cfg.currency,
                    figure_kind=CostFigureKind.ESTIMATE,
                    occurred_at=self._clock.now(),
                    job_id=ctx.job_id,
                    task_id=ctx.task_id,
                    attempt_id=ctx.attempt_id,
                    channel_id=ctx.channel_id,
                    agent_id=executor_id(AGENT_ID),
                    model=settings.model_ref,
                    chars_in=prepared.characters,
                    language=settings.language,
                    units=Decimal(prepared.characters),
                    unit_kind=CostUnitKind.CHARACTERS,
                    price_ref=cfg.price_ref,
                    idempotency_key=key,
                ),
            )
            self._budget.after_call(tx, entry)
        return entry

    # -- internals --------------------------------------------------------------------

    def _call(self, request: TtsRequest, key: IdempotencyKey, provider: str):  # type: ignore[no-untyped-def]  # noqa: ANN202
        retries, max_wait = self._config.max_attempt_retries, self._config.max_retry_after_ms
        assert retries is not None  # noqa: S101 - require_voice()
        assert max_wait is not None  # noqa: S101 - require_voice()
        attempts = retries + 1
        for number in range(1, attempts + 1):
            try:
                result = self._tts.synthesize(request, idempotency_key=key)
            except TemporaryError as exc:
                self._breaker.record_failure(provider, OPERATION_SYNTHESIZE, exc.code)
                if number == attempts or (
                    exc.retry_after_ms is not None and exc.retry_after_ms > max_wait
                ):
                    raise
                self._sleep((exc.retry_after_ms or 0) / 1000)
                continue
            self._breaker.record_success(provider, OPERATION_SYNTHESIZE)
            return result
        raise AssertionError("unreachable")  # pragma: no cover

    def _validate(self, audio: bytes, media_type: str, prepared: PreparedSegment) -> array[int]:
        """F-11: decodable, non-empty, not silent, duration inside the plausibility band; converted
        to PCM mono 48 000 Hz; edges trimmed to ``trim_keep_ms``."""
        cfg = self._config
        assert cfg.trim_keep_ms is not None  # noqa: S101 - require_voice()
        if media_type not in CLIP_MEDIA_TYPES or not audio:
            raise CorruptedOutputError("provider audio is empty or not WAV")
        info, samples = decode_s16_bytes(audio)
        if info.frames == 0:
            raise CorruptedOutputError("provider audio has no samples")
        if info.sample_rate_hz != cfg.sample_rate_hz or info.channels != 1:
            samples = self._convert(audio)
        trimmed = trim_silence(samples, cfg.sample_rate_hz, cfg.trim_keep_ms, cfg.silence_noise_db)
        duration_ms = len(trimmed) * 1000 // cfg.sample_rate_hz
        low, high = cfg.clip_min_ms_per_char, cfg.clip_max_ms_per_char
        if (low is not None and duration_ms < low * prepared.characters) or (
            high is not None and duration_ms > high * prepared.characters
        ):
            raise CorruptedOutputError("provider audio duration is implausible for the text")
        return trimmed

    def _convert(self, audio: bytes) -> array[int]:
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp, "clip_in.wav"), Path(tmp, "clip_out.wav")
            src.write_bytes(audio)
            self._tools.to_working_format(src, dst)
            _, samples = decode_s16_bytes(dst.read_bytes())
        return samples

    def _store_clip(
        self, ctx: ExecContext, prepared: PreparedSegment, samples: array[int]
    ) -> tuple[str, str]:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self._config.sample_rate_hz)
            handle.writeframes(samples.tobytes())
        data = buffer.getvalue()
        sha = hashlib.sha256(data).hexdigest()
        uri = self._storage.blob_uri(
            ctx.tenant, "jobs", f"{ctx.job_id}/s07_voice/clips/{prepared.segment_id}-{sha[:16]}.wav"
        )
        if not self._storage.head(ctx.tenant, uri).exists:
            self._storage.put(ctx.tenant, uri, io.BytesIO(data))
        return uri, sha

    def _stored(
        self,
        ctx: ExecContext,
        prepared: PreparedSegment,
        key: IdempotencyKey,
        result_ref: str | None,
    ) -> ClipResult:
        """A replay (DLQ replay, retry after output loss): the stored clip and its original ledger
        row; no provider call, no new row (NFR-2, SC-6)."""
        if result_ref is None:
            raise CorruptedOutputError("a completed key without a stored clip")
        uri = BlobUri(result_ref)
        head = self._storage.head(ctx.tenant, uri)
        if not head.exists or head.sha256 is None:
            raise CorruptedOutputError("the stored clip is missing")
        data = b"".join(self._storage.get(ctx.tenant, uri, head.sha256))
        _, samples = decode_s16_bytes(data)
        with self._tenancy.transaction(ctx.tenant) as tx:
            original = next(
                (
                    e
                    for e in self._ledger.for_task(tx, ctx.task_id)
                    if e.entry.idempotency_key == key
                ),
                None,
            )
        return ClipResult(
            prepared.segment_id,
            samples,
            str(uri),
            head.sha256,
            prepared.spoken_text_sha256,
            key,
            False,
            prepared.characters,
            original.id if original is not None else None,
            original.entry.amount_micros if original is not None else 0,
        )

    def _fail_key(self, ctx: ExecContext, key: IdempotencyKey) -> None:
        with self._tenancy.transaction(ctx.tenant) as tx:
            record = self._idem.get(tx, key)
            if record is not None and record.status is IdempotencyStatus.IN_PROGRESS:
                self._idem.fail(tx, key, self._clock.now())


__all__ = ["ClipResult", "SegmentSynthesizer", "SynthesisSettings", "estimate_micros", "tts_key"]
