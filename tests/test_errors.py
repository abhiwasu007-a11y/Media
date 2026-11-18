"""07 section 2 catalogue: every code exists once, with its class, disposition and policy."""

import re

import pytest

from amw_core import errors
from amw_core.enums import FailureClass, WaitReason
from tests.docs_tables import error_catalogue

DOC = error_catalogue()


def test_catalogue_codes_equal_the_doc() -> None:
    assert set(errors.CATALOGUE) == set(DOC)
    assert len(errors.CATALOGUE) == len(DOC)


def test_one_exception_class_per_code() -> None:
    assert set(errors.AmwError.registry) == set(DOC)


@pytest.mark.parametrize("code", sorted(DOC))
def test_row_matches_doc(code: str) -> None:
    _meaning, disposition, policy, breaker, escalation = DOC[code]
    spec = errors.CATALOGUE[code]
    assert spec.error_class is FailureClass(code.split(".")[0])
    expected_kind = re.match(r"(RETRY|SUSPEND|FAIL|NO-ATTEMPT)", disposition)
    assert expected_kind is not None
    assert spec.disposition.value == expected_kind[1].replace("-", "_")
    assert spec.retryable is (expected_kind[1] in ("RETRY", "NO-ATTEMPT"))  # 07 reading rule
    if spec.wait_reason is not None:
        assert f"SUSPEND:`{spec.wait_reason.value}`" in disposition
    policy_tick = re.fullmatch(r"`([a-z_]+)`", policy)
    expected_policy = policy_tick[1] if policy_tick else None
    assert (spec.retry_policy.value if spec.retry_policy else None) == expected_policy
    assert spec.breaker_counts is (breaker == "yes")
    assert escalation.startswith(spec.escalation.value)
    cls = errors.AmwError.for_code(code)
    assert issubclass(cls, errors.CLASS_BASES[spec.error_class])
    assert cls.code == code


def test_retryable_defaults() -> None:
    assert errors.NetworkError("x").retryable
    assert not errors.SchemaInvalidError("x").retryable
    assert not errors.BudgetExhaustedError("x").retryable
    assert errors.BudgetExhaustedError("x").spec.wait_reason is WaitReason.AWAITING_BUDGET
    assert errors.CircuitOpenError("x").retryable


def test_exception_carries_fields() -> None:
    exc = errors.RateLimitedError(
        "slow down", retry_after_ms=1000, provider="anthropic", upstream_status=429
    )
    assert exc.code == "TEMPORARY.RATE_LIMITED"
    assert exc.error_class is FailureClass.TEMPORARY
    assert exc.retry_after_ms == 1000
    assert isinstance(exc, errors.TemporaryError)


def test_base_classes_cannot_be_raised() -> None:
    with pytest.raises(TypeError):
        errors.PermanentError("abstract")


def test_unknown_code_subclass_is_refused() -> None:
    with pytest.raises(TypeError, match="not in 07"):
        type("Bogus", (errors.PermanentError,), {"code": "PERMANENT.NOT_A_CODE"})


def test_duplicate_code_subclass_is_refused() -> None:
    with pytest.raises(TypeError, match="duplicate"):
        type("Dup", (errors.PermanentError,), {"code": "PERMANENT.SCHEMA_INVALID"})
