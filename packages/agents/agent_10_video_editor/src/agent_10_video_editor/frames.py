"""Frame grid arithmetic (blueprint 10 section 6.2 items 1-3; F-05, F-06).

Integers only: ``frame(t_ms) = (t_ms * fps_num + 500 * fps_den) // (1000 * fps_den)``
(round half up).
"""

from agent_10_video_editor.errors import input_invalid


class FrameQuantiser:
    @staticmethod
    def _check_fps(fps_num: int, fps_den: int) -> None:
        if fps_num <= 0 or fps_den <= 0:
            raise input_invalid("FPS_NOT_POSITIVE")

    @staticmethod
    def to_frame(t_ms: int, fps_num: int, fps_den: int) -> int:
        FrameQuantiser._check_fps(fps_num, fps_den)
        if t_ms < 0:
            raise input_invalid("NEGATIVE_TIME")
        return (t_ms * fps_num + 500 * fps_den) // (1000 * fps_den)

    @staticmethod
    def frames_to_ms(frames: int, fps_num: int, fps_den: int) -> int:
        """``round_half_up(frames * 1000 * fps_den / fps_num)``."""
        FrameQuantiser._check_fps(fps_num, fps_den)
        if frames < 0:
            raise input_invalid("NEGATIVE_FRAMES")
        return (2 * frames * 1000 * fps_den + fps_num) // (2 * fps_num)


def ms_to_seconds_text(ms: int) -> str:
    """Integer milliseconds as decimal seconds text (no float arithmetic)."""
    return f"{ms // 1000}.{ms % 1000:03d}"
