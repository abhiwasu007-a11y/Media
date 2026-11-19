"""``svc_s07.request_approval`` input. The schema is owned by the Agent 01 blueprint (14 section
S7), which is not in the repository: the payload below is the provisional minimum (CCR-278
PROPOSED): what is approved (kind, workflow) and the subject by hash (03 section 11.6 rule 1: the
approval row is bound to the subject's SHA-256). The decision payload the desk returns carries
``state`` and ``approval_id`` (``ApprovalDesk``)."""

from amw_core.errors import InputInvalidError
from amw_orchestrator.executor import BuildContext, BuiltInput
from amw_orchestrator.input_builders import common as c

SCHEMA = "svc_s07.request_approval.input"


class ApprovalRequestBuilder:
    def build(self, ctx: BuildContext) -> BuiltInput:
        approval = ctx.stage.approval
        if approval is None:
            raise InputInvalidError("an approval stage names its approval kind and workflow")
        kind = approval.approval_kind.value
        if kind == "SCRIPT":
            script = c.payload(ctx, c.script_stage_id(ctx.job))
            subject = c.ref_in(script, "script_document")
            from_stage = c.script_stage_id(ctx.job)
        elif kind == "FINAL_VIDEO":
            render = c.payload(ctx, "s10_render")
            subject = c.ref_in(render, "render_ref")
            from_stage = "s10_render"
        else:
            raise InputInvalidError(
                "no subject mapping for this approval kind", details={"kind": kind}
            )
        data = {
            "approval_kind": kind,
            "workflow_key": approval.workflow_key,
            "subject_stage_id": from_stage,
            "subject_ref": c.as_wire(subject),
            "subject_sha256": subject.sha256,
        }
        return BuiltInput(SCHEMA, "1.0.0", data)
