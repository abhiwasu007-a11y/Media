"""Policy values the builders put into payloads. They are configuration of the orchestrator, never
literals inside a builder; the defaults are the 3A values named by the cited documents, and a
deployment overrides them through ``BuilderSettings``."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BuilderSettings:
    licence_destination: str = "MONETIZED_YOUTUBE"
    """agent_08 / agent_10 ``destination``: the stricter of the two values until the job carries
    its monetisation fact (CCR-278 provisional default)."""
    ai_video_allowed: bool = False
    stills_allowed: bool = False
    """agent_08 7.1: no AI media in 3A (3A_SLICE_SPEC; agent_09 ``limits`` default)."""
    render_preset_long: str = "yt_master_1080p"
    render_preset_shorts: str = "shorts_9x16"
    """agent_10 7.1 ``preset_key`` enum; ``agent_10.render.preset_key`` is the config family."""
    thumbnail_variants_long: int = 3
    thumbnail_variants_shorts: int = 1
    """agent_11 FR-13 / 7.2 (maximum 3) and agent_11 section 1 (Shorts: one)."""
    rubric_version: str = "rubric.v1"
    """agent_16 7.4 / 18 section 9.2."""
    uniqueness_prior_jobs: int = 0
    """agent_16 7.3 ``prior_window.max_prior_jobs``: used in 3C; the cross-video comparator is
    not built in 3A."""
    destination_kinds: tuple[str, ...] = ("FILE_DELIVERY",)
    evaluate_as_destination: str = "YOUTUBE"
    requested_action: str = "DELIVERY"
    """agent_16 7.2 / 7.5 guard G0: 3A has one destination and one action (24 7.1a)."""
