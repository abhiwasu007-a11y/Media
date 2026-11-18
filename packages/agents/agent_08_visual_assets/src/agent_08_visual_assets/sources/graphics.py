"""``GraphicTemplateRenderer`` (tier C graphics, FR-07): text cards, concept diagrams and the
abstract brand motion template, drawn by code with the same deterministic rasteriser as the charts.

All visible text must equal an entry of the script's ``on_screen_text`` (or a versioned template
label): anything else is ``InputInvalid`` (no invented text). The abstract template carries no words.
"""

import textwrap
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

import matplotlib as mpl
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

from amw_core.errors import InputInvalidError

from agent_08_visual_assets.charts.render import (
    BrandPalette,
    RenderedImage,
    font_props,
    new_figure,
    figure_png,
)

TEMPLATE_VERSION = 1


class GraphicKind(StrEnum):
    KINETIC_TEXT = "KINETIC_TEXT"
    TITLE_CARD = "TITLE_CARD"
    DIAGRAM = "DIAGRAM"
    ABSTRACT_MOTION = "ABSTRACT_MOTION"


@dataclass(frozen=True, slots=True)
class DiagramSpec:
    """Nodes are on-screen text entries; edges are ``(from_index, to_index)``."""

    nodes: tuple[str, ...]
    edges: tuple[tuple[int, int], ...]


def _check_text(lines: Sequence[str], allowed: Collection[str]) -> None:
    allowed_set = set(allowed)
    for line in lines:
        if line not in allowed_set:
            raise InputInvalidError("graphic text is not an entry of the on-screen text allowlist")


class GraphicTemplateRenderer:
    @staticmethod
    def render(
        *,
        kind: GraphicKind,
        lines: Sequence[str],
        allowlist: Collection[str],
        width_px: int,
        height_px: int,
        palette: BrandPalette,
        diagram: DiagramSpec | None = None,
    ) -> RenderedImage:
        scale = min(width_px, height_px) / 1080.0
        vertical = height_px > width_px
        with mpl.rc_context({"axes.unicode_minus": False, "text.hinting": "none"}):
            fig = new_figure(width_px, height_px, palette)
            ax = fig.add_axes((0, 0, 1, 1), facecolor=palette.background)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            if kind is GraphicKind.ABSTRACT_MOTION:
                if lines:
                    raise InputInvalidError("the abstract motion template carries no words")
                _abstract(ax, palette)
            elif kind is GraphicKind.DIAGRAM:
                if diagram is None or not diagram.nodes:
                    raise InputInvalidError("a diagram needs nodes")
                _check_text(diagram.nodes, allowlist)
                _diagram(ax, diagram, palette, scale, vertical)
            else:
                if not lines:
                    raise InputInvalidError("a text card needs text")
                _check_text(lines, allowlist)
                _text_card(ax, lines, palette, scale, vertical, kind is GraphicKind.TITLE_CARD)
            return RenderedImage(figure_png(fig), width_px, height_px)


def _text_card(
    ax: "mpl.axes.Axes",
    lines: Sequence[str],
    palette: BrandPalette,
    scale: float,
    vertical: bool,
    title: bool,
) -> None:
    width = 18 if vertical else 32
    wrapped = "\n".join(textwrap.fill(line, width=width) for line in lines)
    ax.add_patch(Rectangle((0.06, 0.47), 0.012, 0.06, color=palette.accent, linewidth=0))
    ax.text(
        0.5,
        0.5,
        wrapped,
        ha="center",
        va="center",
        color=palette.foreground,
        fontproperties=font_props(palette, (74 if title else 58) * scale),
        linespacing=1.3,
    )


def _diagram(
    ax: "mpl.axes.Axes", spec: DiagramSpec, palette: BrandPalette, scale: float, vertical: bool
) -> None:
    n = len(spec.nodes)
    centres: list[tuple[float, float]] = []
    for i, text in enumerate(spec.nodes):
        if vertical:
            cx, cy = 0.5, 0.85 - i * (0.7 / max(n - 1, 1)) if n > 1 else 0.5
            w, h = 0.7, 0.09
        else:
            cx, cy = (0.12 + i * (0.76 / max(n - 1, 1))) if n > 1 else 0.5, 0.5
            w, h = min(0.2, 0.7 / n), 0.2
        centres.append((cx, cy))
        ax.add_patch(
            FancyBboxPatch(
                (cx - w / 2, cy - h / 2), w, h, boxstyle="round,pad=0.01",
                facecolor=palette.shade, edgecolor=palette.accent, linewidth=3 * scale,
            )
        )  # fmt: skip
        ax.text(
            cx, cy, textwrap.fill(text, 12 if not vertical else 26), ha="center", va="center",
            color=palette.foreground, fontproperties=font_props(palette, 34 * scale),
        )  # fmt: skip
    for a, b in spec.edges:
        if not (0 <= a < n and 0 <= b < n):
            raise InputInvalidError("diagram edge refers to a missing node")
        ax.add_patch(
            FancyArrowPatch(
                centres[a], centres[b], arrowstyle="-|>", mutation_scale=30 * scale,
                color=palette.foreground, linewidth=3 * scale, shrinkA=70 * scale, shrinkB=70 * scale,
            )
        )  # fmt: skip


def _abstract(ax: "mpl.axes.Axes", palette: BrandPalette) -> None:
    for i, y in enumerate((0.25, 0.45, 0.65)):
        ax.add_patch(
            Rectangle((0.0, y), 1.0, 0.08, facecolor=palette.shade, alpha=0.18 + 0.1 * i, linewidth=0)
        )
    ax.add_patch(Rectangle((0.0, 0.0), 1.0, 0.02, facecolor=palette.accent, linewidth=0))
