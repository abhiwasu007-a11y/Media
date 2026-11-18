"""Pydantic models of the agent-owned payloads (blueprint 7 and 8) and of the script document.

The JSON Schemas live in the blueprint (agent-owned, 24 section 3.2); these models are the typed
side and are checked against those schemas by the contract tests (C-01...C-06). No script text,
spoken text, consent person data or provider voice reference appears in any output model.
"""

from enum import StrEnum
from typing import Annotated, ClassVar, Literal

from pydantic import Field, StringConstraints

from amw_core.contracts.common import AmwModel, Sha256Hex, StorageUri
from amw_core.enums import PresenterKind, VoiceKind

_UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
ScriptId = Annotated[str, StringConstraints(pattern=rf"^scr_{_UUID7}$")]
VoiceId = Annotated[str, StringConstraints(pattern=rf"^vce_{_UUID7}$")]
LicenceId = Annotated[str, StringConstraints(pattern=rf"^lic_{_UUID7}$")]
ConsentId = Annotated[str, StringConstraints(pattern=rf"^vcn_{_UUID7}$")]
AssetId = Annotated[str, StringConstraints(pattern=rf"^ast_{_UUID7}$")]
ApprovalId = Annotated[str, StringConstraints(pattern=rf"^apr_{_UUID7}$")]
CostEntryRef = Annotated[str, StringConstraints(pattern=rf"^cst_{_UUID7}$")]
Language = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")]
SegmentId = Annotated[str, StringConstraints(pattern=r"^s[0-9]{1,4}$")]
EntryId = Annotated[str, StringConstraints(pattern=r"^d[0-9]{1,5}$")]
CheckId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.-]{3,96}$")]
NonNeg = Annotated[int, Field(ge=0)]

SCHEMA_VOICE_INPUT = "agent_07.voice_synthesis.input"
SCHEMA_VOICE_OUTPUT = "agent_07.voice_synthesis.output"
SCHEMA_MASTER_INPUT = "agent_07.audio_master.input"
SCHEMA_MASTER_OUTPUT = "agent_07.audio_master.output"
SCHEMA_VERSION = "1.0.0"


class Pace(StrEnum):
    SLOW = "SLOW"
    NORMAL = "NORMAL"
    FAST = "FAST"


class AppliedPace(StrEnum):
    SLOW = "SLOW"
    NORMAL = "NORMAL"
    FAST = "FAST"
    NONE = "NONE"


class Emotion(StrEnum):
    NEUTRAL = "NEUTRAL"
    CURIOUS = "CURIOUS"
    SERIOUS = "SERIOUS"
    WARM = "WARM"
    ENERGETIC = "ENERGETIC"
    EMPHASIS = "EMPHASIS"


class AppliedEmotion(StrEnum):
    NEUTRAL = "NEUTRAL"
    CURIOUS = "CURIOUS"
    SERIOUS = "SERIOUS"
    WARM = "WARM"
    ENERGETIC = "ENERGETIC"
    EMPHASIS = "EMPHASIS"
    NONE = "NONE"


class Purpose(StrEnum):
    PRODUCTION = "PRODUCTION"
    SAMPLE = "SAMPLE"


class TimelineSource(StrEnum):
    """No ``UNALIGNED`` value in 3A: a recording without marks is refused (CCR-051)."""

    PROVIDER_CLIPS = "PROVIDER_CLIPS"
    OWNER_MARKS = "OWNER_MARKS"


class PauseKind(StrEnum):
    GAP = "GAP"
    SCENE_PAUSE = "SCENE_PAUSE"


class UnknownTermSource(StrEnum):
    SCRIPT_CANDIDATE = "SCRIPT_CANDIDATE"
    NUMERAL = "NUMERAL"
    MARKUP_CHARACTER = "MARKUP_CHARACTER"


class ReplacementMode(StrEnum):
    SPOKEN_FORM = "SPOKEN_FORM"
    PHONEME = "PHONEME"


class EntryKind(StrEnum):
    NAME = "NAME"
    ENGLISH_TERM = "ENGLISH_TERM"
    ACRONYM = "ACRONYM"
    NUMBER = "NUMBER"
    OTHER = "OTHER"


class MatchType(StrEnum):
    LITERAL = "LITERAL"
    WORD = "WORD"


class ControlLevel(StrEnum):
    NONE = "NONE"
    NATIVE = "NATIVE"


class DenoiseOut(StrEnum):
    OFF = "OFF"
    LIGHT = "LIGHT"


# --- script document (agent_05.script_document, read-only here) ----------------------------


class ScriptSegment(AmwModel):
    segment_id: SegmentId
    text: str
    pace: Pace
    emotion: Emotion
    scene_id: str


class ScriptScene(AmwModel):
    scene_id: str
    deliberate_pause_ms: NonNeg
    pronunciation_candidates: tuple[str, ...] = ()


class ScriptDocument(AmwModel):
    """The slice of ``agent_05.script_document`` Agent 07 reads (15.1). Text never leaves the
    stage: payloads, logs and outputs carry segment IDs and hashes only."""

    segments: Annotated[tuple[ScriptSegment, ...], Field(min_length=1)]
    scenes: tuple[ScriptScene, ...]


class VerificationOutput(AmwModel):
    """The slice of ``agent_06.claim_verification.output`` Agent 07 reads (FR-2)."""

    script_id: ScriptId
    script_version: Annotated[int, Field(ge=1)]
    verification_verdict: Literal["ALLOWED", "BLOCKED", "NEEDS_HUMAN_REVIEW"]


# --- voice synthesis input ------------------------------------------------------------------


class SegmentMark(AmwModel):
    segment_id: SegmentId
    start_ms: NonNeg
    end_ms: Annotated[int, Field(ge=1)]


class HumanNarration(AmwModel):
    asset_ref: StorageUri
    asset_sha256: Sha256Hex
    attests_follows_verified_script: bool
    segment_marks: Annotated[tuple[SegmentMark, ...], Field(min_length=1, max_length=500)]


class VoiceSynthesisInput(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset()

    purpose: Purpose
    script_id: ScriptId
    script_version: Annotated[int, Field(ge=1)]
    iteration: NonNeg
    language: Language
    script_ref: StorageUri
    script_sha256: Sha256Hex
    verification_ref: StorageUri
    verification_approval_id: ApprovalId | None = None
    voice_id: VoiceId
    dictionary_ref: StorageUri
    dictionary_sha256: Sha256Hex | None = None
    human_narration: HumanNarration | None = None


# --- audio master input ---------------------------------------------------------------------


class MusicStemInput(AmwModel):
    stem_ref: StorageUri
    stem_sha256: Sha256Hex
    asset_ids: Annotated[tuple[AssetId, ...], Field(min_length=1)]


class PauseSpan(AmwModel):
    start_ms: NonNeg
    end_ms: Annotated[int, Field(ge=1)]


class AudioMasterInput(AmwModel):
    iteration: NonNeg
    narration_ref: StorageUri
    narration_sha256: Sha256Hex
    timeline_ref: StorageUri
    timeline_sha256: Sha256Hex
    music_stem: MusicStemInput | None = None
    deliberate_pause_spans: Annotated[tuple[PauseSpan, ...], Field(max_length=200)] = ()


# --- pronunciation dictionary (7.4) ---------------------------------------------------------


class DictMatch(AmwModel):
    type: MatchType
    value: Annotated[str, Field(min_length=1, max_length=64)]
    case_sensitive: bool = True


class DictReplacement(AmwModel):
    omit_if_none: ClassVar[frozenset[str]] = frozenset()

    mode: ReplacementMode
    text: Annotated[str, Field(min_length=1, max_length=128)]
    phoneme_alphabet: Annotated[str, Field(max_length=32)] | None = None


class DictEntry(AmwModel):
    entry_id: EntryId
    kind: EntryKind
    match: DictMatch
    replacement: DictReplacement


class DictionaryDocument(AmwModel):
    dictionary_key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.-]{3,64}$")]
    language: Language
    version: Annotated[int, Field(ge=1)]
    entries: Annotated[tuple[DictEntry, ...], Field(max_length=5000)]


# --- voice synthesis output -----------------------------------------------------------------


class VoiceBlock(AmwModel):
    voice_id: VoiceId
    voice_kind: VoiceKind
    licence_id: LicenceId
    provider: Annotated[str, Field(max_length=64)] | None
    model_ref: Annotated[str, Field(max_length=128)] | None
    consent_id: ConsentId | None
    presenter_kind: PresenterKind


class NarrationBlock(AmwModel):
    stem_uri: StorageUri
    sha256: Sha256Hex
    duration_ms: NonNeg
    sample_rate_hz: Literal[48000]
    channels: Literal[1]
    asset_id: AssetId | None


class TimelineSegment(AmwModel):
    segment_id: SegmentId
    start_ms: NonNeg
    end_ms: Annotated[int, Field(ge=1)]
    duration_ms: Annotated[int, Field(ge=1)]
    pace_requested: Pace
    emotion_requested: Emotion
    pace_applied: AppliedPace
    emotion_applied: AppliedEmotion
    spoken_text_sha256: Sha256Hex | None
    reused_clip: bool
    idempotency_key: Annotated[str, Field(max_length=256)] | None


class TimelinePause(AmwModel):
    after_segment_id: SegmentId
    start_ms: NonNeg
    end_ms: Annotated[int, Field(ge=1)]
    kind: PauseKind


class TimelineBlock(AmwModel):
    source: TimelineSource
    timeline_uri: StorageUri
    timeline_sha256: Sha256Hex
    segments: Annotated[tuple[TimelineSegment, ...], Field(max_length=500)]
    pauses: tuple[TimelinePause, ...] = ()


class DictionaryHit(AmwModel):
    entry_id: EntryId
    segment_id: SegmentId
    count: Annotated[int, Field(ge=1)]
    mode: ReplacementMode


class UnknownTerm(AmwModel):
    term_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    segment_ids: tuple[SegmentId, ...]
    source: UnknownTermSource


class DictionaryBlock(AmwModel):
    asset_id: AssetId
    version: Annotated[int, Field(ge=1)]
    dictionary_sha256: Sha256Hex
    hits_total: NonNeg
    hits: tuple[DictionaryHit, ...]
    unknown_terms: tuple[UnknownTerm, ...]


class SilenceRun(AmwModel):
    start_ms: int
    end_ms: int


class VoiceMeasurements(AmwModel):
    clipping_samples: NonNeg
    peak_dbfs: float
    noise_floor_dbfs: float | None
    integrated_lufs: float | None
    silence_runs: tuple[SilenceRun, ...]


class IntakeBlock(AmwModel):
    source_sha256: Sha256Hex
    source_sample_rate_hz: Annotated[int, Field(ge=8000)]
    source_channels: Annotated[int, Field(ge=1, le=8)]
    source_duration_ms: Annotated[int, Field(ge=1)]
    attestation_recorded: Literal[True]
    marks_count: Annotated[int, Field(ge=1)]


class CostBlock(AmwModel):
    calls: NonNeg
    reused_clips: NonNeg
    characters: NonNeg
    unit_kind: Literal["characters", "audio_ms"]
    figure_kind: Literal["ESTIMATE"]
    cost_entry_ids: tuple[CostEntryRef, ...]


class AdapterCapabilitiesOut(AmwModel):
    pace_control: ControlLevel
    emotion_control: ControlLevel
    phoneme_support: bool
    languages: tuple[Language, ...]
    max_chars_per_request: Annotated[int, Field(ge=1)] | None


class VoiceProvenance(AmwModel):
    adapter: Annotated[str, Field(max_length=64)]
    adapter_capabilities: AdapterCapabilitiesOut
    config_version: Annotated[str, Field(max_length=64)]
    script_sha256: Sha256Hex
    dictionary_sha256: Sha256Hex


class VoiceSynthesisOutput(AmwModel):
    purpose: Purpose
    script_id: ScriptId
    script_version: Annotated[int, Field(ge=1)]
    iteration: NonNeg
    language: Language
    voice: VoiceBlock
    narration: NarrationBlock
    timeline: TimelineBlock
    dictionary: DictionaryBlock
    voice_measurements: VoiceMeasurements
    intake: IntakeBlock | None
    cost: CostBlock
    provenance: VoiceProvenance


# --- audio master output --------------------------------------------------------------------


class GateReason(AmwModel):
    check_id: CheckId
    measured: float | str | None
    threshold: float | str | None
    remedy_stage_id: Literal["s07_voice"]


class MasterFileBlock(AmwModel):
    master_uri: StorageUri
    sha256: Sha256Hex
    duration_ms: Annotated[int, Field(ge=1)]
    sample_rate_hz: Literal[48000]
    channels: Literal[2]


class LoudnessBlock(AmwModel):
    integrated_lufs: float | None
    true_peak_dbtp: float | None
    lra_lu: float | None


class MasterSilenceRun(AmwModel):
    start_ms: int
    end_ms: int
    in_deliberate_pause: bool


class MasterMeasurements(AmwModel):
    pre: LoudnessBlock
    post: LoudnessBlock
    clipping_samples: NonNeg
    silence_runs: tuple[MasterSilenceRun, ...]
    noise_floor_dbfs: float | None
    duration_delta_samples: int


class MasteringBlock(AmwModel):
    passes: Annotated[int, Field(ge=1)]
    gain_db: float
    limiter_ceiling_dbtp: float
    limiter_gain_reduction_db: float
    denoise_mode: DenoiseOut


class CodecVerificationBlock(AmwModel):
    codec: Literal["aac"]
    profile: Literal["LC"]
    sample_rate_hz: Literal[48000]
    channels: Literal[2]
    bitrate_bps: Annotated[int, Field(ge=384_000)]
    post_codec: LoudnessBlock


class CodecProfileBlock(AmwModel):
    codec: Literal["aac"]
    profile: Literal["LC"]
    sample_rate_hz: Literal[48000]
    channels: Literal[2]
    bitrate_bps: Annotated[int, Field(ge=384_000)]
    encoder: Annotated[str, Field(min_length=1, max_length=64)]
    rate_mode: Annotated[str, Field(min_length=1, max_length=16)]


class MusicOut(AmwModel):
    offset_db: float
    asset_ids: Annotated[tuple[AssetId, ...], Field(min_length=1)]
    stem_uri: StorageUri
    stem_sha256: Sha256Hex
    licence_rows_verified: Literal[True]


class MasterProvenance(AmwModel):
    ffmpeg_build: Annotated[str, Field(max_length=128)]
    config_version: Annotated[str, Field(max_length=64)]
    narration_sha256: Sha256Hex
    timeline_sha256: Sha256Hex


class AudioMasterOutput(AmwModel):
    gate_verdict: Literal["PASSED", "FAILED"]
    gate_reasons: tuple[GateReason, ...]
    iteration: NonNeg
    master: MasterFileBlock
    measurements: MasterMeasurements
    mastering: MasteringBlock
    codec_verification: CodecVerificationBlock
    codec_profile: CodecProfileBlock
    music: MusicOut | None
    provenance: MasterProvenance


# --- narration timeline blob (hash-chained hand-off to Agent 09 / 10) ------------------------


class NarrationTimeline(AmwModel):
    """The write-once timeline document that ``audio_master`` and Agent 10 read by hash."""

    script_id: ScriptId
    script_version: Annotated[int, Field(ge=1)]
    iteration: NonNeg
    purpose: Purpose = Purpose.PRODUCTION
    """A SAMPLE stem is never mastered (M1: refuse SAMPLE stems)."""
    source: TimelineSource
    total_duration_ms: Annotated[int, Field(ge=1)]
    segments: tuple[TimelineSegment, ...]
    pauses: tuple[TimelinePause, ...] = ()
