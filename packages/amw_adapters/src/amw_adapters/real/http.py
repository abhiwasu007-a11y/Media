"""HTTPS plumbing shared by the real adapters: injectable transport, typed 07 errors, bounded
in-call retries, value-free logging.

Retry rule (PR-09, PR-12: neither provider documents an idempotency key for a paid call):
a request is re-sent inside one adapter call only when the provider cannot have processed it:
a connect-phase failure (nothing was sent), or HTTP 429 (the request was rejected). A 429 without
``Retry-After`` is re-sent only when the catalogue allows it (Anthropic: never; such a 429 is the
spend cap, PR-09). Every other failure (5xx, overloaded, read timeout, broken connection after
the request was sent) is raised at once as its 07 code, with ``retry_after_ms`` when the provider
gave one, and the 07 retry policy of the task decides (07 section 3).

Logs carry ids, sizes, hashes and counts only: never the key, a header value, the prompt or the
response body.
"""

import hashlib
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from amw_adapters.real.catalogue import InCallRetry
from amw_core.config import RetryPolicySettings
from amw_core.errors import (
    AmwError,
    AuthInvalidError,
    CallTimeoutError,
    ConfigInvalidError,
    InputInvalidError,
    NetworkError,
    RateLimitedError,
    Upstream5xxError,
)
from amw_core.observability import get_logger
from amw_core.retries import backoff_ms

DEFAULT_BACKOFF = RetryPolicySettings(
    base_ms=2_000, multiplier=2, cap_ms=300_000, jitter=Decimal("0.5"), max_attempts=5
)
"""07 section 3.3 ``temporary`` design defaults (ESTIMATE); the registry passes the configured
``retry.temporary`` policy. The in-call cap ``max_in_call_wait_ms`` bounds every wait."""

Classifier = Callable[[httpx.Response], AmwError]


def body_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def retry_after_ms(response: httpx.Response) -> int | None:
    """``Retry-After`` in whole milliseconds when it is a number of seconds; else ``None``."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = Decimal(raw.strip())
    except ArithmeticError:
        return None
    if not seconds.is_finite() or seconds < 0:
        return None
    return int(seconds * 1000)


def json_or_empty(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def status_error(
    status: int,
    *,
    provider: str,
    upstream_code: str | None,
    retry_after: int | None,
) -> AmwError:
    """Generic HTTP status -> 07 code (ADR-007 section 2.10, ADR-008 section 2.9). Provider
    classifiers refine it first. The message never contains the provider's text."""
    kw: dict[str, Any] = {
        "provider": provider,
        "upstream_status": status,
        "upstream_code": upstream_code,
    }
    if status == 429:
        return RateLimitedError("provider rate limit", retry_after_ms=retry_after, **kw)
    if status in (401, 402, 403):
        return AuthInvalidError("provider rejected the credential or account", **kw)
    if status == 404:
        return ConfigInvalidError("provider resource not found (model, voice or path)", **kw)
    if status >= 500:
        return Upstream5xxError("provider server error", retry_after_ms=retry_after, **kw)
    return InputInvalidError("provider rejected the request", **kw)


@dataclass(frozen=True, slots=True)
class HttpOutcome:
    response: httpx.Response
    attempts: int
    duration_ms: int


class ProviderHttp:
    """One provider's HTTPS client. ``transport`` is injectable (tests: ``httpx.MockTransport``
    or a recorded-fixture transport; no network, no key)."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        connect_timeout_ms: int,
        retry: InCallRetry,
        classify: Classifier,
        transport: httpx.BaseTransport | None = None,
        backoff: RetryPolicySettings = DEFAULT_BACKOFF,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[], float] = random.random,
        clock_ms: Callable[[], int] = lambda: time.monotonic_ns() // 1_000_000,
    ) -> None:
        self.provider = provider
        self._retry = retry
        self._classify = classify
        self._backoff = backoff
        self._sleep = sleep
        self._uniform = uniform
        self._clock_ms = clock_ms
        self._connect_s = connect_timeout_ms / 1000
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            follow_redirects=False,
            trust_env=transport is None,
        )
        self.log = get_logger(f"adapters.{provider}")

    def close(self) -> None:
        self._client.close()

    def _wait_ms(self, k: int, hint: int | None) -> int:
        wait = backoff_ms(self._backoff, k, min(self._uniform(), 0.999999))
        return max(wait, hint or 0)

    def send(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        headers: Mapping[str, str],
        timeout_ms: int,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> HttpOutcome:
        """Send with the in-call retry rule; return a 2xx response or raise its 07 error."""
        timeout = httpx.Timeout(timeout_ms / 1000, connect=min(self._connect_s, timeout_ms / 1000))
        started = self._clock_ms()
        attempt = 0
        while True:
            attempt += 1
            error: AmwError
            retry_allowed = False
            delivery = "unknown"  # fail closed: only a proven non-delivery releases a hold
            try:
                response = self._client.request(
                    method, path, headers=dict(headers), json=json_body, params=params,
                    timeout=timeout,
                )  # fmt: skip
            except httpx.ConnectError, httpx.ConnectTimeout:
                error = NetworkError("provider connection failed", provider=self.provider)
                retry_allowed = True
                delivery = "not_delivered"  # connect phase: nothing was sent
            except httpx.TimeoutException:
                error = CallTimeoutError("provider call timed out", provider=self.provider)
            except httpx.TransportError:
                error = NetworkError("provider connection broke", provider=self.provider)
            else:
                if 200 <= response.status_code < 300:
                    return HttpOutcome(response, attempt, self._clock_ms() - started)
                error = self._classify(response)
                if 400 <= response.status_code < 500:
                    delivery = "not_delivered"  # rejected by the provider, not processed
                if response.status_code == 429:
                    retry_allowed = (
                        error.retry_after_ms is not None
                        or self._retry.retry_429_without_retry_after
                    )
            error.details["delivery"] = delivery
            wait = self._wait_ms(attempt, error.retry_after_ms) if retry_allowed else 0
            self.log.info(
                "provider.call_failed",
                extra={
                    "provider": self.provider,
                    "operation": operation,
                    "attempt": attempt,
                    "error_code": error.code,
                    "upstream_status": error.upstream_status,
                    "upstream_code": error.upstream_code,
                },
            )
            if (
                not retry_allowed
                or attempt > self._retry.max_in_call_retries
                or wait > self._retry.max_in_call_wait_ms
            ):
                raise error
            self._sleep(wait / 1000)
