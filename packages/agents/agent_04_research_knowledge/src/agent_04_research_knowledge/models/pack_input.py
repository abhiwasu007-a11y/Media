"""``agent_04.research_pack.input`` 1.0.0 (blueprint section 7)."""

from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from agent_04_research_knowledge.models.common import (
    ChannelCategory,
    CollectionKey,
    GapId,
    LanguageTag,
    RulePackKeyStr,
)
from agent_04_research_knowledge.models.enums import InputGapReason
from amw_core.contracts.common import AmwModel, StorageUri
from amw_core.contracts.owner_topic import CourseChapterPointer, OwnerReference
from amw_core.enums import RulePackKey, VideoKind

PAYLOAD_SCHEMA = "agent_04.research_pack.input"
PAYLOAD_SCHEMA_VERSION = "1.0.0"


class TopicInput(AmwModel):
    """Fields copied unchanged from ``amw.owner_topic`` 1.0.0."""

    title: Annotated[str, StringConstraints(min_length=3, max_length=400)]
    brief: Annotated[str, StringConstraints(max_length=2000)] | None
    angle: Annotated[str, StringConstraints(max_length=500)] | None
    language: LanguageTag
    video_kind: VideoKind
    course_chapter_pointer: CourseChapterPointer | None


class LibraryScope(AmwModel):
    collection_keys: Annotated[tuple[CollectionKey, ...], Field(max_length=32)] | None


class RevisionGap(AmwModel):
    gap_id: GapId
    gap_text: Annotated[str, StringConstraints(max_length=500)]
    reason: InputGapReason


class Revision(AmwModel):
    iteration: Annotated[int, Field(ge=1, le=10, strict=True)]
    gaps: Annotated[tuple[RevisionGap, ...], Field(max_length=50)]
    prior_pack_ref: StorageUri


class ResearchPackInput(AmwModel):
    topic: TopicInput
    channel_category: ChannelCategory
    active_rule_packs: Annotated[tuple[RulePackKeyStr, ...], Field(min_length=1)]
    library_scope: LibraryScope
    owner_references: Annotated[tuple[OwnerReference, ...], Field(max_length=20)]
    revision: Revision | None

    @model_validator(mode="after")
    def _general_pack_always_active(self) -> Self:
        if RulePackKey.YOUTUBE_GENERAL.value not in self.active_rule_packs:
            raise ValueError("active_rule_packs must contain rp.youtube_general")
        return self

    @property
    def iteration(self) -> int:
        """Revision loop number used in the task idempotency key (CCR-005); 0 for the first."""
        return 0 if self.revision is None else self.revision.iteration
