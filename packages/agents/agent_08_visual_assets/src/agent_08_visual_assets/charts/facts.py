"""``ChartFactsBuilder``: the ``agent_08.chart_facts`` document of a real chart (CCR-004, FR-22).

Facts ``f01`` to ``f04`` are computed by code from the dataset window only and rendered from fixed
English templates over historical numbers: no direction word, no forecast, no method wording
(FIN-R13). No model writes a fact. ``SCHEMATIC`` charts have no market data and emit nothing.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from amw_core.enums import ChartDataKind
from amw_core.errors import InputInvalidError

_UNIT_WORD = {"1D": "daily", "1W": "weekly", "1M": "monthly"}
_PCT_QUANT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class FactBar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True, slots=True)
class Fact:
    fact_id: str
    kind: str
    statement: str
    data: dict[str, object]


@dataclass(frozen=True, slots=True)
class ChartFacts:
    facts: tuple[Fact, ...]
    emit_document: bool


def _num(value: Decimal) -> str:
    return format(value, "f")


class ChartFactsBuilder:
    @staticmethod
    def build(chart_kind: ChartDataKind, timeframe: str, bars: Sequence[FactBar]) -> ChartFacts:
        if chart_kind is ChartDataKind.SCHEMATIC:
            return ChartFacts((), False)
        if not bars:
            raise InputInvalidError("a real chart needs at least one bar")
        if timeframe not in _UNIT_WORD:
            raise InputInvalidError("unsupported chart timeframe")
        first, last = bars[0], bars[-1]
        high_bar = low_bar = first  # strict comparison: the earliest bar wins on equal values
        for bar in bars[1:]:
            if bar.high > high_bar.high:
                high_bar = bar
            if bar.low < low_bar.low:
                low_bar = bar
        if first.close == 0:
            raise InputInvalidError("first close is zero: the change cannot be stated")
        pct = ((last.close - first.close) / first.close * 100).quantize(
            _PCT_QUANT, rounding=ROUND_HALF_UP
        )
        n = len(bars)
        facts = (
            Fact(
                "f01",
                "WINDOW_RANGE",
                f"The window contains {n} {_UNIT_WORD[timeframe]} bars from "
                f"{first.day.isoformat()} to {last.day.isoformat()}.",
                {"bars": n, "first_date": first.day, "last_date": last.day},
            ),
            Fact(
                "f02",
                "WINDOW_HIGH",
                f"The highest high in the window is {_num(high_bar.high)}, on the bar dated "
                f"{high_bar.day.isoformat()}.",
                {"value": _num(high_bar.high), "date": high_bar.day},
            ),
            Fact(
                "f03",
                "WINDOW_LOW",
                f"The lowest low in the window is {_num(low_bar.low)}, on the bar dated "
                f"{low_bar.day.isoformat()}.",
                {"value": _num(low_bar.low), "date": low_bar.day},
            ),
            Fact(
                "f04",
                "CLOSE_CHANGE",
                f"The close of the last bar is {_num(last.close)} against {_num(first.close)} "
                f"for the first bar, a change of {_num(pct)} percent.",
                {
                    "first_close": _num(first.close),
                    "last_close": _num(last.close),
                    "change_pct": _num(pct),
                },
            ),
        )
        return ChartFacts(facts, True)
