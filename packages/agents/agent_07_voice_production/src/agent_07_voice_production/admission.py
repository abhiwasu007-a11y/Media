"""Admission rule of ``s07_master`` (24.1, ADR-012 section 3.3, IT-05): a HEAVY_CPU render task is
never claimed in market hours or after the drain flag; ``s07_voice`` (light, ``AI_IO``) is
admitted in both cases (a running voice task checkpoints at drain by itself, FR-20)."""

from dataclasses import dataclass

TASK_VOICE = "agent_07.voice_synthesis"
TASK_MASTER = "agent_07.audio_master"


@dataclass(frozen=True, slots=True)
class AdmissionState:
    market_hours: bool
    drain_flag: bool


def is_admitted(task_type: str, state: AdmissionState) -> bool:
    if task_type == TASK_MASTER:
        return not (state.market_hours or state.drain_flag)
    return task_type == TASK_VOICE
