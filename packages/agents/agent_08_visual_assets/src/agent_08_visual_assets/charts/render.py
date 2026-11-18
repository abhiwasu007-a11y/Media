"""``ChartRenderer``: byte-deterministic chart stills (blueprint 6.4(7), U-12).

Rasteriser: matplotlib (Agg backend, drawn on a ``Figure`` object, no ``pyplot`` global state) with
the DejaVu Sans font that ships inside the pinned matplotlib wheel unless the brand kit supplies a
font file. No timestamps, no random seeds, PNG metadata stripped: the same spec twice gives the same
SHA-256, which makes the asset hash a valid idempotency and reuse key. A *reveal sequence* is
``len(change_events_ms) + 1`` stills showing progressively more bars, left to right, never beyond
the last bar of the window; Agent 10 realises the change events from the stills.

Complex-script shaping (Devanagari conjuncts) is NOT available in this rasteriser; see the package
README (open item). Text drawn here comes from the allowlists only (latin labels and numbers).
"""

import hashlib
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

import matplotlib as mpl
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle

from amw_core.errors import InputInvalidError

from agent_08_visual_assets.charts.annotations import Annotation, AnnotationKind
from agent_08_visual_assets.charts.dataset import Bar
from agent_08_visual_assets.charts.spec import canonical_json

DPI = 100
RENDERER_ID = "matplotlib-agg"
PNG_METADATA: dict[str, str | None] = {"Software": None}
KNOWN_INDICATORS = ("SMA", "EMA", "RSI")
SCHEMATIC_LABEL = "Illustrative example, not real data"


@dataclass(frozen=True, slots=True)
class BrandPalette:
    """Colours and optional font file of the brand kit (``#rrggbb``)."""

    background: str
    foreground: str
    grid: str
    up: str
    down: str
    accent: str
    shade: str
    font_path: str | None = None

    def sha256(self) -> str:
        data = {k: getattr(self, k) for k in self.__slots__}
        return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RenderedImage:
    png: bytes
    width_px: int
    height_px: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.png).hexdigest()


def parse_indicator(name: str) -> tuple[str, int]:
    kind, _, period = name.partition("_")
    if kind not in KNOWN_INDICATORS or not period.isdigit() or not 2 <= int(period) <= 400:
        raise InputInvalidError(f"unknown indicator {name!r}")
    return kind, int(period)


def sma(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        out.append(running / period if i >= period - 1 else None)
    return out


def ema(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    k = 2.0 / (period + 1)
    prev: float | None = None
    for i, v in enumerate(values):
        if i < period - 1:
            out.append(None)
            continue
        prev = sum(values[:period]) / period if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(values: Sequence[float], period: int) -> list[float | None]:
    """Wilder's RSI."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(values)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def font_props(palette: BrandPalette, size: float) -> FontProperties:
    if palette.font_path is not None:
        return FontProperties(fname=palette.font_path, size=size)
    return FontProperties(family="DejaVu Sans", size=size)


def figure_png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    FigureCanvasAgg(fig)
    fig.savefig(buf, format="png", dpi=DPI, metadata=PNG_METADATA, facecolor=fig.get_facecolor())
    return buf.getvalue()


def new_figure(width_px: int, height_px: int, palette: BrandPalette) -> Figure:
    return Figure(figsize=(width_px / DPI, height_px / DPI), dpi=DPI, facecolor=palette.background)


@dataclass(frozen=True, slots=True)
class ChartRenderInput:
    """Everything the drawing needs; the window is ``bars[first:last+1]`` of ``series``."""

    series: Sequence[Bar]
    first_bar_index: int
    last_bar_index: int
    title: str
    indicators: tuple[str, ...]
    annotations: tuple[Annotation, ...]
    width_px: int
    height_px: int
    palette: BrandPalette
    label_texts: Mapping[str, str] | None = None


class ChartRenderer:
    @staticmethod
    def render(spec: ChartRenderInput, *, shown_bars: int | None = None) -> RenderedImage:
        """One still; ``shown_bars`` limits the reveal to the first n bars of the window."""
        with mpl.rc_context({"axes.unicode_minus": False, "text.hinting": "none"}):
            return ChartRenderer._draw(spec, shown_bars)

    @staticmethod
    def reveal_sequence(spec: ChartRenderInput, steps: int) -> list[RenderedImage]:
        """``steps`` stills with progressively more bars; the last shows the whole window."""
        total = spec.last_bar_index - spec.first_bar_index + 1
        if steps < 1:
            raise InputInvalidError("a reveal sequence has at least one still")
        counts = [max(1, -(-total * (i + 1) // steps)) for i in range(steps)]
        counts[-1] = total
        return [ChartRenderer.render(spec, shown_bars=n) for n in counts]

    @staticmethod
    def _draw(spec: ChartRenderInput, shown_bars: int | None) -> RenderedImage:  # noqa: PLR0914
        window = list(spec.series[spec.first_bar_index : spec.last_bar_index + 1])
        if not window:
            raise InputInvalidError("empty chart window")
        n = len(window)
        shown = n if shown_bars is None else max(1, min(shown_bars, n))
        palette = spec.palette
        vertical = spec.height_px > spec.width_px
        scale = min(spec.width_px, spec.height_px) / 1080.0
        fig = new_figure(spec.width_px, spec.height_px, palette)
        parsed = [parse_indicator(i) for i in spec.indicators]
        has_rsi = any(k == "RSI" for k, _ in parsed)
        grid = fig.add_gridspec(
            2 if has_rsi else 1,
            1,
            height_ratios=[3, 1] if has_rsi else [1],
            left=0.10 if vertical else 0.07,
            right=0.97,
            top=0.90,
            bottom=0.10,
            hspace=0.08,
        )
        ax = fig.add_subplot(grid[0])
        closes = [float(b.close) for b in spec.series[: spec.last_bar_index + 1]]
        lows = [float(b.low) for b in window]
        highs = [float(b.high) for b in window]
        y_lo, y_hi = min(lows), max(highs)
        pad = (y_hi - y_lo) * 0.08 or 1.0
        ax.set_xlim(-1, n)
        ax.set_ylim(y_lo - pad, y_hi + pad)
        ax.set_facecolor(palette.background)
        ax.grid(True, color=palette.grid, linewidth=0.6 * max(scale, 0.5))
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_color(palette.grid)
        body_w = 0.6
        for i, bar in enumerate(window[:shown]):
            colour = palette.up if bar.close >= bar.open else palette.down
            ax.vlines(i, float(bar.low), float(bar.high), color=colour, linewidth=1.4 * scale)
            o, c = float(bar.open), float(bar.close)
            ax.add_patch(
                Rectangle(
                    (i - body_w / 2, min(o, c)),
                    body_w,
                    max(abs(c - o), (y_hi - y_lo) * 0.002),
                    facecolor=colour,
                    edgecolor=colour,
                    linewidth=0.8 * scale,
                )
            )
        for (kind, period), name in zip(parsed, spec.indicators, strict=True):
            if kind == "RSI":
                continue
            line = (sma if kind == "SMA" else ema)(closes, period)[spec.first_bar_index :]
            pts = [(i, v) for i, v in enumerate(line[:shown]) if v is not None]
            if pts:
                ax.plot(
                    [p[0] for p in pts],
                    [p[1] for p in pts],
                    color=palette.accent,
                    linewidth=2.0 * scale,
                    label=name,
                )
        ChartRenderer._annotations(ax, spec, window, shown, y_lo - pad, y_hi + pad, scale)
        ticks = _tick_positions(n, 4 if vertical else 7)
        tick_font = font_props(palette, 20 * scale)
        ax.set_xticks([t for t in ticks if t < shown])
        ax.set_xticklabels(
            [window[t].date.isoformat() for t in ticks if t < shown],
            fontproperties=tick_font,
            color=palette.foreground,
            rotation=45 if vertical else 0,
            ha="right" if vertical else "center",
        )
        _edge_align(ax, vertical)
        for label in ax.get_yticklabels():
            label.set_fontproperties(tick_font)
            label.set_color(palette.foreground)
        ax.tick_params(colors=palette.foreground)
        if has_rsi:
            ChartRenderer._rsi_panel(fig, grid, spec, parsed, closes, shown, n, scale, ticks)
            ax.set_xticklabels([])
        fig.text(
            0.5,
            0.95,
            spec.title,
            ha="center",
            va="center",
            color=palette.foreground,
            fontproperties=font_props(palette, 30 * scale),
        )
        return RenderedImage(figure_png(fig), spec.width_px, spec.height_px)

    @staticmethod
    def _annotations(
        ax: "mpl.axes.Axes",
        spec: ChartRenderInput,
        window: Sequence[Bar],
        shown: int,
        y_lo: float,
        y_hi: float,
        scale: float,
    ) -> None:
        palette = spec.palette
        first = spec.first_bar_index
        for a in spec.annotations:
            kind = AnnotationKind(a.kind)
            if kind is AnnotationKind.MARK_BAR and a.bar is not None:
                i = a.bar - first
                if i < shown:
                    ax.plot(
                        [i],
                        [float(window[i].high) + (y_hi - y_lo) * 0.03],
                        marker="v",
                        color=palette.accent,
                        markersize=14 * scale,
                    )
            elif kind is AnnotationKind.SHADE_RANGE and a.from_bar is not None and a.to_bar is not None:
                lo, hi = a.from_bar - first, min(a.to_bar - first, shown - 1)
                if lo <= hi:
                    ax.axvspan(lo - 0.5, hi + 0.5, color=palette.shade, alpha=0.25, linewidth=0)
            elif kind is AnnotationKind.HLINE_THROUGH_BARS and a.price is not None:
                x0 = (a.from_bar if a.from_bar is not None else first) - first
                x1 = min((a.to_bar if a.to_bar is not None else first) - first, shown - 1)
                if x0 <= x1:
                    ax.hlines(
                        float(Decimal(a.price)), x0, x1, color=palette.accent,
                        linewidth=2.0 * scale, linestyles="dashed",
                    )  # fmt: skip
            elif kind is AnnotationKind.LABEL and a.bar is not None and a.text is not None:
                i = a.bar - first
                if i < shown:
                    ax.annotate(
                        a.text,
                        (i, float(window[i].high)),
                        xytext=(0, 28 * scale),
                        textcoords="offset points",
                        ha="center",
                        color=palette.foreground,
                        fontproperties=font_props(palette, 22 * scale),
                    )

    @staticmethod
    def _rsi_panel(
        fig: Figure,
        grid: "mpl.gridspec.GridSpec",
        spec: ChartRenderInput,
        parsed: Sequence[tuple[str, int]],
        closes: Sequence[float],
        shown: int,
        n: int,
        scale: float,
        ticks: Sequence[int],
    ) -> None:
        palette = spec.palette
        ax = fig.add_subplot(grid[1])
        ax.set_facecolor(palette.background)
        ax.set_xlim(-1, n)
        ax.set_ylim(0, 100)
        ax.grid(True, color=palette.grid, linewidth=0.6 * max(scale, 0.5))
        for spine in ax.spines.values():
            spine.set_color(palette.grid)
        for kind, period in parsed:
            if kind != "RSI":
                continue
            line = rsi(closes, period)[spec.first_bar_index :]
            pts = [(i, v) for i, v in enumerate(line[:shown]) if v is not None]
            if pts:
                ax.plot(
                    [p[0] for p in pts], [p[1] for p in pts], color=palette.accent, linewidth=2 * scale
                )
        window = spec.series[spec.first_bar_index : spec.last_bar_index + 1]
        font = font_props(palette, 20 * scale)
        ax.set_xticks([t for t in ticks if t < shown])
        vertical = spec.height_px > spec.width_px
        ax.set_xticklabels(
            [window[t].date.isoformat() for t in ticks if t < shown],
            fontproperties=font,
            color=palette.foreground,
            rotation=45 if vertical else 0,
            ha="right" if vertical else "center",
        )
        _edge_align(ax, vertical)
        ax.tick_params(colors=palette.foreground)
        for label in ax.get_yticklabels():
            label.set_fontproperties(font)
            label.set_color(palette.foreground)

    @staticmethod
    def render_schematic(
        points: Sequence[Decimal],
        *,
        width_px: int,
        height_px: int,
        palette: BrandPalette,
        label: str = SCHEMATIC_LABEL,
    ) -> RenderedImage:
        """Owner-given schematic points only; the template adds the fixed label (6.4(6))."""
        if len(points) < 2:
            raise InputInvalidError("a schematic chart needs at least two points")
        scale = min(width_px, height_px) / 1080.0
        with mpl.rc_context({"axes.unicode_minus": False, "text.hinting": "none"}):
            fig = new_figure(width_px, height_px, palette)
            ax = fig.add_axes((0.08, 0.12, 0.88, 0.74), facecolor=palette.background)
            ax.plot(range(len(points)), [float(p) for p in points], color=palette.accent, linewidth=4 * scale)
            ax.grid(True, color=palette.grid, linewidth=0.6 * max(scale, 0.5))
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_color(palette.grid)
            fig.text(
                0.5, 0.94, label, ha="center", va="center", color=palette.foreground,
                fontproperties=font_props(palette, 30 * scale),
            )  # fmt: skip
            return RenderedImage(figure_png(fig), width_px, height_px)


def _edge_align(ax: "mpl.axes.Axes", vertical: bool) -> None:
    """Keep the outer date labels inside the canvas."""
    labels = ax.get_xticklabels()
    if labels and not vertical:
        labels[-1].set_ha("right")
        labels[0].set_ha("left")


def _tick_positions(n: int, count: int) -> list[int]:
    if n <= count:
        return list(range(n))
    step = (n - 1) / (count - 1)
    return sorted({round(i * step) for i in range(count)})
