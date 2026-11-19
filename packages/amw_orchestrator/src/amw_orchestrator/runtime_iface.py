"""Bridge to lane S4's ``amw_runtime`` (runtime config, preflight, market calendar, disclaimer).

While S4's package is not merged, clearly named LOCAL STAND-INS with the agreed signatures are
used, and ``SOURCE`` says so. The stand-ins hold no owner value of their own: caps come from the
environment mapping the caller passes, and the calendar stand-in only knows the weekday rule and
the regular-session clock window (NSE holidays are not modelled: REQUIRES REVIEW (S4)).
"""

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from amw_core.errors import ConfigInvalidError


class Calendar(Protocol):
    def render_allowed(self, dt: datetime) -> bool: ...


@dataclass(frozen=True, slots=True)
class StandInConfig:
    per_video_cap_micros_usd: int
    pilot_cap_micros_usd: int
    secret_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StandInDisclaimer:
    text: str
    version: str
    status: str = "DRAFT – not lawyer-approved"  # noqa: RUF001 (owner-set label)


class TestCalendarFixture:
    """TEST CALENDAR FIXTURE (not S4's calendar): render is refused Monday-Friday inside the
    regular NSE equity session window, Asia/Kolkata. Holidays are not modelled."""

    zone = ZoneInfo("Asia/Kolkata")
    open_, close = time(9, 0), time(15, 45)

    def render_allowed(self, dt: datetime) -> bool:
        local = dt.astimezone(self.zone)
        if local.weekday() >= 5:
            return True
        return not (self.open_ <= local.time() <= self.close)


def _runtime(module: str) -> Any | None:
    try:
        return importlib.import_module(f"amw_runtime.{module}")
    except ModuleNotFoundError:
        return None


def source() -> str:
    return "amw_runtime (S4)" if _runtime("config") is not None else "LOCAL STAND-IN (S4 pending)"


def load_runtime_config(env: Mapping[str, str]) -> Any:
    mod = _runtime("config")
    if mod is not None:
        return mod.load_runtime_config(env)
    try:
        return StandInConfig(
            per_video_cap_micros_usd=int(env["AMW_PER_VIDEO_CAP_MICROS_USD"]),
            pilot_cap_micros_usd=int(env["AMW_PILOT_CAP_MICROS_USD"]),
        )
    except KeyError, ValueError:
        raise ConfigInvalidError(
            "budget caps are not configured: no spend without a limit"
        ) from None


def market_calendar() -> Calendar:
    mod = _runtime("calendar")
    if mod is not None:
        cal: Calendar = mod.MarketCalendar()
        return cal
    return TestCalendarFixture()


def get_disclaimer(version: str) -> Any:
    mod = _runtime("disclaimer")
    if mod is not None:
        return mod.get_disclaimer(version)
    return StandInDisclaimer(
        text="हा व्हिडिओ केवळ शैक्षणिक आहे (PLUMBING TEST), गुंतवणूक सल्ला नाही.", version=version
    )
