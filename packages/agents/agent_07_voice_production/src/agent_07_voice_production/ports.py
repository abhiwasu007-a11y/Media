"""Ports of the Agent 07 stages: everything that touches a database row, a provider or a binary.

Dependency rule (27 section 7.1): the package imports ``amw_core`` and the narrowed stage-facing
``TtsSynthesizer`` view; the worker injects the concrete adapters. Nothing here imports another
agent. Rows are read through ``FactsReader`` inside a tenant transaction (RLS is the second line,
explicit org filters are the first); every side effect goes through an adapter with an idempotency
key.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_07_voice_production.contracts import ControlLevel, Language
from amw_adapters.tts.protocol import TtsAdapter, TtsRequest, TtsResult
from amw_core.enums import ApprovalState, LicenceSourceType, LicenceState, ThirdPartyPermission
from amw_core.ids import ChannelId, OrgId, WireId
from amw_core.interfaces.tenancy_context import TenantTransaction
from amw_core.interfaces.voices import VoiceConsentRecord, VoiceRecord

# --- TTS: capabilities and the stage-facing view (ADR-008, blueprint 9) -------------------


@dataclass(frozen=True, slots=True)
class TtsCapabilities:
    """What the chosen adapter declares (11). An undeclared control is never faked."""

    pace_control: ControlLevel
    emotion_control: ControlLevel
    phoneme_support: bool
    languages: tuple[Language, ...]
    max_chars_per_request: int | None
    markup_delimiters: tuple[str, ...] = ()
    """Provider markup delimiters beyond ``< > &`` that must be escaped (6.3 step 4)."""


@runtime_checkable
class TtsSynthesizer(Protocol):
    """The only TTS type a stage receives: ``synthesize`` and ``capabilities``. ``list_voices`` (a
    whole-account read) is deliberately absent (19.1 control 1, test S-09)."""

    @property
    def provider(self) -> str: ...

    def capabilities(self) -> TtsCapabilities: ...

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult: ...


class TtsAdapterView:
    """Narrow a full ``TtsAdapter`` to the stage-facing view. Capabilities are declared by the
    worker from the adapter's own documentation and config (the amw_adapters Protocol carries none
    yet: see core_needs in the lane report)."""

    def __init__(self, adapter: TtsAdapter, capabilities: TtsCapabilities) -> None:
        self._adapter = adapter
        self._capabilities = capabilities

    @property
    def provider(self) -> str:
        return self._adapter.provider

    def capabilities(self) -> TtsCapabilities:
        return self._capabilities

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult:
        return self._adapter.synthesize(request, idempotency_key=idempotency_key)


# --- row facts (read side of the tables of blueprint 13) ----------------------------------


@dataclass(frozen=True, slots=True)
class LicenceFacts:
    licence_id: WireId
    org_id: OrgId | None
    """None = platform-held licence (the provider terms held by the platform owner)."""
    state: LicenceState
    source_type: LicenceSourceType
    covers_monetized_youtube: bool | None
    third_party_permission: ThirdPartyPermission
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class VoiceBundle:
    """One voice with what the policy gates need, read under RLS in one transaction."""

    voice: VoiceRecord
    licence: LicenceFacts | None
    """None when ``voices.licence_id`` points at no licence row (MISSING_DEPENDENCY)."""
    consent: VoiceConsentRecord | None
    voice_owner_is_org_owner: bool


@dataclass(frozen=True, slots=True)
class ApprovalFacts:
    state: ApprovalState
    subject_sha256: str | None


@dataclass(frozen=True, slots=True)
class ScriptRowFacts:
    content_sha256: str
    """``scripts.content_sha256`` of the write-once row ``(script_id, script_version)``."""


@dataclass(frozen=True, slots=True)
class AssetFacts:
    asset_id: WireId
    org_id: OrgId
    kind: str
    active: bool
    allowed_channel_ids: tuple[ChannelId, ...] | None
    content_sha256: str


@dataclass(frozen=True, slots=True)
class JobFacts:
    monetized_destination: bool


@runtime_checkable
class FactsReader(Protocol):
    """Reads of 13 (all inside the caller's tenant transaction; a row of another org is absent)."""

    def script_row(
        self, tx: TenantTransaction, script_id: str, version: int
    ) -> ScriptRowFacts | None: ...

    def approval(self, tx: TenantTransaction, approval_id: str) -> ApprovalFacts | None: ...

    def voice_bundle(self, tx: TenantTransaction, voice_id: str) -> VoiceBundle | None: ...

    def brand_kit_voice_id(self, tx: TenantTransaction, channel_id: ChannelId) -> str | None: ...

    def job(self, tx: TenantTransaction, job_id: str) -> JobFacts | None: ...

    def org_is_platform_owner(self, tx: TenantTransaction) -> bool: ...

    def asset_by_ref(self, tx: TenantTransaction, uri: str) -> AssetFacts | None: ...

    def music_licence_rows_exist(self, tx: TenantTransaction, asset_ids: tuple[str, ...]) -> bool:
        """3B: every music asset has a ``MUSIC_BED`` licence-ledger row (D6)."""
        ...


@dataclass(frozen=True, slots=True)
class NarrationRegistration:
    """Rows of FR-14: the narration ``assets`` row and the ``licence_ledger`` ``VOICE`` row."""

    content_sha256: str
    stem_uri: str
    voice: VoiceRecord
    licence_id: WireId
    source_type: LicenceSourceType
    job_id: str
    task_id: str
    is_realistic_synthetic: bool


@dataclass(frozen=True, slots=True)
class RegisteredNarration:
    asset_id: WireId
    created: bool
    """False on a replay: the existing rows were returned and nothing was written (F-18)."""


@runtime_checkable
class NarrationRegistry(Protocol):
    def register(
        self, tx: TenantTransaction, registration: NarrationRegistration
    ) -> RegisteredNarration: ...


@runtime_checkable
class CircuitBreaker(Protocol):
    """Breaker key ``(provider, operation_class = tts.synthesize, credential_scope)`` (12.1)."""

    def is_open(self, provider: str, operation: str) -> bool: ...

    def record_failure(self, provider: str, operation: str, code: str) -> None: ...

    def record_success(self, provider: str, operation: str) -> None: ...


@runtime_checkable
class ControlPort(Protocol):
    """DRAIN / pause controls, honoured at segment and pass boundaries (FR-20)."""

    def drain_requested(self) -> bool: ...


# --- audio tools (FFmpeg and ffprobe behind a Protocol) -----------------------------------


@dataclass(frozen=True, slots=True)
class StreamFacts:
    sample_rate_hz: int
    channels: int
    duration_samples: int
    codec: str
    bit_rate_bps: int | None = None
    profile: str | None = None

    @property
    def duration_ms(self) -> int:
        return (self.duration_samples * 1000 + self.sample_rate_hz // 2) // self.sample_rate_hz


@dataclass(frozen=True, slots=True)
class Loudness:
    integrated_lufs: float | None
    true_peak_dbtp: float | None
    lra_lu: float | None


@dataclass(frozen=True, slots=True)
class SilenceSpan:
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True, slots=True)
class AudioAnalysis:
    """One measurement of a stem: format, loudness, clipping, silence and noise floor."""

    stream: StreamFacts
    loudness: Loudness
    clipping_samples: int
    peak_dbfs: float
    silence_runs: tuple[SilenceSpan, ...]
    noise_floor_dbfs: float | None


@runtime_checkable
class AudioTools(Protocol):
    """Used by the voice step: probe, analyse, convert to the working format (PCM mono 48 kHz).
    The AI worker carries the same pinned binaries as the render worker (12.2)."""

    def probe(self, path: Path) -> StreamFacts: ...

    def analyse(self, path: Path, *, silence_noise_db: float, silence_min_s: float) -> AudioAnalysis: ...

    def to_working_format(self, src: Path, dst: Path) -> None: ...
