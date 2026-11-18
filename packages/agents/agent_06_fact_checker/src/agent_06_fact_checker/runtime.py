"""Run context, paid-call runner and checkpoints shared by both steps (07 section 10; ADR-007).

``PaidCallRunner`` is the only place a model is called: budget check (E2) before, the adapter call
with a ``llm.call`` idempotency key, a cost-ledger row and ``after_call`` (E3) after, a parse into
a Pydantic model and at most one repair with the validation error appended. ``StepCheckpoints``
writes the validated state after each paid call so a resume never pays twice (FR-15).
"""

import io
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError

from agent_06_fact_checker.config import LlmStepSettings
from agent_06_fact_checker.hashing import canonical_json, sha256_hex
from agent_06_fact_checker.prompts import RenderedPrompt, user_message
from amw_adapters.llm.protocol import LlmAdapter, LlmMessage, LlmRequest, LlmResponse
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import CostFigureKind
from amw_core.errors import (
    InvalidJsonError,
    LoopCapExceededError,
    OutputSchemaInvalidError,
)
from amw_core.ids import (
    ActorRef,
    AttemptId,
    ChannelId,
    CorrelationId,
    IdempotencyKey,
    JobId,
    OrgId,
    TaskId,
    make_idempotency_key,
)
from amw_core.interfaces import (
    BlobStorage,
    BlobUri,
    BudgetGuard,
    CallCheck,
    CheckpointStore,
    Clock,
    CostLedger,
    NewCheckpoint,
    NewCostEntry,
    TenancyContext,
    TenantContext,
)

AGENT_ID = "agent_06"


@dataclass(frozen=True, slots=True)
class RunContext:
    """What the worker hands a step besides the Task Input."""

    attempt_id: AttemptId
    stage_id: str
    iteration: int = 0
    """The stage's revision counter (V2 check 6); ``None`` is never accepted."""

    def tenant(self, task: TaskInput) -> TenantContext:
        return TenantContext(
            org_id=OrgId(task.org_id),
            actor=ActorRef(AGENT_ID),
            correlation_id=CorrelationId(task.correlation_id),
        )


@dataclass(slots=True)
class UsageTotals:
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached_in: int = 0
    llm_calls: int = 0
    cost_micros: int = 0
    currency: str = "USD"
    cost_entry_ids: list[str] = field(default_factory=list)


def task_key(task: TaskInput) -> TaskId:
    return TaskId(task.task_id)


class PaidCallRunner:
    """Reservation check, adapter call, ledger row, parse, one repair (blueprint 10.2, 10.4)."""

    def __init__(
        self,
        *,
        llm: LlmAdapter,
        budget: BudgetGuard,
        ledger: CostLedger,
        tenancy: TenancyContext,
        clock: Clock,
        settings: LlmStepSettings,
        max_repairs: int,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._ledger = ledger
        self._tenancy = tenancy
        self._clock = clock
        self._settings = settings
        self._max_repairs = max_repairs

    def complete_json[M: BaseModel](
        self,
        *,
        task: TaskInput,
        ctx: RunContext,
        usage: UsageTotals,
        step_key: str,
        prompt: RenderedPrompt,
        variables: dict[str, object],
        model: type[M],
        language: str,
        check: Callable[[M], Sequence[str]],
    ) -> M:
        """One paid call (+ at most one repair). ``check`` returns problems that justify a repair
        (ids only, never claim text); an empty list accepts the result."""
        messages: list[LlmMessage] = [LlmMessage(role="user", content=user_message(variables))]
        cap = task.resource_budget.max_llm_calls
        for attempt in range(self._max_repairs + 1):
            if cap is not None and usage.llm_calls >= cap:
                raise LoopCapExceededError("max_llm_calls reached")
            raw = self._call(task, ctx, usage, f"{step_key}", attempt, prompt, messages, language)
            parsed, problems, invalid_json = self._parse(model, raw, check)
            if not problems and parsed is not None:
                return parsed
            if attempt >= self._max_repairs:
                details = {"step_key": step_key, "problems": problems[:20]}
                text = f"{step_key}: {len(problems)} problem(s) after the repair"
                if invalid_json:
                    raise InvalidJsonError(text, details=details)
                raise OutputSchemaInvalidError(text, details=details)
            messages.append(LlmMessage(role="assistant", content=raw))
            messages.append(
                LlmMessage(
                    role="user",
                    content="Your output was rejected. Return one corrected JSON object only. "
                    "Problems: " + "; ".join(problems[:20]),
                )
            )
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _parse[M: BaseModel](
        model: type[M], raw: str, check: Callable[[M], Sequence[str]]
    ) -> tuple[M | None, list[str], bool]:
        try:
            parsed = model.model_validate(_loads(raw))
        except InvalidJsonError as exc:
            return None, [f"not valid JSON: {exc.message}"], True
        except ValidationError as exc:
            return None, [_pydantic_problem(exc)], False
        return parsed, list(check(parsed)), False

    def _call(
        self,
        task: TaskInput,
        ctx: RunContext,
        usage: UsageTotals,
        step_key: str,
        seq: int,
        prompt: RenderedPrompt,
        messages: Sequence[LlmMessage],
        language: str,
    ) -> str:
        tenant = ctx.tenant(task)
        key = make_idempotency_key(task.org_id, "llm.call", [task.task_id, step_key, seq])
        request = LlmRequest(
            model=self._settings.model,
            system=prompt.system,
            messages=tuple(messages),
            max_output_tokens=self._settings.max_output_tokens,
            temperature=self._settings.temperature,
            timeout_ms=self._settings.timeout_ms,
            cache_system_prompt=self._settings.cache_system_prompt,
            language=language,
        )
        with self._tenancy.transaction(tenant) as tx:
            self._budget.check_call(
                tx,
                CallCheck(
                    task_id=task_key(task),
                    job_id=JobId(task.job_id),
                    provider=self._llm.provider,
                    estimated_cost_micros=self._settings.cost_budget_micros,
                    currency=self._settings.currency,
                ),
            )
        response: LlmResponse = self._llm.complete(request, idempotency_key=key)
        self._record(task, ctx, usage, response, key)
        return response.text

    def _record(
        self,
        task: TaskInput,
        ctx: RunContext,
        usage: UsageTotals,
        response: LlmResponse,
        key: IdempotencyKey,
    ) -> None:
        u = response.usage
        entry = NewCostEntry(
            provider=u.provider,
            operation=u.operation,
            amount_micros=u.amount_micros,
            currency=u.currency,
            figure_kind=CostFigureKind.ESTIMATE,
            occurred_at=self._clock.now(),
            job_id=JobId(task.job_id),
            task_id=task_key(task),
            attempt_id=ctx.attempt_id,
            channel_id=ChannelId(task.channel_id) if task.channel_id else None,
            agent_id=None,
            model=u.model,
            billing_mode=u.billing_mode,
            tokens_in=u.tokens_in,
            tokens_out=u.tokens_out,
            tokens_cached_in=u.tokens_cached_in,
            tokens_cache_write_in=u.tokens_cache_write_in,
            chars_in=u.chars_in,
            language=u.language,
            price_ref=u.price_ref,
            idempotency_key=key,
        )
        with self._tenancy.transaction(ctx.tenant(task)) as tx:
            row = self._ledger.record(tx, entry)
            self._budget.after_call(tx, row)
        usage.llm_calls += 1
        usage.tokens_in += u.tokens_in or 0
        usage.tokens_out += u.tokens_out or 0
        usage.tokens_cached_in += u.tokens_cached_in or 0
        usage.cost_micros += u.amount_micros
        usage.currency = u.currency
        usage.cost_entry_ids.append(row.id)


def _loads(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):  # a fenced block is still one JSON value
        text = text.strip("`")
        text = text[text.find("{") :] if "{" in text else text
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidJsonError(f"line {exc.lineno} column {exc.colno}: {exc.msg}") from None


def _pydantic_problem(exc: ValidationError) -> str:
    """Locations and error types only: no input value, no claim text, reaches logs or errors."""
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors()[:20]
    )


class StepCheckpoints:
    """Checkpoint rows (04 5.7) whose state blob holds the validated results per step key."""

    def __init__(
        self,
        *,
        store: CheckpointStore,
        blobs: BlobStorage,
        tenancy: TenancyContext,
        clock: Clock,
        task: TaskInput,
        ctx: RunContext,
    ) -> None:
        self._store = store
        self._blobs = blobs
        self._tenancy = tenancy
        self._clock = clock
        self._task = task
        self._ctx = ctx
        self._seq = 0
        self.state: dict[str, Any] = {}
        self._effects: list[IdempotencyKey] = []

    def load(self) -> dict[str, Any]:
        tenant = self._ctx.tenant(self._task)
        with self._tenancy.transaction(tenant) as tx:
            record = self._store.latest(tx, task_key(self._task))
        if record is None:
            return self.state
        self._seq = record.seq
        data = b"".join(
            self._blobs.get(
                tenant,
                _blob(record.checkpoint.state_ref),
                record.checkpoint.state_sha256,
            )
        )
        loaded = json.loads(data.decode("utf-8"))
        self.state = dict(loaded)
        self._effects = list(record.checkpoint.completed_effects)
        return self.state

    def save(self, step_key: str, value: Any, progress: float | None = None) -> None:
        """Record ``value`` under ``step_key`` and write a new checkpoint row."""
        self.state[step_key] = value
        tenant = self._ctx.tenant(self._task)
        body = canonical_json(self.state).encode("utf-8")
        job = self._task.job_id
        path = f"{job}/checkpoints/{self._task.task_id}/{self._seq + 1:04d}.json"
        uri = self._blobs.blob_uri(tenant, "jobs", path)
        info = self._blobs.put(tenant, uri, io.BytesIO(body))
        self._effects.append(
            make_idempotency_key(self._task.org_id, "db.output", [self._task.task_id, step_key])
        )
        ratio = None if progress is None else Decimal(str(round(progress, 3)))
        with self._tenancy.transaction(tenant) as tx:
            record = self._store.write(
                tx,
                NewCheckpoint(
                    task_id=task_key(self._task),
                    attempt_id=self._ctx.attempt_id,
                    step_key=step_key,
                    state_ref=info.uri,
                    state_sha256=sha256_hex(body),
                    completed_effects=tuple(self._effects),
                    progress_ratio=ratio,
                ),
                self._clock.now(),
            )
        self._seq = record.seq


def _blob(uri: str) -> BlobUri:
    return BlobUri(uri)
