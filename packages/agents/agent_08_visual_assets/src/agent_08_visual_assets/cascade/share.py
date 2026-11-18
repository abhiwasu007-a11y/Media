"""``TierShareGuard`` (D13) and ``TierMixReporter``: the strict tier-E limit (18 section 2.3)."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from amw_core.enums import VisualSourceTier
from amw_core.errors import InputInvalidError


@dataclass(frozen=True, slots=True)
class ShareDecision:
    allowed: bool
    e_share_permille: int


class TierShareGuard:
    @staticmethod
    def allows(
        *, e_ms_planned: int, new_e_ms: int, total_visual_ms: int, limit: Decimal
    ) -> ShareDecision:
        """``(planned + new) < limit * total``: exactly the limit is not allowed (TS-03)."""
        if total_visual_ms <= 0:
            raise InputInvalidError("total visual time must be positive")
        e_total = e_ms_planned + new_e_ms
        return ShareDecision(
            allowed=Decimal(e_total) < limit * Decimal(total_visual_ms),
            e_share_permille=e_total * 1000 // total_visual_ms,
        )


@dataclass(frozen=True, slots=True)
class TierShare:
    ms: int
    share_permille: int


class TierMixReporter:
    @staticmethod
    def report(ms_by_tier: Mapping[VisualSourceTier, int]) -> tuple[int, dict[str, TierShare]]:
        """Shares in permille that sum to exactly 1000 (largest remainder), zero total rejected."""
        total = sum(ms_by_tier.get(t, 0) for t in VisualSourceTier)
        if total <= 0:
            raise InputInvalidError("total visual time must be positive")
        tiers = list(VisualSourceTier)
        floors = {t: ms_by_tier.get(t, 0) * 1000 // total for t in tiers}
        remainders = sorted(
            tiers,
            key=lambda t: (-(ms_by_tier.get(t, 0) * 1000 % total), tiers.index(t)),
        )
        for t in remainders[: 1000 - sum(floors.values())]:
            floors[t] += 1
        return total, {t.value: TierShare(ms_by_tier.get(t, 0), floors[t]) for t in tiers}
