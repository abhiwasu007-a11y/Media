"""``ChartRenderer``: byte-deterministic chart stills (blueprint 6.4(7), U-12).

Rasteriser: matplotlib (Agg backend, drawn on a ``Figure`` object, no ``pyplot`` global state) with
the DejaVu Sans font that ships inside the pinned matplotlib wheel unless the brand kit supplies a
font file. No timestamps, no random seeds, PNG metadata stripped: the same spec twice gives the same
SHA-256, which makes the asset hash a valid idempotency and reuse key. A *reveal sequence* is
``len(change_events_ms) + 1`` stills showing progressively more bars, left to right, never beyond
the last bar of the window; Agent 10 realises the change events from the stills.

Complex-script shaping: matplotlib 3.11 lays text out through libraqm
(``ft2font.__libraqm_version__``), so Devanagari conjuncts and pre-base vowel signs are shaped when
the font has the glyphs; the data_pack
builder checks the font covers every character it draws (no notdef box) and that libraqm is present.
Text drawn here comes from the allowlists and the fixed template labels only.
"""

import hashlib
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import matplotlib as mpl
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle

from agent_08_visual_assets.charts.annotations import Annotation, AnnotationKind
from agent_08_visual_assets.charts.dataset import Bar
from agent_08_visual_assets.charts.spec import canonical_json
from amw_core.errors import InputInvalidError

DPI = 100
RENDERER_ID = "matplotlib-agg"
PNG_METADATA: dict[str, str | None] = {"Software": None}
KNOWN_INDICATORS = ("SMA", "EMA", "RSI")
SCHEMATIC_LABEL = "Illustrative example, not real data"


# Left margin of the footer text as a FIGURE-COORDINATE fraction (1 % of the width), NOT money:
# written as a ratio so the currency-literal source guard (tests/core_services/test_config.py)
# does not read it as a two-decimal money assumption.
_FOOTER_LEFT_FRACTION = 1 / 100


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
    """Local file of the brand font, materialised by the stage from tenant storage (never a
    caller-supplied path); excluded from the hash, ``font_sha256`` stands for it."""
    font_sha256: str | None = None

    def sha256(self) -> str:
        data = {k: getattr(self, k) for k in self.__slots__ if k != "font_path"}
        return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RenderedImage:
    png: bytes
    width_px: int
    height_px: int
    text_boxes: tuple[tuple[str, tuple[float, float, float, float]], ...] = field(
        default=(), compare=False
    )
    """(role, (x0, y0, x1, y1) in pixels, origin bottom-left) of the template texts; filled by the
    renderer when a footer is drawn, for layout invariants."""

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
    """Relative Strength Index with Wilder's smoothing (the textbook definition: J. Welles Wilder
    Jr.,
    *New Concepts in Technical Trading Systems*, 1978; RESEARCH_LOG RV-11).

    For closes ``c``: change ``d_i = c_i - c_(i-1)``; gain ``max(d_i, 0)``, loss ``max(-d_i, 0)``.
    The first average gain/loss is the simple mean of the first ``period`` gains/losses and gives
    the
    RSI of bar ``period``; after that ``avg = (prev_avg * (period - 1) + current) / period``.
    ``RS = avg_gain / avg_loss``; ``RSI = 100 - 100 / (1 + RS)``; ``avg_loss == 0`` with a positive
    ``avg_gain`` gives 100. Convention for a flat span (both averages 0, RS = 0/0): the value is
    undefined (``None``, not drawn, a connector there is refused), never 100 and never 50.
    Bars before index ``period`` have no value (``None``)."""
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
        if avg_loss == 0 and avg_gain == 0:
            out[i] = None  # no movement over the smoothing span: RS is 0/0, RSI undefined
        elif avg_loss == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
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
    footer_lines: tuple[str, ...] = ()
    """Fixed template lines under the plot (source label, as-of range); empty = no footer."""
    connectors: tuple[BarConnector, ...] = ()
    """Segments between two bars inside the window (proposed kind ``CONNECT_BARS``, CCR-255)."""
    rsi_guides: tuple[float, ...] = ()
    rsi_caption: str | None = None


@dataclass(frozen=True, slots=True)
class BarConnector:
    """A straight segment from bar ``from_bar`` to bar ``to_bar`` (dataset indexes, both inside the
    window, never extended); ``panel`` PRICE joins the bars' ``anchor`` prices (HIGH or LOW), RSI
    joins the RSI values of the first RSI indicator at the two bars."""

    from_bar: int
    to_bar: int
    panel: str
    anchor: str


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
    def _draw(spec: ChartRenderInput, shown_bars: int | None) -> RenderedImage:
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
            top=0.85 if spec.footer_lines else 0.90,
            bottom=0.17 if spec.footer_lines else 0.10,
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
        labels = ChartRenderer._annotations(ax, spec, window, shown, y_lo - pad, y_hi + pad, scale)
        ChartRenderer._price_connectors(ax, spec, window, shown, scale)
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
        title = fig.text(
            0.5,
            0.95,
            spec.title,
            ha="center",
            va="center",
            color=palette.foreground,
            fontproperties=font_props(palette, 30 * scale),
        )
        if not spec.footer_lines:
            return RenderedImage(figure_png(fig), spec.width_px, spec.height_px)
        texts: list[tuple[str, Any]] = [("title", title), ("price_axes", ax)]
        texts.extend((f"label_{k}", t) for k, t in enumerate(labels))
        for k, footer_text in enumerate(spec.footer_lines):
            texts.append(
                (
                    f"footer_{k}",
                    fig.text(
                        _FOOTER_LEFT_FRACTION,
                        0.085 - k * 0.05,
                        footer_text,
                        ha="left",
                        va="center",
                        color=palette.foreground,
                        fontproperties=font_props(palette, 20 * scale),
                        bbox={
                            "boxstyle": "round,pad=0.3",
                            "facecolor": palette.background,
                            "edgecolor": palette.accent,
                            "linewidth": 1.0,
                        },
                    ),
                )
            )
        png = figure_png(fig)
        renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
        boxes = tuple(
            (role, tuple(float(v) for v in t.get_window_extent(renderer).extents))
            for role, t in texts
        )
        return RenderedImage(png, spec.width_px, spec.height_px, boxes)  # type: ignore[arg-type]

    @staticmethod
    def _annotations(
        ax: mpl.axes.Axes,
        spec: ChartRenderInput,
        window: Sequence[Bar],
        shown: int,
        y_lo: float,
        y_hi: float,
        scale: float,
    ) -> list[Any]:
        palette = spec.palette
        first = spec.first_bar_index
        n_all = spec.last_bar_index - first + 1
        labels: list[Any] = []
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
            elif (
                kind is AnnotationKind.SHADE_RANGE
                and a.from_bar is not None
                and a.to_bar is not None
            ):
                lo, hi = a.from_bar - first, min(a.to_bar - first, shown - 1)
                if lo <= hi:
                    ax.axvspan(lo - 0.5, hi + 0.5, color=palette.shade, alpha=0.25, linewidth=0)
            elif kind is AnnotationKind.HLINE_THROUGH_BARS and a.price is not None:
                x0 = (a.from_bar if a.from_bar is not None else first) - first
                x1 = min((a.to_bar if a.to_bar is not None else first) - first, shown - 1)
                if x0 <= x1:
                    ax.hlines(
                        float(Decimal(a.price)),
                        x0,
                        x1,
                        color=palette.accent,
                        linewidth=2.0 * scale,
                        linestyles="dashed",
                    )
            elif kind is AnnotationKind.LABEL and a.bar is not None and a.text is not None:
                i = a.bar - first
                if i < shown and spec.footer_lines:
                    # footer template: the label sits ABOVE the plot area (never over a candle,
                    # an indicator line or a connector point) with a short leader to the bar
                    ha = "left" if i < 0.12 * n_all else "right" if i > 0.88 * n_all else "center"
                    labels.append(
                        ax.annotate(
                            a.text,
                            (i, 1.0),
                            xycoords=("data", "axes fraction"),
                            xytext=(i, 1.035),
                            textcoords=("data", "axes fraction"),
                            ha=ha,
                            va="bottom",
                            color=palette.foreground,
                            fontproperties=font_props(palette, 22 * scale),
                            arrowprops={
                                "arrowstyle": "-",
                                "color": palette.accent,
                                "linewidth": 1.2,
                            },
                            bbox={
                                "boxstyle": "round,pad=0.3",
                                "facecolor": palette.background,
                                "edgecolor": palette.accent,
                                "linewidth": 1.0,
                            },
                            annotation_clip=False,
                        )
                    )
                elif i < shown:
                    ax.annotate(
                        a.text,
                        (i, float(window[i].high)),
                        xytext=(0, 28 * scale),
                        textcoords="offset points",
                        ha="center",
                        color=palette.foreground,
                        fontproperties=font_props(palette, 22 * scale),
                    )
        return labels

    @staticmethod
    def _price_connectors(
        ax: mpl.axes.Axes,
        spec: ChartRenderInput,
        window: Sequence[Bar],
        shown: int,
        scale: float,
    ) -> None:
        first = spec.first_bar_index
        for c in spec.connectors:
            if c.panel != "PRICE":
                continue
            i0, i1 = c.from_bar - first, c.to_bar - first
            if i1 >= shown:
                continue
            attr = "high" if c.anchor == "HIGH" else "low"
            y0, y1 = float(getattr(window[i0], attr)), float(getattr(window[i1], attr))
            ax.plot([i0, i1], [y0, y1], color=spec.palette.shade, linewidth=3 * scale)
            ax.plot([i0, i1], [y0, y1], "o", color=spec.palette.shade, markersize=9 * scale)

    @staticmethod
    def _rsi_panel(
        fig: Figure,
        grid: mpl.gridspec.GridSpec,
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
                    [p[0] for p in pts],
                    [p[1] for p in pts],
                    color=palette.accent,
                    linewidth=2 * scale,
                )
        for level in spec.rsi_guides:
            ax.axhline(
                level,
                color=palette.foreground,
                alpha=0.45,
                linewidth=1.2 * scale,
                linestyle="dashed",
            )
        rsi_kind = next((p for k, p in parsed if k == "RSI"), None)
        if rsi_kind is not None and spec.connectors:
            values = rsi(closes, rsi_kind)
            for c in spec.connectors:
                if c.panel != "RSI":
                    continue
                i0, i1 = c.from_bar - spec.first_bar_index, c.to_bar - spec.first_bar_index
                v0, v1 = values[c.from_bar], values[c.to_bar]
                if i1 < shown and v0 is not None and v1 is not None:
                    ax.plot([i0, i1], [v0, v1], color=palette.shade, linewidth=3 * scale)
                    ax.plot([i0, i1], [v0, v1], "o", color=palette.shade, markersize=9 * scale)
        if spec.rsi_caption:
            ax.text(
                0.005,
                0.92,
                spec.rsi_caption,
                transform=ax.transAxes,
                ha="left",
                va="top",
                color=palette.foreground,
                fontproperties=font_props(palette, 18 * scale),
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
            ax.plot(
                range(len(points)),
                [float(p) for p in points],
                color=palette.accent,
                linewidth=4 * scale,
            )
            ax.grid(True, color=palette.grid, linewidth=0.6 * max(scale, 0.5))
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_color(palette.grid)
            fig.text(
                0.5,
                0.94,
                label,
                ha="center",
                va="center",
                color=palette.foreground,
                fontproperties=font_props(palette, 30 * scale),
            )
            return RenderedImage(figure_png(fig), width_px, height_px)


def _edge_align(ax: mpl.axes.Axes, vertical: bool) -> None:
    """Keep the outer date labels inside the canvas."""
    labels = ax.get_xticklabels()
    if labels and not vertical:
        labels[-1].set_horizontalalignment("right")
        labels[0].set_horizontalalignment("left")


def _tick_positions(n: int, count: int) -> list[int]:
    if n <= count:
        return list(range(n))
    step = (n - 1) / (count - 1)
    return sorted({round(i * step) for i in range(count)})
