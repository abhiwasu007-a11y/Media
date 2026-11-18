"""Failure handling (07): dispositions and retry decisions, circuit breakers, dead-letter and
controlled replay, the reaper's stuck-work decisions, and the hard caps."""

from amw_core.retries.breaker import Admission, BreakerRow, admit, record, require_closed_or_probe
from amw_core.retries.policy import (
    AttemptFailure,
    RetryDecision,
    backoff_ms,
    decide,
    decide_for_error,
    spec_for,
)

__all__ = [
    "Admission",
    "AttemptFailure",
    "BreakerRow",
    "RetryDecision",
    "admit",
    "backoff_ms",
    "decide",
    "decide_for_error",
    "record",
    "require_closed_or_probe",
    "spec_for",
]
