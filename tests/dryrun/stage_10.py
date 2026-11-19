# mypy: disable-error-code="arg-type,attr-defined,unused-ignore,var-annotated,index,no-untyped-call,misc,union-attr"
# (throw-away dry-run fixtures feed fakes and dataset dicts into typed APIs)
"""``s10_render`` / ``s10_subs`` / ``s10_qc`` -> Agent 10 with the REAL local FFmpeg.

The market-hours guard of Agent 10 stays ON: the admission probe reads the real wall clock in
Asia/Kolkata (no fake time), and the configured market windows are the agent's own test
calendar (Mon-Fri 09:00-16:00 local); the graph runner checks S4's calendar as well.
Render size: ``modest`` = the production preset geometry (1920x1080, yt_master_1080p, x264
``faster``); ``tiny`` (CI) = 640x360 with the QC geometry / bitrate floors lowered to match
(a CONFIG difference only, same code path). Both are stated in the report.
"""

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from agent_10_video_editor.config import AgentTenConfig, Placement
from agent_10_video_editor.deps import StageDeps
from agent_10_video_editor.ffmpeg import ArgvBuilder, ProcessFfmpegRunner
from agent_10_video_editor.guard import LocalTime, ThreadTimerFactory
from agent_10_video_editor.inputs import AssetRecord
from agent_10_video_editor.ports import LicenceSnapshot
from agent_10_video_editor.qc.selftest import QcSelfTest, SelfTestRecord
from agent_10_video_editor.qc.stage import QcStage
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.subtitle_stage import SubtitleStage
from agent_10_video_editor.testing import (
    MemoryAssetCatalog,
    MemoryAuditLog,
    MemoryCostLedger,
    MemoryLicenceReader,
    MemoryQcResultRepository,
    MemoryRenderRepository,
    make_config,
)
from amw_core.contracts import TaskOutput
from amw_core.testing.memory import MemoryCheckpointStore, MemoryIdempotencyStore
from amw_orchestrator.executor import StageCall
from tests.dryrun.base import World, task_input, upstream, upstream_data
from tests.dryrun.kit import MemTenancy, ref_ending

_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


class WallClockAdmission:
    """``AdmissionProbe`` over the real clock (Asia/Kolkata), DEV placement, no drain."""

    zone = ZoneInfo("Asia/Kolkata")

    def now_local(self) -> LocalTime:
        now = datetime.now(UTC).astimezone(self.zone)
        return LocalTime.parse(_DAYS[now.weekday()], f"{now.hour:02d}:{now.minute:02d}")

    def drain_flag(self) -> bool:
        return False

    def placement(self) -> Placement:
        return Placement.DEV


def config(scale: str, profile: str = "qc.long_form") -> AgentTenConfig:
    render: dict[str, Any] = {
        "segment_target_ms": 8000,
        "gop_frames": 60,
        "x264_preset": "faster",
        "threads": 2,
    }
    qc: dict[str, Any] = {"profile": profile}
    # Code-made still graphics encode far below the 18 section 6 floor (8 Mbps) with x264 ABR
    # (dry-run finding): the floors are lowered for the PLUMBING run only and reported.
    qc.update({"video_bitrate_floor_bps": 10_000, "video_bitrate_min_bps": 20_000})
    if scale == "tiny":
        render.update(
            {
                "width_px": 640,
                "height_px": 360,
                "video_bitrate_bps": 1_000_000,
                "video_maxrate_bps": 1_500_000,
                "x264_preset": "faster",
            }
        )
        qc.update({"min_width_px": 640, "min_height_px": 360})
    if profile == "qc.shorts":
        w, h = (360, 640) if scale == "tiny" else (1080, 1920)
        render.update({"width_px": w, "height_px": h, "preset_key": "shorts_9x16"})
        qc.update({"min_width_px": w, "min_height_px": h})
    return make_config(render=render, qc=qc)


def font_code_points(data: bytes) -> frozenset[int]:
    """cmap reader over fontTools (already pinned by agent 11; offline)."""
    import io

    from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

    cmap = TTFont(io.BytesIO(data)).getBestCmap() or {}
    return frozenset(cmap)


class _SelfTests:
    def __init__(self, cfg: AgentTenConfig, work: Any) -> None:
        self.cfg, self.work = cfg, work
        self.cache: dict[str, SelfTestRecord] = {}

    def record_for(self, build_id: str) -> SelfTestRecord:
        if build_id not in self.cache:
            self.work.mkdir(parents=True, exist_ok=True)
            self.cache[build_id] = QcSelfTest.run(
                ProcessFfmpegRunner(), ArgvBuilder(self.cfg.render), self.work, build_id
            )
        return self.cache[build_id]


class EditorExecutor:
    def __init__(self, world: World) -> None:
        self.w = world
        self.renders = MemoryRenderRepository()
        self.assets = MemoryAssetCatalog()
        self.qc_results = MemoryQcResultRepository()
        self.licences = MemoryLicenceReader()
        self.cost = MemoryCostLedger()
        self.audit = MemoryAuditLog()
        self.selftests: dict[str, _SelfTests] = {}

    def _cfg(self, call: StageCall) -> AgentTenConfig:
        shorts = call.job.production_type_key.value == "SHORTS"
        return config(self.w.render_scale, "qc.shorts" if shorts else "qc.long_form")

    def deps(self, call: StageCall) -> StageDeps:
        return StageDeps(
            cfg=self._cfg(call),
            storage=self.w.blobs.storage,
            tenancy=MemTenancy(),
            checkpoints=MemoryCheckpointStore(),
            cost_ledger=self.cost,
            idempotency=MemoryIdempotencyStore(),
            audit=self.audit,
            runner=ProcessFfmpegRunner(),
            admission=self.w.extras.get("admission") or WallClockAdmission(),
            timers=ThreadTimerFactory(),
            clock=self.w.clock,
            scratch_root=self.w.scratch / "a10" / call.task_id,
            renders=self.renders,
            assets=self.assets,
            qc_results=self.qc_results,
            licences=self.licences,
            font_reader=font_code_points,
        )

    # -- input builders ------------------------------------------------------------------------
    def _put(self, call: StageCall, name: str, doc: object) -> tuple[str, str]:
        return self.w.blobs.put_bytes(
            "jobs",
            f"{call.job.job_id}/tasks/{call.task_id}/inputs/{name}",
            json.dumps(doc, sort_keys=True, ensure_ascii=False).encode(),
        )

    def _refs(self, call: StageCall) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        shorts = call.job.production_type_key.value == "SHORTS"
        script_stage = "s05_shorts" if shorts else "s05_script"
        org = call.job.org_id
        sref = ref_ending(upstream(call, script_stage), ".json")
        doc = self.w.blobs.read_json(sref.uri, sref.sha256)
        on_screen = {}
        for sc in doc.get("scenes", []):
            for text in sc.get("on_screen_text") or []:
                on_screen[__import__("hashlib").sha256(text.encode()).hexdigest()] = text
        from tests.dryrun.runtime_iface import get_disclaimer

        disc = get_disclaimer("v1").text
        for slot in doc.get("disclaimer_slots", []):
            if __import__("hashlib").sha256(disc.encode()).hexdigest() == slot["text_sha256"]:
                on_screen[slot["text_sha256"]] = disc
        view = {
            "script_sha256": sref.sha256,
            "segments": {s["segment_id"]: s["text"] for s in doc["segments"]},
            "on_screen": on_screen,
        }
        plan_ref = upstream_data(call, "s09_plan")["plan_ref"]
        plan_doc = self.w.blobs.read_json(plan_ref["uri"], plan_ref["sha256"])
        keys = self.w.extras.get("template_keys", {})
        kinds = {o["overlay_id"]: o["kind"] for o in plan_doc.get("overlays", [])}
        for ov in plan_doc.get("overlays", []):
            ref = ov.get("template_ref") or f"tpl.code_card.{kinds[ov['overlay_id']].lower()}"
            ov["template_ref"] = keys.get(ref)
        plan_view = self._put(call, "shot_plan_resolved.json", plan_doc)
        manifest_ref = ref_ending(upstream(call, "s08_assets"), "sourcing.json")
        manifest = self.w.blobs.read_json(manifest_ref.uri, manifest_ref.sha256)
        self._register_assets(org, manifest)
        voice = upstream(call, "s07_voice")
        tl = next(r for r in voice.output_refs if "timeline" in r.uri)
        master = upstream_data(call, "s07_master")
        refs = {
            "agent_09.shot_plan.output": plan_view,
            "agent_08.asset_sourcing.output": (manifest_ref.uri, manifest_ref.sha256),
            "agent_07.audio_master.output": self._put(call, "audio_master.json", master),
            "agent_07.voice_synthesis.output": (tl.uri, tl.sha256),
            "agent_05.script_document": self._put(call, "script_strings.json", view),
        }
        out = [
            {"uri": u, "purpose": "PRIOR_OUTPUT", "sha256": h, "schema": s}
            for s, (u, h) in refs.items()
        ]
        return out, refs["agent_05.script_document"][1], manifest

    def _register_assets(self, org: str, manifest: dict[str, Any]) -> None:
        ledger: list[dict[str, Any]] = []
        assets: dict[str, dict[str, Any]] = {}
        lic = "PLUMBING_SELF_GRANT"
        for shot in manifest["shots"]:
            if shot.get("asset_id"):
                self.assets.add(
                    org,
                    AssetRecord(
                        asset_id=shot["asset_id"],
                        uri=shot["asset_uri"],
                        sha256=shot["fingerprints"]["sha256"],
                    ),
                )
                assets[shot["asset_id"]] = {"status": "ACTIVE", "ai_item": False}
                ledger.append(
                    {
                        "asset_id": shot["asset_id"],
                        "licence_id": lic,
                        "render_id": None,
                        "used_from_ms": None,
                        "used_to_ms": None,
                        "usage_kind": "SHOT",
                    }
                )
            for still in shot.get("reveal_stills", []):
                self.assets.add(
                    org,
                    AssetRecord(
                        asset_id=still["asset_id"], uri=still["asset_uri"], sha256=still["sha256"]
                    ),
                )
                assets[still["asset_id"]] = {"status": "ACTIVE", "ai_item": False}
                ledger.append(
                    {
                        "asset_id": still["asset_id"],
                        "licence_id": lic,
                        "render_id": None,
                        "used_from_ms": None,
                        "used_to_ms": None,
                        "usage_kind": "IMAGE",
                    }
                )
        for aid, (uri, sha) in self.w.extras.get("templates", {}).items():
            self.assets.add(org, AssetRecord(asset_id=aid, uri=uri, sha256=sha))
        for item in [*manifest.get("overlays", []), *manifest.get("fonts", [])]:
            aid = item.get("template_asset_id") or item.get("asset_id")
            assets[aid] = {"status": "ACTIVE", "ai_item": False}
            ledger.append(
                {
                    "asset_id": aid,
                    "licence_id": lic,
                    "render_id": None,
                    "used_from_ms": None,
                    "used_to_ms": None,
                    "usage_kind": "OVERLAY",
                }
            )
        self.licences.snapshot_value = LicenceSnapshot(
            ledger=ledger,
            licences={
                lic: {
                    "state": "ACTIVE",
                    "covers_monetized_youtube": True,
                    "expires_in_days": None,
                    "third_party_permission": "PERMITTED",
                    "org": org,
                }
            },
            assets=assets,
        )

    # -- stages --------------------------------------------------------------------------------
    def execute(self, call: StageCall) -> TaskOutput:
        kind = call.stage.task_type.split(".", 1)[1]
        refs, script_sha, _manifest = self._refs(call)
        shorts = call.job.production_type_key.value == "SHORTS"
        if kind == "render":
            payload = {
                "render_kind": "MASTER",
                "preset_key": "shorts_9x16" if shorts else "yt_master_1080p",
                "aspect_ratio": "9:16" if shorts else "16:9",
                "language": call.job.language,
                "iteration": call.iteration,
                "verified_script_sha256": script_sha,
                "previous_render_ref": None,
                "music_bed": None,
            }
            ti = task_input(call, "agent_10", "agent_10.render.input", payload, refs)
            return RenderStage(self.deps(call)).run(
                ti, call.attempt_id, envelope_org=call.job.org_id
            )
        rdata = upstream_data(call, "s10_render")
        r_uri, r_sha = self._put(call, "render_output.json", rdata)
        refs = [
            *refs,
            {
                "uri": r_uri,
                "purpose": "PRIOR_OUTPUT",
                "sha256": r_sha,
                "schema": "agent_10.render.output",
            },
            {
                "uri": rdata["timeline_ref"]["uri"],
                "purpose": "PRIOR_OUTPUT",
                "sha256": rdata["timeline_ref"]["sha256"],
                "schema": "agent_10.timeline",
            },
        ]
        if kind == "subtitles":
            payload = {
                "render_id": rdata["render_id"],
                "language": call.job.language,
                "iteration": call.iteration,
                "verified_script_sha256": script_sha,
                "caption_style": None,
            }
            ti = task_input(call, "agent_10", "agent_10.subtitles.input", payload, refs)
            return SubtitleStage(self.deps(call)).run(ti, call.attempt_id)
        sdata = upstream_data(call, "s10_subs")
        s_uri, s_sha = self._put(call, "subs_output.json", sdata)
        refs.append(
            {
                "uri": s_uri,
                "purpose": "PRIOR_OUTPUT",
                "sha256": s_sha,
                "schema": "agent_10.subtitles.output",
            }
        )
        payload = {
            "render_id": rdata["render_id"],
            "render_sha256": rdata["render_ref"]["sha256"],
            "qc_profile": "qc.shorts" if shorts else "qc.long_form",
            "iteration": call.iteration,
            "music_bed": None,
            "destination": "MONETIZED_YOUTUBE",
        }
        ti = task_input(call, "agent_10", "agent_10.technical_qc.input", payload, refs)
        deps = self.deps(call)
        key = "shorts" if shorts else "long"
        if key not in self.selftests:
            self.selftests[key] = _SelfTests(deps.cfg, self.w.scratch / f"selftest_{key}")
        return QcStage(deps, self.selftests[key]).run(ti, call.attempt_id)
