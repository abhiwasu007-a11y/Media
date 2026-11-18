"""``amw.owner_topic`` to the Agent 05 task input (blueprint 1.2, 7.1).

In 3A the topic stage is replaced by the owner's topic recorded by the operator tool. The
orchestrator copies ``title``, ``angle``, ``target_duration_ms``, ``video_kind``,
``course_chapter_pointer`` and ``language`` unchanged; ``brief`` and ``owner_references`` belong to
Agent 04 and ``shorts_wanted`` to the orchestrator, so Agent 05 receives none of them.
"""

from collections.abc import Sequence

from agent_05_scriptwriter.contracts import (
    ChapterPointer,
    Revision,
    ScriptDraftInput,
    Topic,
)
from agent_05_scriptwriter.errors import InputInvalid
from amw_core.contracts.owner_topic import OwnerTopic

SUPPORTED_LANGUAGES = ("mr-IN", "en-IN", "hi-IN")


def topic_from_owner_topic(owner: OwnerTopic) -> Topic:
    return Topic(title=owner.title, angle=owner.angle, target_duration_ms=owner.target_duration_ms)


def script_draft_input_from_owner_topic(
    owner: OwnerTopic,
    *,
    channel_category: str,
    active_rule_packs: Sequence[str],
    iteration: int = 0,
    revision: Revision | None = None,
) -> ScriptDraftInput:
    """Build the ``agent_05.script_draft.input`` payload from the recorded owner topic."""
    if owner.language not in SUPPORTED_LANGUAGES:
        raise InputInvalid("language is not one of mr-IN, en-IN, hi-IN")
    pointer = (
        ChapterPointer(label=owner.course_chapter_pointer.label)
        if owner.course_chapter_pointer is not None
        else None
    )
    return ScriptDraftInput(
        topic=topic_from_owner_topic(owner),
        video_kind=owner.video_kind.value,
        language=owner.language,  # type: ignore[arg-type]
        channel_category=channel_category,
        owner_sebi_registration="UNREGISTERED",
        active_rule_packs=list(active_rule_packs),
        course_chapter_pointer=pointer,
        iteration=iteration,
        revision=revision,
    )
