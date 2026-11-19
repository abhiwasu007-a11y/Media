"""Typed refusals of the runtime package. Integrators map them to the 07 codes (config problems
use ``amw_core.errors.ConfigInvalidError`` directly)."""

from dataclasses import dataclass


class RuntimeRefusal(Exception):  # noqa: N818 (a refusal, not an error condition)
    """Base of every refusal raised by amw_runtime. Messages never contain secret values."""


@dataclass(frozen=True)
class UnmetItem:
    """One unmet preflight requirement: a stable code and a value-free explanation."""

    code: str
    message: str


class PreflightRefused(RuntimeRefusal):
    """The run must not start; ``items`` lists EVERY unmet requirement."""

    def __init__(self, items: tuple[UnmetItem, ...]) -> None:
        self.items = items
        super().__init__("preflight refused: " + "; ".join(f"{i.code}: {i.message}" for i in items))


class CalendarUnavailableError(RuntimeRefusal):
    """The market calendar is missing, invalid by design, or does not cover the date."""


class BarsTooRecentError(RuntimeRefusal):
    """A chart bar is inside the SEBI price-data lag (IN-02, FIN-R9) or its date is unknown."""


class ChartSourceRefusedError(RuntimeRefusal):
    """Chart data may come only from the course data_pack."""


class DisclaimerError(RuntimeRefusal):
    """The disclaimer template is missing, unknown or fails its hash check."""
