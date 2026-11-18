"""``ChartLagGuard`` and ``EarliestPublishDate``: price-data lag arithmetic (FIN-R9, IN-02).

Pure date arithmetic in UTC calendar days (blueprint 6.4(4)). ``data_end_date`` is the last
calendar date the last bar can cover (daily: its date; weekly: start + 6 days; monthly: start +
30 days, unless the dataset carries a period end), the largest possible span, so the guard errs
on the safe side. ``OLDER_THAN_LAG`` iff ``age_days >= lag_days``. A missing date is ``UNKNOWN``
and is treated as within the lag. Nothing here reads a clock: ``today`` is passed in.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from amw_core.enums import DataAgeVsLag
from amw_core.errors import ConfigInvalidError, InputInvalidError

SUPPORTED_TIMEFRAMES = ("1D", "1W", "1M")
_SPAN_DAYS = {"1D": 0, "1W": 6, "1M": 30}


@dataclass(frozen=True, slots=True)
class LagResult:
    data_end_date: date | None
    age_days: int | None
    data_age_vs_lag: DataAgeVsLag
    usable: bool
    earliest_publish_date: date | None


class ChartLagGuard:
    @staticmethod
    def bar_end_date(timeframe: str, last_bar_start: date, period_end: date | None) -> date:
        if period_end is not None:
            return period_end
        return last_bar_start + timedelta(days=_SPAN_DAYS[timeframe])

    @classmethod
    def classify(
        cls,
        *,
        timeframe: str,
        lag_days: int,
        platform_min_lag_days: int,
        last_bar_start: date | None,
        period_end: date | None,
        today: date,
    ) -> LagResult:
        if lag_days < platform_min_lag_days:
            raise ConfigInvalidError("price data lag is below the platform minimum")
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise InputInvalidError("unsupported chart timeframe")
        if last_bar_start is None:
            return LagResult(None, None, DataAgeVsLag.UNKNOWN, False, None)
        if last_bar_start > today:
            raise InputInvalidError("last bar is dated in the future")
        end = cls.bar_end_date(timeframe, last_bar_start, period_end)
        age = (today - end).days
        older = age >= lag_days
        return LagResult(
            end,
            age,
            DataAgeVsLag.OLDER_THAN_LAG if older else DataAgeVsLag.WITHIN_LAG,
            older,
            end + timedelta(days=lag_days),
        )


class EarliestPublishDate:
    @staticmethod
    def compute(ends: Sequence[date], lag_days: int) -> date | None:
        """Latest ``end + lag`` over the real-data charts; ``None`` without any (EP-01/02)."""
        if not ends:
            return None
        return max(ends) + timedelta(days=lag_days)
