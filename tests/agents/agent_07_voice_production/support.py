"""In-memory fakes and builders shared by the Agent 07 tests (no network, no real audio files)."""

import hashlib
import io
import shutil
import wave
from array import array
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_07_voice_production.config import AgentSevenConfig
from agent_07_voice_production.contracts import ControlLevel
from agent_07_voice_production.pcm import count_clipped, peak_dbfs, read_s16, wav_info
from agent_07_voice_production.ports import (
    ApprovalFacts,
    AssetFacts,
    AudioAnalysis,
    JobFacts,
    Loudness,
    NarrationRegistration,
    RegisteredNarration,
    ScriptRowFacts,
    StreamFacts,
    TtsCapabilities,
    VoiceBundle,
)
from amw_adapters.tts.fake import FakeTtsAdapter
from amw_adapters.tts.protocol import TtsRequest, TtsResult
from amw_core.enums import CostFigureKind
from amw_core.errors import (
    BudgetExhaustedError,
    CorruptedOutputError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
)
from amw_core.ids import ASSET, COST_ENTRY, AssetId, ChannelId, OrgId, WireId
from amw_core.interfaces.budget_guard import CallCheck
from amw_core.interfaces.cost_ledger import CostEntry, NewCostEntry
from amw_core.interfaces.storage import BlobHead, BlobInfo, BlobUri
from amw_core.interfaces.tenancy_context import TenantContext, TenantTransaction
from amw_core.testing.memory import MemoryTransaction

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
RATE = 48_000


class FakeClock:
    def __init__(self) -> None:
        self._mono = 0

    def now(self) -> datetime:
        return NOW

    def monotonic_ms(self) -> int:
        self._mono += 5
        return self._mono


class MemoryTenancy:
    @contextmanager
    def transaction(self, context: TenantContext) -> Iterator[TenantTransaction]:
        yield MemoryTransaction(context)

    def require_same_tenant(self, tx: TenantTransaction, org_id: str) -> None:
        if tx.context.org_id != org_id:
            raise CrossTenantRefError("other tenant")

    def cache_key(self, org_id: OrgId, area: str, key: str) -> str:
        return f"amw:{org_id}:{area}:{key}"


class MemoryBlobs:
    """``BlobStorage`` in memory: org check on every operation, write-once, hash-verified reads."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.reads: list[str] = []

    def blob_uri(self, context: TenantContext, area: str, path: str) -> BlobUri:
        return BlobUri(f"amw-blob://{context.org_id}/{area}/{path}")

    def _check(self, context: TenantContext, uri: str) -> None:
        owner = uri.split("://", 1)[1].split("/", 1)[0]
        if owner not in (str(context.org_id), "platform"):
            raise CrossTenantRefError("blob belongs to another tenant")

    def put(self, context: TenantContext, uri: BlobUri, stream: Any) -> BlobInfo:
        self._check(context, uri)
        if uri in self.data:
            raise InputInvalidError("write-once path already exists")
        body = stream.read()
        self.data[uri] = body
        return BlobInfo(uri, hashlib.sha256(body).hexdigest(), len(body))

    def get(self, context: TenantContext, uri: BlobUri, expected_sha256: str) -> Iterator[bytes]:
        self._check(context, uri)
        self.reads.append(uri)
        if uri not in self.data:
            raise MissingDependencyError("blob not found")
        body = self.data[uri]
        if hashlib.sha256(body).hexdigest() != expected_sha256:
            raise CorruptedOutputError("blob hash mismatch")
        yield body

    def head(self, context: TenantContext, uri: BlobUri) -> BlobHead:
        self._check(context, uri)
        body = self.data.get(uri)
        if body is None:
            return BlobHead(False, None, None)
        return BlobHead(True, hashlib.sha256(body).hexdigest(), len(body))

    def list_prefix(self, context: TenantContext, org_id: OrgId, area: str) -> list[BlobInfo]:
        return []

    def seed(self, uri: str, body: bytes) -> str:
        self.data[uri] = body
        return hashlib.sha256(body).hexdigest()


class MemoryLedger:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, CostFigureKind], CostEntry] = {}

    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        key = (str(entry.idempotency_key), entry.figure_kind)
        if key in self.rows:
            return self.rows[key]
        row = CostEntry(COST_ENTRY.new(), tx.context.org_id, entry)
        self.rows[key] = row
        return row

    def for_task(self, tx: TenantTransaction, task_id: str) -> list[CostEntry]:
        return [r for r in self.rows.values() if str(r.entry.task_id) == str(task_id)]

    def get(self, tx: TenantTransaction, entry_id: str) -> CostEntry | None:
        return next((r for r in self.rows.values() if r.id == entry_id), None)

    def for_job(self, tx: TenantTransaction, job_id: str) -> list[CostEntry]:
        return [r for r in self.rows.values() if str(r.entry.job_id) == str(job_id)]

    def job_totals(self, tx: TenantTransaction, job_id: str) -> None:
        raise NotImplementedError

    @property
    def total_micros(self) -> int:
        return sum(r.entry.amount_micros for r in self.rows.values())


class FakeBudget:
    def __init__(self, *, provider_row: bool = True, reservation_micros: int = 50_000_000) -> None:
        self.provider_row = provider_row
        self.remaining = reservation_micros

    def check_provider_gate(self, tx: TenantTransaction, provider: str) -> None:
        if not self.provider_row:
            raise BudgetExhaustedError("no ACTIVE provider budget row")

    def check_call(self, tx: TenantTransaction, check: CallCheck) -> None:
        if check.estimated_cost_micros > self.remaining:
            raise BudgetExhaustedError("estimate exceeds the reservation")

    def after_call(self, tx: TenantTransaction, entry: CostEntry) -> list[Any]:
        self.remaining -= entry.entry.amount_micros
        return []


class FakeBreaker:
    def __init__(self, *, open_: bool = False) -> None:
        self.open = open_
        self.failures: list[str] = []

    def is_open(self, provider: str, operation: str) -> bool:
        return self.open

    def record_failure(self, provider: str, operation: str, code: str) -> None:
        self.failures.append(code)

    def record_success(self, provider: str, operation: str) -> None:
        pass


class FakeControl:
    def __init__(self, *, drain: bool = False) -> None:
        self.drain = drain
        self.after_n_checks: int | None = None
        self._checks = 0

    def drain_requested(self) -> bool:
        self._checks += 1
        if self.after_n_checks is not None:
            return self._checks > self.after_n_checks
        return self.drain


@dataclass
class FakeFacts:
    script_hash: str | None = None
    approval_facts: ApprovalFacts | None = None
    bundle: VoiceBundle | None = None
    brand_kit_voice: str | None = None
    monetized: bool = True
    platform_owner: bool = True
    assets: dict[str, AssetFacts] = field(default_factory=dict)
    music_licensed: bool = True
    script_row_present: bool = True

    def script_row(
        self, tx: TenantTransaction, script_id: str, version: int
    ) -> ScriptRowFacts | None:
        if not self.script_row_present or self.script_hash is None:
            return None
        return ScriptRowFacts(self.script_hash)

    def approval(self, tx: TenantTransaction, approval_id: str) -> ApprovalFacts | None:
        return self.approval_facts

    def voice_bundle(self, tx: TenantTransaction, voice_id: str) -> VoiceBundle | None:
        return self.bundle

    def brand_kit_voice_id(self, tx: TenantTransaction, channel_id: ChannelId) -> str | None:
        return self.brand_kit_voice

    def job(self, tx: TenantTransaction, job_id: str) -> JobFacts | None:
        return JobFacts(self.monetized)

    def org_is_platform_owner(self, tx: TenantTransaction) -> bool:
        return self.platform_owner

    def asset_by_ref(self, tx: TenantTransaction, uri: str) -> AssetFacts | None:
        return self.assets.get(uri)

    def music_licence_rows_exist(self, tx: TenantTransaction, asset_ids: tuple[str, ...]) -> bool:
        return self.music_licensed


class FakeRegistry:
    def __init__(self) -> None:
        self.by_sha: dict[str, AssetId] = {}
        self.asset_rows = 0
        self.licence_rows = 0
        self.last: NarrationRegistration | None = None

    def register(
        self, tx: TenantTransaction, registration: NarrationRegistration
    ) -> RegisteredNarration:
        self.last = registration
        if registration.content_sha256 in self.by_sha:
            return RegisteredNarration(WireId(self.by_sha[registration.content_sha256]), False)
        asset = ASSET.new()
        self.by_sha[registration.content_sha256] = asset
        self.asset_rows += 1
        self.licence_rows += 1
        return RegisteredNarration(WireId(asset), True)


# --- audio ----------------------------------------------------------------------------------


def tone_samples(duration_ms: int, *, freq: float = 440.0, amplitude: float = 0.3) -> array[int]:
    """A 440 Hz square wave: never near zero, so edge trimming keeps every sample."""
    n = duration_ms * RATE // 1000
    peak = int(32767 * amplitude)
    half = RATE // (2 * int(freq))
    return array("h", (peak if (i // half) % 2 == 0 else -peak for i in range(n)))


def wav_bytes(samples: array[int], rate: int = RATE, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return buf.getvalue()


class ToneTts(FakeTtsAdapter):
    """The shared fake adapter with synthetic audio: a 440 Hz tone whose duration is
    ``characters x ms_per_char`` (a fixture parameter), or garbage on demand."""

    def __init__(self, *, ms_per_char: int = 50, behaviour: str = "OK", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ms_per_char = ms_per_char
        self.behaviour = behaviour
        self.invocations = 0
        self.requests: list[TtsRequest] = []

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult:
        self.invocations += 1
        self.requests.append(request)
        base = super().synthesize(request, idempotency_key=idempotency_key)
        if self.behaviour == "GARBAGE_ALWAYS":
            audio = b"not a wav at all"
        elif self.behaviour == "SILENT":
            audio = wav_bytes(array("h", bytes(2 * RATE)))
        else:
            audio = wav_bytes(tone_samples(len(request.text) * self.ms_per_char))
        return base.model_copy(update={"audio": audio})


def capabilities(
    *,
    pace: str = "NATIVE",
    emotion: str = "NATIVE",
    phoneme: bool = False,
    languages: tuple[str, ...] = ("mr-IN", "hi-IN"),
    max_chars: int | None = None,
) -> TtsCapabilities:
    return TtsCapabilities(ControlLevel(pace), ControlLevel(emotion), phoneme, languages, max_chars)


class ViewOf:
    """Stage-facing view over a ``ToneTts`` (no ``list_voices``)."""

    def __init__(self, adapter: ToneTts, caps: TtsCapabilities) -> None:
        self._adapter = adapter
        self._caps = caps

    @property
    def provider(self) -> str:
        return self._adapter.provider

    def capabilities(self) -> TtsCapabilities:
        return self._caps

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult:
        return self._adapter.synthesize(request, idempotency_key=idempotency_key)


class PcmTools:
    """``AudioTools`` computed from real PCM (clipping, peak) with fixed nominal loudness."""

    def probe(self, path: Path) -> StreamFacts:
        info = wav_info(path)
        return StreamFacts(info.sample_rate_hz, info.channels, info.frames, "pcm_s16le")

    def analyse(
        self, path: Path, *, silence_noise_db: float, silence_min_s: float
    ) -> AudioAnalysis:
        info, samples = read_s16(path)
        stream = StreamFacts(info.sample_rate_hz, info.channels, info.frames, "pcm_s16le")
        return AudioAnalysis(
            stream, Loudness(-20.0, -6.0, 5.0), count_clipped(samples), peak_dbfs(samples), (), None
        )

    def to_working_format(self, src: Path, dst: Path) -> None:
        shutil.copyfile(src, dst)


def config(**overrides: Any) -> AgentSevenConfig:
    values: dict[str, Any] = {
        "config_version": "test-1",
        "provider": "fake_tts",
        "model_ref": "fake-model",
        "gap_ms": 300,
        "trim_keep_ms": 0,
        "price_micros_per_1k_chars": 80_000,
        "price_ref": "fake-pricing-v0",
        "sample_max_segments": 2,
    }
    values.update(overrides)
    return AgentSevenConfig.checked(**values)
