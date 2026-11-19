"""``agent_11.thumbnail_variants`` input (agent_11 sections 7.1-7.2).

Refs by hash: script, verification, shot plan (``plan_ref``), brand kit, and from iteration 1 the
previous set manifest. ``variant_count`` is configuration (``BuilderSettings``). The failing
results that routed a thumbnail revision name no variant (``ValidationResult`` has no such field),
so ``revision_feedback`` stays empty until CCR-277 defines the mapping (provisional default).
"""

from typing import Any

from amw_core.enums import ContextRefPurpose
from amw_orchestrator.executor import BuildContext, BuiltInput
from amw_orchestrator.input_builders import common as c
from amw_orchestrator.input_builders.settings import BuilderSettings

SCHEMA = "agent_11.thumbnail_variants.input"
P = ContextRefPurpose.PRIOR_OUTPUT
MANIFEST = r"thumbnails/manifest-[0-9a-f]+\.json"


class ThumbnailBuilder:
    def __init__(self, settings: BuilderSettings) -> None:
        self._s = settings

    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        script = c.ref_in(c.payload(ctx, c.script_stage_id(job)), "script_document")
        ver = c.artifact(c.stage_output(ctx, "s06_verify"), r"claim_verification_output\.json")
        plan = c.ref_in(c.payload(ctx, "s09_plan"), "plan_ref")
        kit = c.brand_kit_doc(ctx)
        previous = None
        if ctx.iteration > 0:
            previous = c.artifact(c.require_iteration_output(ctx), MANIFEST)
        data: dict[str, Any] = {
            "production_type_key": job.production_type_key.value,
            "language": job.language,
            "variant_count": self._s.thumbnail_variants_shorts
            if c.is_shorts(job)
            else self._s.thumbnail_variants_long,
            "aspect_ratio": "16:9",
            "iteration": ctx.iteration,
            "script_ref": c.as_wire(script),
            "verification_ref": c.as_wire(ver),
            "shot_plan_ref": c.as_wire(plan),
            "brand_kit_ref": c.as_wire(kit),
            "previous_set_ref": c.as_wire(previous) if previous is not None else None,
            "revision_feedback": [],
        }
        refs = [
            c.context_ref(kit, ContextRefPurpose.BRAND_KIT),
            *c.rule_pack_refs(ctx),
            c.profile_ref(ctx),
            c.context_ref(script, P, c.SCRIPT_DOCUMENT_SCHEMA),
            c.context_ref(ver, P, "agent_06.claim_verification.output"),
            c.context_ref(plan, P, "agent_09.shot_plan.output"),
        ]
        if previous is not None:
            refs.append(c.context_ref(previous, P, "agent_11.thumbnail_manifest"))
        return BuiltInput(SCHEMA, "1.0.0", data, tuple(refs))
