"""Admission rule of ``s07_master`` (24.1, ADR-012 section 3.3): a HEAVY_CPU render task is never
claimed in market hours or after the drain flag; ``s07_voice`` (light) is still admitted."""

from dataclasses import dataclass

TASK_VOICE = "agent_07.voice_synthesis"
TASK_MASTER = "agent_07.audio_master"


@dataclass(frozen=True, slots=True)
class AdmissionState:
    market_hours: bool
    drain_flag: bool


def is_admitted(task_type: str, state: AdmissionState) -> bool:
    if state.drain_flag:
        return False
    if task_type == TASK_MASTER and state.market_hours:
        return False
    return task_type in (TASK_VOICE, TASK_MASTER)
