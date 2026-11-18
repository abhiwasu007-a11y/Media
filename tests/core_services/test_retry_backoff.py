"""07 section 3.1 backoff + jitter formula."""

from decimal import Decimal

import pytest

from amw_core.config import RetryPolicySettings, load_settings
from amw_core.enums import RetryPolicy
from amw_core.errors import InputInvalidError
from amw_core.retries import backoff_ms, spec_for
from amw_core.retries.policy import policy_of

pytestmark = pytest.mark.unit
TEMP = load_settings(environ={}).retry_policy(RetryPolicy.TEMPORARY)


@pytest.mark.parametrize(
    ("k", "u", "expected"),
    [
        (1, 0.0, 1_000),  # d=2000, (1-0.5)*2000
        (1, 0.5, 1_500),
        (2, 0.0, 2_000),  # d=4000
        (3, 0.999, 7_996),  # d=8000: 4000 + 0.999*4000 = 7996
        (9, 0.0, 150_000),  # 2000*2^8 = 512000 -> capped at 300000
        (20, 0.0, 150_000),
    ],
)
def test_formula(k: int, u: float, expected: int) -> None:
    assert backoff_ms(TEMP, k, u) == expected


def test_wait_stays_within_d_k() -> None:
    for k in range(1, 12):
        d_k = min(TEMP.cap_ms, TEMP.base_ms * 2 ** (k - 1))
        low, high = backoff_ms(TEMP, k, 0.0), backoff_ms(TEMP, k, 0.999_999)
        assert d_k // 2 == low and low <= high < d_k


def test_zero_jitter_is_deterministic() -> None:
    p = RetryPolicySettings(base_ms=100, multiplier=3, cap_ms=10_000, jitter=Decimal(0), max_attempts=3)
    assert [backoff_ms(p, k, 0.7) for k in (1, 2, 3)] == [100, 300, 900]


@pytest.mark.parametrize(("k", "u"), [(0, 0.1), (1, 1.0), (1, -0.1), (1, float("nan"))])
def test_rejects_out_of_range(k: int, u: float) -> None:
    with pytest.raises(InputInvalidError):
        backoff_ms(TEMP, k, u)


def test_spec_lookup() -> None:
    assert spec_for("TEMPORARY.NETWORK").breaker_counts
    assert policy_of("AGENT.CRASH") is RetryPolicy.AGENT
    assert policy_of("PERMANENT.INPUT_INVALID") is None
