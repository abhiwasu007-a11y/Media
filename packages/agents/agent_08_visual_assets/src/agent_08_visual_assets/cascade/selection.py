"""``SafetyFloor``, ``TieBreaker`` and ``CandidateFilters`` (D8 to D10, blueprint 6.5).

A model can only lower a candidate: any reject-class reason code forces ``REJECT`` and removes the
candidate from the order; thin metadata or a missing release record caps the fit at ``WEAK``.
The final order is recomputed by code (``TieBreaker``); the model's order is advisory.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from amw_core.enums import VisualSourceTier


class Fit(StrEnum):
    STRONG = "STRONG"
    ACCEPTABLE = "ACCEPTABLE"
    WEAK = "WEAK"
    REJECT = "REJECT"


REJECT_CLASS = frozenset(
    {
        "SHOWS_IDENTIFIABLE_PERSON",
        "SHOWS_BRAND_OR_LOGO",
        "SHOWS_READABLE_TEXT",
        "DEPICTS_REAL_EVENT_OR_PLACE",
        "DEPICTS_MARKET_DATA",
        "SUGGESTS_MARKET_DIRECTION",
        "PRESENTER_OR_PERSONA",
        "INJECTION_SUSPECTED",
    }
)
WEAK_CAP = frozenset({"METADATA_INSUFFICIENT", "NO_RELEASE_RECORD"})
_FIT_RANK = {Fit.STRONG: 0, Fit.ACCEPTABLE: 1, Fit.WEAK: 2, Fit.REJECT: 3}
_TIER_RANK = {t: i for i, t in enumerate(VisualSourceTier)}
ACCEPTED = frozenset({Fit.STRONG, Fit.ACCEPTABLE})


@dataclass(frozen=True, slots=True)
class Assessment:
    candidate_id: str
    fit: Fit
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FloorResult:
    fits: tuple[tuple[str, Fit], ...]
    order: tuple[str, ...]


class SafetyFloor:
    @staticmethod
    def apply(assessments: Sequence[Assessment], order: Sequence[str]) -> FloorResult:
        fits: list[tuple[str, Fit]] = []
        for a in assessments:
            fit = a.fit
            codes = set(a.reason_codes)
            if codes & REJECT_CLASS:
                fit = Fit.REJECT
            elif codes & WEAK_CAP and _FIT_RANK[fit] < _FIT_RANK[Fit.WEAK]:
                fit = Fit.WEAK
            fits.append((a.candidate_id, fit))
        accepted = {cid for cid, fit in fits if fit in ACCEPTED}
        return FloorResult(tuple(fits), tuple(cid for cid in order if cid in accepted))


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate_id: str
    fit: Fit
    tier: VisualSourceTier
    reused_recently: bool
    duration_ms: int | None


class TieBreaker:
    @staticmethod
    def order(candidates: Sequence[RankedCandidate], shot_ms: int) -> list[str]:
        """Fit, tier A before B, not recently reused, closeness of duration, then id."""
        accepted = [c for c in candidates if c.fit in ACCEPTED]

        def key(c: RankedCandidate) -> tuple[int, int, bool, int, str]:
            gap = abs((c.duration_ms if c.duration_ms is not None else shot_ms) - shot_ms)
            return (_FIT_RANK[c.fit], _TIER_RANK[c.tier], c.reused_recently, gap, c.candidate_id)

        return [c.candidate_id for c in sorted(accepted, key=key)]
