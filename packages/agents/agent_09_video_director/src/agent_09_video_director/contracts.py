"""Pydantic models of agent_09 (blueprint 7, 8, 8.1.1, 8.2; payload-local enums, GLOSSARY 6.52)."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

HOOK_SECTION_ID = "hook"
"""Reserved ``section_id`` of the hook scenes and segments of an Agent 05 document (CCR-202)."""
TEMPLATE_ID_RE = r"^[a-z][a-z0-9_]{1,63}$"
"""GLOSSARY section 1 *Template ID* (CCR-204)."""
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ShotId = Annotated[str, StringConstraints(pattern=r"^sh[0-9]{2,4}$")]
SlotId = Annotated[str, StringConstraints(pattern=r"^sl[0-9]{2,4}$")]
TextId = Annotated[str, StringConstraints(pattern=r"^t[0-9]{1,3}$")]
BatchId = Annotated[str, StringConstraints(pattern=r"^b[0-9]{2}$")]
Ms = Annotated[int, Field(strict=True)]


class Model(BaseModel):
    """Frozen, no extra fields: every payload is closed (27 section 7.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class AspectRatio(StrEnum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"


class SegmentKind(StrEnum):
    HOOK_PROOF = "HOOK_PROOF"
    HOOK_WHY = "HOOK_WHY"
    HOOK_COVERS = "HOOK_COVERS"
    SHORT_HOOK = "SHORT_HOOK"
    BODY = "BODY"
    RECAP = "RECAP"
    COURSE_POINTER = "COURSE_POINTER"
    FULL_VIDEO_POINTER = "FULL_VIDEO_POINTER"
    DISCLAIMER = "DISCLAIMER"


class IntentKind(StrEnum):
    FOOTAGE = "FOOTAGE"
    CHART = "CHART"
    DIAGRAM = "DIAGRAM"
    TEXT_CARD = "TEXT_CARD"


class Framing(StrEnum):
    WIDE = "WIDE"
    MEDIUM = "MEDIUM"
    CLOSE_UP = "CLOSE_UP"
    DETAIL = "DETAIL"
    TOP_DOWN = "TOP_DOWN"
    NONE = "NONE"


class Motion(StrEnum):
    STATIC = "STATIC"
    SLOW_PUSH_IN = "SLOW_PUSH_IN"
    SLOW_PULL_OUT = "SLOW_PULL_OUT"
    PAN_LEFT = "PAN_LEFT"
    PAN_RIGHT = "PAN_RIGHT"
    PUNCH_IN = "PUNCH_IN"


class Tier(StrEnum):
    A = "A_OWNER_REAL"
    B = "B_LICENSED_STOCK"
    C = "C_CODE_MOTION"
    D = "D_AI_VIDEO"
    E = "E_AI_STILL"


class Device(StrEnum):
    CUTAWAY_BROLL = "CUTAWAY_BROLL"
    GRAPHIC = "GRAPHIC"
    ZOOM = "ZOOM"
    SOUND_CUE = "SOUND_CUE"
    ANGLE_CHANGE = "ANGLE_CHANGE"


class InterruptWindow(StrEnum):
    FIRST_DROPOFF = "FIRST_DROPOFF"
    MIDPOINT = "MIDPOINT"
    SCRIPT_PLANNED = "SCRIPT_PLANNED"


class TransitionKind(StrEnum):
    CUT = "CUT"
    CROSS_DISSOLVE = "CROSS_DISSOLVE"
    PUSH = "PUSH"
    ZOOM_THROUGH = "ZOOM_THROUGH"


class Anchor(StrEnum):
    CENTER = "CENTER"
    UPPER_THIRD = "UPPER_THIRD"
    LOWER_THIRD = "LOWER_THIRD"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class Origin(StrEnum):
    MODEL = "MODEL"
    REPAIRED = "REPAIRED"
    FALLBACK = "FALLBACK"
    CODE_CHART = "CODE_CHART"
    CODE_DISCLAIMER = "CODE_DISCLAIMER"


class HeldReason(StrEnum):
    CHART_REVEAL = "CHART_REVEAL"
    DELIBERATE_PAUSE = "DELIBERATE_PAUSE"
    DISCLAIMER = "DISCLAIMER"
    SCRIPT_NON_EXPLANATORY = "SCRIPT_NON_EXPLANATORY"


class SlotRole(StrEnum):
    HOOK = "HOOK"
    EXPLAIN = "EXPLAIN"
    RECAP = "RECAP"
    SECTION_OPENER = "SECTION_OPENER"
    INTERRUPT_REQUIRED = "INTERRUPT_REQUIRED"


class OverlayKind(StrEnum):
    BRAND_STING = "BRAND_STING"
    LOWER_THIRD = "LOWER_THIRD"
    CAPTION_CARD = "CAPTION_CARD"
    CHAPTER_CARD = "CHAPTER_CARD"
    DISCLAIMER_CARD = "DISCLAIMER_CARD"
    END_SCREEN = "END_SCREEN"


# ---------------------------------------------------------------- script / timeline inputs


class Segment(Model):
    segment_id: str = Field(pattern=r"^s[0-9]{1,4}$")
    kind: SegmentKind
    scene_id: str
    section_id: str | None = None
    chart_ref: str | None = None
    parent_segment_ids: tuple[str, ...] = ()
    text: str = ""


class Scene(Model):
    scene_id: str
    section_id: str | None = None
    beat: str = "EXPLAIN"
    segment_ids: tuple[str, ...]
    on_screen_text: tuple[str, ...] = ()
    tier_hint: Tier = Tier.B
    visual_description: str = ""
    change_beats: int = Field(default=1, ge=0)
    interrupt: Any = None
    deliberate_pause_ms: int | None = None
    explanatory: bool = True
    chart_id: str | None = None


class Section(Model):
    section_id: str
    section_kind: str = "CONCEPT"
    heading_local: str = ""
    scene_ids: tuple[str, ...] = ()
    first_segment_id: str | None = None


class ChartRequest(Model):
    chart_id: str = Field(pattern=r"^chart_[0-9a-z_]{1,32}$")
    first_segment_id: str
    must_be_historical: bool = True


class DisclaimerSlot(Model):
    slot_id: str
    segment_id: str
    text_sha256: SHA256


class ScriptDoc(Model):
    script_id: str
    version: int = Field(ge=1)
    language: str
    aspect_ratio: AspectRatio
    sections: tuple[Section, ...] = ()
    scenes: tuple[Scene, ...]
    segments: tuple[Segment, ...]
    chart_requests: tuple[ChartRequest, ...] = ()
    disclaimer_slots: tuple[DisclaimerSlot, ...] = ()


class TimelineSegment(Model):
    segment_id: str
    start_ms: int | None
    end_ms: int | None


class NarrationTimeline(Model):
    source: Literal["PROVIDER_CLIPS", "OWNER_MARKS", "UNALIGNED"]
    segments: tuple[TimelineSegment, ...]


class BrandKit(Model):
    intro_ref: str | None = None
    intro_duration_ms: int | None = None
    outro_ref: str | None = None
    lower_third_template_ref: str | None = None
    fallback_template_key: str = "tpl.abstract_motion"
    banned_words: tuple[str, ...] = ()


class Limits(Model):
    ai_video_allowed_ms: int = Field(default=0, ge=0)
    ai_still_allowed: bool = False
    sfx_library_enabled: bool = False
    music_library_enabled: bool = False


class RevisionFeedback(Model):
    check_id: str
    severity: Literal["BLOCKING", "WARNING"]
    source_stage_id: str | None = None
    shot_ids: tuple[str, ...] = ()
    measured: float | None = None
    threshold: float | None = None


# ---------------------------------------------------------------- slots and directions


class TextOption(Model):
    text_id: TextId
    text: str


class SceneVisualIntent(Model):
    tier_hint: Tier
    description: str


class DirectionSlot(Model):
    """One entry of ``slots`` of the step input (prompt section A)."""

    slot_id: SlotId
    scene_id: str
    section_kind: str | None
    role: SlotRole
    duration_ms: int = Field(ge=1)
    narration_excerpt: str
    scene_visual_intent: SceneVisualIntent
    text_options: tuple[TextOption, ...] = ()
    allowed_devices: tuple[Device, ...] = ()


class StepLimits(Model):
    max_intent_chars: int = Field(ge=1, le=240)
    max_rationale_chars: int = Field(ge=1, le=160)


class Capabilities(Model):
    ai_video_allowed: bool
    still_allowed: bool
    sound_cue_available: bool


class TailItem(Model):
    slot_id: SlotId
    intent_kind: Literal["FOOTAGE", "DIAGRAM", "TEXT_CARD"]
    framing: Framing


class DirectionInput(Model):
    """``agent_09.shot_plan.direction.input`` 1.0.0."""

    batch_id: BatchId
    language: str = Field(pattern=r"^[a-z]{2,3}-[A-Z]{2}$")
    channel_category: str = Field(min_length=1, max_length=40)
    aspect_ratio: AspectRatio
    banned_subjects: tuple[Annotated[str, Field(min_length=1, max_length=60)], ...] = Field(
        default=(), max_length=50
    )
    limits: StepLimits
    capabilities: Capabilities
    previous_tail: tuple[TailItem, ...] = Field(default=(), max_length=2)
    slots: tuple[DirectionSlot, ...]


class Depiction(Model):
    real_person: bool
    identifiable_person: bool
    market_direction_imagery: bool
    market_data_screen: bool
    brand_or_logo: bool
    ai_presenter: bool
    realistic_event_depiction: bool
    schematic: bool


class Direction(Model):
    slot_id: SlotId
    status: Literal["OK", "NO_SAFE_VISUAL"]
    reason_code: (
        Literal[
            "DIRECTION_IMAGERY_ONLY",
            "MARKET_DATA_SCREEN",
            "NARRATION_IS_A_CALL",
            "REAL_PERSON_ONLY",
            "REAL_EVENT_ONLY",
            "BANNED_SUBJECT",
            "INSTRUCTION_IN_INPUT",
            "TOO_VAGUE",
        ]
        | None
    )
    intent_kind: Literal["FOOTAGE", "DIAGRAM", "TEXT_CARD"] | None
    intent_text: str = Field(max_length=240)
    framing: Framing
    motion: Motion
    still_ok: bool
    needs_ai_video: bool
    interrupt_device: Device | None
    transition_hint: TransitionKind
    text_ids: tuple[TextId, ...] = Field(max_length=2)
    subject_anchor: Anchor | None
    depiction: Depiction
    rationale: str = Field(max_length=160)


class Refusal(Model):
    reason: Literal[
        "INSUFFICIENT_INPUT",
        "RULE_WOULD_BE_BROKEN",
        "OUT_OF_SCOPE",
        "CONFLICTING_INSTRUCTIONS",
        "UNSAFE_CONTENT",
    ]
    message: str = Field(max_length=1000)
    missing_inputs: tuple[str, ...] = ()
    violated_rule_ids: tuple[Annotated[str, Field(pattern=r"^[A-Z]{2,8}-R[0-9]{1,3}$")], ...] = ()


class DirectionOutput(Model):
    """``agent_09.shot_plan.direction.output`` 1.0.0."""

    batch_id: BatchId
    directions: tuple[Direction, ...] = Field(max_length=40)
    refusal: Refusal | None


# ---------------------------------------------------------------- plan objects


class Held(Model):
    reason: HeldReason
    max_ms: int


class InterruptInfo(Model):
    device: Device
    window: InterruptWindow


class Transition(Model):
    kind: TransitionKind
    duration_ms: int = Field(ge=0)


class TextRefScene(Model):
    scene_id: str
    index: int = Field(ge=0)
    sha256: SHA256


class TextRefDisclaimer(Model):
    disclaimer_slot_id: str
    sha256: SHA256


TextRef = TextRefScene | TextRefDisclaimer


class Depict(Model):
    realistic_event_depiction: bool
    schematic: bool


class Vertical(Model):
    subject_anchor: Anchor
    safe_area_class: Literal["DEFAULT"] = "DEFAULT"


class Shot(Model):
    shot_id: ShotId
    seq: int = Field(ge=1)
    scene_id: str
    section_id: str | None
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=1)
    duration_ms: int = Field(ge=1)
    segment_ids: tuple[str, ...]
    intent_kind: IntentKind
    intent_text: str = Field(max_length=240)
    framing: Framing
    motion: Motion
    allowed_tiers: tuple[Tier, ...] = Field(min_length=1)
    tier_hint: Tier
    fallback_template_key: str
    explanatory: bool
    held: Held | None
    change_events_ms: tuple[int, ...]
    interrupt: InterruptInfo | None
    transition_in: Transition
    cut_offset_ms: int
    jl_kind: Literal["J", "L"] | None
    chart_id: str | None
    text_refs: tuple[TextRef, ...]
    depiction: Depict
    origin: Origin
    content_key: SHA256
    vertical: Vertical | None
    parent_shot_id: ShotId | None


class Overlay(Model):
    overlay_id: str = Field(pattern=r"^ov[0-9]{2,4}$")
    kind: OverlayKind
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=1)
    template_ref: Annotated[str, StringConstraints(min_length=1)]
    """A template ID (GLOSSARY, CCR-204): never null, never a URI or asset ID."""
    text_refs: tuple[TextRef, ...] = ()
    vertical_variant: bool = False


class Chapter(Model):
    section_id: str
    start_ms: int
    title_local: str


class MusicPlan(Model):
    bed: Literal["NONE", "REQUESTED"]
    start_ms: int | None
    end_ms: int | None
    offset_db_range: tuple[float, float] = (-20.0, -15.0)
    asset_hint: str | None = None


class DeliberatePause(Model):
    start_ms: int
    end_ms: int
    reason: str


class AudioPlan(Model):
    music: MusicPlan
    sfx_cues: tuple[dict[str, Any], ...] = ()
    deliberate_pauses: tuple[DeliberatePause, ...] = ()


class HookFacts(Model):
    start_ms: Literal[0] = 0
    end_ms: int
    first_payoff_ms: int
    segment_ids: tuple[str, ...]


class DeliberateHold(Model):
    start_ms: int
    end_ms: int
    shot_id: ShotId
    reason: HeldReason


class InterruptSummary(Model):
    shot_id: ShotId
    device: Device
    window: InterruptWindow


class JlCutSummary(Model):
    boundary_ms: int
    kind: Literal["J", "L"] | None = None
    offset_ms: int | None = None
    from_shot_id: str | None = None
    to_shot_id: str | None = None
    skipped_reason: str | None = None


class TierBudget(Model):
    worst_case_e_share_permille: int
    e_limit_permille: int
    ai_video_allowed_ms: int
    ai_video_limit_ms: int


class Stats(Model):
    slot_count: int
    llm_slot_count: int
    fallback_count: int
    repaired_count: int
    change_events_total: int
    max_gap_ms: int
    min_gap_ms: int


class CallInfo(Model):
    step_key: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    tokens_cached_in: int
    cost_entry_id: str


class Provenance(Model):
    """Blueprint 8.1: not part of the determinism hash."""

    prompt_id: str
    prompt_sha256: SHA256 | None
    rule_pack_versions: dict[str, str]
    config_key_families: tuple[str, ...]
    calls: tuple[CallInfo, ...]


class ShotPlan(Model):
    """The plan blob (payload of ``agent_09.shot_plan.output`` 1.0.0, without ``plan_ref``)."""

    script_id: str
    script_version: int
    script_sha256: SHA256
    language: str
    aspect_ratio: AspectRatio
    iteration: int
    timing_basis: Literal["MEASURED"] = "MEASURED"
    narration_timeline_sha256: SHA256
    content_end_ms: int
    total_duration_ms: int
    hook: HookFacts
    shots: tuple[Shot, ...]
    overlays: tuple[Overlay, ...]
    audio_plan: AudioPlan
    chapters: tuple[Chapter, ...]
    deliberate_hold: tuple[DeliberateHold, ...]
    deliberate_black: tuple[()] = ()
    interrupts: tuple[InterruptSummary, ...]
    jl_cuts: tuple[JlCutSummary, ...]
    tier_budget: TierBudget
    stats: Stats
    refusal: Refusal | None = None
    realism: tuple[dict[str, Any], ...] = ()
    provenance: Provenance | None = None


class Slot(Model):
    """A timed slot of the skeleton (code-made; the model only fills direction)."""

    slot_id: SlotId
    scene_id: str
    section_id: str | None
    start_ms: int
    end_ms: int
    segment_ids: tuple[str, ...]
    role: SlotRole
    intent_kind: IntentKind | None = None
    origin: Origin = Origin.MODEL
    held: Held | None = None
    change_events_ms: tuple[int, ...] = ()
    explanatory: bool = True
    chart_id: str | None = None
    interrupt_window: InterruptWindow | None = None
    ordinal: int = 0

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


# ---------------------------------------------------------------- Task Input payload (7.2)


class HashedRef(Model):
    uri: str
    sha256: SHA256


class ScriptRef(HashedRef):
    script_id: str
    version: int = Field(ge=1)


class VerificationRef(HashedRef):
    verified_script_sha256: SHA256
    stage_verdict: Literal["ALLOWED", "NEEDS_HUMAN_REVIEW"]
    approval_id: str | None = None


class ShotPlanInput(Model):
    """``payload.data`` of ``agent_09.shot_plan.input`` 1.0.0 (closed, 7.2)."""

    production_type_key: Literal["CHANNEL_LONG_FORM", "SHORTS"]
    aspect_ratio: AspectRatio
    script_ref: ScriptRef
    verification_ref: VerificationRef
    narration_timeline_ref: HashedRef
    brand_kit_ref: HashedRef
    channel_category: Annotated[str, StringConstraints(max_length=40)]
    active_rule_packs: Annotated[
        tuple[Annotated[str, StringConstraints(pattern=r"^rp\.[a-z0-9_]{2,40}$")], ...],
        Field(min_length=1),
    ]
    parent_plan_ref: HashedRef | None = None
    iteration: int = Field(ge=0)
    previous_plan_ref: HashedRef | None
    revision_feedback: tuple[RevisionFeedback, ...] = Field(default=(), max_length=64)
    limits: Limits = Field(default_factory=Limits)


# ---------------------------------------------------------------- slice models of other documents
# 03 section 2.3 rule 2 (CCR-200): a consumer maps another component's document with its own slice
# model that ignores every field it does not read; ``forbid`` is only for own documents.


class SliceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _SliceVisualIntent(SliceModel):
    tier_hint: Tier
    description: str = ""
    change_beats: int = Field(default=1, ge=0)


class _SliceScene(SliceModel):
    scene_id: str
    section_id: str | None = None
    beat: str = "EXPLAIN"
    segment_ids: tuple[str, ...]
    on_screen_text: tuple[str, ...] = ()
    visual_intent: _SliceVisualIntent | None = None
    interrupt: Any = None
    deliberate_pause_ms: int = Field(default=0, ge=0)
    explanatory: bool = True
    chart_id: str | None = None


class _SliceSegment(SliceModel):
    segment_id: str
    kind: SegmentKind
    scene_id: str
    section_id: str | None = None
    chart_ref: str | None = None
    parent_segment_ids: tuple[str, ...] = ()
    text: str = ""


class _SliceSection(SliceModel):
    section_id: str
    section_kind: str = "CONCEPT"
    heading_local: str = ""
    scene_ids: tuple[str, ...] = ()


class _SliceChartRequest(SliceModel):
    chart_id: str = Field(pattern=r"^chart_[0-9a-z_]{1,32}$")
    first_segment_id: str
    must_be_historical: bool = True


class _SliceDisclaimerSlot(SliceModel):
    slot_id: str
    segment_id: str
    text_sha256: SHA256


class ScriptDocSlice(SliceModel):
    """What Agent 09 reads of the ``agent_05.script_document`` blob (agent_05 8.3, CCR-202).

    ``sections[]`` holds real sections only; hook scenes carry ``section_id = "hook"`` and
    disclaimer scenes ``null``; both stay as written (no re-attribution). A scene without a
    ``visual_intent`` (hook, disclaimer) takes the model defaults; ``deliberate_pause_ms = 0``
    means no deliberate pause (the document writes ``0``, never null).
    """

    script_id: str
    version: int = Field(ge=1)
    language: str
    aspect_ratio: AspectRatio
    sections: tuple[_SliceSection, ...] = ()
    scenes: tuple[_SliceScene, ...]
    segments: tuple[_SliceSegment, ...]
    chart_requests: tuple[_SliceChartRequest, ...] = ()
    disclaimer_slots: tuple[_SliceDisclaimerSlot, ...] = ()

    def to_script_doc(self) -> ScriptDoc:
        scenes = tuple(
            Scene(
                scene_id=sc.scene_id,
                section_id=sc.section_id,
                beat=sc.beat,
                segment_ids=sc.segment_ids,
                on_screen_text=sc.on_screen_text,
                tier_hint=sc.visual_intent.tier_hint if sc.visual_intent else Tier.B,
                visual_description=sc.visual_intent.description if sc.visual_intent else "",
                change_beats=sc.visual_intent.change_beats if sc.visual_intent else 1,
                interrupt=sc.interrupt,
                deliberate_pause_ms=sc.deliberate_pause_ms or None,
                explanatory=sc.explanatory,
                chart_id=sc.chart_id,
            )
            for sc in self.scenes
        )
        return ScriptDoc(
            script_id=self.script_id,
            version=self.version,
            language=self.language,
            aspect_ratio=self.aspect_ratio,
            sections=tuple(
                Section(
                    section_id=x.section_id,
                    section_kind=x.section_kind,
                    heading_local=x.heading_local,
                    scene_ids=x.scene_ids,
                )
                for x in self.sections
            ),
            scenes=scenes,
            segments=tuple(
                Segment(
                    segment_id=g.segment_id,
                    kind=g.kind,
                    scene_id=g.scene_id,
                    section_id=g.section_id,
                    chart_ref=g.chart_ref,
                    parent_segment_ids=g.parent_segment_ids,
                    text=g.text,
                )
                for g in self.segments
            ),
            chart_requests=tuple(
                ChartRequest(
                    chart_id=c.chart_id,
                    first_segment_id=c.first_segment_id,
                    must_be_historical=c.must_be_historical,
                )
                for c in self.chart_requests
            ),
            disclaimer_slots=tuple(
                DisclaimerSlot(
                    slot_id=d.slot_id, segment_id=d.segment_id, text_sha256=d.text_sha256
                )
                for d in self.disclaimer_slots
            ),
        )


class _SliceTimelineSegment(SliceModel):
    segment_id: str
    start_ms: int | None = None
    end_ms: int | None = None


class TimelineSlice(SliceModel):
    """What Agent 09 reads of the narration timeline blob (agent_07 8: source, segment times)."""

    source: Literal["PROVIDER_CLIPS", "OWNER_MARKS", "UNALIGNED"]
    segments: tuple[_SliceTimelineSegment, ...]

    def to_timeline(self) -> NarrationTimeline:
        return NarrationTimeline(
            source=self.source,
            segments=tuple(
                TimelineSegment(segment_id=g.segment_id, start_ms=g.start_ms, end_ms=g.end_ms)
                for g in self.segments
            ),
        )


class BrandKitSlice(SliceModel):
    """The brand kit fields Agent 09 reads (04 5.12): template IDs, never URIs (CCR-204)."""

    intro_ref: str | None = None
    intro_duration_ms: int | None = None
    outro_ref: str | None = None
    lower_third_template_ref: str | None = None
    banned_words: tuple[str, ...] = ()

    def to_brand_kit(self) -> BrandKit:
        return BrandKit(
            intro_ref=self.intro_ref,
            intro_duration_ms=self.intro_duration_ms,
            outro_ref=self.outro_ref,
            lower_third_template_ref=self.lower_third_template_ref,
            banned_words=self.banned_words,
        )
