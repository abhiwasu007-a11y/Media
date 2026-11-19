"""Chart-data policy (interface 4): chart data comes ONLY from the course data_pack, whose
location is a pointer outside git (the private store). This module never reads that location.

The lag rule is the SEBI 30-day price-data lag (IN-02, FIN-R9). The arithmetic is agent 06's
``classify`` (``as_of - last_bar >= lag_days``); an unknown bar date is refused (fail closed).
"""

from dataclasses import dataclass
from datetime import date

from agent_06_fact_checker.models import DataAge
from agent_06_fact_checker.price_age import classify
from amw_core.errors import ConfigInvalidError
from amw_runtime.config import DEFAULT_CONFIG_FILE, RuntimeConfig
from amw_runtime.data_files import read_json
from amw_runtime.errors import BarsTooRecentError, ChartSourceRefusedError


def _packaged_lag_days() -> int:
    try:
        return int(read_json(DEFAULT_CONFIG_FILE)["price_data_lag"]["days"])
    except ValueError, KeyError, TypeError:
        raise ConfigInvalidError("price_data_lag.days missing in the runtime config") from None


def assert_bars_older_than_lag(
    last_bar_date: date | None, as_of: date, *, lag_days: int | None = None
) -> None:
    """Raise ``BarsTooRecentError`` unless ``as_of - last_bar_date >= lag_days`` (config data,
    30 days from IN-02, unless a caller passes the loaded config value)."""
    lag = _packaged_lag_days() if lag_days is None else lag_days
    if last_bar_date is not None and last_bar_date > as_of:
        raise BarsTooRecentError("last bar date is after the publish/extraction date")
    if classify(last_bar_date, as_of, lag) is not DataAge.OLDER_THAN_LAG:
        raise BarsTooRecentError(
            "chart bars are not older than the SEBI price-data lag (or their date is unknown)"
        )


@dataclass(frozen=True)
class ChartDataPolicy:
    source_kind: str
    location: str | None
    lag_days: int

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> ChartDataPolicy:
        return cls(
            config.chart_data_source_kind, config.chart_data_location, config.price_data_lag_days
        )

    def require_source(self, source_kind: str) -> None:
        if source_kind != self.source_kind:
            raise ChartSourceRefusedError("chart data may come only from the course data_pack")

    def assert_bars_older_than_lag(self, last_bar_date: date | None, as_of: date) -> None:
        assert_bars_older_than_lag(last_bar_date, as_of, lag_days=self.lag_days)
