"""``TierCascade`` (D2/D3, blueprint 6.3): strictly A to E, every skipped tier has a reason.

The cascade is pure: the tiers are *probes* (callables) that either accept a payload or name a
skip reason. In production a probe searches, ranks and acquires; in the golden dataset a probe is
built from recorded facts. A chart request is served by tier C only and never falls to stock or AI
(D3); a footage shot falls to the next tier only with a recorded reason.
"""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from amw_core.enums import (
    ChartDataKind,
    DataAgeVsLag,
    ShotUnresolvedReason,
    SourcingWarning,
    VisualSkipReason,
    VisualSourceTier,
)

A = VisualSourceTier.A_OWNER_REAL
B = VisualSourceTier.B_LICENSED_STOCK
C = VisualSourceTier.C_CODE_MOTION
D = VisualSourceTier.D_AI_VIDEO
E = VisualSourceTier.E_AI_STILL
TIER_ORDER = (A, B, C, D, E)


class IntentKind(StrEnum):
    """Internal intent: the plan's ``DIAGRAM`` and ``TEXT_CARD`` are both ``GRAPHIC``."""

    FOOTAGE = "FOOTAGE"
    CHART = "CHART"
    GRAPHIC = "GRAPHIC"


class StepRefusalReason(StrEnum):
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    CONFLICTING_INSTRUCTIONS = "CONFLICTING_INSTRUCTIONS"
    UNSAFE_CONTENT = "UNSAFE_CONTENT"


@dataclass(frozen=True, slots=True)
class Skip:
    tier: VisualSourceTier
    reason: VisualSkipReason


@dataclass(frozen=True, slots=True)
class Attempt[T]:
    """Outcome of one tier probe: an accepted payload or a skip reason.

    ``unsafe`` marks a skip caused by an ``UNSAFE_CONTENT`` step refusal, which decides the
    unresolved reason of a shot that ends without any source."""

    accepted: T | None = None
    skip: VisualSkipReason | None = None
    unsafe: bool = False


def accept[T](payload: T) -> Attempt[T]:
    return Attempt(accepted=payload)


def skip_with[T](reason: VisualSkipReason, *, unsafe: bool = False) -> Attempt[T]:
    return Attempt(skip=reason, unsafe=unsafe)


@dataclass(frozen=True, slots=True)
class ChartAttempt[T]:
    accepted: T | None = None
    unresolved: ShotUnresolvedReason | None = None


@dataclass(slots=True)
class Probes[T]:
    """Lazy tier probes of one shot; a probe is called only when the cascade reaches its tier."""

    owner: Callable[[], Attempt[T]] | None = None
    stock: Callable[[], Attempt[T]] | None = None
    graphic: Callable[[], Attempt[T]] | None = None
    ai_video: Callable[[], Attempt[T]] | None = None
    ai_still: Callable[[], Attempt[T]] | None = None
    chart: Callable[[], ChartAttempt[T]] | None = None


@dataclass(frozen=True, slots=True)
class CascadeResult[T]:
    sourced: bool
    tier: VisualSourceTier | None
    skips: tuple[Skip, ...]
    warnings: tuple[SourcingWarning, ...]
    unresolved_reason: ShotUnresolvedReason | None
    payload: T | None = None


@dataclass(slots=True)
class _Run[T]:
    skips: list[Skip] = field(default_factory=list)
    unsafe: bool = False
    result: CascadeResult[T] | None = None


def chart_preconditions(
    *,
    kind: ChartDataKind,
    case_found: bool,
    dataset_found: bool,
    method_content: bool,
    release_approved: bool,
    data_age: DataAgeVsLag | None,
) -> ShotUnresolvedReason | None:
    """Why a chart request cannot be drawn, or ``None``. Order: case, dataset, release, lag.

    Owner-material gaps come first (they fail the task); the lag is a plan-fixable gate reason.
    A schematic chart needs only its schematic case and carries no data age (CCR-042)."""
    if not case_found:
        return ShotUnresolvedReason.NO_CHART_CASE
    if kind is ChartDataKind.SCHEMATIC:
        return None
    if not dataset_found:
        return ShotUnresolvedReason.NO_DATASET
    if method_content and not release_approved:
        return ShotUnresolvedReason.METHOD_NOT_RELEASED
    if data_age is not DataAgeVsLag.OLDER_THAN_LAG:
        return ShotUnresolvedReason.DATA_WITHIN_LAG  # UNKNOWN is treated as within the lag
    return None


class TierCascade:
    @staticmethod
    def resolve_shot[T](
        *,
        intent: IntentKind,
        probes: Probes[T],
        prohibited_depiction: bool = False,
        unsafe_refusal: bool = False,
        allowed_tiers: Collection[VisualSourceTier] | None = None,
    ) -> CascadeResult[T]:
        run: _Run[T] = _Run()
        if intent is IntentKind.CHART:
            return TierCascade._chart(run, probes)
        if intent is IntentKind.GRAPHIC:
            return TierCascade._graphic(run, probes)
        return TierCascade._footage(
            run,
            probes,
            prohibited=prohibited_depiction or unsafe_refusal,
            unsafe=unsafe_refusal,
            allowed=allowed_tiers,
        )

    # -- chart and graphic: tier C only ----------------------------------------------------------

    @staticmethod
    def _not_applicable[T](run: _Run[T]) -> None:
        for tier in (A, B, D, E):
            run.skips.append(Skip(tier, VisualSkipReason.NOT_APPLICABLE_INTENT))

    @staticmethod
    def _chart[T](run: _Run[T], probes: Probes[T]) -> CascadeResult[T]:
        TierCascade._not_applicable(run)
        attempt = probes.chart() if probes.chart is not None else ChartAttempt()
        if attempt.unresolved is not None:
            return CascadeResult(False, None, tuple(run.skips), (), attempt.unresolved)
        if attempt.accepted is None:
            return CascadeResult(
                False, None, tuple(run.skips), (), ShotUnresolvedReason.NO_CHART_CASE
            )
        return CascadeResult(True, C, tuple(run.skips), (), None, attempt.accepted)

    @staticmethod
    def _graphic[T](run: _Run[T], probes: Probes[T]) -> CascadeResult[T]:
        TierCascade._not_applicable(run)
        attempt = probes.graphic() if probes.graphic is not None else Attempt()
        if attempt.accepted is None:
            run.skips.append(Skip(C, VisualSkipReason.NO_TEMPLATE_CONTENT))
            return CascadeResult(
                False, None, tuple(run.skips), (), ShotUnresolvedReason.NO_TEMPLATE_CONTENT
            )
        return CascadeResult(True, C, tuple(run.skips), (), None, attempt.accepted)

    # -- footage: A, B, C, D, E ------------------------------------------------------------------

    @staticmethod
    def _footage[T](
        run: _Run[T],
        probes: Probes[T],
        *,
        prohibited: bool,
        unsafe: bool,
        allowed: Collection[VisualSourceTier] | None,
    ) -> CascadeResult[T]:
        run.unsafe = unsafe

        def planned(tier: VisualSourceTier) -> bool:
            return allowed is None or tier in allowed

        def done(
            tier: VisualSourceTier, payload: T, warnings: tuple[SourcingWarning, ...] = ()
        ) -> CascadeResult[T]:
            return CascadeResult(True, tier, tuple(run.skips), warnings, None, payload)

        def try_tier(
            tier: VisualSourceTier,
            probe: Callable[[], Attempt[T]] | None,
            *,
            not_planned: VisualSkipReason,
            disabled: VisualSkipReason,
        ) -> Attempt[T]:
            """Order: prohibited depiction, not planned, no probe wired, then the probe."""
            if prohibited:
                return skip_with(VisualSkipReason.PROHIBITED_DEPICTION)
            if not planned(tier):
                return skip_with(not_planned)
            if probe is None:
                return skip_with(disabled)
            return probe()

        a = try_tier(
            A,
            probes.owner,
            not_planned=VisualSkipReason.NOT_APPLICABLE_INTENT,
            disabled=VisualSkipReason.NO_CANDIDATE,
        )
        if a.accepted is not None:
            return done(A, a.accepted)
        run.skips.append(Skip(A, a.skip or VisualSkipReason.NO_CANDIDATE))
        run.unsafe = run.unsafe or a.unsafe

        b = try_tier(
            B,
            probes.stock,
            not_planned=VisualSkipReason.NOT_APPLICABLE_INTENT,
            disabled=VisualSkipReason.TIER_DISABLED,
        )
        if b.accepted is not None:
            return done(B, b.accepted)
        run.skips.append(Skip(B, b.skip or VisualSkipReason.NO_CANDIDATE))
        run.unsafe = run.unsafe or b.unsafe

        # Tier C is applicable unless the plan marked the shot as needing AI video (6.3 item 5);
        # the stage encodes that by not wiring a graphic probe.
        c = probes.graphic() if probes.graphic is not None else None
        if c is not None and c.accepted is not None:
            return done(C, c.accepted, (SourcingWarning.FOOTAGE_INTENT_DOWNGRADED_TO_GRAPHIC,))
        run.skips.append(Skip(C, VisualSkipReason.NO_TEMPLATE_CONTENT))

        d = try_tier(
            D,
            probes.ai_video,
            not_planned=VisualSkipReason.TIER_DISABLED,
            disabled=VisualSkipReason.TIER_DISABLED,
        )
        if d.accepted is not None:
            return done(D, d.accepted)
        run.skips.append(Skip(D, d.skip or VisualSkipReason.TIER_DISABLED))

        e = try_tier(
            E,
            probes.ai_still,
            not_planned=VisualSkipReason.TIER_DISABLED,
            disabled=VisualSkipReason.TIER_DISABLED,
        )
        if e.accepted is not None:
            return done(E, e.accepted)
        run.skips.append(Skip(E, e.skip or VisualSkipReason.TIER_DISABLED))

        reason = (
            ShotUnresolvedReason.UNSAFE_CONTENT
            if run.unsafe
            else ShotUnresolvedReason.NO_SOURCE_IN_ANY_TIER
        )
        return CascadeResult(False, None, tuple(run.skips), (), reason)

    # -- verification ----------------------------------------------------------------------------

    @staticmethod
    def missing_skip_reasons(
        chosen: VisualSourceTier | None, skips: Sequence[Skip]
    ) -> list[VisualSourceTier]:
        """Tiers above the chosen one (all tiers when unresolved) lacking a recorded reason."""
        recorded = {s.tier for s in skips}
        limit = TIER_ORDER.index(chosen) if chosen is not None else len(TIER_ORDER)
        return [t for t in TIER_ORDER[:limit] if t not in recorded]
