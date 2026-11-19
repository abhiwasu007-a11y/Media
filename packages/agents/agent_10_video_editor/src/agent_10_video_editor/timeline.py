"""Render timeline ``$T``: compile, hash, reveal steps, text binding, font coverage, upstream gate.

Blueprint 10 section 6.2, F-03, F-07..F-10, F-48. Everything here is pure (no I/O): the golden
dataset drives it directly. Frames are integers; the plan's own milliseconds are kept next to
them because licence matching uses plan milliseconds (18 section 7.9).
"""

import itertools
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt

from agent_10_video_editor.canonical import canonical_json, canonical_sha256, sha256_hex
from agent_10_video_editor.config import AgentTenConfig
from agent_10_video_editor.errors import input_invalid, missing_dependency
from agent_10_video_editor.frames import FrameQuantiser
from agent_10_video_editor.inputs import (
    AssetManifest,
    AssetRecord,
    AudioMaster,
    ManifestShot,
    NarrationTimeline,
    PlanOverlay,
    PlanShot,
    ScriptStrings,
    ShotPlan,
)
from amw_core.font_coverage import uncovered_code_points

END_SCREEN_SHOT_ID = "end_screen"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class Fps(_Model):
    num: StrictInt
    den: StrictInt


IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp"})
"""Extensions rendered as a looped still (no source duration to run out of)."""


class RevealStep(_Model):
    k: StrictInt
    start_frame: StrictInt
    asset_id: str
    asset_sha256: str
    asset_uri: str


class TimelineShot(_Model):
    shot_id: str
    start_frame: StrictInt
    end_frame: StrictInt
    plan_start_ms: StrictInt
    plan_end_ms: StrictInt
    asset_id: str
    asset_sha256: str
    asset_uri: str
    source_in_ms: StrictInt
    crop: dict[str, Any]
    motion: str
    transition_in: dict[str, Any]
    tier: str | None
    change_events_ms: tuple[StrictInt, ...]
    reveal_steps: tuple[RevealStep, ...]
    intent_kind: str

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame


class TimelineOverlay(_Model):
    overlay_id: str
    kind: str
    start_frame: StrictInt
    end_frame: StrictInt
    plan_start_ms: StrictInt
    plan_end_ms: StrictInt
    template_asset_id: str
    template_sha256: str
    template_uri: str
    text_sha256s: tuple[str, ...]


class AudioInfo(_Model):
    master_sha256: str
    duration_ms: StrictInt
    codec_profile_sha256: str


class Timeline(_Model):
    fps: Fps
    total_frames: StrictInt
    shots: tuple[TimelineShot, ...]
    overlays: tuple[TimelineOverlay, ...]
    end_screen: TimelineShot | None
    audio: AudioInfo
    preset_key: str
    render_kind: str
    colour: dict[str, str]

    def canonical(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def shots_frames(self) -> list[dict[str, Any]]:
        return [
            {
                "shot_id": s.shot_id,
                "start_frame": s.start_frame,
                "end_frame": s.end_frame,
                "frames": s.frames,
            }
            for s in self.shots
        ]

    @property
    def expected_render_duration_ms(self) -> int:
        return FrameQuantiser.frames_to_ms(self.total_frames, self.fps.num, self.fps.den)

    def visual_parts(self) -> tuple[TimelineShot, ...]:
        """V1 in order, end-screen span last (it is part of the visual track)."""
        return (*self.shots, *((self.end_screen,) if self.end_screen else ()))


class TimelineHasher:
    @staticmethod
    def canonical_json(timeline: Mapping[str, Any]) -> bytes:
        return canonical_json(dict(timeline))

    @staticmethod
    def sha256(timeline: Mapping[str, Any]) -> str:
        return canonical_sha256(dict(timeline))

    @staticmethod
    def timeline_sha256(timeline: Timeline) -> str:
        return canonical_sha256(timeline.canonical())


# ----------------------------------------------------------------------------- reveal steps


class RevealStepBuilder:
    """F-48: ``len(change_events_ms) + 1`` stills give step k at frame(change_events_ms[k-1])."""

    @staticmethod
    def build[T](
        shot: Mapping[str, Any],
        change_events_ms: Sequence[int],
        stills: Sequence[T],
        fps_num: int,
        fps_den: int,
    ) -> list[tuple[int, int, T]]:
        """Return ``(k, start_frame, still)`` triples."""
        shot_id = str(shot["shot_id"])
        if len(stills) != len(change_events_ms) + 1:
            raise input_invalid(f"REVEAL_COUNT:{shot_id}")
        starts = [int(shot["start_frame"])] + [
            FrameQuantiser.to_frame(ms, fps_num, fps_den) for ms in change_events_ms
        ]
        end_frame = int(shot["end_frame"])
        previous = -1
        for start in starts:
            if start <= previous or start >= end_frame:
                raise input_invalid(f"ZERO_FRAME_REVEAL:{shot_id}")
            previous = start
        return [
            (k, start, still) for k, (start, still) in enumerate(zip(starts, stills, strict=True))
        ]


# ----------------------------------------------------------------------------- upstream gate


class UpstreamGate:
    """F-03: deterministic gate before any media work (a10.q.upstream)."""

    @staticmethod
    def check_render(
        *,
        timing_basis: str,
        shot_ids: Sequence[str],
        manifest_entries: Sequence[Mapping[str, Any]],
        audio_gate_verdict: str,
        audio_sample_rate_hz: int,
        audio_channels: int,
        audio_duration_ms: int,
        narration_end_ms: int,
        script_sha_equal: bool,
        aspect_ratio: str,
        unresolved_shot_ids: Sequence[str] = (),
    ) -> None:
        invalid: list[str] = []
        missing: list[str] = []
        if timing_basis != "MEASURED":
            invalid.append("PLAN_NOT_MEASURED")
        if not script_sha_equal:
            invalid.append("SCRIPT_HASH_MISMATCH")
        usable = {
            str(e["shot_id"])
            for e in manifest_entries
            if e.get("aspect_ratio") == aspect_ratio and e.get("status") in ("SOURCED", "REUSED")
        }
        missing.extend(f"NO_ASSET:{sid}" for sid in shot_ids if sid not in usable)
        missing.extend(f"NO_ASSET:{sid}" for sid in unresolved_shot_ids if sid in shot_ids)
        if audio_gate_verdict != "PASSED":
            missing.append("AUDIO_MASTER_NOT_PASSED")
        if (
            audio_sample_rate_hz != 48000
            or audio_channels != 2
            or audio_duration_ms < narration_end_ms
        ):
            invalid.append("AUDIO_COVERAGE")
        if invalid:
            raise input_invalid(*invalid)
        if missing:
            raise missing_dependency(*dict.fromkeys(missing))

    @staticmethod
    def check_models(
        *,
        plan: ShotPlan,
        manifest: AssetManifest,
        audio: AudioMaster,
        narration: NarrationTimeline,
        script_sha256: str,
        verified_script_sha256: str,
        aspect_ratio: str,
    ) -> None:
        narration_end = narration.end_ms
        if narration_end is None:
            narration_end = max((s.end_ms for s in narration.segments), default=0)
        UpstreamGate.check_render(
            timing_basis=plan.timing_basis,
            shot_ids=[s.shot_id for s in plan.shots],
            manifest_entries=[m.model_dump() for m in manifest.shots],
            audio_gate_verdict=audio.gate_verdict,
            audio_sample_rate_hz=audio.master.sample_rate_hz,
            audio_channels=audio.master.channels,
            audio_duration_ms=audio.master.duration_ms,
            narration_end_ms=narration_end,
            script_sha_equal=script_sha256 == verified_script_sha256,
            aspect_ratio=aspect_ratio,
            unresolved_shot_ids=manifest.unresolved_shot_ids,
        )


# ----------------------------------------------------------------------------- compiler


class TimelineCompiler:
    """F-07: quantise boundaries (not durations), select manifest entries, bind assets."""

    @staticmethod
    def _check_tiling(plan: ShotPlan) -> None:
        shots = plan.shots
        violations: list[str] = []
        if not shots:
            raise input_invalid("NO_SHOTS")
        if shots[0].start_ms != 0:
            violations.append(f"TILING_GAP:START>{shots[0].shot_id}")
        for a, b in itertools.pairwise(shots):
            if b.start_ms > a.end_ms:
                violations.append(f"TILING_GAP:{a.shot_id}>{b.shot_id}")
            elif b.start_ms < a.end_ms:
                violations.append(f"TILING_OVERLAP:{a.shot_id}>{b.shot_id}")
        last = shots[-1]
        if last.end_ms not in (plan.content_end_ms, plan.total_duration_ms):
            kind = "TILING_GAP" if last.end_ms < plan.content_end_ms else "TILING_OVERLAP"
            violations.append(f"{kind}:{last.shot_id}>END")
        if violations:
            raise input_invalid(*violations)

    @staticmethod
    def _select(manifest: AssetManifest, shot_id: str, aspect_ratio: str) -> ManifestShot | None:
        for entry in manifest.shots:
            if entry.shot_id == shot_id and entry.aspect_ratio == aspect_ratio:
                return entry
        return None

    @staticmethod
    def compile(
        plan: ShotPlan,
        manifest: AssetManifest,
        assets: Mapping[str, AssetRecord],
        audio: AudioMaster,
        cfg: AgentTenConfig,
        aspect_ratio: str,
        render_kind: str = "MASTER",
    ) -> Timeline:
        fps_num, fps_den = cfg.render.fps_num, cfg.render.fps_den
        TimelineCompiler._check_tiling(plan)

        def fr(ms: int) -> int:
            return FrameQuantiser.to_frame(ms, fps_num, fps_den)

        invalid: list[str] = []
        missing: list[str] = []
        shots: list[TimelineShot] = []
        for ps in plan.shots:
            start_f, end_f = fr(ps.start_ms), fr(ps.end_ms)
            if end_f <= start_f:
                invalid.append(f"ZERO_FRAME_SHOT:{ps.shot_id}")
                continue
            entry = TimelineCompiler._select(manifest, ps.shot_id, aspect_ratio)
            if entry is None or entry.status == "UNRESOLVED" or not entry.asset_uri:
                missing.append(f"NO_ASSET:{ps.shot_id}")
                continue
            asset_id = entry.asset_id or ""
            record = assets.get(asset_id)
            sha = (
                entry.fingerprints.sha256
                if entry.fingerprints
                else (record.sha256 if record else None)
            )
            if not asset_id or sha is None:
                missing.append(f"NO_ASSET:{ps.shot_id}")
                continue
            media = entry.media
            crop = (
                media.crop.model_dump()
                if media
                else {"mode": "NONE", "anchor": None, "keep_permille": 1000}
            )
            steps: tuple[RevealStep, ...] = ()
            if ps.intent_kind == "CHART" or entry.reveal_stills:
                try:
                    steps = TimelineCompiler._reveal(
                        ps, entry, start_f, end_f, fps_num, fps_den, missing
                    )
                except Exception as exc:
                    invalid.extend(
                        getattr(exc, "details", {}).get("violations", ["REVEAL_INVALID"])
                    )
                    continue
            if not steps and media is not None and media.duration_ms is not None:
                ext = entry.asset_uri.rsplit(".", 1)[-1].lower()
                needs_ms = media.source_in_ms + FrameQuantiser.frames_to_ms(
                    end_f - start_f, fps_num, fps_den
                )
                one_frame_ms = FrameQuantiser.frames_to_ms(1, fps_num, fps_den)
                if ext not in IMAGE_EXTENSIONS and needs_ms - media.duration_ms > one_frame_ms:
                    # tpad=clone would silently freeze the tail: refuse instead (SOURCE_TOO_SHORT)
                    invalid.append(f"SOURCE_TOO_SHORT:{ps.shot_id}")
                    continue
            shots.append(
                TimelineShot(
                    shot_id=ps.shot_id,
                    start_frame=start_f,
                    end_frame=end_f,
                    plan_start_ms=ps.start_ms,
                    plan_end_ms=ps.end_ms,
                    asset_id=asset_id,
                    asset_sha256=sha,
                    asset_uri=entry.asset_uri,
                    source_in_ms=media.source_in_ms if media else 0,
                    crop=crop,
                    motion=ps.motion,
                    transition_in=ps.transition_in.model_dump(),
                    tier=entry.tier,
                    change_events_ms=tuple(ps.change_events_ms),
                    reveal_steps=steps,
                    intent_kind=ps.intent_kind,
                )
            )
        if invalid:
            raise input_invalid(*dict.fromkeys(invalid))
        if missing:
            raise missing_dependency(*dict.fromkeys(missing))

        total_frames = fr(plan.total_duration_ms)
        overlays, end_screen = TimelineCompiler._overlays(
            plan, manifest, assets, fr, shots, total_frames
        )
        if shots[-1].end_frame != (end_screen.start_frame if end_screen else total_frames):
            raise input_invalid(f"TILING_GAP:{shots[-1].shot_id}>END")
        profile_sha = canonical_sha256(audio.codec_profile.model_dump())
        return Timeline(
            fps=Fps(num=fps_num, den=fps_den),
            total_frames=total_frames,
            shots=tuple(shots),
            overlays=tuple(overlays),
            end_screen=end_screen,
            audio=AudioInfo(
                master_sha256=audio.master.sha256,
                duration_ms=audio.master.duration_ms,
                codec_profile_sha256=profile_sha,
            ),
            preset_key=cfg.render.preset_key,
            render_kind=render_kind,
            colour=cfg.render.colour.model_dump(),
        )

    @staticmethod
    def _reveal(
        ps: PlanShot,
        entry: ManifestShot,
        start_f: int,
        end_f: int,
        fps_num: int,
        fps_den: int,
        missing: list[str],
    ) -> tuple[RevealStep, ...]:
        stills = sorted(entry.reveal_stills, key=lambda s: s.k)
        triples = RevealStepBuilder.build(
            {"shot_id": ps.shot_id, "start_frame": start_f, "end_frame": end_f},
            ps.change_events_ms,
            stills,
            fps_num,
            fps_den,
        )
        expected_starts = [ps.start_ms, *ps.change_events_ms]
        out: list[RevealStep] = []
        for k, start, still in triples:
            if still.k != k or still.start_ms != expected_starts[k]:
                raise input_invalid(f"REVEAL_COUNT:{ps.shot_id}")
            if not still.licence_id or not still.ledger_entry_ids:
                missing.append(f"NO_ASSET:{ps.shot_id}#{k}")
            out.append(
                RevealStep(
                    k=k,
                    start_frame=start,
                    asset_id=still.asset_id,
                    asset_sha256=still.sha256,
                    asset_uri=still.asset_uri,
                )
            )
        return tuple(out)

    @staticmethod
    def _overlays(
        plan: ShotPlan,
        manifest: AssetManifest,
        assets: Mapping[str, AssetRecord],
        fr: Any,
        shots: list[TimelineShot],
        total_frames: int,
    ) -> tuple[list[TimelineOverlay], TimelineShot | None]:
        by_id = {o.overlay_id: o for o in manifest.overlays}
        out: list[TimelineOverlay] = []
        end_screen: TimelineShot | None = None
        v1_end_ms = plan.shots[-1].end_ms
        for po in plan.overlays:
            mo = by_id.get(po.overlay_id)
            record = assets.get(mo.template_asset_id) if mo else None
            if mo is None or record is None:
                raise missing_dependency(f"NO_ASSET:{po.overlay_id}")
            if po.template_ref is not None and po.template_ref != record.uri:
                raise input_invalid(f"TEMPLATE_MISMATCH:{po.overlay_id}")
            start_f, end_f = fr(po.start_ms), fr(po.end_ms)
            if end_f <= start_f:
                raise input_invalid(f"ZERO_FRAME_OVERLAY:{po.overlay_id}")
            overlay = TimelineOverlay(
                overlay_id=po.overlay_id,
                kind=po.kind,
                start_frame=start_f,
                end_frame=min(end_f, total_frames),
                plan_start_ms=po.start_ms,
                plan_end_ms=po.end_ms,
                template_asset_id=record.asset_id,
                template_sha256=record.sha256,
                template_uri=record.uri,
                text_sha256s=tuple(t.sha256 for t in po.text_refs),
            )
            out.append(overlay)
            if (
                po.kind == "END_SCREEN"
                and v1_end_ms < plan.total_duration_ms
                and po.start_ms == v1_end_ms
            ):
                end_screen = TimelineShot(
                    shot_id=END_SCREEN_SHOT_ID,
                    start_frame=overlay.start_frame,
                    end_frame=total_frames,
                    plan_start_ms=po.start_ms,
                    plan_end_ms=plan.total_duration_ms,
                    asset_id=record.asset_id,
                    asset_sha256=record.sha256,
                    asset_uri=record.uri,
                    source_in_ms=0,
                    crop={"mode": "NONE", "anchor": None, "keep_permille": 1000},
                    motion="STATIC",
                    transition_in={"kind": "CUT", "duration_ms": 0},
                    tier="C_CODE_MOTION",
                    change_events_ms=(),
                    reveal_steps=(),
                    intent_kind="TEXT_CARD",
                )
        if v1_end_ms < plan.total_duration_ms and end_screen is None:
            raise input_invalid(f"TILING_GAP:{shots[-1].shot_id}>END")
        return out, end_screen


# ----------------------------------------------------------------------------- text and fonts


class TextBinder:
    """F-09: every on-screen text is a script string bound by SHA-256; no free text."""

    @staticmethod
    def bind(
        overlays: Sequence[PlanOverlay | TimelineOverlay], script: ScriptStrings
    ) -> dict[str, str]:
        bound: dict[str, str] = {}
        for overlay in overlays:
            hashes = (
                overlay.text_sha256s
                if isinstance(overlay, TimelineOverlay)
                else tuple(t.sha256 for t in overlay.text_refs)
            )
            for sha in hashes:
                text = script.on_screen.get(sha)
                if text is None:
                    raise input_invalid(f"TEXT_REF_MISSING:{overlay.overlay_id}")
                if sha256_hex(text.encode()) != sha:
                    raise input_invalid(f"TEXT_HASH_MISMATCH:{overlay.overlay_id}")
                bound[sha] = text
        return bound


class FontCoverage:
    """F-10: every code point of every bound text must be in the brand font's cmap."""

    @staticmethod
    def check(font_code_points: set[int] | frozenset[int], texts: Sequence[str]) -> None:
        missing = sorted(uncovered_code_points(texts, [frozenset(font_code_points)]))
        if missing:
            raise input_invalid(*(f"GLYPH_MISSING:U+{cp:04X}" for cp in missing))
