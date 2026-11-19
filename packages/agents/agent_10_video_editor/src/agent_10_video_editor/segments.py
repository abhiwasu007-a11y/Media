"""Segments, content-addressed keys and resume (blueprint 10 section 6.3; F-11..F-13).

A segment closes at the first shot end where its accumulated frames reach ``target_frames``;
shots are never split, so every segment starts on a shot boundary (GOP-safe: the encoder forces an
IDR frame and a closed GOP at each segment start). The segment key is the SHA-256 of the canonical
JSON of ``{slice_sha256, asset_sha256s, args_sha256, ffmpeg_build_id}``; the same key means the
same bytes, so a finished segment is reused after a kill, a drain, a DLQ replay and across
revision iterations.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt

from agent_10_video_editor.canonical import canonical_sha256
from agent_10_video_editor.errors import config_invalid
from agent_10_video_editor.timeline import Timeline, TimelineOverlay, TimelineShot


@dataclass(frozen=True, slots=True)
class ShotFrames:
    shot_id: str
    start_frame: int
    end_frame: int


@dataclass(frozen=True, slots=True)
class Segment:
    ordinal: int
    start_frame: int
    end_frame: int
    shot_ids: tuple[str, ...]

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame


def target_frames_of(segment_target_ms: int, fps_num: int, fps_den: int) -> int:
    """``ceil(segment_target_ms * fps_num / (1000 * fps_den))``."""
    return math.ceil(segment_target_ms * fps_num / (1000 * fps_den))


class SegmentPlanner:
    @staticmethod
    def plan(shots: Sequence[ShotFrames], target_frames: int) -> list[Segment]:
        if target_frames <= 0:
            raise config_invalid("SEGMENT_TARGET_NOT_POSITIVE")
        segments: list[Segment] = []
        current: list[ShotFrames] = []
        for shot in shots:
            current.append(shot)
            if current[-1].end_frame - current[0].start_frame >= target_frames:
                segments.append(_close(len(segments), current))
                current = []
        if current:
            segments.append(_close(len(segments), current))
        return segments


def _close(ordinal: int, shots: Sequence[ShotFrames]) -> Segment:
    return Segment(
        ordinal=ordinal,
        start_frame=shots[0].start_frame,
        end_frame=shots[-1].end_frame,
        shot_ids=tuple(s.shot_id for s in shots),
    )


class SegmentKey:
    @staticmethod
    def compute(
        slice_sha256: str, asset_sha256s: Sequence[str], args_sha256: str, ffmpeg_build_id: str
    ) -> str:
        return canonical_sha256(
            {
                "slice_sha256": slice_sha256,
                "asset_sha256s": list(asset_sha256s),
                "args_sha256": args_sha256,
                "ffmpeg_build_id": ffmpeg_build_id,
            }
        )


def plan_segments(timeline: Timeline, target_frames: int) -> list[Segment]:
    return SegmentPlanner.plan(
        [ShotFrames(s.shot_id, s.start_frame, s.end_frame) for s in timeline.visual_parts()],
        target_frames,
    )


@dataclass(frozen=True, slots=True)
class SegmentSlice:
    """What one segment encodes: its visual parts and the overlays that intersect it."""

    segment: Segment
    parts: tuple[TimelineShot, ...]
    overlays: tuple[TimelineOverlay, ...]

    def canonical(self) -> dict[str, Any]:
        return {
            "start_frame": self.segment.start_frame,
            "end_frame": self.segment.end_frame,
            "parts": [p.model_dump(mode="json") for p in self.parts],
            "overlays": [o.model_dump(mode="json") for o in self.overlays],
        }

    @property
    def slice_sha256(self) -> str:
        return canonical_sha256(self.canonical())

    def asset_sha256s(self) -> list[str]:
        """Every input asset hash in staging order (shots or reveal steps, then overlays)."""
        out: list[str] = []
        for part in self.parts:
            if part.reveal_steps:
                out.extend(step.asset_sha256 for step in part.reveal_steps)
            else:
                out.append(part.asset_sha256)
        out.extend(o.template_sha256 for o in self.overlays)
        return out


def slice_for(timeline: Timeline, segment: Segment) -> SegmentSlice:
    parts = tuple(
        p
        for p in timeline.visual_parts()
        if p.start_frame >= segment.start_frame and p.end_frame <= segment.end_frame
    )
    overlays = tuple(
        o
        for o in timeline.overlays
        if not (
            timeline.end_screen is not None
            and o.kind == "END_SCREEN"
            and o.start_frame == timeline.end_screen.start_frame
        )
        and o.start_frame < segment.end_frame
        and o.end_frame > segment.start_frame
    )
    return SegmentSlice(segment=segment, parts=parts, overlays=overlays)


# ----------------------------------------------------------------------------- checkpoint state


class SegmentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    ordinal: StrictInt
    key: str
    uri: str
    sha256: str
    size_bytes: StrictInt
    frames: StrictInt
    ssim_all: str | None = None
    ssim_frames: StrictInt = 0
    """Frame pairs the SSIM covers (checked equal to the sampled frame count)."""
    """SSIM ``All`` of this segment against its lossless reference (ADR-014); ``None`` for a
    segment adopted from storage without a checkpoint (not measured)."""


class RenderState(BaseModel):
    """The checkpoint state blob (section 16): IDs, keys, hashes and URIs only."""

    model_config = ConfigDict(frozen=True)

    render_id: str
    final_uri: str
    timeline_sha256: str | None = None
    timeline_uri: str | None = None
    segments: dict[int, SegmentRecord] = {}
    market_hours_checks: StrictInt = 0
    night_window_checks: StrictInt = 0
    registered: bool = False
    gop: dict[str, int | bool] = {}
    args_sha256: str | None = None

    def with_segment(self, record: SegmentRecord) -> RenderState:
        return self.model_copy(update={"segments": {**self.segments, record.ordinal: record}})


@dataclass(frozen=True, slots=True)
class BlobFacts:
    exists: bool
    sha256: str | None
    size_bytes: int | None


@dataclass(frozen=True, slots=True)
class ResumePlan:
    reusable: tuple[SegmentRecord, ...]
    to_encode: tuple[int, ...]
    adopted: tuple[SegmentRecord, ...]
    """Orphans (renamed but not checkpointed) that were verified and must be checkpointed."""


class ResumeVerifier:
    """F-13 / section 6.3.3: the first unverified segment ends the skip run."""

    @staticmethod
    def verify(
        segments: Sequence[tuple[Segment, str, str]],
        state: RenderState | None,
        head: Callable[[str], BlobFacts],
        probe_frames: Callable[[str], int | None],
    ) -> ResumePlan:
        """``segments`` are ``(segment, key, uri)``; ``probe_frames(uri)`` returns the frame count
        of the stored blob, or ``None`` when the blob cannot be probed (it is then re-encoded)."""
        reusable: list[SegmentRecord] = []
        adopted: list[SegmentRecord] = []
        to_encode: list[int] = []
        broken = False
        for segment, key, uri in segments:
            if broken:
                to_encode.append(segment.ordinal)
                continue
            facts = head(uri)
            recorded = state.segments.get(segment.ordinal) if state else None
            if (
                facts.exists
                and recorded is not None
                and recorded.key == key
                and facts.sha256 == recorded.sha256
                and facts.size_bytes == recorded.size_bytes
            ):
                reusable.append(recorded)
            elif facts.exists and recorded is None and facts.sha256 and facts.size_bytes:
                frames = probe_frames(uri)
                if frames == segment.frames:
                    record = SegmentRecord(
                        ordinal=segment.ordinal,
                        key=key,
                        uri=uri,
                        sha256=facts.sha256,
                        size_bytes=facts.size_bytes,
                        frames=frames,
                    )
                    reusable.append(record)
                    adopted.append(record)
                else:
                    broken = True
                    to_encode.append(segment.ordinal)
            else:
                broken = True
                to_encode.append(segment.ordinal)
        return ResumePlan(tuple(reusable), tuple(to_encode), tuple(adopted))


def segments_index(records: Mapping[int, SegmentRecord]) -> list[SegmentRecord]:
    return [records[k] for k in sorted(records)]
