"""``SpeechBudgeter`` (blueprint 10.1, D-PRE-4): budgets from the configured rate, never guessed."""

import math
from dataclasses import dataclass
from fractions import Fraction

from agent_05_scriptwriter.contracts import SceneBudget, SpeechBudget
from agent_05_scriptwriter.text import to_fraction


@dataclass(frozen=True, slots=True)
class BudgetsResult:
    budget: SpeechBudget | None
    verdict: str  # PASS | WARN


def hook_budget(
    rate_cps: float | None, window_ms: int, min_fill_ratio: float | None
) -> BudgetsResult:
    """``beat = floor(W / 3000 x rate)``, ``max = 3 x beat``, ``min = ceil(max x fill ratio)``."""
    if rate_cps is None or min_fill_ratio is None:
        return BudgetsResult(None, "WARN")
    beat = math.floor(Fraction(window_ms, 3000) * to_fraction(rate_cps))
    maximum = 3 * beat
    minimum = math.ceil(maximum * to_fraction(min_fill_ratio))
    if beat < 1 or minimum < 1:
        return BudgetsResult(None, "WARN")
    return BudgetsResult(
        SpeechBudget(hook_chars_min=minimum, hook_chars_max=maximum, beat_chars_target=beat),
        "PASS",
    )


def scene_budget(
    *,
    share_permille: int,
    target_ms: int,
    rate_cps: float | None,
    size_tolerance: float | None,
    max_scenes: int,
    max_change_gap_ms: int,
) -> SceneBudget:
    """Characters allowed in a section (+/- ``size_tolerance``); ``null`` bounds without a rate."""
    if rate_cps is None or size_tolerance is None:
        return SceneBudget(
            chars_min=None,
            chars_max=None,
            max_scenes=max_scenes,
            max_change_gap_ms=max_change_gap_ms,
            speech_rate_cps=rate_cps,
        )
    centre = Fraction(share_permille, 1000) * Fraction(target_ms, 1000) * to_fraction(rate_cps)
    tolerance = to_fraction(size_tolerance)
    return SceneBudget(
        chars_min=max(1, math.floor(centre * (1 - tolerance))),
        chars_max=max(1, math.ceil(centre * (1 + tolerance))),
        max_scenes=max_scenes,
        max_change_gap_ms=max_change_gap_ms,
        speech_rate_cps=rate_cps,
    )
