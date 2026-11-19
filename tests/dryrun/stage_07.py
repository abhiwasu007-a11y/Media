# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated,index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""``s07_voice`` / ``s07_master`` -> Agent 07 with a fake TTS that writes REAL audio.

The fake voice is the agents' own ``ToneTts`` (a 440 Hz tone whose length follows the text,
``ms_per_char``); probing, silence and loudness measurement and the master use the REAL
FFmpeg tools of Agent 07 (``FfmpegAudioTools`` / ``FfmpegMasteringBackend``).
"""

import json
from datetime import timedelta
from typing import Any

from agent_07_voice_production.ffmpeg import FfmpegAudioTools, SubprocessRunner
from agent_07_voice_production.master import FfmpegMasteringBackend
from agent_07_voice_production.master_stage import AudioMasterStage, MasterDeps
from agent_07_voice_production.ports import AssetFacts, LicenceFacts, VoiceBundle
from agent_07_voice_production.voice_stage import VoiceDeps, VoiceSynthesisStage
from amw_adapters.tts import TtsRequest, TtsResult
from amw_core.contracts import TaskOutput
from amw_core.enums import (
    AssetStatus,
    LicenceSourceType,
    LicenceState,
    PresenterKind,
    ThirdPartyPermission,
    VoiceKind,
)
from amw_core.ids import Prefix, new_id
from amw_core.interfaces.voices import VoiceRecord
from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore
from amw_orchestrator.executor import StageCall
from amw_orchestrator.metering import MeteredTts
from tests.agents.agent_07_voice_production import support as s7
from tests.dryrun.base import World, task_input, upstream, upstream_data
from tests.dryrun.kit import AllowBudget, MemTenancy, MirrorLedger, ref_ending


class _MeteredView:
    """Agent 07's stage-facing TTS view over the metered fake (no ``list_voices``)."""

    def __init__(self, metered: MeteredTts, caps: Any) -> None:
        self._m, self._caps = metered, caps

    @property
    def provider(self) -> str:
        return self._m.provider

    def capabilities(self) -> Any:
        return self._caps

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult:
        return self._m.synthesize(request, idempotency_key=idempotency_key)


class VoiceExecutor:
    def __init__(self, world: World, ms_per_char: int) -> None:
        self.w = world
        self.ms_per_char = ms_per_char
        self.voice_id = new_id(Prefix.VOICE)
        self.registry = s7.FakeRegistry()
        self._dictionary: tuple[str, str] | None = None

    def _facts(self, call: StageCall, script_sha: str, dict_uri: str, dict_sha: str) -> Any:
        org = call.job.org_id
        licence = LicenceFacts(
            new_id(Prefix.LICENCE),
            org,
            LicenceState.ACTIVE,
            LicenceSourceType.TTS_PROVIDER,
            True,
            ThirdPartyPermission.PERMITTED,
        )
        voice = VoiceRecord(
            self.voice_id,
            org,
            "PLUMBING fake tone voice",
            VoiceKind.PROVIDER_STOCK,
            "fake_tts",
            "fake-neutral-1",
            ("mr-IN", "hi-IN"),
            None,
            None,
            licence.licence_id,
            PresenterKind.NEUTRAL_NARRATION,
            AssetStatus.ACTIVE,
        )
        return s7.FakeFacts(
            script_hash=script_sha,
            bundle=VoiceBundle(voice, licence, None, False),
            brand_kit_voice=self.voice_id,
            monetized=False,
            platform_owner=True,
            assets={
                dict_uri: AssetFacts(
                    new_id(Prefix.ASSET), org, "DOCUMENT", True, (call.job.channel_id,), dict_sha
                )
            },
        )

    def execute(self, call: StageCall) -> TaskOutput:
        script_stage = "s05_shorts" if "s05_shorts" in call.upstream else "s05_script"
        sdata = upstream_data(call, script_stage)
        sref = ref_ending(upstream(call, script_stage), ".json")
        vref = ref_ending(upstream(call, "s06_verify"), "claim_verification_output.json")
        if self._dictionary is None:
            doc = {
                "dictionary_key": "plumbing-dict",
                "language": "mr-IN",
                "version": 1,
                "entries": [],
            }
            self._dictionary = self.w.blobs.put_bytes(
                "assets", "dictionaries/plumbing-mr.json", json.dumps(doc).encode()
            )
        dict_uri, dict_sha = self._dictionary
        tone = s7.ToneTts(ms_per_char=self.ms_per_char)
        caps = s7.capabilities()
        deps = VoiceDeps(
            config=s7.config(),
            tts=_MeteredView(MeteredTts(tone, self.w.meter, 100_000), caps),  # type: ignore[arg-type]
            storage=self.w.blobs.storage,
            tenancy=MemTenancy(),
            idempotency=MemoryIdempotencyStore(),
            ledger=MirrorLedger(),  # type: ignore[arg-type]
            budget=AllowBudget(),  # type: ignore[arg-type]
            breaker=s7.FakeBreaker(),
            checkpoints=MemoryCheckpointStore(),
            facts=self._facts(call, sref.sha256, dict_uri, dict_sha),
            registry=self.registry,
            tools=FfmpegAudioTools(SubprocessRunner()),
            clock=self.w.clock,
            control=s7.FakeControl(),
            scratch_root=self.w.scratch / "a07" / call.task_id,
            sleep=lambda _s: None,
        )
        payload = {
            "purpose": "PRODUCTION",
            "script_id": sdata["script_id"],
            "script_version": sdata["version"],
            "iteration": call.iteration,
            "language": sdata["language"],
            "script_ref": sref.uri,
            "script_sha256": sref.sha256,
            "verification_ref": vref.uri,
            "verification_approval_id": None,
            "voice_id": self.voice_id,
            "dictionary_ref": dict_uri,
            "dictionary_sha256": dict_sha,
            "human_narration": None,
        }
        ti = task_input(call, "agent_07", "agent_07.voice_synthesis.input", payload)
        return VoiceSynthesisStage(deps).run(ti, call.attempt_id)


class MasterExecutor:
    def __init__(self, world: World) -> None:
        self.w = world

    def execute(self, call: StageCall) -> TaskOutput:
        voice = upstream(call, "s07_voice")
        narration = next(r for r in voice.output_refs if r.media_type.startswith("audio/"))
        timeline = next(r for r in voice.output_refs if "timeline" in r.uri)
        tools = FfmpegAudioTools(SubprocessRunner())
        deps = MasterDeps(
            config=s7.config(),
            storage=self.w.blobs.storage,
            tenancy=MemTenancy(),
            checkpoints=MemoryCheckpointStore(),
            facts=s7.FakeFacts(),
            tools=tools,
            backend=FfmpegMasteringBackend(SubprocessRunner(), tools),
            clock=self.w.clock,
            control=s7.FakeControl(),
            scratch_root=self.w.scratch / "a07m" / call.task_id,
        )
        payload = {
            "iteration": call.iteration,
            "narration_ref": narration.uri,
            "narration_sha256": narration.sha256,
            "timeline_ref": timeline.uri,
            "timeline_sha256": timeline.sha256,
            "music_stem": None,
            "deliberate_pause_spans": [],
        }
        ti = task_input(call, "agent_07", "agent_07.audio_master.input", payload)
        return AudioMasterStage(deps).run(ti, call.attempt_id)


_ = timedelta
