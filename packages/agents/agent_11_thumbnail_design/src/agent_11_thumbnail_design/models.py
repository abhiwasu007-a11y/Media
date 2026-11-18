"""Pydantic models of agent 11 (blueprint 7.3, 8.1, 8.5). Payload-local value sets are Literals."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Language = Literal["mr-IN", "en-IN", "hi-IN"]
TextSource = Literal["BRIEF_TEXT", "TITLE_SPAN", "KEY_TERM"]
PictureKind = Literal["OWNER_IMAGE", "CODE_GLYPH", "NONE"]
ConceptStatus = Literal["OK", "NO_SAFE_CONCEPT"]
ReasonCode = Literal[
    "NO_ELIGIBLE_TEXT",
    "PROMISE_IS_A_CALL",
    "BANNED_SUBJECT",
    "INSTRUCTION_IN_INPUT",
    "TOO_VAGUE",
    "NO_DISTINCT_OPTION",
]
Angle = Literal["TERM_CLARITY", "PROBLEM_FRAMING", "PROCESS_STEPS", "CONTRAST_CONCEPTS"]
HypothesisKind = Literal["CONTROL", "TEXT_ANGLE", "SUBJECT_CHOICE", "LAYOUT_STYLE"]
Emphasis = Literal["PLAIN", "TERM_HIGHLIGHT", "TWO_TONE"]
AccentRole = Literal["PRIMARY", "SECONDARY", "TERTIARY"]
GuardId = Literal["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]
PlannedBy = Literal["LLM", "FALLBACK"]


class A11Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TextOption(A11Model):
    text_id: Annotated[str, Field(pattern=r"^t[0-9]{2}$")]
    text: Annotated[str, Field(min_length=1, max_length=80)]
    source: TextSource
    key_term_ids: tuple[Annotated[str, Field(pattern=r"^k[0-9]+$")], ...]
    word_count: Annotated[int, Field(ge=1, le=12)]


class ExcludedText(A11Model):
    text: str
    source: TextSource
    reason: Literal[
        "EMPTY", "TOO_LONG", "BANNED_WORD", "MUST_NOT_PROMISE", "INJECTION", "FIN_TEXT"
    ]


class PictureOption(A11Model):
    option_id: Annotated[str, Field(pattern=r"^o[0-9]{2}$")]
    kind: PictureKind
    key: str
    label: Annotated[str, Field(min_length=1, max_length=80)]
    has_face: bool
    direction_neutral: bool


class TemplateOffer(A11Model):
    """The closed-choice view of a template (step input 7.3)."""

    template_key: Annotated[str, Field(pattern=r"^tpl_[a-z0-9_]{1,60}$")]
    is_default: bool
    text_lines_max: Annotated[int, Field(ge=1, le=3)]
    supports_subject_kinds: Annotated[tuple[PictureKind, ...], Field(min_length=1)]
    direction_neutral: bool


class SubjectHint(A11Model):
    hint_id: Annotated[str, Field(pattern=r"^hn[0-9]{2}$")]
    shot_id: Annotated[str, Field(pattern=r"^sh[0-9]{2,4}$")]
    shot_role: Literal["HOOK", "PROOF"]
    intent_text: Annotated[str, Field(min_length=1, max_length=300)]
    framing: Literal["WIDE", "MEDIUM", "CLOSE_UP", "DETAIL", "TOP_DOWN", "NONE"]


class Promise(A11Model):
    promise_statement: Annotated[str, Field(min_length=1, max_length=500)]
    promise_key_terms: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]
    working_title_local: Annotated[str, Field(min_length=1, max_length=200)]


class Brief(A11Model):
    subject_idea: Annotated[str, Field(min_length=1, max_length=300)]
    text_idea_local: Annotated[str, Field(min_length=1, max_length=120)]
    must_not_promise: Annotated[tuple[str, ...], Field(max_length=20)]


class Limits(A11Model):
    max_rationale_chars: Annotated[int, Field(ge=40, le=200)]


class PreviousChoice(A11Model):
    template_key: str
    subject_option_id: Annotated[str, Field(pattern=r"^o[0-9]{2}$")]
    text_ids: Annotated[tuple[str, ...], Field(max_length=2)]


class RetryEntry(A11Model):
    concept_id: Annotated[str, Field(pattern=r"^c[1-3]$")]
    guard_id: Annotated[str, Field(pattern=r"^G[1-8]$")] | None
    previous: PreviousChoice


class PreviousConcept(A11Model):
    concept_id: Annotated[str, Field(pattern=r"^c[1-3]$")]
    template_key: str | None
    subject_option_id: Annotated[str, Field(pattern=r"^o[0-9]{2}$")] | None
    text_ids: Annotated[tuple[str, ...], Field(max_length=2)]
    angle: Angle
    hypothesis_kind: HypothesisKind
    emphasis_style: Emphasis
    accent_role: AccentRole
    keep: bool

    @model_validator(mode="after")
    def _keep_needs_choices(self) -> "PreviousConcept":
        if self.keep and (not self.template_key or not self.subject_option_id or not self.text_ids):
            raise ValueError("a kept previous concept needs every choice")
        return self


class RevisionFeedback(A11Model):
    variant_id: Annotated[str, Field(pattern=r"^v[1-3]$")]
    failed_check_ids: Annotated[
        tuple[Annotated[str, Field(pattern=r"^[a-z0-9_.-]{3,96}$")], ...], Field(min_length=1)
    ]


class StepIn(A11Model):
    """``agent_11.thumbnail_variants.concepts.input`` 1.0.0 (blueprint 7.3)."""

    call_seq: Annotated[int, Field(ge=1, le=2)]
    language: Language
    channel_category: Annotated[str, Field(min_length=1, max_length=64)]
    variant_count: Annotated[int, Field(ge=1, le=3)]
    promise: Promise
    brief: Brief
    subject_hints: Annotated[tuple[SubjectHint, ...], Field(max_length=4)]
    subject_options: Annotated[tuple[PictureOptionView, ...], Field(max_length=8)]
    text_options: Annotated[tuple[TextOption, ...], Field(max_length=12)]
    templates: Annotated[tuple[TemplateOffer, ...], Field(max_length=6)]
    banned_subjects: Annotated[tuple[str, ...], Field(max_length=20)]
    limits: Limits
    retry_context: tuple[RetryEntry, ...] | None
    previous_concepts: tuple[PreviousConcept, ...] | None
    revision_feedback: Annotated[tuple[RevisionFeedback, ...], Field(max_length=3)]


class PictureOptionView(A11Model):
    """What the model sees of a picture option (no key)."""

    option_id: Annotated[str, Field(pattern=r"^o[0-9]{2}$")]
    kind: PictureKind
    label: Annotated[str, Field(min_length=1, max_length=80)]
    has_face: bool
    direction_neutral: bool


class Concept(A11Model):
    """One entry of ``agent_11.thumbnail_variants.concepts.output`` (prompt output schema)."""

    concept_id: Annotated[str, Field(pattern=r"^c[1-3]$")]
    status: ConceptStatus
    reason_code: ReasonCode | None
    template_key: Annotated[str, Field(max_length=64)] | None
    subject_option_id: Annotated[str, Field(pattern=r"^o[0-9]{2}$")] | None
    text_ids: Annotated[tuple[Annotated[str, Field(pattern=r"^t[0-9]{2}$")], ...], Field(max_length=2)]
    angle: Angle | None = None
    hypothesis_kind: HypothesisKind | None
    emphasis_style: Emphasis | None
    accent_role: AccentRole | None = None
    rationale: Annotated[str, Field(max_length=200)]

    def choices(self) -> tuple[str | None, str | None, tuple[str, ...]]:
        return (self.template_key, self.subject_option_id, self.text_ids)


class Refusal(A11Model):
    reason: Literal[
        "INSUFFICIENT_INPUT",
        "RULE_WOULD_BE_BROKEN",
        "OUT_OF_SCOPE",
        "CONFLICTING_INSTRUCTIONS",
        "UNSAFE_CONTENT",
    ]
    message: Annotated[str, Field(max_length=1000)]
    missing_inputs: tuple[str, ...]
    violated_rule_ids: tuple[Annotated[str, Field(pattern=r"^[A-Z]{2,8}-R[0-9]{1,3}$")], ...]


class StepOut(A11Model):
    """``agent_11.thumbnail_variants.concepts.output`` 1.0.0."""

    call_seq: Annotated[int, Field(ge=1)]
    concepts: Annotated[tuple[Concept, ...], Field(max_length=3)]
    refusal: Refusal | None

    @model_validator(mode="after")
    def _status_rules(self) -> "StepOut":
        for c in self.concepts:
            if c.status == "OK":
                complete = (
                    c.reason_code is None
                    and c.template_key
                    and c.subject_option_id
                    and c.text_ids
                    and c.angle
                    and c.hypothesis_kind
                    and c.emphasis_style
                    and c.accent_role
                )
                if not complete:
                    raise ValueError("an OK concept needs every choice and no reason code")
            elif (
                c.reason_code is None
                or c.template_key is not None
                or c.subject_option_id is not None
                or c.text_ids
                or c.angle is not None
                or c.hypothesis_kind is not None
                or c.emphasis_style is not None
                or c.accent_role is not None
            ):
                raise ValueError("a NO_SAFE_CONCEPT entry needs a reason code and no choices")
        return self


class GuardHit(A11Model):
    concept_id: str
    guard: GuardId


class ManifestPicture(A11Model):
    kind: PictureKind
    key: Annotated[str, Field(max_length=80)]
    asset_id: str | None


class ManifestText(A11Model):
    text_id: Annotated[str, Field(pattern=r"^t[0-9]{2}$")]
    text: Annotated[str, Field(min_length=1, max_length=80)]


class ManifestFile(A11Model):
    asset_id: str
    uri: str
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ManifestVariant(A11Model):
    variant_id: Annotated[str, Field(pattern=r"^v[1-3]$")]
    concept_id: Annotated[str, Field(pattern=r"^c[1-3]$")]
    is_control: bool
    hypothesis_kind: HypothesisKind
    angle: Angle
    emphasis_style: Emphasis
    accent_role: AccentRole
    template_key: Annotated[str, Field(max_length=64)]
    picture: ManifestPicture
    texts: Annotated[tuple[ManifestText, ...], Field(min_length=1, max_length=2)]
    text_local: Annotated[str, Field(min_length=1, max_length=120)]
    file: ManifestFile


class Canvas(A11Model):
    width_px: Annotated[int, Field(ge=1)]
    height_px: Annotated[int, Field(ge=1)]
    format: Annotated[str, Field(max_length=16)]


class Manifest(A11Model):
    """``agent_11.thumbnail_manifest`` 1.0.0 (blueprint 8.5)."""

    iteration: Annotated[int, Field(ge=0)]
    language: Language
    aspect_ratio: Literal["16:9"]
    canvas: Canvas
    variants: Annotated[tuple[ManifestVariant, ...], Field(min_length=1, max_length=3)]
    set_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
