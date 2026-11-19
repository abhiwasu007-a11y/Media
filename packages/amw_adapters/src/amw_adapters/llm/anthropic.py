"""Anthropic Messages API adapter (ADR-007; facts PR-08, PR-09, PR-10).

* Plain HTTPS through ``httpx`` (``ProviderHttp``, injectable transport). No SDK: nothing else
  in the lock needs it, and the adapter uses two endpoints only.
* The model gets text in and returns text; **no tools are sent and none can run** (prompt
  injection cannot trigger an action). Structured output is parsed and schema-validated by the
  CALLER (agents' structured callers, 27 section 7.3), so the adapter never interprets content.
* ``temperature`` of ``LlmRequest`` is never sent: API version 2026-10-21 removes sampling
  parameters on every model (PR-08). The value is ignored and logged as ignored (CCR-250).
* Refusal (``stop_reason = refusal``) raises ``ProviderRefusalError``; its ``details`` carry the
  refusal category, whether it is billed (PR-10) and the ``usage`` dict of the cost row the
  caller must still record (CCR-252).
* Cost = integer micros from the catalogue price table (``price_ref``), rounded up, always an
  ESTIMATE; an unknown model is ``CONFIG_INVALID`` before any request is sent.
* Logs carry the request id, token counts and a SHA-256 of the request body, never the key or
  any prompt or response text.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any, Final, Literal

import httpx

from amw_adapters.common import CallUsage, request_sha256
from amw_adapters.llm.protocol import (
    OPERATION_COMPLETION,
    OPERATION_COUNT_TOKENS,
    LlmRequest,
    LlmResponse,
    TokenCount,
)
from amw_adapters.real.catalogue import AnthropicCatalogue, AnthropicModel
from amw_adapters.real.guard import CallGuard, PlannedCall, delivery_of, require_guard
from amw_adapters.real.http import (
    DEFAULT_BACKOFF,
    ProviderHttp,
    body_sha256,
    json_or_empty,
    retry_after_ms,
    status_error,
)
from amw_adapters.real.memory import CallMemory
from amw_adapters.real.secrets import SecretRef
from amw_core.config import RetryPolicySettings
from amw_core.enums import BillingMode
from amw_core.errors import (
    AmwError,
    ConfigInvalidError,
    CorruptedOutputError,
    IncompleteOutputError,
    InputInvalidError,
    ProviderRefusalError,
    Upstream5xxError,
)

PROVIDER: Final = "anthropic"
MESSAGES_PATH: Final = "/v1/messages"
COUNT_PATH: Final = "/v1/messages/count_tokens"
_STOP_MAP: Final[dict[str, Literal["end_turn", "max_tokens", "stop_sequence"]]] = {
    "end_turn": "end_turn",
    "max_tokens": "max_tokens",
    "stop_sequence": "stop_sequence",
    "model_context_window_exceeded": "max_tokens",
}
"""``model_context_window_exceeded`` truncates the output like ``max_tokens`` (PR-08)."""
_COUNT_TIMEOUT_MS: Final = 30_000
"""Token counting is a small free call (PR-08); ESTIMATE design default."""


def _classify(response: httpx.Response) -> AmwError:
    body = json_or_empty(response)
    err = body.get("error")
    code = str(err.get("type")) if isinstance(err, dict) and err.get("type") else None
    status = response.status_code
    hint = retry_after_ms(response)
    if status == 529 or code == "overloaded_error":
        return Upstream5xxError(
            "provider overloaded", provider=PROVIDER, upstream_status=status,
            upstream_code=code, retry_after_ms=hint,
        )  # fmt: skip
    return status_error(status, provider=PROVIDER, upstream_code=code, retry_after=hint)


def _int(usage: Mapping[str, Any], name: str) -> int:
    value = usage.get(name)
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CorruptedOutputError("provider usage field invalid", details={"field": name})
    return value


def cost_micros(
    model: AnthropicModel, usage: Mapping[str, Any], default_ttl: Literal["5m", "1h"]
) -> int:
    """Integer micros (rounded up) of one response's usage (PR-10). Prompt length for the band
    counts input, cache reads and cache writes (PR-10)."""
    tokens_in = _int(usage, "input_tokens")
    tokens_out = _int(usage, "output_tokens")
    cache_read = _int(usage, "cache_read_input_tokens")
    cache_write = _int(usage, "cache_creation_input_tokens")
    split = usage.get("cache_creation")
    if isinstance(split, Mapping) and (
        "ephemeral_5m_input_tokens" in split or "ephemeral_1h_input_tokens" in split
    ):
        write_5m = _int(split, "ephemeral_5m_input_tokens")
        write_1h = _int(split, "ephemeral_1h_input_tokens")
    elif default_ttl == "1h":
        write_5m, write_1h = 0, cache_write
    else:
        write_5m, write_1h = cache_write, 0
    band = model.band(tokens_in + cache_read + cache_write)
    per_mtok = (
        tokens_in * band.input
        + write_5m * band.cache_write_5m
        + write_1h * band.cache_write_1h
        + cache_read * band.cache_read
        + tokens_out * band.output
    )
    return -(-per_mtok // 1_000_000)


def worst_case_micros(model: AnthropicModel, request: LlmRequest, overhead_tokens: int) -> int:
    """Upper bound of one ``complete`` call in integer micros, computed locally before the request.

    Prompt tokens are bounded by the UTF-8 bytes of system + messages (a token covers at least one
    byte) plus the catalogue framing allowance; every prompt token is priced at the dearest of the
    input / cache-write rates (cache read is cheaper); the dearest price band up to that prompt
    length is used; output is ``max_output_tokens`` at the output rate.
    """
    prompt = len(request.system.encode("utf-8")) + sum(
        len(m.content.encode("utf-8")) for m in request.messages
    )
    prompt += overhead_tokens
    worst = 0
    for band in model.prices:
        per_in = max(band.input, band.cache_write_5m, band.cache_write_1h)
        total = prompt * per_in + request.max_output_tokens * band.output
        worst = max(worst, -(-total // 1_000_000))
        if band.max_prompt_tokens is None or prompt <= band.max_prompt_tokens:
            break
    return worst


class AnthropicLlmAdapter:
    """``LlmAdapter`` against the Anthropic Messages API.

    Needs a ``CallGuard`` bound to a passed REAL_RUN preflight for ``anthropic``: every request
    is preceded by ``guard.before`` (worst case, refused before the request) and every response
    that arrives is recorded through ``guard.after``."""

    def __init__(
        self,
        catalogue: AnthropicCatalogue,
        secret: SecretRef,
        *,
        guard: CallGuard,
        transport: httpx.BaseTransport | None = None,
        backoff: RetryPolicySettings = DEFAULT_BACKOFF,
        sleep: Callable[[float], None] | None = None,
        uniform: Callable[[], float] | None = None,
    ) -> None:
        self._cat = catalogue
        self._secret = secret
        self._guard = require_guard(guard, provider=PROVIDER, currency=catalogue.currency)
        extra: dict[str, Any] = {}
        if sleep is not None:
            extra["sleep"] = sleep
        if uniform is not None:
            extra["uniform"] = uniform
        self._http = ProviderHttp(
            provider=PROVIDER,
            base_url=catalogue.base_url,
            connect_timeout_ms=catalogue.connect_timeout_ms,
            retry=catalogue.retry,
            classify=_classify,
            transport=transport,
            backoff=backoff,
            **extra,
        )
        self.memory = CallMemory()

    @property
    def provider(self) -> str:
        return PROVIDER

    def close(self) -> None:
        self._http.close()

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._secret.reveal(),
            "anthropic-version": self._cat.api_version,
            "content-type": "application/json",
            "accept": "application/json",
        }

    def _body(self, request: LlmRequest, *, with_max_tokens: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if request.system:
            if request.cache_system_prompt:
                control: dict[str, str] = {"type": "ephemeral"}
                if self._cat.cache_ttl != "5m":
                    control["ttl"] = self._cat.cache_ttl
                body["system"] = [
                    {"type": "text", "text": request.system, "cache_control": control}
                ]
            else:
                body["system"] = request.system
        if with_max_tokens:
            body["max_tokens"] = request.max_output_tokens
        return body

    def _check(self, request: LlmRequest) -> AnthropicModel:
        model = self._cat.model(request.model)
        if request.billing_mode is BillingMode.BATCH:
            raise ConfigInvalidError("batch submission is not part of this adapter (ADR-007 2.6)")
        if request.max_output_tokens > model.max_output_tokens:
            raise InputInvalidError(
                "max_output_tokens above the model maximum",
                details={"model": request.model, "max": model.max_output_tokens},
            )
        return model

    def _usage(
        self,
        operation: str,
        request: LlmRequest,
        key: str,
        usage: Mapping[str, Any],
        amount: int,
        request_id: str | None,
    ) -> CallUsage:
        return CallUsage(
            provider=PROVIDER,
            operation=operation,
            model=request.model,
            billing_mode=request.billing_mode,
            tokens_in=_int(usage, "input_tokens"),
            tokens_out=_int(usage, "output_tokens"),
            tokens_cached_in=_int(usage, "cache_read_input_tokens"),
            tokens_cache_write_in=_int(usage, "cache_creation_input_tokens"),
            chars_in=len(request.system) + sum(len(m.content) for m in request.messages),
            language=request.language,
            amount_micros=amount,
            currency=self._cat.currency,
            price_ref=self._cat.price_ref,
            idempotency_key=key,
            external_request_id=request_id,
        )

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        digest, stored = self.memory.lookup(
            OPERATION_COMPLETION, idempotency_key, request, LlmResponse
        )
        if stored is not None:
            return stored
        try:
            result = self._complete(request, idempotency_key)
        except AmwError as exc:
            self._guard.failed(idempotency_key, delivered=delivery_of(exc))
            self.memory.failed(OPERATION_COMPLETION, idempotency_key, exc.code)
            raise
        self.memory.store(OPERATION_COMPLETION, idempotency_key, digest, result)
        return result

    def _complete(self, request: LlmRequest, key: str) -> LlmResponse:
        model = self._check(request)
        body = self._body(request, with_max_tokens=True)
        payload_sha = body_sha256(json.dumps(body, sort_keys=True).encode("utf-8"))
        self._guard.before(
            PlannedCall(
                PROVIDER,
                OPERATION_COMPLETION,
                worst_case_micros(model, request, self._cat.worst_case_overhead_tokens),
                self._cat.currency,
                key,
                model=request.model,
                price_ref=self._cat.price_ref,
            )
        )
        outcome = self._http.send(
            "POST", MESSAGES_PATH, operation=OPERATION_COMPLETION, headers=self._headers(),
            timeout_ms=request.timeout_ms, json_body=body,
        )  # fmt: skip
        data = json_or_empty(outcome.response)
        request_id = outcome.response.headers.get("request-id") or _str(data.get("id"))
        usage_raw = data.get("usage")
        if data.get("type") != "message" or not isinstance(usage_raw, Mapping):
            raise CorruptedOutputError("provider response is not a message", provider=PROVIDER)
        stop = data.get("stop_reason")
        amount = cost_micros(model, usage_raw, self._cat.cache_ttl)
        self._http.log.info(
            "provider.call",
            extra={
                "provider": PROVIDER,
                "operation": OPERATION_COMPLETION,
                "model": request.model,
                "request_id": request_id,
                "attempts": outcome.attempts,
                "duration_ms": outcome.duration_ms,
                "stop_reason": stop,
                "tokens_in": _int(usage_raw, "input_tokens"),
                "tokens_out": _int(usage_raw, "output_tokens"),
                "tokens_cached_in": _int(usage_raw, "cache_read_input_tokens"),
                "tokens_cache_write_in": _int(usage_raw, "cache_creation_input_tokens"),
                "amount_micros": amount,
                "request_body_sha256": payload_sha,
                "request_sha256": request_sha256(request),
                "temperature_sent": False,  # PR-08, CCR-250
            },
        )
        if stop == "refusal":
            details = data.get("stop_details")
            category = details.get("category") if isinstance(details, Mapping) else None
            billed = category in self._cat.billed_refusal_categories
            usage = self._usage(
                OPERATION_COMPLETION, request, key, usage_raw, amount if billed else 0, request_id
            )
            self._guard.after(usage)
            raise ProviderRefusalError(
                "provider refused the request",
                provider=PROVIDER,
                upstream_code=_str(category),
                details={
                    "category": _str(category),
                    "billed": billed,
                    "usage": usage.model_dump(mode="json"),
                },
            )
        usage = self._usage(OPERATION_COMPLETION, request, key, usage_raw, amount, request_id)
        self._guard.after(usage)  # the response was billed whatever its content
        mapped = _STOP_MAP.get(stop) if isinstance(stop, str) else None
        if mapped is None:
            raise IncompleteOutputError(
                "unexpected stop reason (no tools are offered)",
                provider=PROVIDER,
                upstream_code=_str(stop),
            )
        text = "".join(
            str(block.get("text", ""))
            for block in data.get("content") or ()
            if isinstance(block, Mapping) and block.get("type") == "text"
        )
        return LlmResponse(text=text, stop_reason=mapped, usage=usage)

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> TokenCount:
        digest, stored = self.memory.lookup(
            OPERATION_COUNT_TOKENS, idempotency_key, request, TokenCount
        )
        if stored is not None:
            return stored
        try:
            self._cat.model(request.model)
            self._guard.before(
                PlannedCall(
                    PROVIDER, OPERATION_COUNT_TOKENS, 0, self._cat.currency, idempotency_key
                )
            )
            outcome = self._http.send(
                "POST", COUNT_PATH, operation=OPERATION_COUNT_TOKENS, headers=self._headers(),
                timeout_ms=min(request.timeout_ms, _COUNT_TIMEOUT_MS),
                json_body=self._body(request, with_max_tokens=False),
            )  # fmt: skip
            data = json_or_empty(outcome.response)
            tokens = data.get("input_tokens")
            if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
                raise CorruptedOutputError("token count missing", provider=PROVIDER)
        except AmwError as exc:
            self._guard.failed(idempotency_key, delivered=delivery_of(exc))
            self.memory.failed(OPERATION_COUNT_TOKENS, idempotency_key, exc.code)
            raise
        usage = CallUsage(
            provider=PROVIDER,
            operation=OPERATION_COUNT_TOKENS,
            model=request.model,
            tokens_in=tokens,
            amount_micros=0,  # free (PR-08)
            currency=self._cat.currency,
            price_ref=self._cat.price_ref,
            idempotency_key=idempotency_key,
            external_request_id=outcome.response.headers.get("request-id"),
        )
        result = TokenCount(tokens_in=tokens, usage=usage)
        self.memory.store(OPERATION_COUNT_TOKENS, idempotency_key, digest, result)
        return result


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None
