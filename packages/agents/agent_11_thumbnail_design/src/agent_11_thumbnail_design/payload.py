"""``agent_11.thumbnail_variants.input`` and ``.output`` 1.0.0 as Pydantic models (7.2, 8.1)."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_11_thumbnail_design.models import (
    AccentRole,
    Angle,
    Canvas,
    Emphasis,
    HypothesisKind,
    Language,
    PictureKind,
    PlannedBy,
    Refusal,
    RevisionFeedback,
)

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Ref(_M):
    uri: Annotated[str, Field(min_length=1)]
    sha256: Sha


class ThumbnailInput(_M):
    production_type_key: Literal["CHANNEL_LONG_FORM", "SHORTS"]
    language: Language
    variant_count: Annotated[int, Field(ge=1, le=3)]
    aspect_ratio: Literal["16:9"]
    iteration: Annotated[int, Field(ge=0)]
    script_ref: Ref
    verification_ref: Ref
    shot_plan_ref: Ref
    brand_kit_ref: Ref
    previous_set_ref: Ref | None
    revision_feedback: Annotated[tuple[RevisionFeedback, ...], Field(max_length=3)]


class PayloadPicture(_M):
    option_id: str
    kind: PictureKind
    asset_id: str | None
    has_face: bool
    direction_neutral: bool


class PayloadFile(_M):
    asset_id: str
    uri: str
    sha256: Sha
    size_bytes: int
    media_type: str
    width_px: int
    height_px: int


class PayloadVariant(_M):
    variant_id: Annotated[str, Field(pattern=r"^v[1-3]$")]
    concept_id: Annotated[str, Field(pattern=r"^c[1-3]$")]
    is_control: bool
    hypothesis_kind: HypothesisKind
    angle: Angle
    planned_by: PlannedBy
    template_key: str
    template_version: int
    picture: PayloadPicture
    text_ids: tuple[str, ...]
    text_lines_local: tuple[str, ...]
    text_local: str
    text_language: Language
    emphasis_style: Emphasis
    accent_role: AccentRole
    promise_terms_covered: tuple[str, ...]
    rationale: str
    file: PayloadFile
    composition_sha256: Sha


class Omitted(_M):
    concept_id: str
    reason_code: str


class PlannerInfo(_M):
    llm_enabled: bool
    llm_calls: int
    reasks: int
    fallback_concepts: tuple[str, ...]


class OutputPayload(_M):
    verdict: Literal["ALLOWED", "BLOCKED", "NEEDS_HUMAN_REVIEW"]
    iteration: int
    language: Language
    aspect_ratio: Literal["16:9"]
    canvas: Canvas
    variant_count_requested: int
    variant_count_produced: int
    variants: tuple[PayloadVariant, ...]
    violated_rule_ids: tuple[str, ...]
    omitted: tuple[Omitted, ...]
    promise: dict[str, Any]
    option_stats: dict[str, Any]
    chart_stills_used: tuple[dict[str, Any], ...]
    planner: PlannerInfo
    set_sha256: Sha | None
    refusal: Refusal | None
    provenance: dict[str, Any]
