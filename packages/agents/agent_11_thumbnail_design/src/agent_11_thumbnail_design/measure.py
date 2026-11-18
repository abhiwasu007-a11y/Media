"""Pure measurements: text fit (F-13), contrast ratio (F-15), perceptual-hash distance (F-16)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from agent_11_thumbnail_design.errors import TextDoesNotFitError


class TextMetrics(Protocol):
    def text_width(self, line: str, font_px: int) -> float: ...
    def line_height(self, font_px: int) -> float: ...


@dataclass(frozen=True, slots=True)
class FixtureMetrics:
    """Test metrics: every character advances ``advance_em``; line height is ``line_height_em``."""

    advance_em: float
    line_height_em: float

    def text_width(self, line: str, font_px: int) -> float:
        return len(line) * self.advance_em * font_px

    def line_height(self, font_px: int) -> float:
        return self.line_height_em * font_px


@dataclass(frozen=True, slots=True)
class FitResult:
    font_px: int
    text_w_px: float
    text_h_px: float


def fit_text(
    lines: Sequence[str],
    lines_max: int,
    box_w: float,
    box_h: float,
    metrics: TextMetrics,
    max_font_px: int,
    min_font_px: int,
    font_step_px: int,
) -> FitResult:
    """Largest font from max to min (by step) whose lines fit the box; else TextDoesNotFit."""
    if not lines or len(lines) > lines_max or font_step_px < 1:
        raise TextDoesNotFitError("line count outside the template limit")
    size = max_font_px
    while size >= min_font_px:
        width = max(metrics.text_width(line, size) for line in lines)
        height = metrics.line_height(size) * len(lines)
        if width <= box_w and height <= box_h:
            return FitResult(size, round(width, 4), round(height, 4))
        size -= font_step_px
    raise TextDoesNotFitError("text does not fit at the minimum font size")


def _linear(c: int) -> float:
    v = c / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: Sequence[int]) -> float:
    r, g, b = (_linear(int(c)) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: Sequence[int], bg: Sequence[int]) -> float:
    """Relative-luminance contrast ratio, rounded to 2 decimals."""
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


def hamming_bits(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


@dataclass(frozen=True, slots=True)
class DistinctResult:
    pairs: tuple[tuple[tuple[int, int], int], ...]
    verdict: str


def distinctness(hashes: Sequence[str], min_bits: int) -> DistinctResult:
    pairs = tuple(
        ((i + 1, j + 1), hamming_bits(hashes[i], hashes[j]))
        for i in range(len(hashes))
        for j in range(i + 1, len(hashes))
    )
    return DistinctResult(pairs, "PASS" if all(bits >= min_bits for _, bits in pairs) else "FAIL")
