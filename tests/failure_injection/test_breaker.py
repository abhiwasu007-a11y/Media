"""07 section 12: breaker open / half-open / close (pure state machine of 07 section 4.3)."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from amw_core.config import BreakerSettings
from amw_core.enums import CircuitState, EscalationLevel
from amw_core.errors import ConfigInvalidError
from amw_core.interfaces.system_functions import BreakerKey
from amw_core.retries import admit, record
from amw_core.retries.breaker import (
    BreakerRow,
    counts_as_failure,
    escalation_for,
    new_row,
    open_duration_ms,
)
from tests.core_services.support import T0

pytestmark = pytest.mark.failure_injection
KEY = BreakerKey("llm_provider", "llm.completion", "platform")
CFG = BreakerSettings(half_open_probe_timeout_ms=5_000)
NET = "TEMPORARY.NETWORK"


def _ms(n: int) -> timedelta:
    return timedelta(milliseconds=n)


def test_counted_codes_are_the_07_yes_rows() -> None:
    assert counts_as_failure("TEMPORARY.UPSTREAM_5XX")
    assert counts_as_failure("PUBLISHING.OAUTH_REFRESH_FAILED")
    assert not counts_as_failure("PERMANENT.INPUT_INVALID")  # bad input never opens a breaker
    assert not counts_as_failure("AGENT.CRASH")
    assert not counts_as_failure(None)
    assert not counts_as_failure("X.UNKNOWN")


def test_consecutive_failures_open_then_half_open_then_close() -> None:
    row = new_row(KEY, T0)
    for i in range(4):
        row = record(row, False, NET, T0 + _ms(i), CFG)
        assert row.state is CircuitState.CLOSED
    row = record(row, False, NET, T0 + _ms(5), CFG)
    assert row.state is CircuitState.OPEN
    assert row.open_count == 1
    assert row.open_until == T0 + _ms(5) + _ms(30_000)
    # OPEN: calls rejected without network I/O (NO_ATTEMPT)
    assert not admit(row, T0 + _ms(1_000), CFG).allowed
    # first check at/after open_until -> HALF_OPEN with one probe
    assert row.open_until is not None
    probe = admit(row, row.open_until, CFG)
    assert probe.allowed
    assert probe.probe
    assert probe.row.state is CircuitState.HALF_OPEN
    assert not admit(probe.row, row.open_until, CFG).allowed
    row = record(probe.row, True, None, row.open_until, CFG)
    assert row.state is CircuitState.HALF_OPEN
    assert row.window_calls == 1
    row = record(admit(row, row.window_started_at, CFG).row, True, None, row.window_started_at, CFG)
    assert row.state is CircuitState.CLOSED
    assert row.open_count == 0
    assert row.open_until is None


def test_failure_ratio_opens_within_the_window() -> None:
    row = new_row(KEY, T0)
    outcomes = [True, False, True, False, False]  # 3/5 failures >= 0.5
    for i, ok in enumerate(outcomes):
        row = record(row, ok, None if ok else NET, T0 + _ms(i), CFG)
    assert row.state is CircuitState.OPEN


def test_window_restarts_after_window_ms() -> None:
    row = new_row(KEY, T0)
    for i in range(4):
        row = record(row, i % 2 == 0, None if i % 2 == 0 else NET, T0 + _ms(i), CFG)
    row = record(row, False, NET, T0 + _ms(60_001), CFG)
    assert row.state is CircuitState.CLOSED
    assert row.window_calls == 1


def test_probe_failure_reopens_with_doubled_duration_up_to_the_maximum() -> None:
    row = new_row(KEY, T0)
    for _i in range(5):
        row = record(row, False, NET, T0, CFG)
    durations = []
    now = T0
    for _ in range(8):
        assert row.open_until is not None
        durations.append(row.open_until - now)
        now = row.open_until
        row = record(admit(row, now, CFG).row, False, NET, now, CFG)
        assert row.state is CircuitState.OPEN
    assert [d.total_seconds() for d in durations[:6]] == [30, 60, 120, 240, 480, 900]
    assert all(d.total_seconds() == 900 for d in durations[5:])
    assert escalation_for(row, now, CFG) is EscalationLevel.L2  # open > open_ms_max in total
    assert escalation_for(new_row(KEY, T0), T0, CFG) is EscalationLevel.L1


def test_neutral_failures_never_open_and_do_not_break_a_streak() -> None:
    row = new_row(KEY, T0)
    for _ in range(20):
        row = record(row, False, "PERMANENT.SCHEMA_INVALID", T0, CFG)
    assert row.state is CircuitState.CLOSED
    assert row.window_failures == 0
    row = replace(row, consecutive_failures=4)
    row = record(row, False, "AGENT.CRASH", T0, CFG)
    assert row.consecutive_failures == 4


def test_half_open_neutral_failure_changes_nothing() -> None:
    row = new_row(KEY, T0)
    for _ in range(5):
        row = record(row, False, NET, T0, CFG)
    t = row.open_until
    assert t is not None
    row = record(admit(row, t, CFG).row, True, None, t, CFG)
    row = record(admit(row, t, CFG).row, False, "PERMANENT.PROVIDER_REFUSAL", t, CFG)
    assert row.state is CircuitState.HALF_OPEN
    assert row.window_calls == 1  # an uncounted failure is not a provider fault: no change


def test_late_result_while_open_changes_nothing() -> None:
    row = new_row(KEY, T0)
    for _ in range(5):
        row = record(row, False, NET, T0, CFG)
    late = record(row, False, "TEMPORARY.TIMEOUT", T0 + _ms(10), CFG)
    assert late.state is CircuitState.OPEN
    assert late.open_until == row.open_until
    assert late == row
    # a result recorded after open_until is treated as the first probe outcome
    assert row.open_until is not None
    after = record(row, True, None, row.open_until + _ms(1), CFG)
    assert after.state is CircuitState.HALF_OPEN
    assert after.window_calls == 1


def test_open_duration_formula() -> None:
    assert [open_duration_ms(n, CFG) for n in range(7)] == [
        30_000,
        60_000,
        120_000,
        240_000,
        480_000,
        900_000,
        900_000,
    ]
    assert open_duration_ms(10_000, CFG) == 900_000


def _half_open_with_a_probe() -> tuple[BreakerRow, datetime]:
    row = new_row(KEY, T0)
    for _ in range(5):
        row = record(row, False, NET, T0, CFG)
    assert row.open_until is not None
    t = row.open_until
    probe = admit(row, t, CFG)
    assert probe.allowed
    assert probe.probe
    return probe.row, t


def test_a_probe_that_never_reports_is_reclaimed_after_its_lease() -> None:
    """Re-review N1: a crash after admission must not wedge HALF_OPEN for good."""
    row, t = _half_open_with_a_probe()
    assert row.half_open_in_flight == 1
    assert not admit(row, t + _ms(4_999), CFG).allowed  # lease still running
    again = admit(row, t + _ms(5_001), CFG)
    assert again.allowed
    assert again.probe
    assert again.row.half_open_in_flight == 1
    assert again.row.half_open_probe_until == t + _ms(5_001) + _ms(5_000)


def test_probe_timeout_is_required_configuration() -> None:
    row, t = _half_open_with_a_probe()
    with pytest.raises(ConfigInvalidError):
        admit(replace(row, half_open_in_flight=0), t, BreakerSettings())


def test_a_late_result_of_a_call_admitted_before_the_breaker_opened_frees_no_probe() -> None:
    """Re-review m-a: only a call admitted as a probe may release a probe slot."""
    row, t = _half_open_with_a_probe()
    late_ok = record(row, True, None, t + _ms(1), CFG, probe=False)
    assert late_ok == row
    late_fail = record(row, False, NET, t + _ms(1), CFG, probe=False)
    assert late_fail == row
    assert not admit(late_ok, t + _ms(2), CFG).allowed  # the real probe is still in flight
    done = record(row, True, None, t + _ms(3), CFG, probe=True)
    assert done.half_open_in_flight == 0
    assert done.window_calls == 1
