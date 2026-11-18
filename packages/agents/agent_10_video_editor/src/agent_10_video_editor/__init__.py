"""Agent 10 Video Editor (docs/v4/agents/agent_10_video_editor.md).

Library code run by ``workers/render_worker``: three typed stages, one per task type
(``agent_10.render``, ``agent_10.subtitles``, ``agent_10.technical_qc``). No LLM, no network, no
provider call; FFmpeg and ffprobe are local tools behind the ``FfmpegRunner`` Protocol.
"""

from agent_10_video_editor.qc.stage import QcStage
from agent_10_video_editor.render import RenderStage
from agent_10_video_editor.subtitle_stage import SubtitleStage

__all__ = ["QcStage", "RenderStage", "SubtitleStage"]
