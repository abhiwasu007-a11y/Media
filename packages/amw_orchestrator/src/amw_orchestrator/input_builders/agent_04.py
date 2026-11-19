"""``agent_04.research_pack`` input (``agent_04.research_pack.input`` 1.0.0, agent_04 section 7).

Facts come from the job only: the owner topic (copied unchanged), the channel category
(``finance`` / ``non_finance``, CCR-273: unset or unknown = finance) and the rule packs that follow
from it (24 ``rule_packs``: ``rp.youtube_general`` always, ``rp.finance_sebi_in`` only for finance).
A revision iteration needs the prior pack reference and the gap list. agent_04 section 7.1 leaves
the mapping of Agent 06 reason codes to the four gap reasons to "the Agent 01 blueprint", which is
not in the repository: the revision stays refused with a typed error (CCR-280, no mapping invented).
"""

from amw_core.errors import InputInvalidError
from amw_orchestrator.executor import BuildContext, BuiltInput

PAYLOAD_SCHEMA = "agent_04.research_pack.input"
YOUTUBE_GENERAL = "rp.youtube_general"
FINANCE_SEBI_IN = "rp.finance_sebi_in"


class ResearchPackBuilder:
    def build(self, ctx: BuildContext) -> BuiltInput:
        if ctx.iteration > 0:
            raise InputInvalidError(
                "revision input of agent_04.research_pack is not mapped yet",
                details={"stage_id": ctx.stage.stage_id},
            )
        topic = ctx.job.owner_topic
        finance = ctx.job.finance_rules_apply
        data = {
            "topic": {
                "title": topic.title,
                "brief": topic.brief,
                "angle": topic.angle,
                "language": topic.language,
                "video_kind": topic.video_kind.value,
                "course_chapter_pointer": topic.course_chapter_pointer.to_doc()
                if topic.course_chapter_pointer is not None
                else None,
            },
            "channel_category": ctx.job.channel_category.value,
            "active_rule_packs": [YOUTUBE_GENERAL, *([FINANCE_SEBI_IN] if finance else [])],
            "library_scope": {"collection_keys": None},
            "owner_references": [r.to_doc() for r in topic.owner_references],
            "revision": None,
        }
        return BuiltInput(PAYLOAD_SCHEMA, "1.0.0", data)
