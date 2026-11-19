"""``svc_s07.request_approval`` input. PROVISIONAL (CCR-283 PROPOSED, supersedes the svc_s07
clause of CCR-278): every field is one column the gate task writes to the ``approvals`` row
(04 section 5.16): ``subject`` {``kind`` (``subject_kind``), ``id`` (``subject_id``), ``sha256``
(``subject_sha256``, 03 section 11.6 rule 1)}, ``approval_kind`` and ``workflow_key``. The model
is ``amw_orchestrator.payloads.ApprovalRequestInput``. The decision payload the desk returns is
``ApprovalOutput`` (same module)."""

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
            subject_kind, id_field = "script", "script_id"
            subject = c.ref_in(script, "script_document")
            subject_id = script.get(id_field)
        elif kind == "FINAL_VIDEO":
            render = c.payload(ctx, "s10_render")
            subject_kind, id_field = "render", "render_id"
            subject = c.ref_in(render, "render_ref")
            subject_id = render.get(id_field)
        else:
            raise InputInvalidError(
                "no subject mapping for this approval kind", details={"kind": kind}
            )
        if not isinstance(subject_id, str) or not subject_id:
            raise InputInvalidError(
                "the approval subject has no ID in its stage output", details={"field": id_field}
            )
        data = {
            "subject": {"kind": subject_kind, "id": subject_id, "sha256": subject.sha256},
            "approval_kind": kind,
            "workflow_key": approval.workflow_key,
        }
        return BuiltInput(SCHEMA, "1.0.0", data)
