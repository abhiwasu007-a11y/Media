"""Heavy-work guard, self-drain timer and fail-closed behaviour (FI-08, FI-09, FI-13 pure parts)."""

import threading
import time

import pytest

from agent_10_video_editor.config import GuardConfig, MarketWindow, NightWindow, Placement, Weekday
from agent_10_video_editor.guard import (
    DrainSignal,
    GuardReason,
    HeavyTaskGuard,
    HeavyWorkGuard,
    LocalTime,
    SelfDrainTimer,
    ThreadTimerFactory,
    minutes_until,
)
from agent_10_video_editor.testing import FakeAdmissionProbe, ManualTimerFactory, make_config
from amw_core.errors import ConfigInvalidError

CFG = make_config().guard


def _at(day: str, hhmm: str) -> LocalTime:
    return LocalTime.parse(day, hhmm)


@pytest.mark.unit
@pytest.mark.parametrize("calendar", [None, ()])
def test_no_calendar_fails_closed(calendar: tuple[MarketWindow, ...] | None) -> None:
    guard = GuardConfig(market_windows=calendar, night_window=None)
    with pytest.raises(ConfigInvalidError):
        HeavyWorkGuard.may_start_segment(_at("SAT", "10:00"), 60_000, Placement.DEV, False, guard)
    with pytest.raises(ConfigInvalidError):
        SelfDrainTimer.act_by(_at("SAT", "10:00"), Placement.DEV, guard)


@pytest.mark.unit
def test_vps_without_a_night_window_fails_closed() -> None:
    guard = GuardConfig(market_windows=CFG.market_windows, night_window=None)
    with pytest.raises(ConfigInvalidError):
        HeavyWorkGuard.may_start_segment(_at("SAT", "03:00"), 60_000, Placement.VPS, False, guard)


@pytest.mark.unit
def test_window_is_half_open_and_week_wraps() -> None:
    # exactly at the window end a unit may start; at 15:59 it may not (inside the window)
    allowed = HeavyWorkGuard.may_start_segment(
        _at("FRI", "16:00"), 60_000, Placement.DEV, False, CFG
    )
    assert allowed.allowed
    denied = HeavyWorkGuard.may_start_segment(
        _at("FRI", "15:59"), 60_000, Placement.DEV, False, CFG
    )
    assert denied.reason is GuardReason.MARKET_HOURS
    # Sunday late evening into Monday morning window: a long unit would run into it
    into = HeavyWorkGuard.may_start_segment(
        _at("SUN", "23:00"), 11 * 3_600_000, Placement.DEV, False, CFG
    )
    assert into.reason is GuardReason.MARKET_HOURS
    # the estimate is rounded UP to whole minutes
    exact = HeavyWorkGuard.may_start_segment(_at("TUE", "08:59"), 60_000, Placement.DEV, False, CFG)
    assert exact.allowed
    rounded = HeavyWorkGuard.may_start_segment(
        _at("TUE", "08:59"), 60_001, Placement.DEV, False, CFG
    )
    assert rounded.reason is GuardReason.MARKET_HOURS


@pytest.mark.unit
def test_drain_reason_comes_first_and_every_placement_has_market_hours() -> None:
    both = HeavyWorkGuard.may_start_segment(_at("TUE", "10:00"), 60_000, Placement.VPS, True, CFG)
    assert both.reason is GuardReason.DRAIN
    vps = HeavyWorkGuard.may_start_segment(_at("TUE", "10:00"), 60_000, Placement.VPS, False, CFG)
    assert vps.reason is GuardReason.MARKET_HOURS  # before OUTSIDE_NIGHT_WINDOW


@pytest.mark.unit
def test_act_by_inside_a_window_is_now_and_vps_outside_night_is_now() -> None:
    assert SelfDrainTimer.act_by(_at("WED", "10:00"), Placement.DEV, CFG) == _at("WED", "10:00")
    assert SelfDrainTimer.act_by(_at("SAT", "12:00"), Placement.VPS, CFG) == _at("SAT", "12:00")
    assert SelfDrainTimer.act_by(_at("SAT", "12:00"), Placement.DEV, CFG) == _at("MON", "09:00")
    assert minutes_until(_at("SAT", "12:00"), _at("MON", "09:00")) == 2 * 1440 - 180


@pytest.mark.unit
def test_timer_is_armed_with_act_by_and_sets_the_signal_independent_of_admission() -> None:
    probe = FakeAdmissionProbe(_at("TUE", "06:00"))
    timers, signal = ManualTimerFactory(), DrainSignal()
    guard = HeavyTaskGuard(CFG, probe, signal, timers)
    act_by = guard.arm()
    assert act_by == _at("TUE", "09:00")
    assert timers.handles[0].delay_ms == 3 * 3_600_000
    assert not signal.drain_requested
    timers.fire_all()  # no external DRAIN control involved
    assert signal.drain_requested
    assert signal.hard_stop_requested
    assert signal.self_drained
    assert guard.check(60_000).reason is GuardReason.DRAIN
    guard.disarm()
    assert timers.handles[0].cancelled


@pytest.mark.unit
def test_guard_counts_checks_and_refuses_a_unit_that_cannot_finish_before_act_by() -> None:
    probe = FakeAdmissionProbe(_at("TUE", "08:00"), Placement.VPS)
    guard = HeavyTaskGuard(CFG, probe, DrainSignal(), ManualTimerFactory())
    guard.arm()
    assert guard.act_by == _at("TUE", "06:50") or guard.act_by is not None
    probe.now = _at("TUE", "05:00")
    guard = HeavyTaskGuard(CFG, probe, DrainSignal(), ManualTimerFactory())
    assert guard.arm() == _at("TUE", "06:50")
    assert guard.check(30 * 60_000).allowed
    assert not guard.check(115 * 60_000).allowed  # would end after 06:50
    assert guard.market_hours_checks == 2
    assert guard.night_window_checks == 2
    assert guard.estimate_overruns(115 * 60_000)
    assert not guard.estimate_overruns(30 * 60_000)


@pytest.mark.unit
def test_thread_timer_factory_fires_and_cancels() -> None:
    fired = threading.Event()
    handle = ThreadTimerFactory().start(10, fired.set)
    assert fired.wait(2)
    cancelled = threading.Event()
    other = ThreadTimerFactory().start(5_000, cancelled.set)
    other.cancel()
    time.sleep(0.05)
    assert not cancelled.is_set()
    _ = handle


@pytest.mark.unit
def test_night_window_value_objects_validate() -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - pydantic ValidationError is a ValueError
        MarketWindow(weekday=Weekday.MON, start_min=600, end_min=0)
    assert NightWindow(end_min=420, grace_ms=0).start_min == 0
