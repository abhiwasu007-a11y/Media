"""``Segmenter``, ``ChartIdAllocator``, ``DurationEstimator``, ``ChapterBuilder``,
``DisclaimerSlotter`` helpers (blueprint 10.6). All pure."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_05_scriptwriter.errors import ConfigInvalid
from agent_05_scriptwriter.text import split_sentences, to_fraction


@dataclass(frozen=True, slots=True)
class SegmentPart:
    text: str
    pace: str
    emotion: str


def split_segments(text: str, pace: str, emotion: str) -> tuple[list[SegmentPart], int]:
    """One sentence = one segment; both parts of a split inherit the tags. Returns the parts and
    the number of extra splits (``a05.segment_split`` counter)."""
    parts = split_sentences(text) or [text.strip()]
    return [SegmentPart(p, pace, emotion) for p in parts], len(parts) - 1


@dataclass(frozen=True, slots=True)
class ChartAllocation:
    hook_chart: str | None
    dropped: list[str]
    pool: list[str]


def allocate_charts(
    hook_charts: Mapping[str, str | None], selected: str, pool_n: int
) -> ChartAllocation:
    """The selected hook's chart is renamed to the next free ID (``chart_1``), other options'
    charts are dropped, and the pool for the sections follows."""
    own = hook_charts.get(selected)
    dropped = [k for k, v in hook_charts.items() if k != selected and v is not None]
    first = 1
    hook_chart = None
    if own is not None:
        hook_chart = f"chart_{first}"
        first += 1
    return ChartAllocation(hook_chart, dropped, [f"chart_{first + i}" for i in range(pool_n)])


def section_pool(start: int, count: int) -> list[str]:
    """``count`` chart IDs starting at ``chart_<start>`` for one section."""
    return [f"chart_{start + i}" for i in range(count)]


def estimate_ms(speech_chars: int, rate_cps: float | None, pause_ms: int) -> int | None:
    """``round(speech_chars / rate x 1000) + deliberate_pause_ms``; ``None`` without a rate."""
    if rate_cps is None:
        return None
    return round(speech_chars / to_fraction(rate_cps) * 1000) + pause_ms


def chapter_starts(section_ms: Sequence[int | None]) -> list[int | None]:
    """First chapter at 0 ms always; later starts are cumulative estimates or ``None``."""
    starts: list[int | None] = []
    running: int | None = 0
    for duration in section_ms:
        starts.append(running)
        running = None if running is None or duration is None else running + duration
    return starts


@dataclass(frozen=True, slots=True)
class DisclaimerTemplate:
    ref: str
    version: str
    text: str


def disclaimer_plan(
    *,
    category: str,
    required_categories: frozenset[str],
    template: DisclaimerTemplate | None,
    placements: Sequence[str],
) -> list[str]:
    """Placements to fill: none for a non-finance category; ``ConfigInvalid`` when a category that
    needs a disclaimer has no owner-approved template for the language."""
    if category not in required_categories:
        return []
    if template is None:
        raise ConfigInvalid("no disclaimer template for the channel category and language")
    return list(placements)
