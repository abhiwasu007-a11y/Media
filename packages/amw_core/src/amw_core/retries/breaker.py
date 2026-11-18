"""Circuit breaker state machine (07 section 4; 04 section 5.8 ``circuit_breakers``).

Pure functions over a ``BreakerRow`` that mirrors the table columns. The same rules are
implemented in SQL by ``amw_breaker_record`` and ``amw_breaker_admit`` (migration 0051) so every
worker shares one state; ``test_breaker_sql_matches_the_pure_model`` in
``tests/core_services_db/test_recovery_pg.py`` runs both on the same random event sequences.

Window: a fixed window of ``window_ms`` that restarts when it has elapsed (the stored columns are
``window_started_at`` / ``window_calls`` / ``window_failures``; no per-call history exists).
Counted failures are the codes with "Breaker counts: yes" (07 section 2); other failures are
neutral: they change nothing (no call, no failure, the streak stays), except that a finished
HALF_OPEN probe releases its in-flight slot.
In ``HALF_OPEN`` the window counters hold the consecutive probe successes.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from amw_core.config import BreakerSettings
from amw_core.enums import CircuitState, EscalationLevel
from amw_core.errors import CATALOGUE, ConfigInvalidError
from amw_core.interfaces.system_functions import BreakerKey


@dataclass(frozen=True, slots=True)
class BreakerRow:
    key: BreakerKey
    state: CircuitState
    window_started_at: datetime
    window_calls: int = 0
    window_failures: int = 0
    consecutive_failures: int = 0
    opened_at: datetime | None = None
    open_until: datetime | None = None
    open_count: int = 0
    half_open_in_flight: int = 0
    last_error_code: str | None = None
    half_open_probe_until: datetime | None = None
    """Lease of the last admitted probe; once it has passed, unreported probes are reclaimed."""


def new_row(key: BreakerKey, now: datetime) -> BreakerRow:
    return BreakerRow(key=key, state=CircuitState.CLOSED, window_started_at=now)


def counts_as_failure(error_code: str | None) -> bool:
    if error_code is None:
        return False
    spec = CATALOGUE.get(error_code)
    return spec is not None and spec.breaker_counts


def open_duration_ms(open_count: int, cfg: BreakerSettings) -> int:
    """``min(open_ms * 2^open_count, open_ms_max)`` with ``open_count`` before the increment."""
    return int(min(cfg.open_ms * (2 ** min(open_count, 40)), cfg.open_ms_max))


def _open(row: BreakerRow, now: datetime, cfg: BreakerSettings) -> BreakerRow:
    duration = open_duration_ms(row.open_count, cfg)
    return replace(
        row,
        state=CircuitState.OPEN,
        opened_at=(row.opened_at or now) if row.state is CircuitState.HALF_OPEN else now,
        open_until=now + timedelta(milliseconds=duration),
        open_count=row.open_count + 1,
        half_open_in_flight=0,
        half_open_probe_until=None,
        window_started_at=now,
        window_calls=0,
        window_failures=0,
    )


def _to_half_open(row: BreakerRow, now: datetime) -> BreakerRow:
    return replace(
        row,
        state=CircuitState.HALF_OPEN,
        half_open_in_flight=0,
        half_open_probe_until=None,
        window_started_at=now,
        window_calls=0,
        window_failures=0,
    )


def _roll_window(row: BreakerRow, now: datetime, cfg: BreakerSettings) -> BreakerRow:
    if now - row.window_started_at > timedelta(milliseconds=cfg.window_ms):
        return replace(row, window_started_at=now, window_calls=0, window_failures=0)
    return row


@dataclass(frozen=True, slots=True)
class Admission:
    allowed: bool
    row: BreakerRow
    probe: bool = False


def admit(row: BreakerRow, now: datetime, cfg: BreakerSettings) -> Admission:
    """Model of ``amw_breaker_admit`` (07 section 4.3), used to prove the SQL equal to it; adapters
    never decide from a row they read, they call ``PgBreakerFunctions.admit``. ``OPEN`` rejects
    until ``open_until``; the first check at or after it moves to ``HALF_OPEN``; ``HALF_OPEN``
    admits up to ``half_open_max_probes`` unreported probes, each with a lease of
    ``half_open_probe_timeout_ms`` after which unreported probes are reclaimed."""
    if row.state is CircuitState.CLOSED:
        return Admission(True, row)
    if row.state is CircuitState.OPEN:
        if row.open_until is not None and now < row.open_until:
            return Admission(False, row)
        row = _to_half_open(row, now)
    if (
        row.half_open_in_flight > 0
        and row.half_open_probe_until is not None
        and now > row.half_open_probe_until
    ):
        row = replace(row, half_open_in_flight=0)
    if row.half_open_in_flight >= cfg.half_open_max_probes:
        return Admission(False, row)
    timeout = cfg.half_open_probe_timeout_ms
    if timeout is None:
        raise ConfigInvalidError("breaker.half_open_probe_timeout_ms is not configured")
    return Admission(
        True,
        replace(
            row,
            half_open_in_flight=row.half_open_in_flight + 1,
            half_open_probe_until=now + timedelta(milliseconds=timeout),
        ),
        True,
    )


def record(
    row: BreakerRow,
    succeeded: bool,
    error_code: str | None,
    now: datetime,
    cfg: BreakerSettings,
    probe: bool | None = None,
) -> BreakerRow:
    """Apply one call outcome; the exact mirror of ``amw_breaker_record`` (migration 0051).
    ``probe`` is True for a call admitted as a HALF_OPEN probe, False for one admitted while
    CLOSED (its late result in HALF_OPEN changes nothing and frees no probe slot), None when the
    caller does not use ``admit`` (treated as a probe)."""
    counted = (not succeeded) and counts_as_failure(error_code)
    if row.state is CircuitState.OPEN:
        if row.open_until is None or now < row.open_until:
            return row  # a late result of a call admitted before the breaker opened
        row = _to_half_open(row, now)
    elif row.state is CircuitState.CLOSED:
        row = _roll_window(row, now, cfg)
    if row.state is CircuitState.HALF_OPEN:
        if probe is False:
            return row  # a late result of a call admitted before the breaker opened
        row = replace(row, half_open_in_flight=max(0, row.half_open_in_flight - 1))
    if not succeeded and not counted:
        return row  # not a provider fault (07 section 4.3): only the probe slot is released
    if succeeded:
        row = replace(row, window_calls=row.window_calls + 1, consecutive_failures=0)
        if row.state is CircuitState.HALF_OPEN and (
            row.window_calls >= cfg.half_open_successes_to_close
        ):
            return replace(
                row,
                state=CircuitState.CLOSED,
                window_started_at=now,
                window_calls=0,
                window_failures=0,
                opened_at=None,
                open_until=None,
                open_count=0,
                half_open_in_flight=0,
                half_open_probe_until=None,
            )
        return row
    row = replace(
        row,
        window_calls=row.window_calls + 1,
        window_failures=row.window_failures + 1,
        consecutive_failures=row.consecutive_failures + 1,
        last_error_code=error_code,
    )
    if (
        row.state is CircuitState.HALF_OPEN
        or row.consecutive_failures >= cfg.consecutive_failures
        or (
            row.window_calls >= cfg.min_calls
            and row.window_failures >= cfg.failure_ratio * row.window_calls
        )
    ):
        return _open(row, now, cfg)
    return row


def escalation_for(row: BreakerRow, now: datetime, cfg: BreakerSettings) -> EscalationLevel:
    """L1 for breaker events; L2 when the breaker has been open (incl. re-openings from
    ``HALF_OPEN``) longer than ``open_ms_max`` in total (07 section 4.3)."""
    if (
        row.state is not CircuitState.CLOSED
        and row.opened_at is not None
        and now - row.opened_at > timedelta(milliseconds=cfg.open_ms_max)
    ):
        return EscalationLevel.L2
    return EscalationLevel.L1
