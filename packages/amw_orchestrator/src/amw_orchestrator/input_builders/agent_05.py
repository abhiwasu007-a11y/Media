"""``agent_05.script_draft`` / ``agent_05.shorts_adaptation`` inputs (agent_05 sections 7.1-7.3).

Topic fields are copied unchanged from the job's owner topic (``language`` = ``jobs.language``,
CCR-205 b). The research pack, the rule packs, the compliance profile, the brand kit and (finance
only) the disclaimer template travel as context refs (7.3); the prior script of a revision is the
``script_document`` the previous iteration's payload names. Revision feedback is built from the
failing results of the gate that routed the revision (7.1.1).
"""

from typing import Any

from amw_core.enums import ContextRefPurpose
from amw_core.errors import InputInvalidError
from amw_orchestrator.executor import BuildContext, BuiltInput
from amw_orchestrator.input_builders import common as c

SCRIPT_DRAFT_SCHEMA = "agent_05.script_draft.input"
SHORTS_SCHEMA = "agent_05.shorts_adaptation.input"
RESEARCH_PACK_ARTIFACT = r"research_pack\.json"

_SOURCES = {
    "s06_claims": "CLAIM_EXTRACTION",
    "s06_verify": "CLAIM_VERIFICATION",
    "s06_chart": "CLAIM_VERIFICATION",
    "s02u_unique": "UNIQUENESS",
    "s16_comp": "COMPLIANCE",
    "s16_score": "QUALITY_SCORE",
}
"""agent_05 7.1.1: the gate stage whose failing results routed the revision -> ``source``. Any
other source (an approval decided ``CHANGES_REQUESTED``, a gate of another stage) is ``APPROVER``
only for approval stages; an unknown stage is refused, not guessed."""


def _feedback(ctx: BuildContext) -> list[dict[str, Any]]:
    src_stage = ctx.revision_source_stage_id or ""
    source = _SOURCES.get(src_stage)
    if source is None:
        if not src_stage.startswith("a_"):
            raise InputInvalidError(
                "revision feedback comes from an unknown stage",
                details={"stage_id": src_stage[:64]},
            )
        source = "APPROVER"
    items = [
        {
            "source": source,
            "segment_ref": None,
            "rule_ids": [r.rule_id] if r.rule_id else [],
            "instruction": r.message[:600] or r.check_id,
            "suggested_citation_refs": [],
        }
        for r in c.failing(ctx)[:60]
    ]
    if not items:
        raise InputInvalidError("a script revision needs at least one feedback item")
    return items


def _revision(ctx: BuildContext) -> dict[str, Any] | None:
    if ctx.iteration == 0:
        return None
    prior = c.payload_of(ctx, c.require_iteration_output(ctx))
    return {
        "prior_script": c.as_wire(c.ref_in(prior, "script_document")),
        "feedback": _feedback(ctx),
    }


def _common(ctx: BuildContext) -> dict[str, Any]:
    job, topic = ctx.job, ctx.job.owner_topic
    return {
        "language": job.language,
        "channel_category": job.channel_category.value,
        "owner_sebi_registration": c.OWNER_SEBI_REGISTRATION,
        "active_rule_packs": c.active_rule_packs(job),
        "video_kind": topic.video_kind.value,
        "course_chapter_pointer": topic.course_chapter_pointer.to_doc()
        if topic.course_chapter_pointer is not None
        else None,
        "iteration": ctx.iteration,
        "revision": _revision(ctx),
    }


def _refs(ctx: BuildContext, extra: list[Any]) -> tuple[Any, ...]:
    docs = ctx.job.documents
    refs = [*extra, *c.rule_pack_refs(ctx), c.profile_ref(ctx)]
    if docs.brand_kit is not None:
        refs.append(c.context_ref(docs.brand_kit, ContextRefPurpose.BRAND_KIT))
    if ctx.job.finance_rules_apply:  # the disclaimer is a finance-category input (7.3)
        refs.append(
            c.context_ref(
                c.need(docs.disclaimer_template, "the disclaimer template"),
                ContextRefPurpose.TEMPLATE,
            )
        )
    if ctx.iteration > 0:
        prior = c.payload_of(ctx, c.require_iteration_output(ctx))
        refs.append(
            c.context_ref(
                c.ref_in(prior, "script_document"),
                ContextRefPurpose.PRIOR_OUTPUT,
                c.SCRIPT_DOCUMENT_SCHEMA,
            )
        )
    return tuple(refs)


class ScriptDraftBuilder:
    def build(self, ctx: BuildContext) -> BuiltInput:
        topic = ctx.job.owner_topic
        data = {
            "topic": {
                "title": topic.title,
                "angle": topic.angle,
                "target_duration_ms": topic.target_duration_ms,
            },
            **_common(ctx),
        }
        pack = c.artifact(c.stage_output(ctx, "s04_research"), RESEARCH_PACK_ARTIFACT)
        pack_ref = c.context_ref(
            pack, ContextRefPurpose.PRIOR_OUTPUT, "agent_04.research_pack.output"
        )
        return BuiltInput(SCRIPT_DRAFT_SCHEMA, "1.0.0", data, _refs(ctx, [pack_ref]))


class ShortsAdaptationBuilder:
    """The parent script is the ``s05_script`` output of the parent job. ``removed_segment_ids``
    is empty and ``short_target_duration_ms`` is the child topic's target (provisional defaults,
    CCR-277: agent_05 7.2 names no record of removed segments, 24 section 4 no Shorts duration)."""

    def build(self, ctx: BuildContext) -> BuiltInput:
        parent_out = c.stage_output(ctx, "parent.s05_script")
        parent = c.payload_of(ctx, parent_out)
        doc = c.ref_in(parent, "script_document")
        data = {
            "parent_script": {**c.as_wire(doc), "script_id": parent["script_id"]},
            "removed_segment_ids": [],
            "short_target_duration_ms": ctx.job.owner_topic.target_duration_ms,
            "owner_instruction": None,
            **_common(ctx),
        }
        parent_ref = c.context_ref(doc, ContextRefPurpose.PRIOR_OUTPUT, c.SCRIPT_DOCUMENT_SCHEMA)
        return BuiltInput(SHORTS_SCHEMA, "1.0.0", data, _refs(ctx, [parent_ref]))
