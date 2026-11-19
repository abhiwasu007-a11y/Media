"""``ChartPath``: the chart path of the cascade (blueprint 6.4): case, dataset, release, lag,
annotations, spec, deterministic render, chart facts. Pure with respect to storage: the caller
supplies the case documents and the dataset bytes (already hash-verified by the loaders).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from agent_08_visual_assets.cascade.tier_cascade import ChartAttempt, chart_preconditions
from agent_08_visual_assets.charts.annotations import AnnotationValidator
from agent_08_visual_assets.charts.cases import (
    ChartCase,
    ChartCaseLibrary,
    ChartRequest,
    StoredCase,
)
from agent_08_visual_assets.charts.dataset import BarSeries
from agent_08_visual_assets.charts.facts import ChartFacts, ChartFactsBuilder, FactBar
from agent_08_visual_assets.charts.lag import ChartLagGuard, LagResult
from agent_08_visual_assets.charts.render import (
    BrandPalette,
    ChartRenderer,
    ChartRenderInput,
    RenderedImage,
    parse_indicator,
)
from agent_08_visual_assets.charts.spec import ChartSpec, ChartSpecHasher
from amw_core.enums import ChartDataKind, DataAgeVsLag, ShotUnresolvedReason
from amw_core.errors import InputInvalidError

TEMPLATE_ID = "chart_base"
TEMPLATE_VERSION = 1
HISTORICAL_LABEL = "Historical example"
TEMPLATE_LABELS = {TEMPLATE_ID: (HISTORICAL_LABEL,)}


@dataclass(frozen=True, slots=True)
class ChartContext:
    """Per-shot inputs of the chart path."""

    request: ChartRequest
    cases: Sequence[StoredCase]
    series: BarSeries | None
    dataset_asset_id: str | None
    release_approved: bool
    on_screen_text_allowlist: Sequence[str]
    change_events: int
    today: date
    lag_days: int
    platform_min_lag_days: int
    width_px: int
    height_px: int
    aspect_ratio: str
    palette: BrandPalette


@dataclass(frozen=True, slots=True)
class BuiltChart:
    case: StoredCase
    spec: ChartSpec
    spec_sha256: str
    stills: tuple[RenderedImage, ...]
    """Reveal sequence; the last still shows the whole window (the shot's chart asset)."""
    lag: LagResult | None
    facts: ChartFacts
    bars_count: int
    start_date: date | None
    end_date: date | None
    extra_attributes: Mapping[str, object] = field(default_factory=dict)
    """Additional ``assets.attributes`` of the chart asset (data_pack provenance, CCR-256)."""


@dataclass(frozen=True, slots=True)
class ChartOutcome:
    built: BuiltChart | None
    unresolved: ShotUnresolvedReason | None
    matched: StoredCase | None = None


class ChartPath:
    @staticmethod
    def case_for(ctx: ChartContext) -> StoredCase | None:
        return ChartCaseLibrary.match(ctx.request, ctx.cases)

    @classmethod
    def run(cls, ctx: ChartContext) -> ChartOutcome:
        stored = cls.case_for(ctx)
        case: ChartCase | None = stored.case if stored is not None else None
        kind = ctx.request.chart_kind
        age: DataAgeVsLag | None = None
        lag: LagResult | None = None
        if stored is not None and case is not None and kind is ChartDataKind.REAL_HISTORICAL:
            if ctx.series is not None and case.window is not None:
                if case.window.last_bar_index >= len(ctx.series):
                    raise InputInvalidError("chart case window is outside the dataset")
                last_bar = ctx.series.bars[case.window.last_bar_index]
                lag = ChartLagGuard.classify(
                    timeframe=case.timeframe,
                    lag_days=ctx.lag_days,
                    platform_min_lag_days=ctx.platform_min_lag_days,
                    last_bar_start=last_bar.date,
                    period_end=None,
                    today=ctx.today,
                )
                age = lag.data_age_vs_lag
            else:
                age = DataAgeVsLag.UNKNOWN
        reason = chart_preconditions(
            kind=kind,
            case_found=stored is not None,
            dataset_found=ctx.series is not None,
            method_content=bool(case and case.method_content),
            release_approved=ctx.release_approved,
            data_age=age,
        )
        if reason is not None or stored is None or case is None:
            return ChartOutcome(None, reason or ShotUnresolvedReason.NO_CHART_CASE, stored)
        if kind is ChartDataKind.SCHEMATIC:
            return ChartOutcome(cls._schematic(ctx, stored), None, stored)
        return ChartOutcome(cls._real(ctx, stored, lag), None, stored)

    @staticmethod
    def _schematic(ctx: ChartContext, stored: StoredCase) -> BuiltChart:
        case = stored.case
        points = tuple(Decimal(p) for p in case.schematic_points or ())
        image = ChartRenderer.render_schematic(
            points, width_px=ctx.width_px, height_px=ctx.height_px, palette=ctx.palette
        )
        spec = ChartSpec(
            dataset_sha256="0" * 64,
            window=(0, len(points) - 1),
            instrument="SCHEMATIC",
            timeframe=case.timeframe,
            indicators=(),
            template_id=case.template_id,
            template_version=TEMPLATE_VERSION,
            annotations=(),
            aspect_ratio=ctx.aspect_ratio,
            palette_ref="brand_kit",
            palette_sha256=ctx.palette.sha256(),
        )
        return BuiltChart(
            stored,
            spec,
            ChartSpecHasher.hash(spec),
            (image,),
            None,
            ChartFacts((), False),
            len(points),
            None,
            None,
        )

    @staticmethod
    def _real(ctx: ChartContext, stored: StoredCase, lag: LagResult | None) -> BuiltChart:
        case, series = stored.case, ctx.series
        if series is None or case.window is None or case.instrument is None:
            raise InputInvalidError("real chart without dataset or window")  # guarded earlier
        first, last = case.window.first_bar_index, case.window.last_bar_index
        for name in case.indicators:
            parse_indicator(name)
        labels = TEMPLATE_LABELS.get(case.template_id, ())
        verdict = AnnotationValidator.validate(
            annotations=case.annotations,
            last_bar_index=last,
            first_bar_index=first,
            on_screen_text_allowlist=ctx.on_screen_text_allowlist,
            template_labels=labels,
        )
        if not verdict.ok:
            raise InputInvalidError(
                "chart annotation rejected (FIN-R13)", details={"reason": str(verdict.reason)}
            )
        window_bars = series.window(first, last)
        title = (
            f"{case.instrument}  {case.timeframe}  "
            f"{window_bars[0].date.isoformat()} to {window_bars[-1].date.isoformat()}"
        )
        spec = ChartSpec(
            dataset_sha256=series.sha256,
            window=(first, last),
            instrument=case.instrument,
            timeframe=case.timeframe,
            indicators=case.indicators,
            template_id=case.template_id,
            template_version=TEMPLATE_VERSION,
            annotations=case.annotations,
            aspect_ratio=ctx.aspect_ratio,
            palette_ref="brand_kit",
            reveal_steps=ctx.change_events + 1,
            palette_sha256=ctx.palette.sha256(),
        )
        stills = ChartRenderer.reveal_sequence(
            ChartRenderInput(
                series=series.bars,
                first_bar_index=first,
                last_bar_index=last,
                title=title,
                indicators=case.indicators,
                annotations=case.annotations,
                width_px=ctx.width_px,
                height_px=ctx.height_px,
                palette=ctx.palette,
            ),
            spec.reveal_steps,
        )
        facts = ChartFactsBuilder.build(
            ChartDataKind.REAL_HISTORICAL,
            case.timeframe,
            [FactBar(b.date, b.open, b.high, b.low, b.close) for b in window_bars],
        )
        return BuiltChart(
            stored,
            spec,
            ChartSpecHasher.hash(spec),
            tuple(stills),
            lag,
            facts,
            len(window_bars),
            window_bars[0].date,
            lag.data_end_date if lag is not None and lag.data_end_date else window_bars[-1].date,
        )


def attempt_of(outcome: ChartOutcome) -> ChartAttempt[BuiltChart]:
    return ChartAttempt(accepted=outcome.built, unresolved=outcome.unresolved)
