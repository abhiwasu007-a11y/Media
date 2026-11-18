"""``AiBudgetGate`` (D13, blueprint 6.7): local per-video caps, then the S4 reservation outcome.

Caps have no default: ``0`` or unset disables tier D. A local cap reached skips the tier
(``BUDGET``) and the cascade continues; a refusal by S4 is different: the task suspends
``AWAITING_BUDGET`` and nothing is generated past a refused reservation (BG-06).
"""

from dataclasses import dataclass
from enum import StrEnum

from amw_core.enums import WaitReason
from amw_core.errors import BudgetExhaustedError


class GateAction(StrEnum):
    ALLOW = "ALLOW"
    SKIP_TIER = "SKIP_TIER"
    SUSPEND = "SUSPEND"


@dataclass(frozen=True, slots=True)
class AiGateDecision:
    action: GateAction
    reason: str | None = None
    error_code: str | None = None
    wait_reason: WaitReason | None = None


class AiBudgetGate:
    @staticmethod
    def decide(
        *,
        clips_used: int,
        max_clips: int,
        shot_ms: int,
        max_clip_ms: int,
        remaining_ms: int,
        remaining_micros: int,
        est_clip_micros: int,
        s4_reservation_ok: bool,
    ) -> AiGateDecision:
        if clips_used >= max_clips:
            return AiGateDecision(GateAction.SKIP_TIER, "BUDGET")
        if shot_ms > max_clip_ms:
            return AiGateDecision(GateAction.SKIP_TIER, "CLIP_TOO_LONG")
        if remaining_ms < shot_ms or remaining_micros < est_clip_micros:
            return AiGateDecision(GateAction.SKIP_TIER, "BUDGET")
        if not s4_reservation_ok:
            return AiGateDecision(
                GateAction.SUSPEND,
                None,
                BudgetExhaustedError.code,
                WaitReason.AWAITING_BUDGET,
            )
        return AiGateDecision(GateAction.ALLOW)
