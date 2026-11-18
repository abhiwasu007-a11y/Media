"""TierPlanner (F-18; blueprint 6.6): allowed tiers in hierarchy order, always with tier C."""

from collections.abc import Sequence
from dataclasses import dataclass

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import IntentKind, Limits, Tier
from agent_09_video_director.mathx import round_half_up


@dataclass(frozen=True, slots=True)
class TierShot:
    shot_id: str
    duration_ms: int
    intent_kind: IntentKind = IntentKind.FOOTAGE
    still_ok: bool = False
    needs_ai_video: bool = False


@dataclass(frozen=True, slots=True)
class TierPlan:
    allowed: dict[str, tuple[Tier, ...]]
    e_allowed_shot_ids: tuple[str, ...]
    worst_case_e_share_permille: int
    e_limit_permille: int
    ai_video_allowed_ms: int
    ai_video_limit_ms: int


def plan_tiers(
    shots: Sequence[TierShot], total_ms: int, limits: Limits, cfg: Agent09Config
) -> TierPlan:
    """E is granted in time order while the running worst-case share stays at or below
    ``tier_e_max_share x e_plan_fraction`` (unset fraction: no E); D only when enabled and
    inside the AI-video budget."""
    e_limit_permille = (
        cfg.tier_e_max_share_permille * cfg.tier_e_plan_permille // 1000
        if cfg.tier_e_plan_permille is not None
        else 0
    )
    d_limit = limits.ai_video_allowed_ms
    if cfg.tier_d_max_ms is not None:
        d_limit = min(d_limit, cfg.tier_d_max_ms)
    d_limit = d_limit if cfg.tier_d_enabled else 0
    e_ms = d_ms = 0
    allowed: dict[str, tuple[Tier, ...]] = {}
    e_ids: list[str] = []
    for shot in shots:
        if shot.intent_kind is not IntentKind.FOOTAGE:
            allowed[shot.shot_id] = (Tier.C,)
            continue
        tiers = [Tier.A, Tier.B, Tier.C]
        if shot.needs_ai_video and d_ms + shot.duration_ms <= d_limit:
            tiers.append(Tier.D)
            d_ms += shot.duration_ms
        if (
            shot.still_ok
            and limits.ai_still_allowed
            and e_limit_permille > 0
            and (e_ms + shot.duration_ms) * 1000 <= e_limit_permille * total_ms
        ):
            tiers.append(Tier.E)
            e_ms += shot.duration_ms
            e_ids.append(shot.shot_id)
        allowed[shot.shot_id] = tuple(tiers)
    share = round_half_up(e_ms * 1000, total_ms) if total_ms else 0
    return TierPlan(allowed, tuple(e_ids), share, e_limit_permille, d_ms, d_limit)
