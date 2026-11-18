"""Structured LLM calls: budget check, idempotent paid call, ledger row, parse, one repair.

The model has no tools; it can only return JSON that code validates (blueprint 1.3). A parse or
schema failure is retried once with the validation error (positions and messages only, never the
offending text), then raises ``AGENT.INVALID_JSON`` / ``AGENT.OUTPUT_SCHEMA_INVALID`` (07 agent_parse).
"""

import json
import re
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ValidationError

from agent_04_research_knowledge.errors import InvalidJson, OutputSchemaInvalid
from agent_04_research_knowledge.runtime import RunInfo
from agent_04_research_knowledge.settings import StepLlm
from amw_adapters.llm.protocol import LlmAdapter, LlmMessage, LlmRequest, LlmResponse
from amw_core.enums import CostFigureKind
from amw_core.ids import ExecutorId, IdempotencyScope, idempotency_key_of, make_idempotency_key
from amw_core.interfaces import (
    BudgetGuard,
    CallCheck,
    Clock,
    CostLedger,
    NewCostEntry,
    TenancyContext,
)

_FENCE: Final = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_json_object(text: str) -> object:
    """JSON from a model reply; a single fenced block is tolerated. ``InvalidJson`` otherwise."""
    candidate = text.strip()
    fenced = _FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise InvalidJson(f"model output is not JSON ({exc.msg} at {exc.pos})") from None


def schema_problems[T: BaseModel](model: type[T], data: object) -> tuple[T | None, str]:
    """Validate; the error text names locations and rule types only (no values)."""
    try:
        return model.model_validate(data), ""
    except ValidationError as exc:
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors()[:20]]
        return None, "; ".join(parts)


@dataclass(frozen=True, slots=True)
class CallResult[T: BaseModel]:
    value: T
    last_seq: int


class StructuredLlmCaller:
    def __init__(
        self,
        llm: LlmAdapter,
        tenancy: TenancyContext,
        budget: BudgetGuard,
        ledger: CostLedger,
        clock: Clock,
    ) -> None:
        self._llm, self._tenancy = llm, tenancy
        self._budget, self._ledger, self._clock = budget, ledger, clock

    def _one_call(
        self,
        run: RunInfo,
        step: StepLlm,
        step_key: str,
        call_seq: int,
        system: str,
        user: str,
        language: str | None,
    ) -> LlmResponse:
        run.counter.take()
        with self._tenancy.transaction(run.context) as tx:
            self._budget.check_call(
                tx,
                CallCheck(
                    task_id=run.task_id,
                    job_id=run.job_id,
                    provider=self._llm.provider,
                    estimated_cost_micros=step.cost_budget_micros,
                    currency=run.currency,
                ),
            )
        key = make_idempotency_key(
            run.context.org_id, IdempotencyScope.LLM_CALL, [run.task_id, step_key, call_seq]
        )
        request = LlmRequest(
            model=step.model,
            system=system,
            messages=(LlmMessage(role="user", content=user),),
            max_output_tokens=step.max_output_tokens,
            temperature=step.temperature,
            timeout_ms=step.timeout_ms,
            cache_system_prompt=step.cache_system_prompt,
            language=language,
        )
        response = self._llm.complete(request, idempotency_key=key)
        usage = response.usage
        with self._tenancy.transaction(run.context) as tx:
            entry = self._ledger.record(
                tx,
                NewCostEntry(
                    provider=usage.provider,
                    operation=usage.operation,
                    amount_micros=usage.amount_micros,
                    currency=usage.currency,
                    figure_kind=CostFigureKind.ESTIMATE,
                    occurred_at=self._clock.now(),
                    job_id=run.job_id,
                    task_id=run.task_id,
                    attempt_id=run.attempt_id,
                    agent_id=ExecutorId("agent_04"),
                    model=usage.model,
                    billing_mode=usage.billing_mode,
                    tokens_in=usage.tokens_in,
                    tokens_out=usage.tokens_out,
                    tokens_cached_in=usage.tokens_cached_in,
                    tokens_cache_write_in=usage.tokens_cache_write_in,
                    chars_in=usage.chars_in,
                    language=usage.language,
                    price_ref=usage.price_ref,
                    idempotency_key=idempotency_key_of(usage.idempotency_key),
                ),
            )
            self._budget.after_call(tx, entry)
        totals = run.usage
        totals.llm_calls += 1
        totals.tokens_in += usage.tokens_in or 0
        totals.tokens_out += usage.tokens_out or 0
        totals.tokens_cached_in += usage.tokens_cached_in or 0
        totals.cost_micros += usage.amount_micros
        totals.cost_entry_ids.append(entry.id)
        return response

    def call[T: BaseModel](
        self,
        run: RunInfo,
        step: StepLlm,
        step_key: str,
        system: str,
        user: str,
        model: type[T],
        *,
        repairs: int = 1,
        language: str | None = None,
        seq_start: int = 1,
    ) -> CallResult[T]:
        """One structured call; up to ``repairs`` re-asks with the validation error appended.

        ``seq_start`` continues the ``call_seq`` of the idempotency key after an earlier call of
        the same step (a quality repair), so no two different requests share a key.
        """
        seq = seq_start
        message = user
        while True:
            response = self._one_call(run, step, step_key, seq, system, message, language)
            problem = ""
            try:
                parsed, problem = schema_problems(model, parse_json_object(response.text))
                if parsed is not None:
                    return CallResult(parsed, seq)
                error: type[InvalidJson | OutputSchemaInvalid] = OutputSchemaInvalid
            except InvalidJson as exc:
                problem, error = exc.message, InvalidJson
            run.log.warning("research.llm_output_invalid", step_key=step_key, call_seq=seq)
            if seq - seq_start >= repairs:
                raise error(
                    "model output rejected after the repair", details={"step_key": step_key}
                )
            message = (
                f"{user}\n\n<validation_error>\nYour previous answer was rejected: {problem}. "
                "Return one corrected JSON object only.\n</validation_error>"
            )
            seq += 1
