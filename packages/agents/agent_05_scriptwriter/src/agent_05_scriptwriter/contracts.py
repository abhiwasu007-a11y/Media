"""Pydantic v2 models for every payload of Agent 05 (blueprint sections 7, 8 and the three prompts).

These are the machine form of the JSON Schemas of the blueprint and of appendix A / the Output
JSON Schema of the three prompt files; a contract test compares both directions (27 section 4.4).
Models are strict, closed (``extra = forbid``) and carry no tenant content in their repr beyond
what the fields hold; nothing here is logged.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class A05Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


# ---- enums (GLOSSARY values, as Literals so strict JSON validation needs no enum coercion) ------
Language = Literal["mr-IN", "en-IN", "hi-IN"]
VideoKindLit = Literal["GENERAL", "METHOD_TOPIC"]
Pace = Literal["SLOW", "NORMAL", "FAST"]
Emotion = Literal["NEUTRAL", "CURIOUS", "SERIOUS", "WARM", "ENERGETIC", "EMPHASIS"]
HookStyle = Literal["CONCRETE_CASE", "COMMON_MISTAKE", "QUESTION", "CONTRAST", "MYTH_BUST"]
HookBeatName = Literal["HOOK_PROOF", "HOOK_WHY", "HOOK_COVERS"]
SectionKind = Literal[
    "CONCEPT",
    "WORKED_EXAMPLE",
    "CASE_STUDY_HISTORICAL",
    "COMMON_MISTAKES",
    "RECAP",
    "COURSE_POINTER",
]
SceneBeat = Literal["BODY", "RECAP", "COURSE_POINTER"]
CutBeat = Literal["BODY", "RECAP", "FULL_VIDEO_POINTER"]
TierHint = Literal["A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO"]
InterruptKind = Literal["B_ROLL_CUTAWAY", "GRAPHIC", "ZOOM", "SOUND_CUE", "ANGLE_CHANGE"]
ChartKind = Literal["REAL_HISTORICAL", "SCHEMATIC"]
Timeframe = Literal["1D", "1W", "1M"]
OutcomeShown = Literal["WORKED", "FAILED", "BOTH", "NOT_APPLICABLE"]
OmitReason = Literal[
    "NO_SOURCE", "METHOD_NOT_RELEASED", "METHOD_MIXING", "DURATION_LIMIT", "OUT_OF_SCOPE"
]
DropReason = Literal[
    "NOT_STANDALONE", "DURATION_LIMIT", "REMOVED_IN_REVISION", "OFF_TOPIC", "RULE_RISK"
]
RefusalReasonLit = Literal[
    "INSUFFICIENT_INPUT",
    "RULE_WOULD_BE_BROKEN",
    "OUT_OF_SCOPE",
    "CONFLICTING_INSTRUCTIONS",
    "UNSAFE_CONTENT",
]
FeedbackSource = Literal[
    "CLAIM_EXTRACTION",
    "CLAIM_VERIFICATION",
    "UNIQUENESS",
    "COMPLIANCE",
    "QUALITY_SCORE",
    "APPROVER",
]
Verdict = Literal["ALLOWED", "BLOCKED", "NEEDS_HUMAN_REVIEW"]
ReleaseStatus = Literal["NOT_APPLICABLE", "RELEASED", "NOT_RELEASED"]
CitationKind = Literal["KNOWLEDGE_CHUNK", "EXTERNAL_REFERENCE"]
SegmentKind = Literal[
    "HOOK_PROOF",
    "HOOK_WHY",
    "HOOK_COVERS",
    "SHORT_HOOK",
    "BODY",
    "RECAP",
    "COURSE_POINTER",
    "FULL_VIDEO_POINTER",
    "DISCLAIMER",
]

# ---- id-like strings ----
ConceptId = Annotated[str, StringConstraints(pattern=r"^k[0-9]{1,3}$")]
PackConceptId = Annotated[str, StringConstraints(pattern=r"^c[0-9]{2}$")]
SegmentId = Annotated[str, StringConstraints(pattern=r"^s[0-9]{1,4}$")]
SectionId = Annotated[str, StringConstraints(pattern=r"^sec[0-9]{1,2}$")]
HookId = Annotated[str, StringConstraints(pattern=r"^h[1-9]$")]
ChartId = Annotated[str, StringConstraints(pattern=r"^chart_[0-9a-z_]{1,32}$")]
SceneLocalId = Annotated[str, StringConstraints(pattern=r"^sc[0-9]{1,3}$")]
RuleId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2,8}-R[0-9]{1,3}$")]
CitationRef = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ScriptIdStr = Annotated[
    str,
    StringConstraints(
        pattern=r"^scr_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
CostEntryIdStr = Annotated[
    str,
    StringConstraints(
        pattern=r"^cst_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
ChannelCategory = Annotated[str, StringConstraints(pattern=r"^[a-z_]{3,32}$")]
RulePackKey = Annotated[str, StringConstraints(pattern=r"^rp\.[a-z0-9_]+$")]
PosInt = Annotated[int, Field(ge=1)]


# ---- shared building blocks ----
class Refusal(A05Model):
    """The refusal object of 27 section 4.3 (``refusal_reason``, GLOSSARY section 6.51)."""

    reason: RefusalReasonLit
    message: Annotated[str, StringConstraints(max_length=1000)]
    missing_inputs: list[str]
    violated_rule_ids: list[RuleId]


class FeedbackItem(A05Model):
    source: FeedbackSource
    segment_ref: SegmentId | None
    rule_ids: list[RuleId]
    instruction: Annotated[str, StringConstraints(min_length=1, max_length=600)]
    suggested_citation_refs: list[CitationRef] = Field(default_factory=list)


class ChapterPointer(A05Model):
    label: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ScriptRef(A05Model):
    uri: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    sha256: Sha256


class Revision(A05Model):
    prior_script: ScriptRef
    feedback: Annotated[list[FeedbackItem], Field(min_length=1, max_length=60)]


class Topic(A05Model):
    title: Annotated[str, StringConstraints(min_length=3, max_length=400)]
    angle: Annotated[str, StringConstraints(max_length=500)] | None
    target_duration_ms: Annotated[int, Field(ge=1000)]


class Sentence(A05Model):
    text: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    pace: Pace
    emotion: Emotion


class ConceptRefIn(A05Model):
    concept_id: ConceptId
    citation_refs: Annotated[list[CitationRef], Field(min_length=1)]


class ChartRequest(A05Model):
    chart_id: ChartId
    chart_kind: ChartKind
    instrument: Annotated[str, StringConstraints(max_length=100)] | None
    timeframe: Timeframe
    indicators: Annotated[
        list[Annotated[str, StringConstraints(max_length=40)]], Field(max_length=4)
    ]
    pattern_concept_id: ConceptId
    outcome_shown: OutcomeShown
    must_be_historical: Literal[True]


class Rubric(A05Model):
    viewer_relevance: Annotated[int, Field(ge=0, le=2)]
    curiosity_without_clickbait: Annotated[int, Field(ge=0, le=2)]
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class VisualIntent(A05Model):
    tier_hint: TierHint
    description: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    change_beats: Annotated[int, Field(ge=1, le=12)]


class Interrupt(A05Model):
    kind: InterruptKind


# ---- task input payloads (blueprint sections 7.1, 7.2) ----
class _CommonInput(A05Model):
    language: Language
    channel_category: ChannelCategory
    owner_sebi_registration: Literal["UNREGISTERED"]
    active_rule_packs: Annotated[list[RulePackKey], Field(min_length=1)]
    video_kind: VideoKindLit
    course_chapter_pointer: ChapterPointer | None
    iteration: Annotated[int, Field(ge=0)]
    revision: Revision | None

    @model_validator(mode="after")
    def _general_pack(self) -> Self:
        if "rp.youtube_general" not in self.active_rule_packs:
            raise ValueError("active_rule_packs must contain rp.youtube_general")
        return self


class ScriptDraftInput(_CommonInput):
    """``agent_05.script_draft.input`` 1.0.0."""

    topic: Topic


class ShortsParent(A05Model):
    uri: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    sha256: Sha256
    script_id: ScriptIdStr


class ShortsAdaptationInput(_CommonInput):
    """``agent_05.shorts_adaptation.input`` 1.0.0."""

    parent_script: ShortsParent
    removed_segment_ids: list[SegmentId]
    short_target_duration_ms: Annotated[int, Field(ge=1000)]
    owner_instruction: Annotated[str, StringConstraints(max_length=600)] | None


# ---- step inputs (blueprint 7.4.1; = appendix A of each prompt file) ----
class ConceptBrief(A05Model):
    concept_id: ConceptId
    term_local: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    term_en: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    glossary_term_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    summary: Annotated[str, StringConstraints(max_length=600)]
    citation_refs: list[CitationRef]
    method_content: bool
    release_status: ReleaseStatus


class AvailableCitation(A05Model):
    citation_ref: CitationRef
    kind: CitationKind
    title: Annotated[str, StringConstraints(max_length=300)]


class SpeechBudget(A05Model):
    hook_chars_min: PosInt
    hook_chars_max: PosInt
    beat_chars_target: PosInt


class PlanStepInput(A05Model):
    language: Language
    channel_category: ChannelCategory
    owner_sebi_registration: Literal["UNREGISTERED"]
    active_rule_packs: Annotated[list[RulePackKey], Field(min_length=1)]
    video_kind: VideoKindLit
    topic: Topic
    concept_briefs: list[ConceptBrief]
    available_citations: list[AvailableCitation]
    latin_allow_list: list[Annotated[str, StringConstraints(min_length=1, max_length=60)]]
    speech_budget: SpeechBudget | None
    min_hook_options: Annotated[int, Field(ge=1, le=5)]
    max_hook_options: Annotated[int, Field(ge=1, le=5)]
    max_sections: Annotated[int, Field(ge=1, le=12)]
    hook_history: list[Annotated[str, StringConstraints(min_length=1, max_length=400)]]
    course_chapter_pointer: ChapterPointer | None
    revision_feedback: Annotated[list[FeedbackItem], Field(min_length=1, max_length=60)] | None


class SectionPlanIn(A05Model):
    section_id: SectionId
    section_kind: SectionKind
    heading_local: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    heading_en: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    purpose: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    concept_ids: Annotated[list[ConceptId], Field(max_length=4)]
    needs_interrupt: bool
    is_case_study: bool


class RunningSummary(A05Model):
    sections_done: list[SectionId]
    terms_introduced: list[ConceptId]
    previous_tail: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=500)]], Field(max_length=5)
    ]


class SceneBudget(A05Model):
    chars_min: Annotated[int, Field(ge=1)] | None
    chars_max: Annotated[int, Field(ge=1)] | None
    max_scenes: Annotated[int, Field(ge=1)]
    max_change_gap_ms: Annotated[int, Field(ge=1)]
    speech_rate_cps: Annotated[float, Field(gt=0)] | None


class SectionStepInput(A05Model):
    language: Language
    channel_category: ChannelCategory
    owner_sebi_registration: Literal["UNREGISTERED"]
    active_rule_packs: Annotated[list[RulePackKey], Field(min_length=1)]
    video_kind: VideoKindLit
    section_plan: SectionPlanIn
    concept_briefs: list[ConceptBrief]
    available_citations: list[AvailableCitation]
    latin_allow_list: list[Annotated[str, StringConstraints(min_length=1, max_length=60)]]
    running_summary: RunningSummary
    scene_budget: SceneBudget
    chart_ids_available: list[ChartId]
    revision_feedback: Annotated[list[FeedbackItem], Field(min_length=1, max_length=60)] | None
    previous_text: Annotated[str, StringConstraints(max_length=6000)] | None


class ParentPromise(A05Model):
    working_title_local: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    promise_key_terms: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=40)]],
        Field(min_length=1, max_length=6),
    ]


class ParentSegment(A05Model):
    segment_id: SegmentId
    text: Annotated[str, StringConstraints(min_length=1, max_length=5000)]
    concept_refs: list[ConceptId]
    chart_ref: ChartId | None
    method_label: bool
    hypothetical_example: bool


class ParentSection(A05Model):
    section_id: SectionId
    heading_local: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    segments: Annotated[list[ParentSegment], Field(min_length=1)]


class ParentView(A05Model):
    promise: ParentPromise
    claims_cleared: bool
    removed_segment_ids: list[SegmentId]
    sections: Annotated[list[ParentSection], Field(min_length=1, max_length=12)]


class GlossaryTerm(A05Model):
    concept_id: ConceptId
    term_local: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    term_en: Annotated[str, StringConstraints(min_length=1, max_length=120)]


class CutSpeechBudget(A05Model):
    hook_chars_max: PosInt


class PrevCutSentence(A05Model):
    segment_id: SegmentId
    text: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class PrevCutHook(A05Model):
    hook_id: HookId
    sentences: Annotated[list[PrevCutSentence], Field(min_length=1)]


class PrevCutScene(A05Model):
    scene_local_id: Annotated[str, StringConstraints(pattern=r"^sc[0-9]{1,2}$")]
    parent_segment_ids: list[SegmentId]
    sentences: Annotated[list[PrevCutSentence], Field(min_length=1)]


class PreviousCut(A05Model):
    hook: PrevCutHook
    scenes: Annotated[list[PrevCutScene], Field(min_length=1, max_length=12)]


class CutStepInput(A05Model):
    language: Language
    channel_category: ChannelCategory
    owner_sebi_registration: Literal["UNREGISTERED"]
    active_rule_packs: Annotated[list[RulePackKey], Field(min_length=1)]
    video_kind: VideoKindLit
    parent: ParentView
    glossary_terms: list[GlossaryTerm]
    short_target_duration_ms: Annotated[int, Field(ge=1000)]
    max_duration_ms: Annotated[int, Field(ge=1000)]
    speech_budget: CutSpeechBudget | None
    owner_instruction: Annotated[str, StringConstraints(max_length=600)] | None
    latin_allow_list: list[Annotated[str, StringConstraints(min_length=1, max_length=60)]]
    min_hook_options: Annotated[int, Field(ge=1, le=5)]
    max_hook_options: Annotated[int, Field(ge=1, le=5)]
    hook_history: list[Annotated[str, StringConstraints(min_length=1, max_length=400)]]
    course_chapter_pointer: ChapterPointer | None
    revision_feedback: Annotated[list[FeedbackItem], Field(min_length=1, max_length=60)] | None
    previous_cut: PreviousCut | None


# ---- LLM step outputs ----
class TitlePromise(A05Model):
    working_title_local: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    promise_statement: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    promise_key_terms: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=40)]],
        Field(min_length=1, max_length=6),
    ]


class HookBeat(A05Model):
    beat: HookBeatName
    sentences: Annotated[list[Sentence], Field(min_length=1, max_length=4)]
    concrete_example: Annotated[str, StringConstraints(max_length=300)] | None
    chart_request: ChartRequest | None
    concept_refs: Annotated[list[ConceptRefIn], Field(max_length=4)]


class PlanHook(A05Model):
    hook_id: HookId
    hook_style: HookStyle
    beats: Annotated[list[HookBeat], Field(min_length=3, max_length=3)]
    rubric: Rubric


class PlanSection(A05Model):
    section_id: SectionId
    section_kind: SectionKind
    heading_local: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    heading_en: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    purpose: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    concept_ids: Annotated[list[ConceptId], Field(max_length=4)]
    share_permille: Annotated[int, Field(ge=1, le=1000)]
    needs_interrupt: bool


class ConceptPlanEntry(A05Model):
    concept_id: ConceptId
    taught_in_section_ids: Annotated[list[SectionId], Field(min_length=1)]
    own_words_angle: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    original_example_idea: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    citation_refs: Annotated[list[CitationRef], Field(min_length=1)]


class OmittedConcept(A05Model):
    concept_id: ConceptId
    reason: OmitReason


class ThumbnailBrief(A05Model):
    subject_idea: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    text_idea_local: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    must_not_promise: Annotated[
        list[Annotated[str, StringConstraints(max_length=120)]], Field(max_length=5)
    ]


class PlanOutput(A05Model):
    """``agent_05.script_draft.plan.output`` 1.0.0."""

    title_promise: TitlePromise | None
    hooks: Annotated[list[PlanHook], Field(max_length=5)]
    selected_hook_id: HookId | None
    sections: Annotated[list[PlanSection], Field(max_length=12)]
    concept_plan: Annotated[list[ConceptPlanEntry], Field(max_length=24)]
    omitted_concepts: Annotated[list[OmittedConcept], Field(max_length=24)]
    description_draft: Annotated[str, StringConstraints(min_length=1, max_length=1500)] | None
    thumbnail_brief: ThumbnailBrief | None
    refusal: Refusal | None

    @model_validator(mode="after")
    def _refusal_or_plan(self) -> Self:
        if self.refusal is not None:
            if (
                self.hooks
                or self.sections
                or self.concept_plan
                or self.title_promise is not None
                or self.selected_hook_id is not None
            ):
                raise ValueError("a refusal leaves every plan field empty or null")
        else:
            if (
                len(self.hooks) < 3
                or not self.sections
                or not self.concept_plan
                or self.title_promise is None
                or self.selected_hook_id is None
                or self.description_draft is None
                or self.thumbnail_brief is None
            ):
                raise ValueError("a plan needs >= 3 hooks, sections, concept_plan and promise")
        return self


class Scene(A05Model):
    scene_local_id: SceneLocalId
    beat: SceneBeat
    sentences: Annotated[list[Sentence], Field(min_length=1, max_length=12)]
    on_screen_text: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=120)]], Field(max_length=4)
    ]
    visual_intent: VisualIntent
    concept_refs: Annotated[list[ConceptRefIn], Field(max_length=4)]
    hypothetical_example: bool
    method_label: bool
    interrupt: Interrupt | None
    deliberate_pause_ms: Annotated[int, Field(ge=0, le=3000)]
    explanatory: bool
    pronunciation_candidates: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=40)]], Field(max_length=12)
    ]
    chart_request: ChartRequest | None
    purpose_concept_id: ConceptId | None


class SectionOutput(A05Model):
    """``agent_05.script_draft.section.output`` 1.0.0."""

    section_id: SectionId
    scenes: Annotated[list[Scene], Field(max_length=20)]
    refusal: Refusal | None

    @model_validator(mode="after")
    def _refusal_or_scenes(self) -> Self:
        if self.refusal is not None and self.scenes:
            raise ValueError("a refusal has no scenes")
        if self.refusal is None and not self.scenes:
            raise ValueError("a section needs at least one scene")
        return self


class CutTitlePromise(A05Model):
    short_title_local: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    promise_statement: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    promise_key_terms: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=40)]],
        Field(min_length=1, max_length=6),
    ]


class CutHook(A05Model):
    hook_id: HookId
    hook_style: HookStyle
    sentences: Annotated[list[Sentence], Field(min_length=1, max_length=3)]
    parent_segment_ids: Annotated[list[SegmentId], Field(min_length=1, max_length=4)]
    rubric: Rubric


class CutScene(A05Model):
    scene_local_id: SceneLocalId
    beat: CutBeat
    sentences: Annotated[list[Sentence], Field(min_length=1, max_length=12)]
    on_screen_text: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=120)]], Field(max_length=4)
    ]
    visual_intent: VisualIntent
    concept_refs: Annotated[list[ConceptRefIn], Field(max_length=4)]
    hypothetical_example: bool
    method_label: bool
    interrupt: Interrupt | None
    deliberate_pause_ms: Annotated[int, Field(ge=0, le=3000)]
    explanatory: bool
    pronunciation_candidates: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=40)]], Field(max_length=12)
    ]
    chart_ref: ChartId | None
    parent_segment_ids: Annotated[list[SegmentId], Field(max_length=6)]


class DroppedParent(A05Model):
    parent_segment_id: SegmentId
    reason: DropReason


class CutOutput(A05Model):
    """``agent_05.shorts_adaptation.cut.output`` 1.0.0."""

    title_promise: CutTitlePromise | None
    hooks: Annotated[list[CutHook], Field(max_length=5)]
    selected_hook_id: HookId | None
    scenes: Annotated[list[CutScene], Field(max_length=12)]
    dropped_parent_content: Annotated[list[DroppedParent], Field(max_length=60)]
    refusal: Refusal | None

    @model_validator(mode="after")
    def _refusal_or_cut(self) -> Self:
        if self.refusal is not None:
            if self.hooks or self.scenes or self.title_promise is not None or self.selected_hook_id:
                raise ValueError("a refusal leaves every cut field empty or null")
        elif (
            len(self.hooks) < 3
            or not self.scenes
            or self.title_promise is None
            or self.selected_hook_id is None
        ):
            raise ValueError("a cut needs >= 3 hooks, scenes, a promise and a selected hook")
        return self


# ---- script document (blueprint 8.3) ----
class DocPromise(A05Model):
    working_title_local: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    promise_statement: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    promise_key_terms: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=40)]],
        Field(min_length=1, max_length=6),
    ]


class DocSection(A05Model):
    section_id: Annotated[str, StringConstraints(min_length=1, max_length=16)]
    section_kind: SectionKind
    heading_local: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    heading_en: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    purpose: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    concept_ids: list[ConceptId]
    needs_interrupt: bool
    scene_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=32)]]
    share_permille: Annotated[int, Field(ge=1, le=1000)]


class DocScene(A05Model):
    scene_id: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    section_id: Annotated[str, StringConstraints(min_length=1, max_length=16)] | None
    beat: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    segment_ids: list[SegmentId]
    on_screen_text: list[str]
    visual_intent: VisualIntent | None
    interrupt: Interrupt | None
    deliberate_pause_ms: Annotated[int, Field(ge=0)]
    explanatory: bool
    pronunciation_candidates: list[str]
    chart_id: ChartId | None
    purpose_concept_id: ConceptId | None
    method_label: bool
    hypothetical_example: bool


class DocConceptRef(A05Model):
    concept_id: ConceptId
    pack_concept_id: PackConceptId
    citation_refs: list[CitationRef]


class DocSegment(A05Model):
    segment_id: SegmentId
    kind: SegmentKind
    section_id: Annotated[str, StringConstraints(min_length=1, max_length=16)] | None
    scene_id: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    text: Annotated[str, StringConstraints(min_length=1)]
    pace: Pace | None
    emotion: Emotion | None
    concept_refs: list[DocConceptRef]
    chart_ref: ChartId | None
    method_label: bool
    hypothetical_example: bool
    est_start_ms: Annotated[int, Field(ge=0)] | None
    est_duration_ms: Annotated[int, Field(ge=0)] | None
    parent_segment_ids: list[SegmentId]


class DocChartRequest(A05Model):
    chart_id: ChartId
    chart_kind: ChartKind
    instrument: Annotated[str, StringConstraints(max_length=100)] | None
    timeframe: Timeframe
    indicators: list[str]
    pattern_concept_id: ConceptId
    outcome_shown: OutcomeShown
    must_be_historical: Literal[True]
    first_segment_id: SegmentId


class Chapter(A05Model):
    section_id: Annotated[str, StringConstraints(min_length=1, max_length=16)]
    title_local: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    est_start_ms: Annotated[int, Field(ge=0)] | None


class DisclaimerSlot(A05Model):
    slot_id: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    placement: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    template_ref: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    template_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    text_sha256: Sha256
    segment_id: SegmentId


class OptionOut(A05Model):
    hook_id: HookId
    hook_style: HookStyle
    rubric: Rubric
    total: Annotated[int, Field(ge=0, le=4)]
    qualified: bool
    disqualified_by: list[str]
    segment_ids: list[SegmentId]


class ProvenanceCall(A05Model):
    step_key: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    tokens_cached_in: int
    cost_entry_id: CostEntryIdStr


class Provenance(A05Model):
    """``provenance`` of the script draft result (the cut result uses ``CutProvenance``)."""

    plan_prompt_id: str
    section_prompt_id: str
    prompt_sha256: dict[str, str]
    rule_pack_versions: dict[str, str]
    config_key_families: list[str]
    calls: list[ProvenanceCall]


class CutProvenance(A05Model):
    cut_prompt_id: str
    prompt_sha256: dict[str, str]
    rule_pack_versions: dict[str, str]
    config_key_families: list[str]
    calls: list[ProvenanceCall]


class DocumentProvenance(A05Model):
    prompt_ids: dict[str, str]
    prompt_sha256: dict[str, str]
    rule_pack_versions: dict[str, str]
    config_key_families: list[str]
    section_sha256: dict[str, str]


class OutOmitted(A05Model):
    concept_id: str
    pack_concept_id: str
    reason: OmitReason


class ScriptDocument(A05Model):
    """``agent_05.script_document`` 1.0.0 (blob; write-once; ``content_sha256`` = its SHA-256)."""

    script_id: ScriptIdStr
    job_id: str
    channel_id: str
    language: Language
    version: PosInt
    iteration: Annotated[int, Field(ge=0)]
    aspect_ratio: Literal["16:9", "9:16"]
    promise: DocPromise
    sections: list[DocSection]
    scenes: list[DocScene]
    segments: Annotated[list[DocSegment], Field(min_length=1)]
    chart_requests: list[DocChartRequest]
    chapters: list[Chapter]
    disclaimer_slots: list[DisclaimerSlot]
    description_draft: Annotated[str, StringConstraints(max_length=1500)] | None
    thumbnail_brief: ThumbnailBrief | None
    hook_options: list[OptionOut]
    omitted_concepts: list[OutOmitted]
    provenance: DocumentProvenance


# ---- task output payloads (blueprint 8.2, 8.4) ----
class OutSection(A05Model):
    section_id: SectionId
    section_kind: SectionKind
    heading_local: Annotated[str, StringConstraints(max_length=120)]
    heading_en: Annotated[str, StringConstraints(max_length=120)]
    share_permille: Annotated[int, Field(ge=1, le=1000)]
    first_segment_id: SegmentId
    last_segment_id: SegmentId
    est_start_ms: Annotated[int, Field(ge=0)] | None
    est_duration_ms: Annotated[int, Field(ge=0)] | None
    sha256: Sha256


class OutCoverage(A05Model):
    concept_id: ConceptId
    pack_concept_id: PackConceptId
    taught_in_section_ids: list[str]
    segment_ids: list[SegmentId]


class Totals(A05Model):
    segment_count: int
    word_count: int
    speech_chars: int
    est_duration_ms: int | None
    llm_calls: int


class Flags(A05Model):
    method_used: bool
    method_segment_ids: list[str]
    hypothetical_segment_ids: list[str]
    course_pointer_present: bool


class DocRef(A05Model):
    uri: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    sha256: Sha256


class ScriptDraftResult(A05Model):
    """``agent_05.script_draft.output`` 1.0.0 (``payload.data``)."""

    script_id: ScriptIdStr | None
    version: PosInt
    iteration: Annotated[int, Field(ge=0)]
    language: Language
    verdict: Verdict
    title_promise: DocPromise | None
    hook_options: Annotated[list[OptionOut], Field(max_length=5)]
    selected_hook_id: HookId | None
    sections: Annotated[list[OutSection], Field(max_length=12)]
    concept_coverage: list[OutCoverage]
    omitted_concepts: list[OutOmitted]
    chart_requests: list[DocChartRequest]
    description_draft: Annotated[str, StringConstraints(max_length=1500)] | None
    thumbnail_brief: ThumbnailBrief | None
    totals: Totals
    flags: Flags
    script_document: DocRef | None
    refusal: Refusal | None
    provenance: Provenance


class CutPromiseOut(A05Model):
    short_title_local: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    promise_statement: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    promise_key_terms: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=40)]],
        Field(min_length=1, max_length=6),
    ]


class ParentEcho(A05Model):
    script_id: ScriptIdStr
    sha256: Sha256


class OutScene(A05Model):
    scene_id: Annotated[str, StringConstraints(pattern=r"^sc[0-9]{1,3}$")]
    beat: CutBeat
    segment_ids: Annotated[list[SegmentId], Field(min_length=1)]
    parent_segment_ids: list[SegmentId]
    est_start_ms: Annotated[int, Field(ge=0)] | None
    est_duration_ms: Annotated[int, Field(ge=0)] | None


class OutCutCoverage(A05Model):
    concept_id: ConceptId
    taught_in_scene_ids: list[Annotated[str, StringConstraints(pattern=r"^sc[0-9]{1,3}$")]]
    segment_ids: list[SegmentId]


class ShortsAdaptationResult(A05Model):
    """``agent_05.shorts_adaptation.output`` 1.0.0 (``payload.data``)."""

    script_id: ScriptIdStr | None
    version: PosInt
    iteration: Annotated[int, Field(ge=0)]
    language: Language
    verdict: Verdict
    parent: ParentEcho
    title_promise: CutPromiseOut | None
    hook_options: Annotated[list[OptionOut], Field(max_length=5)]
    selected_hook_id: HookId | None
    scenes: Annotated[list[OutScene], Field(max_length=12)]
    concept_coverage: list[OutCutCoverage]
    dropped_parent_content: Annotated[list[DroppedParent], Field(max_length=60)]
    chart_refs: list[ChartId]
    totals: Totals
    flags: Flags
    script_document: DocRef | None
    refusal: Refusal | None
    provenance: CutProvenance
