"""07 section 12: one test per error code proving its disposition (through ``retries.decide``),
plus every hard cap of 07 section 9 that ``amw_core.retries`` owns reached once."""

from datetime import timedelta

import pytest

from amw_core.config import load_settings
from amw_core.enums import ErrorDisposition, EscalationLevel, WaitReason
from amw_core.errors import (
    CATALOGUE,
    AmwError,
    InvalidTransitionError,
    LoopCapExceededError,
    QualityRepeatedFailureError,
)
from amw_core.retries import AttemptFailure, caps, decide, decide_for_error
from tests.core_services.support import T0
from tests.docs_tables import doc_text, section, table_rows

pytestmark = pytest.mark.failure_injection
CFG = load_settings(environ={})


def _doc_rows() -> dict[str, list[str]]:
    rows = table_rows(section(doc_text("07_FAILURE_MANAGEMENT.md"), r"2\. ", 2))
    return {r[0].strip("`"): r for r in rows if r[0].startswith("`")}


DOC = _doc_rows()


def test_catalogue_and_07_table_have_the_same_codes() -> None:
    assert set(DOC) == set(CATALOGUE)


@pytest.mark.parametrize("code", sorted(CATALOGUE))
def test_first_failure_disposition(code: str) -> None:
    """A first failure of each code ends in exactly the disposition its 07 row states."""
    error = AmwError.for_code(code)("injected failure", retry_after_ms=None)
    decision = decide_for_error(
        error,
        attempt_count=1,
        max_attempts=10,
        class_failures=1,
        now=T0,
        settings=CFG,
        uniform=lambda: 0.5,
    )
    doc_disposition = DOC[code][2]
    spec = CATALOGUE[code]
    match spec.disposition:
        case ErrorDisposition.RETRY:
            assert doc_disposition.startswith("RETRY")
            assert decision.disposition is ErrorDisposition.RETRY
            assert decision.next_attempt_at is not None
            assert decision.next_attempt_at >= T0
            assert decision.consumes_attempt
        case ErrorDisposition.SUSPEND:
            assert doc_disposition.startswith(f"SUSPEND:`{spec.wait_reason}`")
            assert decision.disposition is ErrorDisposition.SUSPEND
            assert decision.wait_reason is spec.wait_reason
            assert not decision.consumes_attempt  # 07 section 3.4: a wait, not a retry
        case ErrorDisposition.NO_ATTEMPT:
            assert doc_disposition.startswith("NO_ATTEMPT")
            assert decision.disposition is ErrorDisposition.NO_ATTEMPT
            assert not decision.consumes_attempt
        case ErrorDisposition.FAIL:
            assert doc_disposition.startswith("FAIL")
            assert decision.disposition is ErrorDisposition.FAIL
            assert decision.code == code


@pytest.mark.parametrize(
    "code", sorted(c for c, s in CATALOGUE.items() if s.disposition is ErrorDisposition.RETRY)
)
def test_retryable_codes_stop_at_their_policy_cap(code: str) -> None:
    """No infinite retries: after the policy's max_attempts the code fails (L2 or its L3)."""
    policy = CFG.retry_policy(CATALOGUE[code].retry_policy)  # type: ignore[arg-type]
    last = None
    for k in range(1, policy.max_attempts + 1):
        last = decide(
            AttemptFailure(code, attempt_count=k, max_attempts=10, class_failures=k, now=T0),
            CFG,
            uniform=lambda: 0.0,
        )
        if k < policy.max_attempts and k < 10:
            assert last.disposition is ErrorDisposition.RETRY, (code, k)
    assert last is not None
    assert last.disposition is ErrorDisposition.FAIL
    assert last.escalation in (EscalationLevel.L2, EscalationLevel.L3)


def test_task_attempt_ceiling_is_a_loop_cap() -> None:
    d = decide(
        AttemptFailure(
            "TEMPORARY.NETWORK", attempt_count=3, max_attempts=3, class_failures=1, now=T0
        ),
        CFG,
    )
    assert d.disposition is ErrorDisposition.FAIL
    assert d.code == "AGENT.LOOP_CAP_EXCEEDED"
    assert d.escalation is EscalationLevel.L3


def test_hard_cap_flag_fails_the_retry() -> None:
    d = decide(
        AttemptFailure(
            "AGENT.CRASH",
            attempt_count=1,
            max_attempts=5,
            class_failures=1,
            now=T0,
            hard_cap_reached=True,
        ),
        CFG,
    )
    assert d.code == "AGENT.LOOP_CAP_EXCEEDED"


def test_agent_parse_retries_once_immediately_then_dead_letters() -> None:
    first = decide(
        AttemptFailure(
            "AGENT.INVALID_JSON", attempt_count=1, max_attempts=10, class_failures=1, now=T0
        ),
        CFG,
    )
    assert first.disposition is ErrorDisposition.RETRY
    assert first.wait_ms == 0
    second = decide(
        AttemptFailure(
            "AGENT.INVALID_JSON", attempt_count=2, max_attempts=10, class_failures=2, now=T0
        ),
        CFG,
    )
    assert second.disposition is ErrorDisposition.FAIL
    assert second.code == "AGENT.INVALID_JSON"


def test_rate_limit_honours_retry_after_and_suspends_beyond_the_maximum() -> None:
    honoured = decide(
        AttemptFailure("TEMPORARY.RATE_LIMITED", 1, 10, 1, T0, retry_after_ms=50_000),
        CFG,
        uniform=lambda: 0.0,
    )
    assert honoured.wait_ms == 50_000
    too_long = decide(
        AttemptFailure("TEMPORARY.RATE_LIMITED", 1, 10, 1, T0, retry_after_ms=3_600_001), CFG
    )
    assert too_long.disposition is ErrorDisposition.SUSPEND
    assert too_long.wait_reason is WaitReason.AWAITING_EXTERNAL
    assert too_long.resume_at == T0 + timedelta(milliseconds=3_600_001)
    assert too_long.escalation is EscalationLevel.L2


def test_deadline_turns_a_retry_into_deadline_exceeded() -> None:
    d = decide(
        AttemptFailure("RESOURCE.RENDER_CRASH", 1, 10, 1, T0, deadline=T0 + timedelta(seconds=10)),
        CFG,
        uniform=lambda: 0.0,
    )
    assert d.disposition is ErrorDisposition.FAIL
    assert d.code == "PERMANENT.DEADLINE_EXCEEDED"


def test_window_shifts_the_next_attempt() -> None:
    opening = T0 + timedelta(hours=10)
    d = decide(
        AttemptFailure("TEMPORARY.TIMEOUT", 1, 10, 1, T0), CFG, admissible_at=lambda _t: opening
    )
    assert d.next_attempt_at == opening


def test_unknown_code_and_bad_ceiling_are_input_errors() -> None:
    from amw_core.errors import InputInvalidError

    with pytest.raises(InputInvalidError):
        decide(AttemptFailure("TEMPORARY.NOPE", 1, 10, 1, T0), CFG)
    with pytest.raises(InputInvalidError):
        decide(AttemptFailure("TEMPORARY.NETWORK", 1, 11, 1, T0), CFG)


# --- every hard cap of 07 section 9 owned by amw_core.retries, reached once ----------------------
def test_cap_max_tasks_per_job() -> None:
    caps.check_task_count(199, CFG)
    with pytest.raises(LoopCapExceededError):
        caps.check_task_count(200, CFG)


def test_cap_max_child_jobs() -> None:
    caps.check_child_jobs(9, CFG)
    with pytest.raises(LoopCapExceededError):
        caps.check_child_jobs(10, CFG)


def test_cap_max_revision_loops() -> None:
    caps.check_revision_loop(2, CFG)
    with pytest.raises(LoopCapExceededError):
        caps.check_revision_loop(3, CFG)


def test_cap_max_replays() -> None:
    caps.check_replays(2, CFG)
    with pytest.raises(LoopCapExceededError):
        caps.check_replays(3, CFG)


def test_cap_max_llm_calls() -> None:
    caps.check_llm_calls(3, 4)
    with pytest.raises(LoopCapExceededError):
        caps.check_llm_calls(4, 4)


def test_cap_max_attempts() -> None:
    caps.check_attempts(4, 5, CFG)
    with pytest.raises(LoopCapExceededError):
        caps.check_attempts(5, 5, CFG)
    with pytest.raises(LoopCapExceededError):
        caps.check_attempts(10, 99, CFG)


def test_cap_lock_conflict_reevaluations() -> None:
    caps.check_lock_reevaluations(4, CFG)
    with pytest.raises(InvalidTransitionError):
        caps.check_lock_reevaluations(5, CFG)


def test_cap_in_attempt_repairs() -> None:
    caps.check_in_attempt_repairs(1, 1)
    with pytest.raises(LoopCapExceededError):
        caps.check_in_attempt_repairs(2, 0)
    with pytest.raises(QualityRepeatedFailureError):
        caps.check_in_attempt_repairs(0, 2)


def test_cap_max_job_active_ms() -> None:
    from amw_core.retries.reaper import job_active_cap_reached

    assert not job_active_cap_reached(86_400_000, CFG)
    assert job_active_cap_reached(86_400_001, CFG)
