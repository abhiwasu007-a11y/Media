"""``amw.owner_topic`` 1.0.0 (03 section 3.4, CCR-006): the owner's topic, recorded as the job
input by the operator tool (``sys_operator``) with owner evidence (03 section 11.6 rule 6)."""

from typing import Annotated, Self

from pydantic import Field, StrictBool, StringConstraints, model_validator

from amw_core.contracts.common import AmwModel
from amw_core.enums import OwnerReferenceKind, VideoKind
from amw_core.ids import UUID7_BODY

KnowledgeSourceIdStr = Annotated[str, StringConstraints(pattern=rf"^ksr_{UUID7_BODY}$")]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://", max_length=2048)]


class CourseChapterPointer(AmwModel):
    label: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class OwnerReference(AmwModel):
    kind: OwnerReferenceKind
    url: HttpsUrl | None
    knowledge_source_id: KnowledgeSourceIdStr | None
    note: Annotated[str, StringConstraints(max_length=500)] | None

    @model_validator(mode="after")
    def _kind_rules(self) -> Self:
        # Schema allOf: EXTERNAL_URL carries only a url; KNOWLEDGE_SOURCE only a source ID.
        if self.kind is OwnerReferenceKind.EXTERNAL_URL and (
            self.url is None or self.knowledge_source_id is not None
        ):
            raise ValueError("EXTERNAL_URL needs url and a null knowledge_source_id")
        if self.kind is OwnerReferenceKind.KNOWLEDGE_SOURCE and (
            self.url is not None or self.knowledge_source_id is None
        ):
            raise ValueError("KNOWLEDGE_SOURCE needs knowledge_source_id and a null url")
        return self


class OwnerTopic(AmwModel):
    title: Annotated[str, StringConstraints(min_length=3, max_length=400)]
    brief: Annotated[str, StringConstraints(max_length=2000)] | None
    angle: Annotated[str, StringConstraints(max_length=500)] | None
    language: Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")]
    video_kind: VideoKind
    course_chapter_pointer: CourseChapterPointer | None
    owner_references: Annotated[tuple[OwnerReference, ...], Field(max_length=20)]
    target_duration_ms: Annotated[int, Field(ge=1000, strict=True)]
    shorts_wanted: StrictBool


__all__ = ["CourseChapterPointer", "OwnerReference", "OwnerTopic"]
