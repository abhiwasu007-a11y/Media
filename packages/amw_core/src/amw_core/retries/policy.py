"""Error-code dispositions and the retry decision (07 sections 2, 3 and 9).

``decide`` is a pure function: it maps one failed attempt to RETRY (with ``next_attempt_at``),
FAIL (with the final code), SUSPEND (with the ``wait_reason``) or NO_ATTEMPT. It never loops and
never exceeds a hard cap: the task ceiling (``limits.max_attempts_per_task``, 10 by DB CHECK), the
per-class policy ``max_attempts`` and the deadline are all checked before a retry is allowed.
"""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal

from amw_core.config import AmwSettings, RetryPolicySettings
from amw_core.enums import ErrorDisposition, EscalationLevel, RetryPolicy, WaitReason
from amw_core.errors import CATALOGUE, AmwError, ErrorSpec, InputInvalidError

TASK_ATTEMPT_CEILING = 10
"""04 section 5.3: ``tasks.max_attempts`` <= 10 (DB CHECK)."""

LOOP_CAP_CODE = "AGENT.LOOP_CAP_EXCEEDED"
DEADLINE_CODE = "PERMANENT.DEADLINE_EXCEEDED"

UniformSource = Callable[[], float]
"""Returns U ~ Uniform[0, 1) (``random.random``); injected so tests are deterministic."""


def spec_for(code: str) -> ErrorSpec:
    """The catalogue row of a code; an unknown code is ``PERMANENT.INPUT_INVALID``."""
    try:
        return CATALOGUE[code]
    except KeyError:
        raise InputInvalidError(f"unknown error code {code!r} (07 section 2)") from None


def backoff_ms(policy: RetryPolicySettings, k: int, u: float) -> int:
    """07 section 3.1 for the k-th retry (k >= 1), in whole milliseconds (floor):

    ``d_k = min(cap_ms, base_ms * multiplier^(k-1))``;
    ``wait_k = d_k * (1 - jitter) + U * d_k * jitter``.
    """
    if k < 1:
        raise InputInvalidError("k counts failed attempts of the class and starts at 1")
    if not 0.0 <= u < 1.0 or math.isnan(u):
        raise InputInvalidError("U must be in [0, 1)")
    d_k = min(policy.cap_ms, policy.base_ms * policy.multiplier ** (k - 1))
    d = Decimal(d_k)
    wait = d * (1 - policy.jitter) + Decimal(repr(u)) * d * policy.jitter
    return int(wait.to_integral_value(rounding=ROUND_FLOOR))


@dataclass(frozen=True, slots=True)
class AttemptFailure:
    """What the decision needs about the failed attempt and its task."""

    code: str
    attempt_count: int
    """``tasks.attempt_count`` including the attempt that just failed."""
    max_attempts: int
    """``tasks.max_attempts`` (<= 10)."""
    class_failures: int
    """Failures of this code's retry policy for this task, including this one (k)."""
    now: datetime
    deadline: datetime | None = None
    retry_after_ms: int | None = None
    hard_cap_reached: bool = False
    """Any other 07 section 9 cap reached (computed by ``amw_core.retries.caps``)."""


@dataclass(frozen=True, slots=True)
class RetryDecision:
    disposition: ErrorDisposition
    code: str
    """The code recorded on the task: the original one, or the cap / deadline code."""
    escalation: EscalationLevel
    next_attempt_at: datetime | None = None
    wait_ms: int | None = None
    wait_reason: WaitReason | None = None
    resume_at: datetime | None = None
    consumes_attempt: bool = True
    reason: str = ""


def _escalated(spec: ErrorSpec) -> EscalationLevel:
    """Level after the retry cap: L2 for retryable classes (07 section 7, L2 trigger)."""
    if spec.escalation is EscalationLevel.L3:
        return EscalationLevel.L3
    return EscalationLevel.L2


def decide(
    failure: AttemptFailure,
    settings: AmwSettings,
    uniform: UniformSource = random.random,
    admissible_at: Callable[[datetime], datetime] | None = None,
) -> RetryDecision:
    """07 sections 2, 3.1, 3.2 and 9 for one failed attempt.

    ``admissible_at`` maps a time to the next admissible time of the task's resource class
    (window interaction, 07 section 3.1); ``None`` means every time is admissible.
    """
    spec = spec_for(failure.code)
    if failure.max_attempts > TASK_ATTEMPT_CEILING or failure.max_attempts < 1:
        raise InputInvalidError("max_attempts must be within 1-10 (04 section 5.3)")
    if spec.disposition is ErrorDisposition.SUSPEND:
        return RetryDecision(
            ErrorDisposition.SUSPEND,
            spec.code,
            spec.escalation,
            wait_reason=spec.wait_reason,
            consumes_attempt=False,
            reason="suspension is a wait, not a retry (07 section 3.4)",
        )
    if spec.disposition is ErrorDisposition.NO_ATTEMPT:
        return RetryDecision(
            ErrorDisposition.NO_ATTEMPT,
            spec.code,
            spec.escalation,
            consumes_attempt=False,
            reason="attempt not started; re-evaluate",
        )
    if spec.disposition is ErrorDisposition.FAIL:
        return RetryDecision(ErrorDisposition.FAIL, spec.code, spec.escalation, reason="permanent")
    # RETRY: every condition of 07 section 3.2 must hold.
    assert spec.retry_policy is not None  # noqa: S101 - catalogue invariant (tested)
    policy = settings.retry_policy(spec.retry_policy)
    if failure.hard_cap_reached:
        return _fail_cap(spec, "a hard cap of 07 section 9 is reached")
    task_cap = min(failure.max_attempts, settings.limits.max_attempts_per_task)
    if failure.attempt_count >= task_cap:
        return _fail_cap(spec, "task attempts exhausted (limits.max_attempts_per_task)")
    if failure.class_failures >= policy.max_attempts:
        return RetryDecision(
            ErrorDisposition.FAIL,
            spec.code,
            _escalated(spec),
            reason=f"retry policy {spec.retry_policy} exhausted",
        )
    wait = backoff_ms(policy, max(failure.class_failures, 1), uniform())
    if failure.retry_after_ms is not None:
        if (
            policy.retry_after_max_ms is not None
            and failure.retry_after_ms > policy.retry_after_max_ms
        ):
            return RetryDecision(
                ErrorDisposition.SUSPEND,
                spec.code,
                EscalationLevel.L2,
                wait_reason=WaitReason.AWAITING_EXTERNAL,
                resume_at=failure.now + timedelta(milliseconds=failure.retry_after_ms),
                consumes_attempt=False,
                reason="retry_after_ms above rate_limited.retry_after_max_ms",
            )
        wait = max(wait, failure.retry_after_ms)
    next_at = failure.now + timedelta(milliseconds=wait)
    if failure.deadline is not None and next_at > failure.deadline:
        return RetryDecision(
            ErrorDisposition.FAIL,
            DEADLINE_CODE,
            EscalationLevel.L2,
            reason="next attempt after deadline",
        )
    if admissible_at is not None:
        next_at = max(next_at, admissible_at(next_at))
    return RetryDecision(
        ErrorDisposition.RETRY,
        spec.code,
        spec.escalation,
        next_attempt_at=next_at,
        wait_ms=wait,
        reason=f"retry {failure.class_failures} of policy {spec.retry_policy}",
    )


def _fail_cap(spec: ErrorSpec, reason: str) -> RetryDecision:
    return RetryDecision(
        ErrorDisposition.FAIL,
        LOOP_CAP_CODE,
        CATALOGUE[LOOP_CAP_CODE].escalation,
        reason=f"{reason}; last error {spec.code}",
    )


def decide_for_error(
    error: AmwError,
    *,
    attempt_count: int,
    max_attempts: int,
    class_failures: int,
    now: datetime,
    settings: AmwSettings,
    deadline: datetime | None = None,
    hard_cap_reached: bool = False,
    uniform: UniformSource = random.random,
) -> RetryDecision:
    """``decide`` for a raised typed error (``retry_after_ms`` is taken from the error)."""
    return decide(
        AttemptFailure(
            code=error.code,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            class_failures=class_failures,
            now=now,
            deadline=deadline,
            retry_after_ms=error.retry_after_ms,
            hard_cap_reached=hard_cap_reached,
        ),
        settings,
        uniform,
    )


def policy_of(code: str) -> RetryPolicy | None:
    return spec_for(code).retry_policy
