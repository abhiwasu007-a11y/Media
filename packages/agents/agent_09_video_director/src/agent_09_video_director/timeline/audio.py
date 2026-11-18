"""AudioCuePlanner (F-22; FR-13): licensed beds and cues only, none in 3A."""

from collections.abc import Sequence

from agent_09_video_director.contracts import (
    AudioPlan,
    DeliberatePause,
    Device,
    InterruptSummary,
    Limits,
    MusicPlan,
)


def plan_audio(
    total_duration_ms: int,
    interrupts: Sequence[InterruptSummary],
    limits: Limits,
    pauses: Sequence[DeliberatePause] = (),
) -> AudioPlan:
    """3A: bed NONE and no SFX. A bed is requested only with ``music_library_enabled``
    (owner's licensed-source decision D6); one SFX cue per ``SOUND_CUE`` interrupt only with
    ``sfx_library_enabled``. The ducking range is the 18 section 5 range."""
    if limits.music_library_enabled:
        music = MusicPlan(bed="REQUESTED", start_ms=0, end_ms=total_duration_ms)
    else:
        music = MusicPlan(bed="NONE", start_ms=None, end_ms=None)
    cues: tuple[dict[str, str], ...] = ()
    if limits.sfx_library_enabled:
        cues = tuple(
            {"shot_id": i.shot_id, "cue": "INTERRUPT"}
            for i in interrupts
            if i.device is Device.SOUND_CUE
        )
    return AudioPlan(music=music, sfx_cues=cues, deliberate_pauses=tuple(pauses))
