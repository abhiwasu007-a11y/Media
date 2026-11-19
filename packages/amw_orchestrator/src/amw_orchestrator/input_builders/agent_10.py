"""``agent_10.render`` / ``agent_10.subtitles`` / ``agent_10.technical_qc`` inputs (agent_10
sections 7.1-7.4; CCR-205 a/b).

``language`` is ``jobs.language`` byte for byte. Each upstream document is one ``PRIOR_OUTPUT``
context ref named by the schema the agent looks for (exactly one per schema). Documents that exist
as blobs are referenced as they are (plan, sourcing manifest, narration timeline, render timeline,
script); documents that exist only as an inline payload (audio master, render and subtitles
outputs) are referenced through ``payload_doc_ref`` (CCR-279 PROPOSED). The budget of these
stages is zero and written by the orchestrator (CCR-205 a), not by a builder.
"""

from typing import Any

from amw_core.enums import ContextRefPurpose
from amw_orchestrator.executor import BuildContext, BuiltInput, DocRef
from amw_orchestrator.input_builders import common as c
from amw_orchestrator.input_builders.settings import BuilderSettings

P = ContextRefPurpose.PRIOR_OUTPUT
MANIFEST = r"sourcing_manifest\.json"


def _prior(doc: DocRef, schema: str) -> Any:
    return c.context_ref(doc, P, schema)


def _upstream_refs(ctx: BuildContext) -> list[Any]:
    script = c.payload(ctx, c.script_stage_id(ctx.job))
    voice = c.payload(ctx, "s07_voice")["timeline"]
    return [
        _prior(c.ref_in(c.payload(ctx, "s09_plan"), "plan_ref"), "agent_09.shot_plan.output"),
        _prior(
            c.artifact(c.stage_output(ctx, "s08_assets"), MANIFEST),
            "agent_08.asset_sourcing.output",
        ),
        _prior(c.payload_doc_ref(ctx, "s07_master"), "agent_07.audio_master.output"),
        _prior(
            DocRef(voice["timeline_uri"], voice["timeline_sha256"]),
            "agent_07.voice_synthesis.output",
        ),
        _prior(c.ref_in(script, "script_document"), c.SCRIPT_DOCUMENT_SCHEMA),
    ]


def _verified_sha(ctx: BuildContext) -> str:
    return str(c.payload(ctx, "s06_verify")["script_sha256"])


class RenderBuilder:
    def __init__(self, settings: BuilderSettings) -> None:
        self._s = settings

    def build(self, ctx: BuildContext) -> BuiltInput:
        job = ctx.job
        previous = None
        if ctx.iteration > 0:
            prior = c.payload_of(ctx, c.require_iteration_output(ctx))
            previous = c.as_wire(c.ref_in(prior, "render_ref"))
        data = {
            "render_kind": "MASTER",
            "preset_key": self._s.render_preset_shorts
            if c.is_shorts(job)
            else self._s.render_preset_long,
            "aspect_ratio": c.aspect_ratio(job),
            "language": job.language,
            "iteration": ctx.iteration,
            "verified_script_sha256": _verified_sha(ctx),
            "previous_render_ref": previous,
            "music_bed": None,
        }
        refs = [
            *_upstream_refs(ctx),
            c.context_ref(c.brand_kit_doc(ctx), ContextRefPurpose.BRAND_KIT),
        ]
        return BuiltInput("agent_10.render.input", "1.0.0", data, tuple(refs))


class SubtitlesBuilder:
    def build(self, ctx: BuildContext) -> BuiltInput:
        render = c.payload(ctx, "s10_render")
        script = c.payload(ctx, c.script_stage_id(ctx.job))
        voice = c.payload(ctx, "s07_voice")["timeline"]
        data = {
            "render_id": render["render_id"],
            "language": ctx.job.language,
            "iteration": ctx.iteration,
            "verified_script_sha256": _verified_sha(ctx),
            "caption_style": None,
        }
        refs = [
            _prior(c.payload_doc_ref(ctx, "s10_render"), "agent_10.render.output"),
            _prior(
                DocRef(voice["timeline_uri"], voice["timeline_sha256"]),
                "agent_07.voice_synthesis.output",
            ),
            _prior(c.ref_in(script, "script_document"), c.SCRIPT_DOCUMENT_SCHEMA),
        ]
        return BuiltInput("agent_10.subtitles.input", "1.0.0", data, tuple(refs))


class TechnicalQcBuilder:
    def __init__(self, settings: BuilderSettings) -> None:
        self._s = settings

    def build(self, ctx: BuildContext) -> BuiltInput:
        render = c.payload(ctx, "s10_render")
        data = {
            "render_id": render["render_id"],
            "render_sha256": render["render_ref"]["sha256"],
            "qc_profile": "qc.shorts" if c.is_shorts(ctx.job) else "qc.long_form",
            "iteration": ctx.iteration,
            "music_bed": None,
            "destination": self._s.licence_destination,
        }
        refs = [
            *_upstream_refs(ctx),
            _prior(c.payload_doc_ref(ctx, "s10_render"), "agent_10.render.output"),
            _prior(c.payload_doc_ref(ctx, "s10_subs"), "agent_10.subtitles.output"),
            _prior(c.ref_in(render, "timeline_ref"), "agent_10.timeline"),
        ]
        return BuiltInput("agent_10.technical_qc.input", "1.0.0", data, tuple(refs))
