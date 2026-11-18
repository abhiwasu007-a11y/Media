"""JudgeClient: the only place Agent 16 calls the ``LlmAdapter`` (F-11, F-14, F-19, F-24).

Fail closed per call (review M3), in this order: the provider breaker (required, never
optional) must be closed; the task's ``CallMeter`` (built from ``LlmStepConfig.max_calls`` /
``max_cost_micros``, ``compliance.gate.max_llm_calls`` and the envelope's ``resource_budget``)
must cover one more call at its worst-case cost; ``BudgetGuard.check_provider_gate`` and
``check_call`` (E2, 09 section 2) must pass. Then the call runs with idempotency scope
``llm.call`` over (task, step key, call seq); one ``cost_ledger`` row is written through
``amw_core`` ``CostLedger`` and ``BudgetGuard.after_call`` (E3) runs on it. The reply is parsed
into the step's Pydantic model; a parse or schema failure is retried **once** with the
validation error appended, then raised (``AGENT.INVALID_JSON`` /
``AGENT.OUTPUT_SCHEMA_INVALID``, DLQ by the worker). The judges have no tools and their output
is data: nothing they return can create a task, change a verdict outside the algebra or touch
approvals (08 section 5.3).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from agent_16_compliance_qa.config import LlmStepConfig
from amw_adapters.llm.protocol import LlmAdapter, LlmMessage, LlmRequest, LlmResponse
from amw_core.contracts.common import ResourceBudget
from amw_core.enums import CostFigureKind
from amw_core.errors import (
    BudgetExhaustedError,
    CircuitOpenError,
    InvalidJsonError,
    LoopCapExceededError,
    OutputSchemaInvalidError,
)
from amw_core.ids import (
    AttemptId,
    ExecutorId,
    IdempotencyScope,
    JobId,
    TaskId,
    make_idempotency_key,
)
from amw_core.interfaces.budget_guard import BudgetGuard, CallCheck
from amw_core.interfaces.clock import Clock
from amw_core.interfaces.cost_ledger import CostLedger, NewCostEntry
from amw_core.interfaces.tenancy_context import TenantTransaction

_SCHEMA_MARK = "## A. Input payload schema"
AGENT_ID = "agent_16"


class Breaker(Protocol):
    """Read side of ``circuit_breakers`` (core_need: an amw_core read interface; the writer is
    ``SystemFunctions.breaker_record``)."""

    def is_open(self, provider: str) -> bool: ...


@dataclass(slots=True)
class CallMeter:
    """The task's call cap and cost budget (S4 reservation), checked before every call."""

    max_calls: int
    max_cost_micros: int
    currency: str
    calls: int = 0
    spent_micros: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached_in: int = 0
    cost_entry_ids: list[str] = field(default_factory=list)

    @classmethod
    def for_task(
        cls, steps: list[LlmStepConfig], gate_max_llm_calls: int, budget: ResourceBudget
    ) -> CallMeter:
        """The tightest of the configured caps and the envelope's ``resource_budget`` (NF-05);
        no step configured => zero calls allowed."""
        caps = [gate_max_llm_calls, sum(s.max_calls for s in steps)]
        if budget.max_llm_calls is not None:
            caps.append(budget.max_llm_calls)
        cost = min(budget.max_cost_micros, sum(s.max_cost_micros for s in steps))
        return cls(
            max_calls=min(caps) if steps else 0, max_cost_micros=cost, currency=budget.currency
        )

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


@dataclass(frozen=True, slots=True)
class CallScope:
    """Who pays for the call: the task's tenant transaction and envelope identifiers."""

    tx: TenantTransaction
    job_id: JobId
    task_id: TaskId
    attempt_id: AttemptId


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
        budget: BudgetGuard,
        costs: CostLedger,
        breaker: Breaker,
        clock: Clock,
        scope: CallScope,
        language: str,
    ) -> None:
        self._llm, self._step, self._meter = llm, step, meter
        self._budget, self._costs, self._breaker, self._clock = budget, costs, breaker, clock
        self._scope, self._language = scope, language

    def _call(self, system: str, user: str, step_key: str, seq: int) -> str:
        sc, provider = self._scope, self._llm.provider
        if self._breaker.is_open(provider):
            raise CircuitOpenError("provider breaker open; no attempt")
        worst = self._step.worst_case_call_micros
        self._meter.check(worst)
        self._budget.check_provider_gate(sc.tx, provider)
        self._budget.check_call(
            sc.tx,
            CallCheck(
                task_id=sc.task_id,
                job_id=sc.job_id,
                provider=provider,
                estimated_cost_micros=worst,
                currency=self._meter.currency,
                tokens_out=self._step.max_output_tokens,
            ),
        )
        key = make_idempotency_key(
            sc.tx.context.org_id, IdempotencyScope.LLM_CALL, [sc.task_id, step_key, seq]
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
        u = response.usage
        entry = self._costs.record(
            sc.tx,
            NewCostEntry(
                provider=u.provider,
                operation=u.operation,
                amount_micros=u.amount_micros,
                currency=u.currency,
                figure_kind=CostFigureKind.ESTIMATE,
                occurred_at=self._clock.now(),
                job_id=sc.job_id,
                task_id=sc.task_id,
                attempt_id=sc.attempt_id,
                agent_id=ExecutorId(AGENT_ID),
                model=request.model,
                billing_mode=u.billing_mode,
                tokens_in=u.tokens_in,
                tokens_out=u.tokens_out,
                tokens_cached_in=u.tokens_cached_in,
                tokens_cache_write_in=u.tokens_cache_write_in,
                chars_in=u.chars_in,
                language=self._language,
                price_ref=u.price_ref,
                idempotency_key=key,
            ),
        )
        self._budget.after_call(sc.tx, entry)
        self._meter.after(response, str(entry.id))
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
