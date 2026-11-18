"""``CadenceChecker`` (blueprint 10.3 ``a05.sec.cadence``; 18 ``edit.visual.cadence``)."""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from agent_05_scriptwriter.text import ceil_div, to_fraction


@dataclass(frozen=True, slots=True)
class CadenceResult:
    verdict: str
    required: int | None
    interrupt_missing: bool


def required_change_beats(
    *, chars: int, sentences: int, pause_ms: int, rate_cps: float | None, max_gap_ms: int
) -> int:
    """``ceil(narration_ms / max_gap)``; without a rate, one beat per two sentences."""
    if rate_cps is None:
        return ceil_div(sentences, 2)
    narration_ms = Fraction(chars) / to_fraction(rate_cps) * 1000 + pause_ms
    return max(0, -(-narration_ms.numerator // (narration_ms.denominator * max_gap_ms)))


def check_cadence(
    *,
    explanatory: bool,
    chars: int,
    sentences: int,
    pause_ms: int,
    rate_cps: float | None,
    max_gap_ms: int,
    change_beats: int,
    hold_reason: str | None,
    needs_interrupt: bool,
    scene_interrupts: Sequence[str | None],
) -> CadenceResult:
    interrupt_missing = needs_interrupt and not any(i is not None for i in scene_interrupts)
    if not explanatory:
        # A held, non-explanatory scene is allowed only with its reason recorded.
        if hold_reason:
            return CadenceResult("FAIL" if interrupt_missing else "PASS", 0, interrupt_missing)
        return CadenceResult("FAIL", None, interrupt_missing)
    required = required_change_beats(
        chars=chars,
        sentences=sentences,
        pause_ms=pause_ms,
        rate_cps=rate_cps,
        max_gap_ms=max_gap_ms,
    )
    ok = change_beats >= required and not interrupt_missing
    return CadenceResult("PASS" if ok else "FAIL", required, interrupt_missing)
