"""agent_07_voice_production: voice synthesis and audio master (blueprint agent_07).

Two task types, no LLM step: ``agent_07.voice_synthesis`` (:class:`VoiceSynthesisStage`) and
``agent_07.audio_master`` (:class:`AudioMasterStage`). The package imports ``amw_core`` and the
TTS adapter Protocol only; concrete adapters, stores and FFmpeg are injected by the worker.
"""

from agent_07_voice_production.master_stage import AudioMasterStage, MasterDeps
from agent_07_voice_production.voice_stage import VoiceDeps, VoiceSynthesisStage

__all__ = ["AudioMasterStage", "MasterDeps", "VoiceDeps", "VoiceSynthesisStage"]
