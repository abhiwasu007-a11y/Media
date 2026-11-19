"""``agent_09.shot_plan`` input (agent_09 section 7.2; CCR-203, CCR-267, ticket PASS6-B1).

Refs only: no ``ScriptDoc`` mapping and no lead-in re-attribution (CCR-202). The verification
ref carries the verified script hash and the stage verdict (``overall.proposed_verdict``, CCR-049;
a BLOCKED verdict never reaches this task). The previous plan of a revision is the previous
iteration's ``plan_ref`` unchanged.
"""

from typing import Any

from amw_core.errors import InputInvalidError
from amw_orchestrator.executor import BuildContext, BuiltInput
from amw_orchestrator.input_builders import common as c

SCHEMA = "agent_09.shot_plan.input"


def _feedback(ctx: BuildContext) -> list[dict[str, Any]]:
    return [
        {
            "check_id": r.check_id,
            "severity": "BLOCKING" if r.blocking else "WARNING",
            "source_stage_id": ctx.revision_source_stage_id,
            "shot_ids": [],
            "measured": float(r.measured) if isinstance(r.measured, int | float) else None,
            "threshold": float(r.threshold) if isinstance(r.threshold, int | float) else None,
        }
        for r in c.failing(ctx)
    ]


class ShotPlanBuilder:
    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        script = c.payload(ctx, c.script_stage_id(job))
        doc = c.ref_in(script, "script_document")
        ver_out = c.stage_output(ctx, "s06_verify")
        ver = c.payload_of(ctx, ver_out)
        verdict = ver["overall"]["proposed_verdict"]
        if verdict not in ("ALLOWED", "NEEDS_HUMAN_REVIEW"):
            raise InputInvalidError("the script verdict does not allow a plan")
        voice = c.payload(ctx, "s07_voice")["timeline"]
        approval = (
            c.payload(ctx, "a_script").get("approval_id") if c.has_stage(ctx, "a_script") else None
        )
        previous = None
        if ctx.iteration > 0:
            previous = c.ref_in(c.payload_of(ctx, c.require_iteration_output(ctx)), "plan_ref")
        parent_plan = None
        if "parent.s09_plan" in ctx.upstream:
            parent_plan = c.as_wire(c.ref_in(c.payload(ctx, "parent.s09_plan"), "plan_ref"))
        data: dict[str, Any] = {
            "production_type_key": job.production_type_key.value,
            "aspect_ratio": c.aspect_ratio(job),
            "script_ref": {
                **c.as_wire(doc),
                "script_id": script["script_id"],
                "version": script["version"],
            },
            "verification_ref": {
                **c.as_wire(c.artifact(ver_out, r"claim_verification_output\.json")),
                "verified_script_sha256": ver["script_sha256"],
                "stage_verdict": verdict,
                "approval_id": approval,
            },
            "narration_timeline_ref": {
                "uri": voice["timeline_uri"],
                "sha256": voice["timeline_sha256"],
            },
            "brand_kit_ref": c.as_wire(c.brand_kit_doc(ctx)),
            "channel_category": job.channel_category.value,
            "active_rule_packs": c.active_rule_packs(job),
            "parent_plan_ref": parent_plan,
            "iteration": ctx.iteration,
            "previous_plan_ref": c.as_wire(previous) if previous is not None else None,
            "revision_feedback": _feedback(ctx) if ctx.iteration > 0 else [],
        }
        return BuiltInput(SCHEMA, "1.0.0", data)
