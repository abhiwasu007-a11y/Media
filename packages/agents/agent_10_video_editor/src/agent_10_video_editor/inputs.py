"""Typed views of the upstream documents Agent 10 consumes (blueprint 10 section 15.1).

Field names are quoted from the producers' blueprints (agent_09 section 8.1 / 8.2, agent_08
section 8.2, agent_07 section 15.2); nothing is redefined. Models ignore fields Agent 10 does not
read (``extra = ignore``) so a producer may add fields; a missing required field is a typed
validation error. All models are frozen.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

from agent_10_video_editor.canonical import sha256_hex
from agent_10_video_editor.taskio import parse_blob

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ShotId = Annotated[str, StringConstraints(pattern=r"^sh[0-9]{2,4}$")]
OverlayId = Annotated[str, StringConstraints(pattern=r"^ov[0-9]{2,4}$")]
Aspect = Literal["16:9", "9:16"]
Tier = Literal["A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO", "E_AI_STILL"]
OverlayKind = Literal[
    "BRAND_STING", "LOWER_THIRD", "CAPTION_CARD", "CHAPTER_CARD", "DISCLAIMER_CARD", "END_SCREEN"
]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Held(_Model):
    reason: str
    max_ms: StrictInt


class Transition(_Model):
    kind: Literal["CUT", "CROSS_DISSOLVE", "PUSH", "ZOOM_THROUGH"] = "CUT"
    duration_ms: StrictInt = 0


class TextRef(_Model):
    sha256: Sha256
    scene_id: str | None = None
    index: StrictInt | None = None
    disclaimer_slot_id: str | None = None


class PlanShot(_Model):
    shot_id: ShotId
    start_ms: StrictInt
    end_ms: StrictInt
    intent_kind: Literal["FOOTAGE", "CHART", "DIAGRAM", "TEXT_CARD"] = "FOOTAGE"
    motion: str = "STATIC"
    explanatory: bool = True
    held: Held | None = None
    change_events_ms: tuple[StrictInt, ...] = ()
    transition_in: Transition = Transition()
    text_refs: tuple[TextRef, ...] = ()
    segment_ids: tuple[str, ...] = ()
    cut_offset_ms: StrictInt = 0
    jl_kind: Literal["J", "L"] | None = None
    interrupt: dict[str, str] | None = None
    section_id: str | None = None


class PlanOverlay(_Model):
    overlay_id: OverlayId
    kind: OverlayKind
    start_ms: StrictInt
    end_ms: StrictInt
    template_ref: str | None = None
    text_refs: tuple[TextRef, ...] = ()


class Interval(_Model):
    start_ms: StrictInt
    end_ms: StrictInt


class Hold(Interval):
    shot_id: ShotId | None = None
    reason: str | None = None


class Hook(_Model):
    end_ms: StrictInt
    first_payoff_ms: StrictInt


class Chapter(_Model):
    section_id: str | None = None
    start_ms: StrictInt


class AudioPlan(_Model):
    deliberate_pauses: tuple[Interval, ...] = ()


class TierBudget(_Model):
    ai_video_limit_ms: StrictInt | None = None


class ShotPlan(_Model):
    """``agent_09.shot_plan.output`` blob (the fields Agent 10 reads)."""

    timing_basis: str
    language: str
    aspect_ratio: Aspect
    total_duration_ms: StrictInt
    content_end_ms: StrictInt
    narration_timeline_sha256: Sha256 | None = None
    script_sha256: Sha256 | None = None
    hook: Hook | None = None
    shots: tuple[PlanShot, ...]
    overlays: tuple[PlanOverlay, ...] = ()
    audio_plan: AudioPlan = AudioPlan()
    chapters: tuple[Chapter, ...] = ()
    deliberate_black: tuple[Interval, ...] = ()
    deliberate_hold: tuple[Hold, ...] = ()
    tier_budget: TierBudget = TierBudget()


class Crop(_Model):
    mode: Literal["NONE", "CENTER_CROP", "ANCHOR_CROP"] = "NONE"
    anchor: Literal["CENTER", "UPPER_THIRD", "LOWER_THIRD", "LEFT", "RIGHT"] | None = None
    keep_permille: Annotated[int, Field(ge=1, le=1000)] = 1000


class Media(_Model):
    width_px: StrictInt
    height_px: StrictInt
    duration_ms: StrictInt | None = None
    source_in_ms: StrictInt = 0
    crop: Crop = Crop()


class Fingerprints(_Model):
    sha256: Sha256


class Disclosure(_Model):
    """The manifest disclosure record (agent_08 D15): both flags are required when it exists."""

    is_realistic_synthetic: bool
    depicts_real_person: bool


class ChartInfo(_Model):
    chart_id: str
    data_end_date: str | None = None


class RevealStill(_Model):
    k: StrictInt
    asset_id: str
    asset_uri: str
    sha256: Sha256
    start_ms: StrictInt
    end_ms: StrictInt
    licence_id: str | None = None
    ledger_entry_ids: tuple[str, ...] = ()


class ManifestShot(_Model):
    shot_id: ShotId
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:5"]
    status: Literal["SOURCED", "REUSED", "UNRESOLVED"]
    tier: Tier | None = None
    asset_id: str | None = None
    asset_uri: str | None = None
    source_type: str | None = None
    licence_id: str | None = None
    ledger_entry_ids: tuple[str, ...] = ()
    usage_kind: str | None = None
    media: Media | None = None
    fingerprints: Fingerprints | None = None
    chart: ChartInfo | None = None
    reveal_stills: tuple[RevealStill, ...] = ()
    disclosure: Disclosure | None = None
    start_ms: StrictInt | None = None
    end_ms: StrictInt | None = None


class ManifestOverlay(_Model):
    overlay_id: OverlayId
    kind: OverlayKind
    template_asset_id: str
    licence_id: str | None = None
    ledger_entry_ids: tuple[str, ...] = ()
    usage_kind: str | None = None


class ManifestFont(_Model):
    asset_id: str
    licence_id: str | None = None
    used_from_ms: StrictInt = 0
    used_to_ms: StrictInt


class ManifestMusic(_Model):
    asset_id: str
    licence_id: str | None = None
    used_from_ms: StrictInt
    used_to_ms: StrictInt


class AssetManifest(_Model):
    """``agent_08.asset_sourcing.output`` (the fields Agent 10 reads)."""

    gate_verdict: Literal["PASSED", "FAILED"] = "PASSED"
    shots: tuple[ManifestShot, ...]
    overlays: tuple[ManifestOverlay, ...] = ()
    fonts: tuple[ManifestFont, ...] = ()
    music_beds: tuple[ManifestMusic, ...] = ()
    unresolved_shot_ids: tuple[ShotId, ...] = ()


class AssetRecord(_Model):
    """One ``assets`` row as far as Agent 10 reads it (04 section 5.15)."""

    asset_id: str
    uri: str
    sha256: Sha256
    status: str = "ACTIVE"
    media_type: str | None = None
    ai_item: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)
    """``assets.attributes`` (04 section 5.15); a ``TEMPLATE`` asset carries ``template_id``."""


class CodecProfile(_Model):
    codec: str
    profile: str
    sample_rate_hz: StrictInt
    channels: StrictInt
    bitrate_bps: StrictInt
    encoder: str
    rate_mode: str


class AudioMasterInfo(_Model):
    master_uri: str
    sha256: Sha256
    duration_ms: StrictInt
    sample_rate_hz: StrictInt = 48000
    channels: StrictInt = 2


class AudioMaster(_Model):
    """``agent_07.audio_master`` output (agent_07 section 15.2)."""

    master: AudioMasterInfo
    codec_profile: CodecProfile
    gate_verdict: Literal["PASSED", "FAILED"]
    clipping_samples: StrictInt = 0


class NarrationSegment(_Model):
    segment_id: str
    start_ms: StrictInt
    end_ms: StrictInt


class NarrationTimeline(_Model):
    """``agent_07.voice_synthesis`` timeline (agent_07 section 8)."""

    source: Literal["PROVIDER_CLIPS", "OWNER_MARKS", "UNALIGNED"]
    language: str | None = None
    segments: tuple[NarrationSegment, ...]
    end_ms: StrictInt | None = None


class ScriptStrings(_Model):
    """The strings Agent 10 reads from a script: ``segment_id`` to text, and on-screen strings by
    SHA-256. Built from the real Agent 05 document by ``ScriptDocumentSlice.to_strings``."""

    script_sha256: Sha256 | None = None
    segments: dict[str, str]
    on_screen: dict[str, str] = {}


class ScriptSegmentSlice(_Model):
    """One ``agent_05.script_document`` segment (``DocSegment``): the two fields Agent 10 reads."""

    segment_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    text: str


class ScriptSceneSlice(_Model):
    """One ``agent_05.script_document`` scene: its on-screen strings (bound by SHA-256)."""

    on_screen_text: tuple[str, ...]


class ScriptDisclaimerSlice(_Model):
    """One ``disclaimer_slots[]`` entry: the slot's text is its ``DISCLAIMER`` segment."""

    text_sha256: Sha256
    segment_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class ScriptDocumentSlice(_Model):
    """Agent 10's slice of the real Agent 05 ``agent_05.script_document`` 1.0.0 (CCR-200, 03
    section 2.3 rule 2): ``segments`` is a list of ``DocSegment`` objects, ``scenes`` carry the
    on-screen strings, ``disclaimer_slots`` the disclaimer text hashes. Every field read is
    required and typed (no defaults); unread fields are ignored. Fail closed: no segment, a
    duplicate ``segment_id`` or a disclaimer slot naming no segment is a schema error."""

    segments: Annotated[tuple[ScriptSegmentSlice, ...], Field(min_length=1)]
    scenes: tuple[ScriptSceneSlice, ...]
    disclaimer_slots: tuple[ScriptDisclaimerSlice, ...]

    @model_validator(mode="after")
    def _ids_unique_and_resolved(self) -> ScriptDocumentSlice:
        ids = [s.segment_id for s in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate segment_id in the script document")
        known = set(ids)
        for slot in self.disclaimer_slots:
            if slot.segment_id not in known:
                raise ValueError("disclaimer slot names a segment that is not in the document")
        return self

    def to_strings(self) -> ScriptStrings:
        """The ``segment_id -> text`` view and the on-screen strings keyed by their SHA-256."""
        text = {s.segment_id: s.text for s in self.segments}
        on_screen = {
            sha256_hex(t.encode("utf-8")): t for sc in self.scenes for t in sc.on_screen_text
        }
        for slot in self.disclaimer_slots:
            on_screen.setdefault(slot.text_sha256, text[slot.segment_id])
        return ScriptStrings(segments=text, on_screen=on_screen)


def parse_script_document(data: bytes, what: str = "agent_05.script_document") -> ScriptStrings:
    """The real Agent 05 script document through its slice (``SCHEMA_INVALID`` on failure)."""
    return parse_blob(ScriptDocumentSlice, data, what).to_strings()
