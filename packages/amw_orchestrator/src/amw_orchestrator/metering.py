"""Metering wrappers at the adapter boundary (09 sections 2 and 5).

Every provider call of every stage goes through one of these wrappers, so the runner can enforce
the three budget points uniformly whatever an agent does internally:

* before the call: the paid-call policy (only allowed providers; the dry run allows fake
  providers only) and E2 ``check_call`` against the task's reservation;
* after the call: one ``cost_ledger`` row (``ESTIMATE``) and E3 ``after_call``.

The wrappers read the running task from a context variable that the runner sets around
``StageExecutor.execute``; a call outside a task is refused (no unattributed spend).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol

from amw_adapters.common import CallUsage
from amw_adapters.llm import LlmAdapter, LlmRequest, LlmResponse, TokenCount
from amw_adapters.tts import TtsAdapter, TtsRequest, TtsResult, VoiceList, VoiceListRequest
from amw_core.errors import ConfigInvalidError


@dataclass(frozen=True, slots=True)
class MeteredTask:
    org_id: str
    job_id: str
    task_id: str
    attempt_id: str
    stage_id: str
    agent_id: str
    channel_id: str | None


class Meter(Protocol):
    def before_call(self, task: MeteredTask, provider: str, estimate_micros: int) -> None:
        """Paid-call policy + E2; raises ``BudgetExhaustedError`` / ``ConfigInvalidError``."""
        ...

    def after_call(self, task: MeteredTask, usage: CallUsage) -> None:
        """Ledger row + E3."""
        ...


_current: ContextVar[MeteredTask | None] = ContextVar("amw_metered_task", default=None)


@contextmanager
def metered_task(task: MeteredTask) -> Iterator[None]:
    token = _current.set(task)
    try:
        yield
    finally:
        _current.reset(token)


def current_task() -> MeteredTask:
    task = _current.get()
    if task is None:
        raise ConfigInvalidError("provider call outside a metered task (unattributed spend)")
    return task


class MeteredLlm:
    """``LlmAdapter`` decorator."""

    def __init__(self, inner: LlmAdapter, meter: Meter, estimate_micros: int) -> None:
        self._inner, self._meter, self._estimate = inner, meter, estimate_micros

    @property
    def provider(self) -> str:
        return self._inner.provider

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        task = current_task()
        self._meter.before_call(task, self._inner.provider, self._estimate)
        response = self._inner.complete(request, idempotency_key=idempotency_key)
        self._meter.after_call(task, response.usage)
        return response

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> TokenCount:
        return self._inner.count_tokens(request, idempotency_key=idempotency_key)


class MeteredTts:
    """``TtsAdapter`` decorator (synthesis is metered; the voice list is not a paid call)."""

    def __init__(self, inner: TtsAdapter, meter: Meter, estimate_micros: int) -> None:
        self._inner, self._meter, self._estimate = inner, meter, estimate_micros

    @property
    def provider(self) -> str:
        return self._inner.provider

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult:
        task = current_task()
        self._meter.before_call(task, self._inner.provider, self._estimate)
        result = self._inner.synthesize(request, idempotency_key=idempotency_key)
        self._meter.after_call(task, result.usage)
        return result

    def list_voices(self, request: VoiceListRequest, *, idempotency_key: str) -> VoiceList:
        return self._inner.list_voices(request, idempotency_key=idempotency_key)
