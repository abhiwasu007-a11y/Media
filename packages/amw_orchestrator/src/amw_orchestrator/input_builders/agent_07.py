"""``agent_07.voice_synthesis`` and ``agent_07.audio_master`` inputs (agent_07 sections 7, 15).

Everything is by reference: the script document and the verification output of ``s06_verify``
(its ``script_sha256`` must equal the script document's hash, else the verified text is not the
text to be voiced and the build is refused). The voice and the pronunciation dictionary are job
documents (brand kit ``voice_id``). The master takes the narration stem and timeline the voice
payload names; its deliberate pauses are the voice timeline's ``SCENE_PAUSE`` spans.
"""

from amw_core.errors import InputInvalidError
from amw_orchestrator.executor import BuildContext, BuiltInput
from amw_orchestrator.input_builders import common as c

VOICE_SCHEMA = "agent_07.voice_synthesis.input"
MASTER_SCHEMA = "agent_07.audio_master.input"


class VoiceSynthesisBuilder:
    def build(self, ctx: BuildContext) -> BuiltInput:
        script = c.payload(ctx, c.script_stage_id(ctx.job))
        doc = c.ref_in(script, "script_document")
        ver_out = c.stage_output(ctx, "s06_verify")
        ver = c.payload_of(ctx, ver_out)
        if ver["script_sha256"] != doc.sha256:
            raise InputInvalidError("the verified script is not the script to be voiced")
        docs = ctx.job.documents
        dictionary = c.need(docs.voice_dictionary, "the pronunciation dictionary")
        bound = c.bound_script_approval(ctx)  # BEFORE the paid voice stage: fail closed
        approval = bound.approval_id if bound is not None else None
        data = {
            "purpose": "PRODUCTION",
            "script_id": script["script_id"],
            "script_version": script["version"],
            "iteration": ctx.iteration,
            "language": ctx.job.language,
            "script_ref": doc.uri,
            "script_sha256": doc.sha256,
            "verification_ref": c.artifact(ver_out, r"claim_verification_output\.json").uri,
            "verification_approval_id": approval,
            "voice_id": c.need(docs.voice_id, "the voice"),
            "dictionary_ref": dictionary.uri,
            "dictionary_sha256": dictionary.sha256,
            "human_narration": None,
        }
        return BuiltInput(VOICE_SCHEMA, "1.0.0", data)


class AudioMasterBuilder:
    def build(self, ctx: BuildContext) -> BuiltInput:
        voice = c.payload(ctx, "s07_voice")
        narration, timeline = voice["narration"], voice["timeline"]
        pauses = [
            {"start_ms": p["start_ms"], "end_ms": p["end_ms"]}
            for p in timeline.get("pauses", [])
            if p.get("kind") == "SCENE_PAUSE"
        ]
        data = {
            "iteration": ctx.iteration,
            "narration_ref": narration["stem_uri"],
            "narration_sha256": narration["sha256"],
            "timeline_ref": timeline["timeline_uri"],
            "timeline_sha256": timeline["timeline_sha256"],
            "music_stem": None,
            "deliberate_pause_spans": pauses,
        }
        return BuiltInput(MASTER_SCHEMA, "1.0.0", data)
