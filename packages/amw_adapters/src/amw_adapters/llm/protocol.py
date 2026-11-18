"""LLM adapter Protocol (ADR-007 section 2: one Protocol, provider by config, per-call cost).

Model IDs come from config (``llm.tiers.<tier>.model``), never from code. Failures use 07 codes
(ADR-007 section 2.10): 429 -> ``RateLimitedError``, 5xx -> ``Upstream5xxError``, timeout ->
``CallTimeoutError``, 401/403 -> ``AuthInvalidError``, safety refusal -> ``ProviderRefusalError``.
Batch submit/poll is 3C (ADR-007 section 2.6) and not in this Protocol yet.
"""

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import Field

from amw_adapters.common import AdapterModel, AdapterResult
from amw_core.enums import BillingMode

OPERATION_COMPLETION = "llm.completion"
OPERATION_COUNT_TOKENS = "llm.count_tokens"


class LlmMessage(AdapterModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1)]


class LlmRequest(AdapterModel):
    model: Annotated[str, Field(min_length=1)]
    system: str
    messages: Annotated[tuple[LlmMessage, ...], Field(min_length=1)]
    max_output_tokens: Annotated[int, Field(ge=1)]
    temperature: Annotated[float, Field(ge=0, le=2)] = 0.0
    timeout_ms: Annotated[int, Field(ge=1)] = 120_000
    cache_system_prompt: bool = False
    billing_mode: BillingMode = BillingMode.STANDARD


class LlmResponse(AdapterResult):
    text: str
    stop_reason: Literal["end_turn", "max_tokens", "stop_sequence"]


class TokenCount(AdapterResult):
    tokens_in: int


@runtime_checkable
class LlmAdapter(Protocol):
    @property
    def provider(self) -> str: ...

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        """One completion (idempotency scope ``llm.call``: task, step key, call seq)."""
        ...

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> TokenCount:
        """Input-token count where the provider supports it (E2 worst-case estimate)."""
        ...
