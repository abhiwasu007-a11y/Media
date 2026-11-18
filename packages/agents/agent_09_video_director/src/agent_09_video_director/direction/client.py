"""DirectionClient (F-29): the only place that calls the LlmAdapter.

No call without budget headroom (S4 reservation, worst case) and a closed breaker; one ledger
record per call; the idempotency key is ``llm.call`` over (task_id, ``direction.bNN``,
call_seq), so a replay returns the stored result and never a second paid call.
"""

from dataclasses import dataclass, field
from typing import Protocol

from agent_09_video_director.config import Agent09Config
from agent_09_video_director.contracts import CallInfo
from agent_09_video_director.direction.prompt import RenderedPrompt
from amw_adapters.llm.protocol import LlmAdapter, LlmMessage, LlmRequest, LlmResponse
from amw_core.errors import BudgetExhaustedError, CircuitOpenError, InvalidJsonError
from amw_core.ids import IdempotencyScope, make_idempotency_key


class CallRecorder(Protocol):
    """Writes the ``cost_ledger`` row and returns its entry id (worker-side, tenancy tx)."""

    def record(self, response: LlmResponse, idempotency_key: str) -> str: ...


class Breaker(Protocol):
    def is_open(self, provider: str) -> bool: ...


@dataclass(slots=True)
class CallMeter:
    """The task's ``resource_budget`` and the S4 reservation, checked before every call."""

    max_calls: int
    max_cost_micros: int
    worst_case_call_micros: int
    calls: int = 0
    spent_micros: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached_in: int = 0
    cost_entry_ids: list[str] = field(default_factory=list)
    call_log: list[CallInfo] = field(default_factory=list)

    def check(self) -> None:
        if (
            self.calls + 1 > self.max_calls
            or self.spent_micros + self.worst_case_call_micros > self.max_cost_micros
        ):
            raise BudgetExhaustedError("reservation does not cover the next call")

    def after(self, response: LlmResponse, entry_id: str, step_key: str = "") -> None:
        u = response.usage
        self.calls += 1
        self.spent_micros += u.amount_micros
        self.tokens_in += u.tokens_in or 0
        self.tokens_out += u.tokens_out or 0
        self.tokens_cached_in += u.tokens_cached_in or 0
        self.cost_entry_ids.append(entry_id)
        self.call_log.append(
            CallInfo(
                step_key=step_key,
                provider=u.provider,
                model=u.model or "",
                tokens_in=u.tokens_in or 0,
                tokens_out=u.tokens_out or 0,
                tokens_cached_in=u.tokens_cached_in or 0,
                cost_entry_id=entry_id,
            )
        )


class DirectionClient:
    def __init__(
        self,
        *,
        llm: LlmAdapter,
        cfg: Agent09Config,
        meter: CallMeter,
        recorder: CallRecorder,
        org_id: str,
        task_id: str,
        language: str,
        breaker: Breaker | None = None,
    ) -> None:
        self._llm, self._cfg, self._meter = llm, cfg, meter
        self._recorder, self._org, self._task = recorder, org_id, task_id
        self._language, self._breaker = language, breaker

    def complete(
        self, prompt: RenderedPrompt, batch_id: str, call_seq: int, extra_user: str = ""
    ) -> str:
        if self._breaker is not None and self._breaker.is_open(self._llm.provider):
            raise CircuitOpenError("provider breaker open; no attempt")
        self._meter.check()
        key = make_idempotency_key(
            self._org, IdempotencyScope.LLM_CALL, [self._task, f"direction.{batch_id}", call_seq]
        )
        content = prompt.user + (f"\n\n{extra_user}" if extra_user else "")
        request = LlmRequest(
            model=self._cfg.llm_model,
            system=prompt.system,
            messages=(LlmMessage(role="user", content=content),),
            max_output_tokens=self._cfg.llm_max_output_tokens,
            temperature=self._cfg.llm_temperature,
            timeout_ms=self._cfg.llm_timeout_ms,
            cache_system_prompt=self._cfg.llm_cache_system_prompt,
            language=self._language,
        )
        response = self._llm.complete(request, idempotency_key=str(key))
        entry_id = self._recorder.record(response, str(key))
        self._meter.after(response, entry_id, f"direction.{batch_id}")
        if response.stop_reason == "max_tokens":
            raise InvalidJsonError("model output truncated at max_output_tokens")
        return response.text
