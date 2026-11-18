"""LLM adapter Protocol for the eval runner (local, minimal).

The real ``amw_adapters`` LLM Protocol (Step 0) will replace this module's Protocol; the runner only
depends on ``LlmAdapter.complete``. Money is integer micros, never float (27 section 7.3 rule 9).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from amw_evals.findings import JsonObject


@dataclass(frozen=True)
class LlmRequest:
    case_id: str
    prompt_id: str
    prompt_text: str
    input_payload: JsonObject
    output_schema: JsonObject | None


@dataclass(frozen=True)
class LlmResponse:
    output: object  # parsed JSON expected; anything else fails the schema assertion
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached_in: int = 0
    cost_micros: int = 0
    currency: str = "USD"
    latency_ms: int = 0


@runtime_checkable
class LlmAdapter(Protocol):
    provider: str
    model: str
    is_fake: bool

    def complete(self, request: LlmRequest) -> LlmResponse: ...


class FakeAdapter:
    """Replays canned outputs keyed by case_id. Never calls anything; always free."""

    provider = "fake"
    model = "fake-1"
    is_fake = True

    def __init__(self, responses: Mapping[str, LlmResponse]) -> None:
        self._responses = dict(responses)
        self.calls: list[str] = []

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls.append(request.case_id)
        try:
            return self._responses[request.case_id]
        except KeyError:
            raise KeyError(f"FakeAdapter has no canned response for {request.case_id}") from None


class BudgetError(RuntimeError):
    """A paid run was requested without an explicit cost cap, or the cap was exceeded."""


BUDGET_ENV = "EVAL_MAX_COST_MICROS"


def resolve_budget(adapter: LlmAdapter, env: Mapping[str, str]) -> int | None:
    """Return the cost cap in micros (None = unlimited, fake adapters only).

    Rule: no paid calls. A non-fake adapter runs only when EVAL_MAX_COST_MICROS is set to a positive
    integer (owner-authorised budget, 27 section 8.3/8.4).
    """
    raw = env.get(BUDGET_ENV, "").strip()
    if raw:
        if not raw.isdigit() or int(raw) <= 0:
            raise BudgetError(f"{BUDGET_ENV} must be a positive integer (micros), got {raw!r}")
        return int(raw)
    if not adapter.is_fake:
        raise BudgetError(
            f"refusing to run non-fake adapter '{adapter.provider}' without {BUDGET_ENV} "
            "(no paid calls without an owner-set budget)"
        )
    return None
