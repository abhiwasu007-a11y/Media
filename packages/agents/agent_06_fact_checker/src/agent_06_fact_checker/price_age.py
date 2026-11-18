"""D0: price-data age classification (FIN-R9, IN-02; blueprint 10.2 ``PriceDataAge``).

Pure date arithmetic; the model never does it. The lag comes from
``compliance.finance_sebi_in.price_data_lag_days`` and is applied at the date handed in (the
extraction snapshot; FIN-R9 is finally evaluated at publish time by Agent 16 and again after the
chart is sourced, the stricter result wins).
"""

from collections.abc import Mapping
from datetime import date

from agent_06_fact_checker.models import ChartDataRef, DataAge, DataAgeBasis
from amw_core.errors import ConfigInvalidError

_STRICTNESS = {DataAge.OLDER_THAN_LAG: 0, DataAge.WITHIN_LAG: 1, DataAge.UNKNOWN: 1}
SUPPORTED_LAG_UNIT = "CALENDAR_DAYS"


def classify(range_end: date | None, today: date, lag_days: int) -> DataAge:
    """``today - range_end >= lag_days`` is ``OLDER_THAN_LAG``; no range end is ``UNKNOWN``."""
    if lag_days < 0:
        raise ConfigInvalidError("price_data_lag_days must be >= 0")
    if range_end is None:
        return DataAge.UNKNOWN
    if (today - range_end).days >= lag_days:
        return DataAge.OLDER_THAN_LAG
    return DataAge.WITHIN_LAG


def stricter(a: DataAge | None, b: DataAge | None) -> DataAge | None:
    """The less permissive value. ``None`` (schematic chart) never overrides a measurement."""
    if a is None:
        return b
    if b is None:
        return a
    return a if _STRICTNESS[a] >= _STRICTNESS[b] else b


def resolve_chart_ages(
    refs: tuple[ChartDataRef, ...],
    range_ends: Mapping[str, date | None],
    today: date,
    lag_days: int,
    lag_unit: str = SUPPORTED_LAG_UNIT,
) -> tuple[ChartDataRef, ...]:
    """Apply D0 to every chart reference and return the references with the value to use.

    * ``CONSTRAINT`` keeps its value (the chart path must meet it, CCR-004).
    * A schematic reference (``null``) keeps ``null``: no FIN-R9 flag.
    * ``MEASURED`` is recomputed from the dataset's last bar date and the stricter of the
      supplied and the recomputed value wins. A reference whose last bar date the lookup cannot
      give is ``UNKNOWN`` (fail closed: ``UNKNOWN`` is treated as inside the lag, GLOSSARY 6.52).
    """
    if lag_unit != SUPPORTED_LAG_UNIT:
        raise ConfigInvalidError(
            "price_data_lag_unit is not supported (13 5.5 is open)", details={"unit": lag_unit}
        )
    out: list[ChartDataRef] = []
    for ref in refs:
        value = ref.data_age_vs_lag
        if ref.basis is DataAgeBasis.MEASURED and value is not None:
            value = stricter(value, classify(range_ends.get(ref.ref_id), today, lag_days))
        out.append(ref.model_copy(update={"data_age_vs_lag": value}))
    return tuple(out)


def recheck_lag_at(
    range_ends: Mapping[str, date | None],
    publish_date: date,
    lag_days: int,
    lag_unit: str = SUPPORTED_LAG_UNIT,
) -> dict[str, DataAge]:
    """FIN-R9 at *publish time* (13 5.5): for Agent 16's authorisation re-check.

    ``publish_date - last_bar >= lag_days`` for every chart, a missing last bar date is
    ``UNKNOWN``. D0 itself is a snapshot at extraction time; this function is the later
    evaluation, with the same arithmetic and the same fail-closed rule."""
    if lag_unit != SUPPORTED_LAG_UNIT:
        raise ConfigInvalidError(
            "price_data_lag_unit is not supported (13 5.5 is open)", details={"unit": lag_unit}
        )
    return {ref: classify(end, publish_date, lag_days) for ref, end in range_ends.items()}
