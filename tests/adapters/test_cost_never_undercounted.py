"""The per-video cap is never under-counted (MAJOR 2 + MINOR of the PR 96 review), with fake
providers: success, failure before delivery, failure after payment then retry, timeout."""

import httpx
import pytest

from amw_adapters.real.guard import CapOnlyCallGuard, call_scope
from amw_core.cost.ledger import effective_rows
from amw_core.enums import CostFigureKind
from amw_core.errors import (
    CallTimeoutError,
    CorruptedOutputError,
    IncompleteOutputError,
    InputInvalidError,
    Upstream5xxError,
)
from tests.adapters.guards import GuardedWorld, cap_guard
from tests.adapters.mock_providers import Scripted, anthropic_message, wav_bytes
from tests.adapters.test_real_guard_and_controls import key, llm, llm_request, tts, tts_request

pytestmark = pytest.mark.failure_injection
BAD_STOP = Scripted(200, anthropic_message(stop_reason="pause_turn"))


def total(world: GuardedWorld) -> int:
    rows = effective_rows(world.w.ledger.for_job(world.w.tx, world.job))
    return sum(r.entry.amount_micros for r in rows)


def keys(world: GuardedWorld) -> list[str]:
    return [str(r.entry.idempotency_key) for r in world.w.ledger.for_job(world.w.tx, world.job)]


def test_success_is_recorded_once() -> None:
    world = GuardedWorld()
    adapter, mock = llm(world.guard("anthropic"))
    with call_scope(world.ctx):
        result = adapter.complete(llm_request(), idempotency_key=key())
    assert total(world) == result.usage.amount_micros > 0
    assert mock.billable == 1


def test_failure_after_payment_then_retry_records_the_second_charge_budget_guard() -> None:
    world = GuardedWorld()
    adapter, mock = llm(world.guard("anthropic"))
    mock.script.append(
        Scripted(
            200,
            anthropic_message(
                stop_reason="pause_turn", usage={"input_tokens": 10, "output_tokens": 5}
            ),
        )
    )
    with call_scope(world.ctx):
        with pytest.raises(IncompleteOutputError):
            adapter.complete(llm_request(), idempotency_key=key())
        paid_first = total(world)
        assert paid_first > 0  # the billed response is recorded
        retry = adapter.complete(llm_request(), idempotency_key=key())  # same key, pays again
    rows = world.rows()
    assert len(rows) == 2
    assert len(set(keys(world))) == 2  # the second charge has its OWN ledger key
    assert total(world) == paid_first + retry.usage.amount_micros  # never silently free
    assert mock.billable == 1  # (the scripted first response is not counted by the mock default)


def test_failure_after_payment_then_retry_is_counted_cap_only_guard() -> None:
    guard = cap_guard("anthropic")
    adapter, mock = llm(guard)
    mock.script.append(BAD_STOP)
    with pytest.raises(IncompleteOutputError):
        adapter.complete(llm_request(), idempotency_key=key())
    first = guard.spent_micros
    retry = adapter.complete(llm_request(), idempotency_key=key())
    assert guard.spent_micros == first + retry.usage.amount_micros
    assert guard.held_micros == 0


def test_tts_billed_but_unusable_audio_then_retry_records_both_charges() -> None:
    world = GuardedWorld()
    adapter, mock = tts(world.guard("elevenlabs"))
    mock.script.append(Scripted(200, wav_bytes(100, 24_000)))  # wrong sample rate: billed, unusable
    with call_scope(world.ctx):
        with pytest.raises(CorruptedOutputError):
            adapter.synthesize(tts_request(), idempotency_key=key(2, "tts.synthesize"))
        first = total(world)
        assert first > 0
        again = adapter.synthesize(tts_request(), idempotency_key=key(2, "tts.synthesize"))
    assert len(world.rows()) == 2
    assert len(set(keys(world))) == 2
    assert total(world) == first + again.usage.amount_micros


def test_5xx_and_timeout_hold_the_worst_case_fail_closed_budget_guard() -> None:
    for script, error in (
        (Scripted(500, {"error": {"type": "api_error"}}), Upstream5xxError),
        (Scripted(0, raise_exc=httpx.ReadTimeout("slow")), CallTimeoutError),
    ):
        world = GuardedWorld()
        guard = world.guard("anthropic")
        adapter, mock = llm(guard)
        mock.script.append(script)
        with call_scope(world.ctx):
            with pytest.raises(error):
                adapter.complete(llm_request(), idempotency_key=key())
            held = world.rows()
            assert len(held) == 1  # the worst case is on the ledger (counted against the cap)
            entry = held[0].entry  # type: ignore[attr-defined]
            assert entry.figure_kind is CostFigureKind.ESTIMATE
            assert entry.amount_micros > 0
            assert total(world) == entry.amount_micros
            # the owner reconciles with the provider's own usage: nothing was billed
            guard.reconcile(held[0], actual_micros=0, verification_ref="provider-usage-console")  # type: ignore[arg-type]
            assert total(world) == 0
            # and a retry is allowed again
            adapter.complete(llm_request(), idempotency_key=key())
        assert total(world) > 0


def test_5xx_and_timeout_hold_the_worst_case_cap_only_guard() -> None:
    for script in (
        Scripted(503, {"error": {"type": "api_error"}}),
        Scripted(0, raise_exc=httpx.ReadTimeout("slow")),
    ):
        guard = cap_guard("anthropic")
        adapter, mock = llm(guard)
        mock.script.append(script)
        with pytest.raises(Exception):  # noqa: B017, PT011 - 5xx / timeout codes checked above
            adapter.complete(llm_request(), idempotency_key=key())
        assert guard.spent_micros == 0
        assert guard.held_micros > 0  # fail closed until reconciled
        guard.reconcile(key(), actual_micros=0)
        assert guard.held_micros == 0


def test_a_hold_that_is_never_reconciled_blocks_calls_over_the_cap() -> None:
    guard = cap_guard("anthropic", cap=200_000)
    adapter, mock = llm(guard)
    for n in range(1, 30):
        mock.script.append(Scripted(0, raise_exc=httpx.ReadTimeout("slow")))
        try:
            adapter.complete(llm_request(), idempotency_key=key(n))
        except CallTimeoutError:
            continue
        break  # not a timeout: the hard stop refused it before the request
    assert guard.held_micros <= 200_000  # unreconciled holds never exceed the cap


def test_proven_non_delivery_releases_the_hold() -> None:
    # 4xx rejection and connect failure: the provider cannot have processed the request
    for script in (
        Scripted(400, {"error": {"type": "invalid_request_error"}}),
        Scripted(0, raise_exc=httpx.ConnectError("refused")),
    ):
        world = GuardedWorld()
        guard = world.guard("anthropic")
        adapter, mock = llm(guard, None)
        mock.script.extend([script, script, script, script, script, script])
        with call_scope(world.ctx), pytest.raises(Exception):  # noqa: B017, PT011
            adapter.complete(llm_request(), idempotency_key=key())
        assert world.rows() == []
        assert guard.in_flight_micros(world.w.org, world.job) == 0
    cap = cap_guard("anthropic")
    adapter, mock = llm(cap)
    mock.script.append(Scripted(400, {"error": {"type": "invalid_request_error"}}))
    with pytest.raises(InputInvalidError):
        adapter.complete(llm_request(), idempotency_key=key())
    assert (cap.spent_micros, cap.held_micros) == (0, 0)
    assert isinstance(cap, CapOnlyCallGuard)
