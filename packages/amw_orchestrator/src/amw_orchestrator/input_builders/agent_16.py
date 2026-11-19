"""``agent_16.compliance_gate`` / ``quality_score`` / ``publication_authorisation`` inputs and
``svc_s02.uniqueness_check`` (agent_16 sections 7.1-7.5). Content is passed by reference only.

The ``routing`` objects are stage IDs of the production type's graph (CCR-047); a builder derives
them from the stages that ran (``s11_thumbs`` only when it ran). Which upstream document fills each
``*_ref`` is fixed here once (CCR-278 PROPOSED, 7.1 names only the document kinds): script =
the script document; claims = ``claim_extraction_output.json``; verification =
``claim_verification_output.json`` of ``s06_verify``; asset manifest = ``sourcing_manifest.json``;
shot plan = ``plan_ref``; voice = the narration timeline; render QC = the QC report and frames =
the evidence manifest named by the QC payload; thumbnails = the set manifest; uniqueness = the
``uniqueness-<iteration>.json`` report; research pack = ``research_pack.json``.
Agent 12 is not built: a job whose graph ran ``s12_meta`` is refused rather than given no metadata.
"""

from typing import Any

from amw_core.enums import ContextRefPurpose
from amw_core.errors import InputInvalidError, MissingDependencyError
from amw_orchestrator.approval_binding import ExpectedSubject, require_bound_approval
from amw_orchestrator.executor import BuildContext, BuiltInput, ChannelCategory, DocRef, JobFacts
from amw_orchestrator.input_builders import common as c
from amw_orchestrator.input_builders.settings import BuilderSettings
from amw_orchestrator.payloads import ApprovalOutput

GATE_SCHEMA = "agent_16.compliance_gate.input"
SCORE_SCHEMA = "agent_16.quality_score.input"
AUTH_SCHEMA = "agent_16.publication_authorisation.input"
UNIQ_SCHEMA = "svc_s02.uniqueness_check.input"
THUMB_MANIFEST = r"thumbnails/manifest-[0-9a-f]+\.json"
P = ContextRefPurpose.PRIOR_OUTPUT


def _thumbs_ref(ctx: BuildContext) -> DocRef:
    if not c.has_stage(ctx, "s11_thumbs"):
        raise MissingDependencyError(
            "no thumbnail set was produced (agent_16 needs thumbnails_ref)"
        )
    return c.artifact(c.stage_output(ctx, "s11_thumbs"), THUMB_MANIFEST)


def _metadata_guard(ctx: BuildContext) -> None:
    if c.has_stage(ctx, "s12_meta"):
        raise InputInvalidError("metadata_ref mapping of Agent 12 is not defined (CCR-278)")


def _thumbs_id(ctx: BuildContext) -> str | None:
    return "s11_thumbs" if c.has_stage(ctx, "s11_thumbs") else None


def _subject(ctx: BuildContext) -> dict[str, str]:
    render = c.payload(ctx, "s10_render")
    script = c.payload(ctx, c.script_stage_id(ctx.job))
    return {
        "render_id": render["render_id"],
        "render_sha256": render["render_ref"]["sha256"],
        "script_id": script["script_id"],
        "script_sha256": c.ref_in(script, "script_document").sha256,
    }


def _qc_refs(ctx: BuildContext) -> tuple[DocRef, DocRef]:
    ev = c.payload(ctx, "s10_qc")["evidence"]
    # CCR-287 (PROPOSED): ``render_qc_ref`` is the ``agent_10.technical_qc.output`` payload document
    # (it names the render: ``render_id``, ``render_sha256``), not the QC report row list
    return (
        c.payload_doc_ref(ctx, "s10_qc"),
        DocRef(ev["manifest_ref"]["uri"], ev["manifest_ref"]["sha256"]),
    )


def _common_refs(ctx: BuildContext) -> list[Any]:
    refs = [c.profile_ref(ctx), *c.rule_pack_refs(ctx)]
    if ctx.job.finance_rules_apply:  # the disclaimer template is a finance input (7.1)
        refs.append(
            c.context_ref(
                c.need(ctx.job.documents.disclaimer_template, "the disclaimer template"),
                ContextRefPurpose.TEMPLATE,
            )
        )
    return refs


class ComplianceGateBuilder:
    def __init__(self, settings: BuilderSettings) -> None:
        self._s = settings

    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        _metadata_guard(ctx)
        qc_report, frames = _qc_refs(ctx)
        script = c.ref_in(c.payload(ctx, c.script_stage_id(job)), "script_document")
        refs = {
            "script_ref": script,
            "claims_ref": c.artifact(
                c.stage_output(ctx, "s06_claims"), r"claim_extraction_output\.json"
            ),
            "verification_ref": c.artifact(
                c.stage_output(ctx, "s06_verify"), r"claim_verification_output\.json"
            ),
            "asset_manifest_ref": c.artifact(
                c.stage_output(ctx, "s08_assets"), r"sourcing_manifest\.json"
            ),
            "shot_plan_ref": c.ref_in(c.payload(ctx, "s09_plan"), "plan_ref"),
            "render_qc_ref": qc_report,
            # CCR-287 (PROPOSED): agent_16 reads the ``voice`` block (voice kind, presenter kind) of
            # the agent_07 output payload, which the narration timeline document does not carry
            "voice_ref": c.payload_doc_ref(ctx, "s07_voice"),
            "thumbnails_ref": _thumbs_ref(ctx),
            "uniqueness_ref": c.artifact(
                c.stage_output(ctx, "s02u_unique"), r"uniqueness-[0-9]+\.json"
            ),
            "research_pack_ref": c.artifact(
                c.stage_output(ctx, "s04_research"), r"research_pack\.json"
            ),
            "frames_ref": frames,
        }
        data = {
            "subject": _subject(ctx),
            "iteration": ctx.iteration,
            "channel_category": _channel_category(job),
            "production_type_key": job.production_type_key.value,
            "destination_kinds": list(self._s.destination_kinds),
            "evaluate_as_destination": self._s.evaluate_as_destination,
            "owner_sebi_registration": c.OWNER_SEBI_REGISTRATION,
            "language": job.language,
            "routing": {
                "script_stage_id": c.script_stage_id(job),
                "assets_stage_id": "s08_assets",
                "thumbnails_stage_id": _thumbs_id(ctx),
            },
            "inputs": {**{k: c.as_wire(v) for k, v in refs.items()}, "metadata_ref": None},
        }
        return BuiltInput(GATE_SCHEMA, "1.0.0", data, tuple(_common_refs(ctx)))


def _channel_category(job: JobFacts) -> str:
    """CCR-288 (PROVISIONAL): the gate compares this value for equality with ``channels.category``
    as the row stores it, so the builder sends the row value when the job carries it, else the
    resolved label. The row value never changes what the job is: finance-ness stays the resolved
    ``job.channel_category``; a row that says ``finance`` on a job resolved as non-finance is
    refused (a finance channel must never look non-finance)."""
    row = job.channel_category_row
    if row is None:
        return job.channel_category.value
    if not job.finance_rules_apply and row.strip().lower() == ChannelCategory.FINANCE.value:
        raise InputInvalidError(
            "the channel row says finance but the job is resolved as non-finance",
            details={"field": "channel_category"},
        )
    return row


class QualityScoreBuilder:
    def __init__(self, settings: BuilderSettings) -> None:
        self._s = settings

    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        _metadata_guard(ctx)
        qc_report, frames = _qc_refs(ctx)
        refs = {
            "script_ref": c.ref_in(c.payload(ctx, c.script_stage_id(job)), "script_document"),
            "claims_ref": c.artifact(
                c.stage_output(ctx, "s06_claims"), r"claim_extraction_output\.json"
            ),
            "verification_ref": c.artifact(
                c.stage_output(ctx, "s06_verify"), r"claim_verification_output\.json"
            ),
            "research_pack_ref": c.artifact(
                c.stage_output(ctx, "s04_research"), r"research_pack\.json"
            ),
            "render_qc_ref": qc_report,
            "shot_plan_ref": c.ref_in(c.payload(ctx, "s09_plan"), "plan_ref"),
            "thumbnails_ref": _thumbs_ref(ctx),
            "gate_output_ref": c.artifact(
                c.stage_output(ctx, "s16_comp"), r"compliance_gate-[0-9]+\.json"
            ),
            "frames_ref": frames,
        }
        data = {
            "subject": _subject(ctx),
            "iteration": ctx.iteration,
            "rubric_version": self._s.rubric_version,
            "language": job.language,
            "audience_level": None,
            "routing": {
                "script_stage_id": c.script_stage_id(job),
                "plan_stage_id": "s09_plan",
                "voice_stage_id": "s07_voice",
                "render_stage_id": "s10_render",
                "thumbnails_stage_id": _thumbs_id(ctx),
            },
            "inputs": {**{k: c.as_wire(v) for k, v in refs.items()}, "metadata_ref": None},
        }
        return BuiltInput(SCORE_SCHEMA, "1.0.0", data, ())


def _bound_final_approval(ctx: BuildContext) -> ApprovalOutput:
    """The final approval, accepted only for the CURRENT render (and, when the graph approves the
    script, the CURRENT script): hash, subject, org and confirmed evidence (CCR-296 PROVISIONAL,
    ``amw_orchestrator.approval_binding``)."""
    sub = _subject(ctx)
    org = ctx.job.org_id
    if c.has_stage(ctx, "a_script"):  # a script approval relied on must still be of this script
        require_bound_approval(
            c.payload(ctx, "a_script"),
            stage_id="a_script",
            approval_kind="SCRIPT",
            subject=ExpectedSubject("script", sub["script_id"], sub["script_sha256"]),
            org_id=org,
            evidence=ctx.evidence,
            real_run=ctx.real_run,
        )
    return require_bound_approval(
        c.payload(ctx, "a_final"),
        stage_id="a_final",
        approval_kind="FINAL_VIDEO",
        subject=ExpectedSubject("render", sub["render_id"], sub["render_sha256"]),
        org_id=org,
        evidence=ctx.evidence,
        real_run=ctx.real_run,
    )


class AuthorisationBuilder:
    def __init__(self, settings: BuilderSettings) -> None:
        self._s = settings

    def build(self, ctx: BuildContext) -> BuiltInput:
        approval = _bound_final_approval(ctx)
        thumbs = c.payload(ctx, "s11_thumbs")["variants"]
        packs = ctx.job.documents.rule_packs
        subject = {**_subject(ctx), "thumbnail_set_sha256": [v["file"]["sha256"] for v in thumbs]}
        data = {
            "subject": subject,
            "iteration": ctx.iteration,
            "approval_id": approval.approval_id,
            "gate_task_id": c.need(ctx.upstream_task_ids.get("s16_comp"), "the gate task ID"),
            "score_task_id": c.need(ctx.upstream_task_ids.get("s16_score"), "the score task ID"),
            "requested_action": self._s.requested_action,
            "intended_publish_date_utc": None,
            "pack_versions": [
                {"rule_pack_id": p.rule_pack_id, "version": p.version}
                for p in (
                    c.need(packs.get(k), "the rule pack", pack=k)
                    for k in c.active_rule_packs(ctx.job)
                )
            ],
        }
        refs = [c.profile_ref(ctx), *c.rule_pack_refs(ctx)]
        return BuiltInput(AUTH_SCHEMA, "1.0.0", data, tuple(refs))


class UniquenessBuilder:
    def __init__(self, settings: BuilderSettings) -> None:
        self._s = settings

    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        render = c.payload(ctx, "s10_render")
        script = c.ref_in(c.payload(ctx, c.script_stage_id(job)), "script_document")
        sid = c.payload(ctx, c.script_stage_id(job))["script_id"]
        template = c.need(job.documents.uniqueness_template, "the uniqueness template")
        data = {
            "subject": {
                "script_id": sid,
                "script_sha256": script.sha256,
                "render_id": render["render_id"],
                "render_sha256": render["render_ref"]["sha256"],
            },
            "iteration": ctx.iteration,
            "channel_id": job.channel_id,
            "production_type_key": job.production_type_key.value,
            "routing": {"script_stage_id": c.script_stage_id(job)},
            "inputs": {
                "script_ref": c.as_wire(script),
                "shot_plan_ref": c.as_wire(c.ref_in(c.payload(ctx, "s09_plan"), "plan_ref")),
                "thumbnails_ref": c.as_wire(_thumbs_ref(ctx)),
                "template_ref": c.as_wire(template),
            },
            "prior_window": {"max_prior_jobs": self._s.uniqueness_prior_jobs},
        }
        refs = [c.profile_ref(ctx), c.context_ref(template, ContextRefPurpose.TEMPLATE)]
        return BuiltInput(UNIQ_SCHEMA, "1.0.0", data, tuple(refs))
