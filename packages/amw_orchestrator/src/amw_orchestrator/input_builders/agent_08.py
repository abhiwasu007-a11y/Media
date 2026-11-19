"""``agent_08.asset_sourcing`` input (agent_08 sections 7.1-7.2; CCR-203, CCR-205 c, CCR-268).

``shot_plan_ref`` is the Agent 09 ``plan_ref`` unchanged (no hand-off copy). The brand kit is the
one required ``BRAND_KIT`` context ref. A revision names the previous manifest; ``changed_shot_ids``
is empty unless a failing result names shots (none of the 3A gates does, so the whole plan is
re-sourced, which is the stricter reading).
"""

from amw_core.enums import ContextRefPurpose
from amw_orchestrator.executor import BuildContext, BuiltInput
from amw_orchestrator.input_builders import common as c
from amw_orchestrator.input_builders.settings import BuilderSettings

SCHEMA = "agent_08.asset_sourcing.input"
MANIFEST = r"sourcing_manifest\.json"


class AssetSourcingBuilder:
    def __init__(self, settings: BuilderSettings) -> None:
        self._s = settings

    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        stage_id = c.script_stage_id(job)
        script = c.payload(ctx, stage_id)
        plan = c.payload(ctx, "s09_plan")["plan_ref"]
        previous = None
        if ctx.iteration > 0:
            prev = c.artifact(c.require_iteration_output(ctx), MANIFEST)
            previous = c.as_wire(prev)
        data = {
            "shot_plan_ref": {k: plan[k] for k in ("uri", "sha256", "schema", "schema_version")},
            "script_ref": {
                **c.as_wire(c.ref_in(script, "script_document")),
                "script_id": script["script_id"],
            },
            "aspect_ratios": [c.aspect_ratio(job)],
            "destination": self._s.licence_destination,
            "script_stage_id": stage_id,
            "channel_category": job.channel_category.value,
            "active_rule_packs": c.active_rule_packs(job),
            "ai_video_allowed": self._s.ai_video_allowed,
            "stills_allowed": self._s.stills_allowed,
            "iteration": ctx.iteration,
            "previous_sourcing_ref": previous,
            "changed_shot_ids": [],
        }
        kit = c.context_ref(c.brand_kit_doc(ctx), ContextRefPurpose.BRAND_KIT)
        return BuiltInput(SCHEMA, "1.0.0", data, (kit,))
