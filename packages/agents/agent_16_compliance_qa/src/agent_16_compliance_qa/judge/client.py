"""JudgeClient: the only place Agent 16 calls the ``LlmAdapter`` (F-11, F-14, F-19, F-24).

Per call: breaker closed, the task's ``resource_budget`` (call cap and worst-case cost) checked
before the call, idempotency scope ``llm.call`` over (task, step key, batch, call seq) so a
replay returns the stored result, one ``cost_ledger`` row through ``CallRecorder``. The reply is
parsed into the step's Pydantic model; a parse or schema failure is retried **once** with the
validation error appended, then raised (``AGENT.INVALID_JSON`` / ``AGENT.OUTPUT_SCHEMA_INVALID``,
DLQ by the worker). The judges have no tools and their output is data: nothing they return can
create a task, change a verdict outside the algebra or touch approvals (08 section 5.3).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from agent_16_compliance_qa.config import LlmStepConfig
from amw_adapters.llm.protocol import LlmAdapter, LlmMessage, LlmRequest, LlmResponse
from amw_core.errors import (
    BudgetExhaustedError,
    CircuitOpenError,
    InvalidJsonError,
    LoopCapExceededError,
    OutputSchemaInvalidError,
)
from amw_core.ids import IdempotencyScope, make_idempotency_key

_SCHEMA_MARK = "## A. Input payload schema"


class CallRecorder(Protocol):
    """Writes the ``cost_ledger`` row (worker side, tenancy transaction); returns its id."""

    def record(self, response: LlmResponse, idempotency_key: str) -> str: ...


class Breaker(Protocol):
    def is_open(self, provider: str) -> bool: ...


@dataclass(slots=True)
class CallMeter:
    """The task's call cap and cost budget (S4 reservation), checked before every call."""

    max_calls: int
    max_cost_micros: int
    calls: int = 0
    spent_micros: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached_in: int = 0
    cost_entry_ids: list[str] = field(default_factory=list)

    def check(self, worst_case_micros: int) -> None:
        if self.calls + 1 > self.max_calls:
            raise LoopCapExceededError("LLM call cap of the task reached")
        if self.spent_micros + worst_case_micros > self.max_cost_micros:
            raise BudgetExhaustedError("reservation does not cover the next call")

    def after(self, response: LlmResponse, entry_id: str) -> None:
        u = response.usage
        self.calls += 1
        self.spent_micros += u.amount_micros
        self.tokens_in += u.tokens_in or 0
        self.tokens_out += u.tokens_out or 0
        self.tokens_cached_in += u.tokens_cached_in or 0
        self.cost_entry_ids.append(entry_id)


def system_prompt(prompt_text: str, packs: Mapping[str, str]) -> str:
    """Role..Self-check of the prompt file with the platform rule packs inlined (the cacheable
    prefix holds no tenant data, CCR-025); the step input schema section is not sent."""
    end = prompt_text.find(_SCHEMA_MARK)
    start = prompt_text.find("## Role")
    body = prompt_text[start if start >= 0 else 0 : end if end >= 0 else len(prompt_text)]
    for key, text in packs.items():
        body = body.replace("{{rule_pack:" + key + "}}", text)
    return body


class JudgeClient:
    def __init__(
        self,
        *,
        llm: LlmAdapter,
        step: LlmStepConfig,
        meter: CallMeter,
        recorder: CallRecorder,
        org_id: str,
        task_id: str,
        language: str,
        breaker: Breaker | None = None,
    ) -> None:
        self._llm, self._step, self._meter = llm, step, meter
        self._recorder, self._org, self._task = recorder, org_id, task_id
        self._language, self._breaker = language, breaker

    def _call(self, system: str, user: str, step_key: str, seq: int) -> str:
        if self._breaker is not None and self._breaker.is_open(self._llm.provider):
            raise CircuitOpenError("provider breaker open; no attempt")
        self._meter.check(self._step.worst_case_call_micros)
        key = make_idempotency_key(
            self._org, IdempotencyScope.LLM_CALL, [self._task, step_key, seq]
        )
        request = LlmRequest(
            model=self._step.model,
            system=system,
            messages=(LlmMessage(role="user", content=user),),
            max_output_tokens=self._step.max_output_tokens,
            temperature=self._step.temperature,
            timeout_ms=self._step.timeout_ms,
            cache_system_prompt=self._step.cache_system_prompt,
            language=self._language,
        )
        response = self._llm.complete(request, idempotency_key=str(key))
        self._meter.after(response, self._recorder.record(response, str(key)))
        if response.stop_reason == "max_tokens":
            raise InvalidJsonError("judge output truncated at max_output_tokens")
        return response.text

    def judge[M: BaseModel](
        self, system: str, payload: Mapping[str, Any], model: type[M], step_key: str
    ) -> M:
        """One judged batch: parse, retry once with the error, then raise (07 section 2)."""
        user = "<<<INPUT\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\nINPUT>>>"
        error: str | None = None
        for seq in (0, 1):
            text = self._call(
                system, user if error is None else f"{user}\n\n{error}", step_key, seq
            )
            try:
                return model.model_validate(json.loads(text))
            except json.JSONDecodeError as exc:
                error = f"Your previous reply was not valid JSON ({exc.msg}). Reply with JSON only."
                last: Exception = InvalidJsonError("judge reply is not JSON")
            except ValidationError as exc:
                error = f"Your previous reply failed the output schema: {str(exc)[:800]}"
                last = OutputSchemaInvalidError("judge reply failed the step schema")
        raise last
