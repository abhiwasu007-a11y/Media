"""``StructuredCaller`` (blueprint 10.7, 11, NFR-03/05): one LLM step with bounded repairs.

Per step at most one parse repair (invalid JSON or schema: the call appends the validation error)
and at most one quality repair (a deterministic check failed: the call lists the failed check IDs),
so at most 3 calls. A parse failure of the quality-repair call is not repaired again. Every call is
reserved against the budget first, keyed ``(task_id, step_key, call_seq)`` for idempotency (scope
``llm.call``, 03 section 9.2) and captured in the cost ledger. The model has no tools.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from agent_05_scriptwriter.checks.results import CheckResult, failing_ids
from agent_05_scriptwriter.errors import (
    InvalidJson,
    LoopCapExceeded,
    OutputSchemaInvalid,
    QualityRepeatedFailure,
)
from agent_05_scriptwriter.llm.prompt_renderer import RenderedPrompt
from agent_05_scriptwriter.observability import log_event
from agent_05_scriptwriter.protocols import CallBudget, CallLedger, LedgerRow, StepContext
from agent_05_scriptwriter.settings import LlmStepSettings
from amw_adapters.llm import LlmAdapter, LlmMessage, LlmRequest
from amw_core.ids import IdempotencyScope, make_idempotency_key


@dataclass(slots=True)
class CallRecord:
    step_key: str
    call_seq: int
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    tokens_cached_in: int
    cost_entry_id: str
    amount_micros: int = 0

    def as_dict(self) -> dict[str, str | int]:
        return {
            "step_key": self.step_key,
            "call_seq": self.call_seq,
            "provider": self.provider,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_cached_in": self.tokens_cached_in,
            "cost_entry_id": self.cost_entry_id,
            "amount_micros": self.amount_micros,
        }


@dataclass(slots=True)
class CallCounter:
    """LLM calls of the whole task against ``resource_budget.max_llm_calls``."""

    used: int = 0


@dataclass(slots=True)
class StepResult[T: BaseModel]:
    parsed: T
    results: list[CheckResult]
    records: list[CallRecord] = field(default_factory=list)
    repaired: bool = False


Check = Callable[[BaseModel], list[CheckResult]]


def _validation_summary(exc: ValidationError) -> str:
    """Locations and messages only: never the offending input values (they may be content)."""
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:20])


class StructuredCaller:
    def __init__(
        self, llm: LlmAdapter, ledger: CallLedger, budget: CallBudget, counter: CallCounter
    ) -> None:
        self._llm = llm
        self._ledger = ledger
        self._budget = budget
        self._counter = counter

    def run_step[T: BaseModel](
        self,
        ctx: StepContext,
        *,
        model_cls: type[T],
        step: LlmStepSettings,
        step_key: str,
        rendered: RenderedPrompt,
        language: str,
        check: Callable[[T], list[CheckResult]],
        is_refusal: Callable[[T], bool],
    ) -> StepResult[T]:
        records: list[CallRecord] = []
        messages: list[LlmMessage] = [LlmMessage(role="user", content=rendered.user)]
        seq = 0
        parse_repaired = False
        quality_repaired = False
        while True:
            text = self._call(
                ctx, step, step_key, seq, rendered.system, messages, language, records
            )
            try:
                parsed = model_cls.model_validate(json.loads(text))
            except (json.JSONDecodeError, ValidationError) as exc:
                invalid_json = isinstance(exc, json.JSONDecodeError)
                if parse_repaired or quality_repaired:
                    log_event("llm_step.parse_failed", step_key=step_key, repair=True)
                    if invalid_json:
                        raise InvalidJson("model output is not valid JSON") from None
                    raise OutputSchemaInvalid("model output violates the schema") from None
                parse_repaired = True
                detail = (
                    "the output is not valid JSON"
                    if isinstance(exc, json.JSONDecodeError)
                    else _validation_summary(exc)
                )
                messages += [
                    LlmMessage(role="assistant", content=text or "(empty)"),
                    LlmMessage(
                        role="user",
                        content="Your output was rejected: "
                        + detail
                        + ". Return one corrected JSON object only.",
                    ),
                ]
                seq += 1
                continue
            if is_refusal(parsed):
                return StepResult(
                    parsed, check(parsed), records, parse_repaired or quality_repaired
                )
            results = check(parsed)
            failing = failing_ids(results)
            if not failing:
                return StepResult(parsed, results, records, parse_repaired or quality_repaired)
            log_event("llm_step.quality_failed", step_key=step_key, check_ids=failing)
            if quality_repaired:
                raise QualityRepeatedFailure(
                    "deterministic checks still fail after the repair",
                    details={"step_key": step_key, "check_ids": failing},
                )
            quality_repaired = True
            messages += [
                LlmMessage(role="assistant", content=text),
                LlmMessage(
                    role="user",
                    content="These deterministic checks failed: "
                    + ", ".join(failing)
                    + _rule_hint(results)
                    + ". Fix them and return one corrected JSON object only.",
                ),
            ]
            seq += 1

    def _call(
        self,
        ctx: StepContext,
        step: LlmStepSettings,
        step_key: str,
        seq: int,
        system: str,
        messages: Sequence[LlmMessage],
        language: str,
        records: list[CallRecord],
    ) -> str:
        if self._counter.used >= ctx.max_llm_calls:
            raise LoopCapExceeded("max_llm_calls reached", details={"step_key": step_key})
        self._budget.check_call(ctx, step.cost_budget_micros)
        request = LlmRequest(
            model=step.model,
            system=system,
            messages=tuple(messages),
            max_output_tokens=step.max_output_tokens,
            temperature=step.temperature,
            timeout_ms=step.timeout_ms,
            cache_system_prompt=step.cache_system_prompt,
            language=language,
        )
        key = make_idempotency_key(
            ctx.org_id, IdempotencyScope.LLM_CALL, [ctx.task_id, step_key, seq]
        )
        self._counter.used += 1
        response = self._llm.complete(request, idempotency_key=key)
        row: LedgerRow = self._ledger.record(ctx, step_key, seq, response.usage)
        records.append(
            CallRecord(
                step_key,
                seq,
                row.provider,
                row.model,
                row.tokens_in,
                row.tokens_out,
                row.tokens_cached_in,
                row.cost_entry_id,
                row.amount_micros,
            )
        )
        log_event(
            "llm_step.call",
            step_key=step_key,
            count=seq,
            org_id=ctx.org_id,
            task_id=ctx.task_id,
        )
        return response.text


def _rule_hint(results: Sequence[CheckResult]) -> str:
    rules = sorted({r for res in results if res.failed_blocking for r in res.rule_ids})
    return f" (rules: {', '.join(rules)})" if rules else ""
