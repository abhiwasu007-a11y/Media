"""Heavy-work guard and self-drain timer (blueprint 10 section 6.4; F-04, F-47; ADR-012).

D1 and CCR-056 apply.

The guard applies to every ``HEAVY_CPU`` task of this agent (render, subtitles, technical QC) on
every placement: no unit starts inside a market window, and a running unit is stopped (checkpoint,
never a kill mid-write of a final blob) before the next market window opens. The calendar and the
night window are operational configuration; with no calendar configured the guard FAILS CLOSED
(``PERMANENT.CONFIG_INVALID``), it never defaults to "allowed".

Pure functions here use minute granularity: ``now`` is floored to the minute, the unit estimate is
rounded up to whole minutes (conservative on both sides). Window intervals are half-open.
"""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from agent_10_video_editor.config import (
    GuardConfig,
    MarketWindow,
    NightWindow,
    Placement,
    Weekday,
)
from agent_10_video_editor.errors import config_invalid

_WEEKDAYS: tuple[Weekday, ...] = tuple(Weekday)
_DAY = 1440
_WEEK = 7 * _DAY


class GuardReason(StrEnum):
    DRAIN = "DRAIN"
    MARKET_HOURS = "MARKET_HOURS"
    OUTSIDE_NIGHT_WINDOW = "OUTSIDE_NIGHT_WINDOW"
    NIGHT_WINDOW_END = "NIGHT_WINDOW_END"


@dataclass(frozen=True, slots=True)
class LocalTime:
    """A local wall-clock instant at minute granularity: weekday plus minute of day."""

    weekday: Weekday
    minute_of_day: int

    @property
    def week_minute(self) -> int:
        return _WEEKDAYS.index(self.weekday) * _DAY + self.minute_of_day

    @staticmethod
    def from_week_minute(value: int) -> LocalTime:
        value %= _WEEK
        return LocalTime(_WEEKDAYS[value // _DAY], value % _DAY)

    @staticmethod
    def parse(weekday: str, hhmm: str) -> LocalTime:
        hours, minutes = hhmm.split(":")
        return LocalTime(Weekday(weekday), int(hours) * 60 + int(minutes))

    @property
    def hhmm(self) -> str:
        return f"{self.minute_of_day // 60:02d}:{self.minute_of_day % 60:02d}"


def minutes_until(now: LocalTime, later: LocalTime) -> int:
    """Whole minutes from ``now`` to ``later`` (0 when equal, wrapping over the week)."""
    return (later.week_minute - now.week_minute) % _WEEK


@dataclass(frozen=True, slots=True)
class GuardResult:
    allowed: bool
    reason: GuardReason | None


@runtime_checkable
class AdmissionProbe(Protocol):
    """Clock, drain flag and placement, injected by the worker (no module reads them directly)."""

    def now_local(self) -> LocalTime: ...

    def drain_flag(self) -> bool: ...

    def placement(self) -> Placement: ...


def _calendar(guard: GuardConfig) -> tuple[MarketWindow, ...]:
    if not guard.market_windows:
        raise config_invalid("NO_MARKET_CALENDAR")
    return guard.market_windows


def _window_spans(windows: Sequence[MarketWindow]) -> list[tuple[int, int]]:
    """Absolute week-minute spans of every window for the previous, this and the next week."""
    spans: list[tuple[int, int]] = []
    for week in (-1, 0, 1):
        for window in windows:
            base = week * _WEEK + _WEEKDAYS.index(window.weekday) * _DAY
            spans.append((base + window.start_min, base + window.end_min))
    return sorted(spans)


def _ceil_minutes(ms: int) -> int:
    return max(0, -(-ms // 60_000))


class HeavyWorkGuard:
    """F-04: the same function serves a render segment, a QC group or an evidence pass."""

    @staticmethod
    def may_start_segment(
        now_local: LocalTime,
        est_segment_ms: int,
        placement: Placement,
        drain_flag: bool,
        guard: GuardConfig,
    ) -> GuardResult:
        if drain_flag:
            return GuardResult(False, GuardReason.DRAIN)
        windows = _calendar(guard)
        now = now_local.week_minute
        end = now + _ceil_minutes(est_segment_ms)
        probe_end = max(end, now + 1)
        for start, stop in _window_spans(windows):
            if now < stop and start < probe_end:
                return GuardResult(False, GuardReason.MARKET_HOURS)
        if placement is Placement.VPS:
            night = _night(guard)
            minute = now_local.minute_of_day
            if not night.start_min <= minute < night.end_min:
                return GuardResult(False, GuardReason.OUTSIDE_NIGHT_WINDOW)
            limit = night.end_min - _ceil_minutes(night.grace_ms)
            if minute + _ceil_minutes(est_segment_ms) > limit:
                return GuardResult(False, GuardReason.NIGHT_WINDOW_END)
        return GuardResult(True, None)


def _night(guard: GuardConfig) -> NightWindow:
    if guard.night_window is None:
        raise config_invalid("NO_NIGHT_WINDOW")
    return guard.night_window


class SelfDrainTimer:
    """F-47: ``act_by`` is the earlier of the next market-window start and (VPS) ``07:00 - grace``.

    ``act_by(...)`` is pure. ``arm`` starts a one-shot timer through the injected ``TimerFactory``
    which sets the ``DrainSignal`` at ``act_by``; the signal is independent of admission and of any
    external ``DRAIN`` control (FI-13).
    """

    @staticmethod
    def act_by(now_local: LocalTime, placement: Placement, guard: GuardConfig) -> LocalTime:
        windows = _calendar(guard)
        now = now_local.week_minute
        candidates: list[int] = []
        for start, stop in _window_spans(windows):
            if start <= now < stop:
                candidates.append(now)  # already inside a window: drain immediately
            elif start > now:
                candidates.append(start)
        result = min(candidates)
        if placement is Placement.VPS:
            night = _night(guard)
            drain_point = (now // _DAY) * _DAY + night.end_min - _ceil_minutes(night.grace_ms)
            in_night = night.start_min <= now_local.minute_of_day < night.end_min
            # inside the grace zone drain_point is in the past: act now, never wrap to next week
            result = min(result, max(drain_point, now) if in_night else now)
        return LocalTime.from_week_minute(result)

    @staticmethod
    def delay_ms(now_local: LocalTime, act_by: LocalTime) -> int:
        return minutes_until(now_local, act_by) * 60_000


class DrainSignal:
    """Thread-safe flags: ``drain`` (checkpoint at the next safe point) and ``hard_stop``.

    ``hard_stop`` is set by the self-drain timer at ``act_by``: a running FFmpeg process is then
    terminated (SIGTERM), its scratch ``.part`` discarded and the task checkpoints before the
    window opens. Final blobs are never written in a way a stop can interrupt (atomic put).
    """

    def __init__(self) -> None:
        self._drain = threading.Event()
        self._hard = threading.Event()
        self.self_drained = False

    def request_drain(self) -> None:
        self._drain.set()

    def fire_self_drain(self) -> None:
        self.self_drained = True
        self._drain.set()
        self._hard.set()

    def hard_stop(self) -> None:
        self._hard.set()

    @property
    def drain_requested(self) -> bool:
        return self._drain.is_set()

    @property
    def hard_stop_requested(self) -> bool:
        return self._hard.is_set()


class TimerHandle(Protocol):
    def cancel(self) -> None: ...


class TimerFactory(Protocol):
    def start(self, delay_ms: int, callback: Callable[[], None]) -> TimerHandle: ...


class ThreadTimerFactory:
    """Production timer: ``threading.Timer`` daemon threads."""

    def start(self, delay_ms: int, callback: Callable[[], None]) -> TimerHandle:
        timer = threading.Timer(delay_ms / 1000, callback)
        timer.daemon = True
        timer.start()
        return timer


class HeavyTaskGuard:
    """Runtime wrapper used by the three stages: counters, probe, signal and the armed timer."""

    def __init__(
        self,
        guard: GuardConfig,
        probe: AdmissionProbe,
        signal: DrainSignal,
        timers: TimerFactory,
    ) -> None:
        self._guard = guard
        self._probe = probe
        self.signal = signal
        self._timers = timers
        self._handle: TimerHandle | None = None
        self.market_hours_checks = 0
        self.night_window_checks = 0
        self.act_by: LocalTime | None = None

    def arm(self) -> LocalTime:
        """Arm the self-drain timer at task start (fails closed without a calendar)."""
        now = self._probe.now_local()
        placement = self._probe.placement()
        act_by = SelfDrainTimer.act_by(now, placement, self._guard)
        self.act_by = act_by
        self._handle = self._timers.start(
            SelfDrainTimer.delay_ms(now, act_by), self.signal.fire_self_drain
        )
        return act_by

    def disarm(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def check(self, est_ms: int) -> GuardResult:
        """Guard a unit of ``est_ms`` (segment, mux, QC group, evidence pass)."""
        placement = self._probe.placement()
        self.market_hours_checks += 1
        if placement is Placement.VPS:
            self.night_window_checks += 1
        drain = self._probe.drain_flag() or self.signal.drain_requested
        result = HeavyWorkGuard.may_start_segment(
            self._probe.now_local(), est_ms, placement, drain, self._guard
        )
        if self.act_by is not None and result.allowed:
            now = self._probe.now_local()
            if minutes_until(now, self.act_by) < _ceil_minutes(est_ms):
                return GuardResult(False, GuardReason.MARKET_HOURS)
        return result

    def estimate_overruns(self, est_ms: int) -> bool:
        """True when a unit that is already running cannot finish before ``act_by``."""
        if self.act_by is None:
            return False
        return minutes_until(self._probe.now_local(), self.act_by) < _ceil_minutes(est_ms)
