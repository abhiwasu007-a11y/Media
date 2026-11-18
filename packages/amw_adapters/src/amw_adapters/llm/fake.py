"""Deterministic in-memory LLM fake (no network)."""

from typing import Any

from amw_adapters.common import (
    FAKE_PRICE_REF,
    CallUsage,
    FailurePlan,
    FakeEngine,
    FakeProvider,
    FixtureStore,
    fake_provider,
)
from amw_adapters.llm.protocol import (
    OPERATION_COMPLETION,
    OPERATION_COUNT_TOKENS,
    LlmRequest,
    LlmResponse,
    TokenCount,
)


def _approx_tokens(request: LlmRequest) -> int:
    chars = len(request.system) + sum(len(m.content) for m in request.messages)
    return max(1, chars // 4)


class FakeLlmAdapter:
    def __init__(
        self,
        *,
        provider: str = FakeProvider.LLM,
        currency: str = "USD",
        input_price_micros_per_token: int = 1,
        output_price_micros_per_token: int = 5,
        failures: FailurePlan | None = None,
        fixtures: FixtureStore | None = None,
    ) -> None:
        self._provider = fake_provider(provider)
        self._currency = currency
        self._in_price = input_price_micros_per_token
        self._out_price = output_price_micros_per_token
        self.engine = FakeEngine("llm", failures=failures, fixtures=fixtures)

    @property
    def provider(self) -> str:
        return self._provider

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        def build(digest: str, fixture: dict[str, Any] | None) -> LlmResponse:
            fx = fixture or {}
            text = str(fx.get("text", f"fake completion {digest[:16]}"))
            tokens_in = int(fx.get("tokens_in", _approx_tokens(request)))
            tokens_out = min(
                int(fx.get("tokens_out", max(1, len(text) // 4))), request.max_output_tokens
            )
            cached = int(fx.get("tokens_cached_in", 0))
            usage = CallUsage(
                provider=self._provider,
                operation=OPERATION_COMPLETION,
                model=request.model,
                billing_mode=request.billing_mode,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_cached_in=cached,
                tokens_cache_write_in=int(fx.get("tokens_cache_write_in", 0)),
                chars_in=len(request.system) + sum(len(m.content) for m in request.messages),
                language=request.language,
                amount_micros=tokens_in * self._in_price + tokens_out * self._out_price,
                currency=self._currency,
                price_ref=FAKE_PRICE_REF,
                idempotency_key=idempotency_key,
                external_request_id=f"fake-{digest[:12]}",
            )
            return LlmResponse(
                text=text, stop_reason=fx.get("stop_reason", "end_turn"), usage=usage
            )

        return self.engine.run(OPERATION_COMPLETION, idempotency_key, request, build, LlmResponse)

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> TokenCount:
        def build(_digest: str, fixture: dict[str, Any] | None) -> TokenCount:
            tokens_in = int((fixture or {}).get("tokens_in", _approx_tokens(request)))
            usage = CallUsage(
                provider=self._provider,
                operation=OPERATION_COUNT_TOKENS,
                model=request.model,
                tokens_in=tokens_in,
                amount_micros=0,
                currency=self._currency,
                price_ref=FAKE_PRICE_REF,
                idempotency_key=idempotency_key,
            )
            return TokenCount(tokens_in=tokens_in, usage=usage)

        return self.engine.run(OPERATION_COUNT_TOKENS, idempotency_key, request, build, TokenCount)
