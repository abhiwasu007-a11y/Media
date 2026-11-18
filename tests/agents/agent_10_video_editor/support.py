"""Test support: sample worlds (plan, manifest, assets, audio) for Agent 10 tests."""

from typing import Any

from agent_10_video_editor.inputs import (
    AssetManifest,
    AssetRecord,
    AudioMaster,
    ShotPlan,
)
from agent_10_video_editor.testing import make_config
from agent_10_video_editor.timeline import Timeline, TimelineCompiler

SHA_A = "a" * 64


def audio_master(duration_ms: int, *, verdict: str = "PASSED") -> AudioMaster:
    return AudioMaster.model_validate(
        {
            "master": {
                "master_uri": "amw-blob://org_x/jobs/j/master.wav",
                "sha256": SHA_A,
                "duration_ms": duration_ms,
                "sample_rate_hz": 48000,
                "channels": 2,
            },
            "codec_profile": {
                "codec": "aac",
                "profile": "LC",
                "sample_rate_hz": 48000,
                "channels": 2,
                "bitrate_bps": 384000,
                "encoder": "aac",
                "rate_mode": "CBR",
            },
            "gate_verdict": verdict,
        }
    )


def compile_case(i: dict[str, Any]) -> Timeline:
    """Build plan, manifest and catalog from the abstract shots of a golden case and compile."""
    fps_num, fps_den = i["fps_num"], i["fps_den"]
    total = i["total_duration_ms"]
    shots: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    assets: dict[str, AssetRecord] = {}
    for n, s in enumerate(i["shots"]):
        shots.append({"shot_id": s["shot_id"], "start_ms": s["start_ms"], "end_ms": s["end_ms"]})
        if s["asset"] == "present":
            asset_id = f"asset_{n}"
            digest = f"{n:02x}" * 32
            entries.append(
                {
                    "shot_id": s["shot_id"],
                    "aspect_ratio": "16:9",
                    "status": "SOURCED",
                    "tier": "C_CODE_MOTION",
                    "asset_id": asset_id,
                    "asset_uri": f"amw-blob://org_x/assets/{asset_id}.png",
                    "fingerprints": {"sha256": digest},
                }
            )
            assets[asset_id] = AssetRecord(
                asset_id=asset_id, uri=f"amw-blob://org_x/assets/{asset_id}.png", sha256=digest
            )
    content_end = shots[-1]["end_ms"]
    plan = ShotPlan.model_validate(
        {
            "timing_basis": "MEASURED",
            "language": "mr",
            "aspect_ratio": "16:9",
            "total_duration_ms": total,
            "content_end_ms": content_end,
            "shots": shots,
        }
    )
    manifest = AssetManifest.model_validate({"shots": entries})
    cfg = make_config(render={"fps_num": fps_num, "fps_den": fps_den})
    return TimelineCompiler.compile(plan, manifest, assets, audio_master(total), cfg, "16:9")


# ----------------------------------------------------------------------------- stage-level world

import json  # noqa: E402
from collections.abc import Callable, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Protocol  # noqa: E402

from agent_10_video_editor.canonical import sha256_hex  # noqa: E402
from agent_10_video_editor.config import AgentTenConfig, Placement  # noqa: E402
from agent_10_video_editor.deps import StageDeps  # noqa: E402
from agent_10_video_editor.guard import LocalTime  # noqa: E402
from agent_10_video_editor.ports import LicenceSnapshot  # noqa: E402
from agent_10_video_editor.testing import (  # noqa: E402
    FakeAdmissionProbe,
    FakeClock,
    FakeFfmpegRunner,
    ManualTimerFactory,
    MemoryAssetCatalog,
    MemoryAuditLog,
    MemoryBlobStorage,
    MemoryCostLedger,
    MemoryLicenceReader,
    MemoryQcResultRepository,
    MemoryRenderRepository,
    MemoryTenancy,
)
from amw_core.contracts.task_input import TaskInput  # noqa: E402
from amw_core.ids import ASSET, ATTEMPT, JOB, ORG, TASK, ActorRef  # noqa: E402
from amw_core.interfaces.tenancy_context import TenantContext  # noqa: E402
from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore  # noqa: E402

IDK = "idk_" + "ab" * 32
COR = "cor_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e94"
NIGHT = LocalTime.parse("SAT", "22:00")  # outside every market window of the fixture calendar


class MediaFactory(Protocol):
    """Generates real synthetic media at test time (never real material, never network)."""

    def shot(self, label: str, duration_ms: int) -> tuple[bytes, str]: ...

    def still(self, label: str) -> bytes: ...

    def master(self, duration_ms: int) -> bytes: ...


class World:
    """One tenant, one job, a tiled plan with generated (fake) assets and a passed audio master."""

    def __init__(
        self,
        tmp: Path,
        *,
        shots: int = 4,
        shot_ms: int = 4000,
        chart: bool = False,
        config: AgentTenConfig | None = None,
        now: LocalTime = NIGHT,
        placement: Placement = Placement.DEV,
        org: str | None = None,
        media: MediaFactory | None = None,
        storage: MemoryBlobStorage | None = None,
        script_overrides: dict[str, str] | None = None,
        entry_overrides: dict[int, dict[str, Any]] | None = None,
        channel_id: str | None = None,
    ) -> None:
        self.org = org or str(ORG.new())
        self.job = str(JOB.new())
        self.task = str(TASK.new())
        self.attempt = str(ATTEMPT.new())
        self.cfg = config or make_config()
        self.ctx = TenantContext(org_id=self.org, actor=ActorRef("agent_10"))  # type: ignore[arg-type]
        self.storage = storage or MemoryBlobStorage()
        self.tenancy = MemoryTenancy()
        self.checkpoints = MemoryCheckpointStore()
        self.cost = MemoryCostLedger()
        self.idempotency = MemoryIdempotencyStore()
        self.audit = MemoryAuditLog()
        self.runner = FakeFfmpegRunner()
        self.probe = FakeAdmissionProbe(now, placement)
        self.timers = ManualTimerFactory()
        self.clock = FakeClock()
        self.renders = MemoryRenderRepository()
        self.assets = MemoryAssetCatalog()
        self.qc_results = MemoryQcResultRepository()
        self.licences = MemoryLicenceReader()
        self.scratch = tmp / "scratch"
        self.n_shots, self.shot_ms, self.chart = shots, shot_ms, chart
        self.media = media
        self.script_overrides = script_overrides or {}
        self.entry_overrides = entry_overrides or {}
        self.channel_id = channel_id
        self.refs: dict[str, tuple[str, str]] = {}
        self.docs: dict[str, Any] = {}
        self._build()

    def hook_checkpoints(self, on_write: Callable[[str], None]) -> None:
        """Call ``on_write(step_key)`` after every checkpoint row is written."""
        inner = self.checkpoints
        real_write = inner.write

        def write(tx: Any, checkpoint: Any, now: Any) -> Any:
            record = real_write(tx, checkpoint, now)
            on_write(checkpoint.step_key)
            return record

        inner.write = write  # type: ignore[method-assign]

    # -- documents ------------------------------------------------------------------------------

    def revise_shot(self, index: int, data: bytes, ext: str = "mp4") -> None:
        """A revision iteration: replace the asset of one shot (new asset id, new bytes) and
        refresh the manifest document and its context ref; a new task id is allocated."""
        entries = self.docs["agent_08.asset_sourcing.output"]["shots"]
        entry = entries[index]
        asset_id, uri, sha = self._asset(f"{entry['shot_id']}-rev", data, ext)
        entry.update({"asset_id": asset_id, "asset_uri": uri, "fingerprints": {"sha256": sha}})
        raw = json.dumps(self.docs["agent_08.asset_sourcing.output"], sort_keys=True).encode()
        self.refs["agent_08.asset_sourcing.output"] = self.put("manifest-rev.json", raw)
        self.task = str(TASK.new())
        self.attempt = str(ATTEMPT.new())

    def put(self, name: str, data: bytes) -> tuple[str, str]:
        uri = f"amw-blob://{self.org}/jobs/{self.job}/inputs/{name}"
        info = self.storage.put_bytes(self.ctx, uri, data)
        return info.uri, info.sha256

    def _asset(self, label: str, payload: bytes, ext: str = "png") -> tuple[str, str, str]:
        asset_id = str(ASSET.new())
        uri, sha = self.put(f"{label}.{ext}", payload)
        self.assets.add(self.org, AssetRecord(asset_id=asset_id, uri=uri, sha256=sha))
        return asset_id, uri, sha

    def _build(self) -> None:
        total = self.n_shots * self.shot_ms
        shots: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = []
        segments: dict[str, str] = {}
        narration: list[dict[str, Any]] = []
        for n in range(self.n_shots):
            sid = f"sh{n + 1:02d}"
            start, end = n * self.shot_ms, (n + 1) * self.shot_ms
            is_chart = self.chart and n == 1
            events = [start + self.shot_ms // 2] if is_chart else []
            shots.append(
                {
                    "shot_id": sid,
                    "start_ms": start,
                    "end_ms": end,
                    "intent_kind": "CHART" if is_chart else "FOOTAGE",
                    "change_events_ms": events,
                    "section_id": "sec1",
                    "segment_ids": [f"s{n + 1}"],
                }
            )
            if self.media is not None:
                data, ext = self.media.shot(sid, self.shot_ms)
                asset_id, uri, sha = self._asset(sid, data, ext)
            else:
                asset_id, uri, sha = self._asset(sid, f"asset-{sid}".encode())
            stills: list[dict[str, Any]] = []
            if is_chart:
                bounds = [start, *events]
                for k, st in enumerate(bounds):
                    still_bytes = (
                        self.media.still(f"{sid}-{k}")
                        if self.media is not None
                        else f"still-{sid}-{k}".encode()
                    )
                    a, u, h = self._asset(f"{sid}-still{k}", still_bytes)
                    stills.append(
                        {
                            "k": k,
                            "asset_id": a,
                            "asset_uri": u,
                            "sha256": h,
                            "start_ms": st,
                            "end_ms": ([*bounds, end])[k + 1],
                            "licence_id": "lic_x",
                            "ledger_entry_ids": ["lcu_x"],
                        }
                    )
            entries.append(
                {
                    "shot_id": sid,
                    "aspect_ratio": "16:9",
                    "status": "SOURCED",
                    "tier": "C_CODE_MOTION",
                    "asset_id": asset_id,
                    "asset_uri": uri,
                    "fingerprints": {"sha256": sha},
                    "reveal_stills": stills,
                }
            )
            entries[-1].update(self.entry_overrides.get(n, {}))
            segments[f"s{n + 1}"] = f"line number {n + 1} of the narration text"
            narration.append({"segment_id": f"s{n + 1}", "start_ms": start, "end_ms": end})
        segments.update(self.script_overrides)
        script_sha = sha256_hex(json.dumps(segments, sort_keys=True).encode())
        self.script_sha = script_sha
        plan = {
            "timing_basis": "MEASURED",
            "language": "mr",
            "aspect_ratio": "16:9",
            "total_duration_ms": total,
            "content_end_ms": total,
            "shots": shots,
            "hook": {"end_ms": 8000, "first_payoff_ms": 6000},
            "chapters": [{"section_id": "sec1", "start_ms": 0}],
        }
        master_bytes = self.media.master(total) if self.media is not None else b"RIFF-fake-master"
        master_uri, master_sha = self.put("master.wav", master_bytes)
        audio = {
            "master": {
                "master_uri": master_uri,
                "sha256": master_sha,
                "duration_ms": total,
                "sample_rate_hz": 48000,
                "channels": 2,
            },
            "codec_profile": {
                "codec": "aac",
                "profile": "LC",
                "sample_rate_hz": 48000,
                "channels": 2,
                "bitrate_bps": 384000,
                "encoder": "aac",
                "rate_mode": "CBR",
            },
            "gate_verdict": "PASSED",
        }
        docs = {
            "agent_09.shot_plan.output": plan,
            "agent_08.asset_sourcing.output": {"shots": entries},
            "agent_07.audio_master.output": audio,
            "agent_07.voice_synthesis.output": {
                "source": "PROVIDER_CLIPS",
                "language": "mr",
                "segments": narration,
            },
            "agent_05.script_document": {"script_sha256": script_sha, "segments": segments},
        }
        self.docs = docs
        for schema, doc in docs.items():
            data = json.dumps(doc, sort_keys=True).encode()
            uri, sha = self.put(f"{schema}.json", data)
            self.refs[schema] = (uri, sha)
        # the verified script hash is the hash of the script blob (script_sha256 field mirrors it)
        _, blob_sha = self.refs["agent_05.script_document"]
        self.script_blob_sha = blob_sha
        self.total_ms = total

    # -- inputs ---------------------------------------------------------------------------------

    def _ref(self, schema: str, uri: str, sha: str) -> dict[str, Any]:
        return {"uri": uri, "purpose": "PRIOR_OUTPUT", "sha256": sha, "schema": schema}

    def task_input(
        self,
        kind: str,
        payload: dict[str, Any],
        extra_refs: Sequence[dict[str, Any]] = (),
        schemas: Sequence[str] | None = None,
    ) -> TaskInput:
        names = schemas or list(self.refs)
        refs = [self._ref(s, *self.refs[s]) for s in names if s in self.refs] + list(extra_refs)
        return TaskInput.model_validate(
            {
                "org_id": self.org,
                "job_id": self.job,
                "task_id": self.task,
                "project_id": None,
                "channel_id": self.channel_id,
                "agent_id": "agent_10",
                "source_agent": "agent_01",
                "priority": "NORMAL",
                "deadline": None,
                "context_refs": refs,
                "resource_budget": {
                    "max_cost_micros": 0,
                    "currency": "INR",
                    "max_wall_ms": 10**9,
                    "max_llm_calls": 0,
                },
                "payload": {
                    "payload_schema": f"agent_10.{kind}.input",
                    "payload_schema_version": "1.0.0",
                    "data": payload,
                },
                "correlation_id": COR,
                "idempotency_key": IDK,
                "retry_count": 0,
                "schema_version": "1.0.0",
            }
        )

    def render_input(self, **override: Any) -> TaskInput:
        payload = {
            "render_kind": "MASTER",
            "preset_key": "yt_master_1080p",
            "aspect_ratio": "16:9",
            "language": "mr",
            "iteration": 0,
            "verified_script_sha256": self.script_blob_sha,
            "previous_render_ref": None,
            "music_bed": None,
        }
        payload.update(override)
        return self.task_input("render", payload)

    def deps(self) -> StageDeps:
        return StageDeps(
            cfg=self.cfg,
            storage=self.storage,
            tenancy=self.tenancy,
            checkpoints=self.checkpoints,
            cost_ledger=self.cost,
            idempotency=self.idempotency,
            audit=self.audit,
            runner=self.runner,
            admission=self.probe,
            timers=self.timers,
            clock=self.clock,
            scratch_root=self.scratch,
            renders=self.renders,
            assets=self.assets,
            qc_results=self.qc_results,
            licences=self.licences,
        )


__all__ = ["LicenceSnapshot", "World", "audio_master", "compile_case"]


def payload_data(output: Any) -> dict[str, Any]:
    """The inline payload data of a Task Output (asserts it is present)."""
    assert output.payload is not None
    assert output.payload.data is not None
    data: dict[str, Any] = output.payload.data
    return data


def run_chain(world: World) -> dict[str, Any]:
    """render -> subtitles on the world; returns outputs and the QC task input."""
    from agent_10_video_editor.qc.stage import QcStage  # noqa: F401
    from agent_10_video_editor.render import RenderStage
    from agent_10_video_editor.subtitle_stage import SubtitleStage

    render_out = RenderStage(world.deps()).run(
        world.render_input(), world.attempt, envelope_org=world.org
    )
    assert render_out.payload is not None
    assert render_out.payload.data is not None
    rdata = render_out.payload.data
    r_uri, r_sha = world.put("render.output.json", json.dumps(rdata, sort_keys=True).encode())
    world.refs["agent_10.render.output"] = (r_uri, r_sha)
    world.refs["agent_10.timeline"] = (
        rdata["timeline_ref"]["uri"],
        rdata["timeline_ref"]["sha256"],
    )
    world.task, world.attempt = str(TASK.new()), str(ATTEMPT.new())  # each stage is its own task
    subs_in = world.task_input(
        "subtitles",
        {
            "render_id": rdata["render_id"],
            "language": "mr",
            "iteration": 0,
            "verified_script_sha256": world.script_blob_sha,
            "caption_style": None,
        },
        schemas=[
            "agent_10.render.output",
            "agent_07.voice_synthesis.output",
            "agent_05.script_document",
        ],
    )
    subs_out = SubtitleStage(world.deps()).run(subs_in, world.attempt)
    assert subs_out.payload is not None
    assert subs_out.payload.data is not None
    s_uri, s_sha = world.put(
        "subs.output.json", json.dumps(subs_out.payload.data, sort_keys=True).encode()
    )
    world.refs["agent_10.subtitles.output"] = (s_uri, s_sha)
    world.task, world.attempt = str(TASK.new()), str(ATTEMPT.new())
    qc_in = world.task_input(
        "technical_qc",
        {
            "render_id": rdata["render_id"],
            "render_sha256": rdata["render_ref"]["sha256"],
            "qc_profile": "qc.long_form",
            "iteration": 0,
            "music_bed": None,
            "destination": "MONETIZED_YOUTUBE",
        },
    )
    return {"render": render_out, "subtitles": subs_out, "qc_input": qc_in}


def licensed_snapshot(world: World) -> LicenceSnapshot:
    """Ledger rows covering every shot, one ACTIVE monetised licence, every asset ACTIVE."""
    ledger = []
    assets = {}
    for entry in world.docs["agent_08.asset_sourcing.output"]["shots"]:
        assets[entry["asset_id"]] = {"status": "ACTIVE", "ai_item": False}
        ledger.append(
            {
                "asset_id": entry["asset_id"],
                "licence_id": "L1",
                "render_id": None,
                "used_from_ms": None,
                "used_to_ms": None,
                "usage_kind": "SHOT",
            }
        )
        for still in entry["reveal_stills"]:
            assets[still["asset_id"]] = {"status": "ACTIVE", "ai_item": False}
            ledger.append(
                {
                    "asset_id": still["asset_id"],
                    "licence_id": "L1",
                    "render_id": None,
                    "used_from_ms": None,
                    "used_to_ms": None,
                    "usage_kind": "IMAGE",
                }
            )
    licences = {
        "L1": {
            "state": "ACTIVE",
            "covers_monetized_youtube": True,
            "expires_in_days": None,
            "third_party_permission": "PERMITTED",
            "org": world.org,
        }
    }
    return LicenceSnapshot(ledger=ledger, licences=licences, assets=assets)
