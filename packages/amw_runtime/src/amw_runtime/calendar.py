"""NSE market calendar and the render-time guard (interface 3).

Session times and holidays are data files (``data/calendar``, research log NSE-01..NSE-03).
``render_allowed`` is False inside the guard window on trading days (IST has no DST) and fails
closed when the calendar for the date's year is missing, invalid by design or not VERIFIED.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from amw_runtime.data_files import DATA_DIR, read_json
from amw_runtime.errors import CalendarUnavailableError

SESSION_FILE = "nse_session.json"


def _hhmm(value: Any) -> time:
    try:
        hour, minute = str(value).split(":")
        return time(int(hour), int(minute))
    except ValueError:
        raise CalendarUnavailableError("session time is not HH:MM") from None


@dataclass(frozen=True)
class RenderDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class _YearData:
    holidays: frozenset[date]
    special_sessions: frozenset[date]


class MarketCalendar:
    """Config for the NSE regular equity session plus the official holiday lists."""

    def __init__(self, calendar_dir: Path | None = None) -> None:
        self._dir = calendar_dir or DATA_DIR / "calendar"
        try:
            sess = read_json(self._dir / SESSION_FILE)
            self.tz = timezone(timedelta(minutes=int(sess["timezone_offset_minutes"])))
            self.regular_open = _hhmm(sess["regular_open"])
            self.regular_close = _hhmm(sess["regular_close"])
            self.guard_start = _hhmm(sess["guard_start"])
            self.guard_end = _hhmm(sess["guard_end"])
        except ValueError, KeyError, TypeError:
            raise CalendarUnavailableError("session config missing or invalid") from None
        if not self.guard_start <= self.regular_open < self.regular_close <= self.guard_end:
            raise CalendarUnavailableError("session config is inconsistent")
        self._years: dict[int, _YearData | str] = {}

    def _year(self, year: int) -> _YearData:
        cached = self._years.get(year)
        if cached is None:
            cached = self._load_year(year)
            self._years[year] = cached
        if isinstance(cached, str):
            raise CalendarUnavailableError(cached)
        return cached

    def _load_year(self, year: int) -> _YearData | str:
        path = self._dir / f"nse_holidays_{year}.json"
        if not path.is_file():
            return f"no holiday list for {year}"
        try:
            raw = read_json(path)
            if raw.get("year") != year or raw.get("status") != "VERIFIED":
                return f"holiday list for {year} is not VERIFIED (REQUIRES REVIEW)"
            rows = raw["holidays"]
            special = raw.get("special_sessions") or []
            if not isinstance(rows, list) or not rows:
                return f"holiday list for {year} is empty"
            hol = frozenset(date.fromisoformat(r["date"]) for r in rows)
            spec = frozenset(date.fromisoformat(r["date"]) for r in special)
        except ValueError, KeyError, TypeError:
            return f"holiday list for {year} is invalid"
        if any(d.year != year for d in hol | spec):
            return f"holiday list for {year} holds a date of another year"
        return _YearData(hol, spec)

    def covers(self, year: int) -> bool:
        try:
            self._year(year)
        except CalendarUnavailableError:
            return False
        return True

    def _local(self, dt: datetime) -> datetime:
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise CalendarUnavailableError("a timezone-aware datetime is required")
        return dt.astimezone(self.tz)

    def is_trading_day(self, day: date) -> bool:
        data = self._year(day.year)
        if day in data.special_sessions:
            return True
        return day.weekday() < 5 and day not in data.holidays

    def in_regular_session(self, dt: datetime) -> bool:
        """``regular_open <= time < regular_close`` on a trading day (NSE-01: 09:15 to 15:30)."""
        local = self._local(dt)
        return self.is_trading_day(local.date()) and (
            self.regular_open <= local.time() < self.regular_close
        )

    def _day_blocked(self, day: date) -> bool:
        """A special session (e.g. Muhurat) has no recorded timing: the WHOLE day is blocked."""
        return day in self._year(day.year).special_sessions

    def check_render(self, dt: datetime) -> RenderDecision:
        """Decision for one instant. Fails closed (``allowed=False``) when the calendar cannot
        answer; a naive datetime is a programming error and raises."""
        return self.check_render_window(dt, dt)

    def check_render_window(self, start: datetime, end: datetime) -> RenderDecision:
        """The whole window [start, end] must stay clear of the guard window on every trading
        day and of every special-session day (fail closed for any year the calendar lacks)."""
        first, last = self._local(start), self._local(end)
        if last < first:
            return RenderDecision(False, "render window ends before it starts")
        day = first.date()
        while day <= last.date():
            try:
                if self._day_blocked(day):
                    return RenderDecision(False, "special market session day (timings unknown)")
                trading = self.is_trading_day(day)
            except CalendarUnavailableError as exc:
                return RenderDecision(False, f"calendar unavailable: {exc}")
            if trading:
                g_start = datetime.combine(day, self.guard_start, tzinfo=self.tz)
                g_end = datetime.combine(day, self.guard_end, tzinfo=self.tz)
                if first < g_end and last >= g_start:
                    return RenderDecision(
                        False, "inside the market-hours guard window on a trading day"
                    )
            day += timedelta(days=1)
        return RenderDecision(True, "outside the market-hours guard window")

    def render_allowed(self, dt: datetime) -> bool:
        return self.check_render(dt).allowed


def now_utc() -> datetime:
    return datetime.now(UTC)
