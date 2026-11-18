"""Typed errors of Agent 08 and the ``AdapterErrorMapper`` (blueprint 10.1, section 18).

No new 07 code is introduced: this module only maps provider outcomes onto the existing
``amw_core.errors`` classes. Typed exceptions raised by Agent 08 code come from ``amw_core``
directly; the two Agent 08 specific conditions below carry their 07 code in ``details``.
"""

from dataclasses import dataclass
from enum import StrEnum

from amw_core.errors import (
    AuthInvalidError,
    CallTimeoutError,
    MissingDependencyError,
    NetworkError,
    ProviderRefusalError,
    RateLimitedError,
    Upstream5xxError,
)

ERR_RATE_LIMITED = RateLimitedError.code
ERR_UPSTREAM_5XX = Upstream5xxError.code
ERR_AUTH_INVALID = AuthInvalidError.code
ERR_PROVIDER_REFUSAL = ProviderRefusalError.code
ERR_TIMEOUT = CallTimeoutError.code
ERR_NETWORK = NetworkError.code
ERR_MISSING_DEPENDENCY = MissingDependencyError.code

_POLICY_SIGNALS = frozenset({"CONTENT_POLICY", "SAFETY", "POLICY_VIOLATION"})


class MapOutcome(StrEnum):
    ERROR = "ERROR"
    CANDIDATE_GONE = "CANDIDATE_GONE"


@dataclass(frozen=True, slots=True)
class ProviderOutcome:
    """What an adapter observed; ``http_status`` / ``timeout`` / ``network_error`` are exclusive."""

    adapter: str
    http_status: int | None = None
    retry_after_s: int | None = None
    timeout: bool = False
    network_error: str | None = None
    provider_signal: str | None = None
    phase: str | None = None


@dataclass(frozen=True, slots=True)
class MappedError:
    outcome: MapOutcome
    error_code: str | None
    retry_after_ms: int | None
    retryable: bool


class UnmappedOutcomeError(ValueError):
    """The adapter reported an outcome that has no mapping (a bug in the adapter)."""


class AdapterErrorMapper:
    """Provider outcome to a 07 code (EM-01 to EM-07); pure."""

    @staticmethod
    def map(outcome: ProviderOutcome) -> MappedError:
        if outcome.timeout:
            return MappedError(MapOutcome.ERROR, ERR_TIMEOUT, None, True)
        if outcome.network_error is not None:
            return MappedError(MapOutcome.ERROR, ERR_NETWORK, None, True)
        status = outcome.http_status
        if status is None:
            raise UnmappedOutcomeError("outcome has no status, timeout or network error")
        if status == 404 and outcome.phase == "download":
            # A vendor item removed at download is a dropped candidate, not an error (F-07).
            return MappedError(MapOutcome.CANDIDATE_GONE, None, None, False)
        if outcome.provider_signal in _POLICY_SIGNALS:
            return MappedError(MapOutcome.ERROR, ERR_PROVIDER_REFUSAL, None, False)
        if status == 429:
            retry_ms = None if outcome.retry_after_s is None else outcome.retry_after_s * 1000
            return MappedError(MapOutcome.ERROR, ERR_RATE_LIMITED, retry_ms, True)
        if status in (401, 403):
            return MappedError(MapOutcome.ERROR, ERR_AUTH_INVALID, None, False)
        if 500 <= status <= 599:
            return MappedError(MapOutcome.ERROR, ERR_UPSTREAM_5XX, None, True)
        raise UnmappedOutcomeError(f"no mapping for HTTP status {status}")
