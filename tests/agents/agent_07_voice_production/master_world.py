"""Builds the world of one ``audio_master`` golden case: a descriptor-driven stub of FFmpeg.

The stub returns the measurements of the case's stem descriptor and simulates gain + limiter and
the codec overshoot of ``codec_model`` (``stub`` measurement mode of the dataset README). Real
FFmpeg measurements are exercised by the integration test and the recorded-output parser tests.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_07_voice_production import contracts as c
from agent_07_voice_production.config import DenoiseMode
from agent_07_voice_production.master import CodecFacts
from agent_07_voice_production.master_stage import AudioMasterStage, MasterDeps
from agent_07_voice_production.ports import (
    AudioAnalysis,
    Loudness,
    SilenceSpan,
    StreamFacts,
)
from amw_core.contracts.task_output import TaskOutput
from amw_core.errors import AgentCrashError, RenderCrashError
from amw_core.exec_context import ExecContext
from amw_core.ids import CHANNEL, Prefix, new_id
from amw_core.testing.memory import MemoryCheckpointStore
from tests.agents.agent_07_voice_production.support import (
    FakeClock,
    FakeControl,
    FakeFacts,
    MemoryBlobs,
    MemoryTenancy,
    config,
    exec_ctx,
)
from tests.agents.agent_07_voice_production.voice_world import OTHER_ORG, make_task_input

ORG = "org_01939e5a-7c3b-7d1e-8a4f-0123456789ab"


@dataclass
class StubFfmpeg:
    """Implements ``AudioTools`` and ``MasteringBackend`` from a stem descriptor."""

    stem: dict[str, Any]
    overshoots: list[float]
    bitrate_bps: int
    faults: list[dict[str, Any]]
    renders: list[dict[str, float]] = field(default_factory=list)
    _gain: float = 0.0
    _ceiling: float = 0.0

    # -- AudioTools
    def probe(self, path: Path) -> StreamFacts:
        raise NotImplementedError

    def to_working_format(self, src: Path, dst: Path) -> None:
        raise NotImplementedError

    def analyse(
        self, path: Path, *, silence_noise_db: float, silence_min_s: float
    ) -> AudioAnalysis:
        s = self.stem
        samples = s["duration_ms"] * s["sample_rate_hz"] // 1000
        return AudioAnalysis(
            StreamFacts(s["sample_rate_hz"], s["channels"], samples, "pcm_s16le"),
            Loudness(s["integrated_lufs"], s["true_peak_dbtp"], s["lra_lu"]),
            s["clipping_samples"],
            -6.0,
            tuple(SilenceSpan(r["start_ms"], r["end_ms"]) for r in s["silence_runs"]),
            s["noise_floor_dbfs"],
        )

    # -- MasteringBackend
    def render(
        self,
        src: Path,
        dst: Path,
        *,
        gain_db: float,
        ceiling_dbtp: float,
        input_channels: int,
        denoise: DenoiseMode,
    ) -> None:
        n = len(self.renders) + 1
        for fault in self.faults:
            if fault.get("fault") == "FFMPEG_CRASH" and fault["at"] == f"during_pass_{n}":
                raise RenderCrashError("ffmpeg exited abnormally")
        self.renders.append({"gain": gain_db, "ceiling": ceiling_dbtp})
        self._gain, self._ceiling = gain_db, ceiling_dbtp
        dst.write_bytes(b"MASTER" + f"{gain_db}:{ceiling_dbtp}".encode())

    def measure_mapped(self, stem: Path, *, input_channels: int) -> Loudness:
        s = self.stem  # the stub models no channel term: the descriptor is the mapped value
        return Loudness(s["integrated_lufs"], s["true_peak_dbtp"], s["lra_lu"])

    def count_clipping(self, path: Path) -> int:
        return 0

    def analyse_master(self, path: Path) -> tuple[StreamFacts, Loudness]:
        n = len(self.renders)
        for fault in self.faults:
            if fault.get("fault") == "UNPARSABLE_OUTPUT" and fault["at"] == f"pass_{n}_measure":
                raise AgentCrashError("ffmpeg ebur128 produced no Summary block")
        s = self.stem
        predicted = s["true_peak_dbtp"] + self._gain
        tp = min(predicted, self._ceiling)
        reduction = max(0.0, predicted - self._ceiling)
        loudness = s["integrated_lufs"] + self._gain - 0.25 * reduction
        samples = s["duration_ms"] * s["sample_rate_hz"] // 1000
        return (
            StreamFacts(48_000, 2, samples, "pcm_s24le"),
            Loudness(round(loudness, 3), round(tp, 3), s["lra_lu"]),
        )

    def codec_verify(self, master: Path, workdir: Path, *, bitrate_bps: int) -> CodecFacts:
        _, post = self.analyse_master(master)
        idx = min(len(self.renders) - 1, len(self.overshoots) - 1)
        assert post.true_peak_dbtp is not None
        shifted = Loudness(
            post.integrated_lufs, round(post.true_peak_dbtp + self.overshoots[idx], 3), post.lra_lu
        )
        return CodecFacts("aac", "LC", 48_000, 2, self.bitrate_bps, shifted)

    def build(self) -> str:
        return "ffmpeg stub"


@dataclass
class MasterWorld:
    stage: AudioMasterStage
    task_input: Any
    blobs: MemoryBlobs
    ffmpeg: StubFfmpeg
    checkpoints: MemoryCheckpointStore
    control: FakeControl
    deps: MasterDeps

    def ctx(self, attempt: str | None = None) -> ExecContext:
        return exec_ctx(self.task_input, attempt or new_id(Prefix.TASK_ATTEMPT))

    def run(self, attempt: str | None = None) -> TaskOutput:
        return self.stage.run(self.task_input, self.ctx(attempt))

    def master_written(self) -> bool:
        return any(u.endswith("/artifacts/master.wav") for u in self.blobs.data)


def build(case: dict[str, Any], scratch: Path) -> MasterWorld:
    fx = case["input"]["fixtures"]
    payload: dict[str, Any] = json.loads(json.dumps(case["input"]["payload"]))
    stem, tl, cfgx = fx["stem"], fx["timeline"], fx["config"]
    blobs = MemoryBlobs()
    stem_bytes = b"STEM" + case["case_id"].encode()
    stem_sha = hashlib.sha256(stem_bytes).hexdigest()
    ref_org = OTHER_ORG if stem["org"] == "other" else ORG
    payload["narration_ref"] = payload["narration_ref"].replace(ORG, ref_org)
    blobs.seed(payload["narration_ref"], stem_bytes)
    payload["narration_sha256"] = stem_sha if stem["sha_matches"] else payload["narration_sha256"]
    timeline = c.NarrationTimeline(
        script_id="scr_98d3acae-b594-7687-8641-4f666d21ff77",
        script_version=1,
        iteration=payload["iteration"],
        purpose=c.Purpose(stem["purpose"]),
        source=c.TimelineSource.PROVIDER_CLIPS,
        total_duration_ms=tl["total_duration_ms"],
        segments=(
            c.TimelineSegment(
                segment_id="s1",
                start_ms=0,
                end_ms=tl["total_duration_ms"],
                duration_ms=tl["total_duration_ms"],
                pace_requested=c.Pace.NORMAL,
                emotion_requested=c.Emotion.NEUTRAL,
                pace_applied=c.AppliedPace.NONE,
                emotion_applied=c.AppliedEmotion.NONE,
                spoken_text_sha256=None,
                reused_clip=False,
                idempotency_key=None,
            ),
        ),
    )
    tl_bytes = timeline.model_dump_json().encode()
    blobs.seed(payload["timeline_ref"], tl_bytes)
    payload["timeline_sha256"] = hashlib.sha256(tl_bytes).hexdigest()
    if payload.get("music_stem") is not None:
        music = b"MUSIC" + case["case_id"].encode()
        blobs.seed(payload["music_stem"]["stem_ref"], music)
        payload["music_stem"]["stem_sha256"] = hashlib.sha256(music).hexdigest()

    cm = fx["codec_model"]
    ffmpeg = StubFfmpeg(
        stem, list(cm["post_codec_true_peak_overshoot_db"]), cm["bitrate_bps"], fx["faults"]
    )
    for fault in fx[
        "faults"
    ]:  # AM-30 needs a second pass to exist: see the module note in the test
        if fault.get("fault") == "FFMPEG_CRASH":
            ffmpeg.overshoots = [0.6, *ffmpeg.overshoots[1:]]
    control = FakeControl(drain=any(f.get("control") == "DRAIN" for f in fx["faults"]))
    keys = (
        "target_lufs",
        "true_peak_max_dbtp",
        "tolerance_lu",
        "max_passes",
        "limiter_ceiling_dbtp",
        "codec_headroom_step_db",
        "max_limiter_reduction_db",
        "max_silence_ms",
        "music_enabled",
        "min_bitrate_bps",
        "denoise_mode",
    )
    cfg = config(**{k: cfgx[k] for k in keys})
    facts = FakeFacts(
        music_licensed=all(
            a["licence_ledger_row"] for a in (fx["music"] or {"assets": []})["assets"]
        )
    )
    checkpoints = MemoryCheckpointStore()
    deps = MasterDeps(
        config=cfg,
        storage=blobs,
        tenancy=MemoryTenancy(),
        checkpoints=checkpoints,
        facts=facts,
        tools=ffmpeg,
        backend=ffmpeg,
        clock=FakeClock(),
        control=control,
        scratch_root=scratch,
    )
    task_input = make_task_input(
        ORG, CHANNEL.new(), payload, "agent_07.audio_master.input", "agent_07"
    )
    return MasterWorld(
        AudioMasterStage(deps), task_input, blobs, ffmpeg, checkpoints, control, deps
    )
