"""``agent_13.file_delivery`` input (``amw_delivery.models.BundleInputs``; 3A slice spec section 4).

Everything a bundle shows is taken from the stored outputs of the stages that produced it: the
render, the thumbnail set, the SRT files, the QC rows, the score rows, the gate rows and the
compliance verdict. The policy values the delivery package refuses to decide (banner, disclaimer
wording and status label, disclosure note, config version, size limits) and the S4 cost report come
from the runtime through ``BuildServices`` (never hard-coded here; a missing service is a typed
refusal). A bundle of a Shorts job (a 9:16 file and no 16:9 file) and the 9:16 add-on of a
long-form job are not mapped (CCR-277): the 3A bundle is the 16:9 long-form one.
"""

from typing import Any

from amw_core.errors import InputInvalidError, MissingDependencyError
from amw_orchestrator.executor import BuildContext, BuiltInput
from amw_orchestrator.input_builders import common as c
from amw_orchestrator.input_builders.settings import BuilderSettings

SCHEMA = "agent_13.file_delivery.input"


def _measured(value: object) -> str | None:
    return None if value is None else str(value)


class FileDeliveryBuilder:
    def __init__(self, settings: BuilderSettings) -> None:
        self._s = settings

    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        if c.is_shorts(job):
            raise InputInvalidError("the 3A bundle is the 16:9 long-form one (CCR-277)")
        services = c.need(ctx.services, "the build services")
        facts = dict(services.delivery_facts(job))
        render = c.payload(ctx, "s10_render")
        thumbs = c.payload(ctx, "s11_thumbs")
        subs = c.payload(ctx, "s10_subs")
        qc_out = c.stage_output(ctx, "s10_qc")
        score = c.payload(ctx, "s16_score")
        comp_out = c.stage_output(ctx, "s16_comp")
        auth = c.payload(ctx, "s16_auth")
        variants = thumbs["variants"]
        if not variants:
            raise MissingDependencyError("no thumbnail variant to deliver")
        chosen = next((v for v in variants if v.get("is_control")), variants[0])
        data: dict[str, Any] = {
            "org_id": job.org_id,
            "job_id": job.job_id,
            "deliverable_preset": self._s.render_preset_long,
            "production_type_key": job.production_type_key.value,
            "production_type_version": str(job.production_type_version),
            "config_version": facts["config_version"],
            "metadata_present": c.has_stage(ctx, "s12_meta"),
            "banner": facts["banner"],
            "disclaimer": facts["disclaimer"],
            "disclosure_note": facts["disclosure_note"],
            "video_16x9": {k: render["render_ref"][k] for k in ("uri", "sha256", "size_bytes")},
            "video_9x16": None,
            "shorts_wanted": False,
            "thumbnails": [
                {
                    "option_id": v["variant_id"],
                    "ref": {k: v["file"][k] for k in ("uri", "sha256", "size_bytes")},
                    "media_type": v["file"]["media_type"],
                }
                for v in variants
            ],
            "chosen_thumbnail_id": chosen["variant_id"],
            "subtitles": [
                {
                    "language": s["language"],
                    "ref": {k: s[k] for k in ("uri", "sha256", "size_bytes")},
                }
                for s in subs["srt"]
            ],
            "primary_language": job.language,
            "qc_checks": [
                {
                    "check_id": r.check_id,
                    "verdict": r.verdict.value,
                    "measured": _measured(r.measured),
                    "threshold": _measured(r.threshold),
                    "unit": r.unit,
                }
                for r in qc_out.validation_results
            ],
            "score_rows": [
                {
                    "dimension": d["dimension"],
                    "source": "MACHINE",
                    "max_points": str(d["max_points"]),
                    "points": str(d["points"]),
                    "evidence": "",
                }
                for d in score["dimensions"]
            ],
            "gates": [
                {
                    "gate_id": r.check_id,
                    "passed": r.verdict.value in ("PASS", "WARN", "SKIPPED"),
                    "remedy": r.remedy_stage_id,
                    "blocking": r.blocking,
                }
                for r in comp_out.validation_results
                if r.gate
            ],
            "compliance": {
                "verdict": auth["verdict"],
                "authorised_for_delivery": auth["authorised_action"] == self._s.requested_action,
                "authorisation_verdict_id": auth["authorisation_verdict_id"],
                "render_sha256": auth["subject"]["render_sha256"],
            },
            "cost_report": dict(services.cost_report(job)),
            "limits": facts["limits"],
        }
        return BuiltInput(SCHEMA, "1.0.0", data)
