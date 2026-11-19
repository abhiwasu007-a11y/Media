"""Anthropic adapter specifics: wire format, cost arithmetic, error mapping, in-call retry rule,
secrets and logs. Mock transport and recorded fixtures only (no network, no key)."""

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from amw_adapters.llm import LlmMessage, LlmRequest
from amw_adapters.llm.anthropic import AnthropicLlmAdapter, cost_micros
from amw_adapters.real.catalogue import AnthropicCatalogue, load_catalogue
from amw_adapters.real.secrets import SecretRef
from amw_core.enums import BillingMode
from amw_core.errors import (
    AuthInvalidError,
    CallTimeoutError,
    ConfigInvalidError,
    CorruptedOutputError,
    IncompleteOutputError,
    InputInvalidError,
    NetworkError,
    ProviderRefusalError,
    RateLimitedError,
    Upstream5xxError,
)
from amw_core.ids import ORG, make_idempotency_key
from tests.adapters.guards import cap_guard
from tests.adapters.mock_providers import (
    ANTHROPIC_SECRET,
    TEST_ENV,
    TEST_KEY_VALUE,
    MockAnthropic,
    RecordedTransport,
    Scripted,
    anthropic_message,
)

pytestmark = pytest.mark.unit
CAT = load_catalogue().anthropic
K = make_idempotency_key(ORG.new(), "llm.call", ["tsk_a", "s", 1])
PROMPT = "PROMPT-CANARY confidential prompt text"


def req(model: str = "claude-sonnet-5-5", **kw: Any) -> LlmRequest:
    base: dict[str, Any] = {
        "model": model,
        "system": "system rules",
        "messages": (LlmMessage(role="user", content=PROMPT),),
        "max_output_tokens": 100,
        "temperature": 0.7,
    }
    return LlmRequest(**{**base, **kw})


def make(
    mock: MockAnthropic | None = None,
    cat: AnthropicCatalogue = CAT,
    env: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[AnthropicLlmAdapter, MockAnthropic, list[float]]:
    mock = mock or MockAnthropic()
    sleeps: list[float] = []
    adapter = AnthropicLlmAdapter(
        cat,
        SecretRef(ANTHROPIC_SECRET, TEST_ENV if env is None else env),
        guard=cap_guard("anthropic"),
        transport=transport or mock.transport(),
        sleep=sleeps.append,
        uniform=lambda: 0.0,
    )
    return adapter, mock, sleeps


def test_wire_format_no_sampling_no_tools_cached_system() -> None:
    adapter, mock, _ = make()
    out = adapter.complete(req(cache_system_prompt=True), idempotency_key=K)
    sent = mock.requests[0]
    body = json.loads(sent.content)
    assert sent.url.path == "/v1/messages"
    assert sent.headers["anthropic-version"] == CAT.api_version == "2026-10-21"
    assert body["system"] == [
        {"type": "text", "text": "system rules", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["max_tokens"] == 100
    assert "temperature" not in body
    assert out.text.startswith("mock reply")  # thinking block ignored
    assert out.usage.tokens_cache_write_in == 8
    assert out.usage.external_request_id is not None
    assert out.usage.external_request_id.startswith("req_mock")
    assert out.usage.price_ref == "anthropic-pricing@PR-10"


def test_one_hour_cache_ttl_and_plain_system() -> None:
    adapter, mock, _ = make(cat=CAT.model_copy(update={"cache_ttl": "1h"}))
    adapter.complete(req(cache_system_prompt=True), idempotency_key=K)
    assert json.loads(mock.requests[0].content)["system"][0]["cache_control"]["ttl"] == "1h"
    adapter2, mock2, _ = make()
    adapter2.complete(req(system=""), idempotency_key=K)
    assert "system" not in json.loads(mock2.requests[0].content)


def test_cost_arithmetic_from_catalogue() -> None:
    opus = CAT.models["claude-opus-5-5"]
    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_input_tokens": 2000,
        "cache_creation_input_tokens": 300,
        "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 200},
    }
    # 1000*4 + 100*5 + 200*8 + 2000*0.2 + 500*20 = 4000+500+1600+400+10000 micros
    assert cost_micros(opus, usage, "5m") == 16_500
    assert cost_micros(opus, {"input_tokens": 1, "output_tokens": 0}, "5m") == 4
    sonnet = CAT.models["claude-sonnet-5-5"]
    assert (
        cost_micros(sonnet, {"input_tokens": 0, "cache_creation_input_tokens": 1000}, "1h") == 4000
    )
    haiku = CAT.models["claude-haiku-5-5"]
    small = {"input_tokens": 100_000, "output_tokens": 1000}
    assert cost_micros(haiku, small, "5m") == 100_000 * 100_000 // 10**6 + 500  # band 1
    big = {"input_tokens": 99_000, "cache_read_input_tokens": 1_001, "output_tokens": 1000}
    assert cost_micros(haiku, big, "5m") == -(
        -(99_000 * 500_000 + 1_001 * 50_000 + 1000 * 2_500_000) // 10**6
    )
    one = {"input_tokens": 1, "output_tokens": 0}
    assert cost_micros(haiku, one, "5m") == 1  # 0.1 micro rounds up
    with pytest.raises(CorruptedOutputError):
        cost_micros(haiku, {"input_tokens": -1}, "5m")


def test_unknown_model_and_limits_refused_before_any_request() -> None:
    adapter, mock, _ = make()
    with pytest.raises(ConfigInvalidError):
        adapter.complete(req(model="claude-not-in-log"), idempotency_key=K)
    with pytest.raises(ConfigInvalidError):
        adapter.count_tokens(req(model="claude-not-in-log"), idempotency_key=K)
    with pytest.raises(ConfigInvalidError):
        adapter.complete(req(billing_mode=BillingMode.BATCH), idempotency_key=K)
    with pytest.raises(InputInvalidError):
        adapter.complete(req(max_output_tokens=128_001), idempotency_key=K)
    assert mock.requests == []


def test_missing_secret_names_the_name_only() -> None:
    adapter, mock, _ = make(env={})
    with pytest.raises(ConfigInvalidError) as info:
        adapter.complete(req(), idempotency_key=K)
    assert info.value.details == {"name": ANTHROPIC_SECRET}
    assert mock.requests == []
    assert repr(SecretRef(ANTHROPIC_SECRET, TEST_ENV)) == f"SecretRef('{ANTHROPIC_SECRET}')"
    with pytest.raises(ConfigInvalidError):
        SecretRef("ANTHROPIC_KEY", TEST_ENV)


@pytest.mark.security
def test_logs_never_carry_key_or_prompt(caplog: pytest.LogCaptureFixture) -> None:
    adapter, mock, _ = make()
    mock.script.append(Scripted(500, {"error": {"type": "api_error", "message": PROMPT}}))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(Upstream5xxError) as info:
            adapter.complete(req(), idempotency_key=K)
        adapter.complete(req(), idempotency_key=K)
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "provider.call" in text
    assert TEST_KEY_VALUE not in text
    assert "PROMPT-CANARY" not in text
    assert "PROMPT-CANARY" not in str(info.value)
    assert TEST_KEY_VALUE not in repr(adapter.__dict__)


@pytest.mark.failure_injection
def test_429_with_retry_after_is_retried_in_call() -> None:
    adapter, mock, sleeps = make()
    mock.script.append(Scripted(429, {"error": {"type": "rate_limit_error"}}, {"retry-after": "3"}))
    adapter.complete(req(), idempotency_key=K)
    assert len(mock.requests) == 2
    assert sleeps == [3.0]  # max(backoff with U=0 -> 1000 ms, retry-after 3000 ms)


@pytest.mark.failure_injection
def test_429_without_retry_after_is_a_spend_cap_not_retried() -> None:
    adapter, mock, sleeps = make()
    mock.script.append(Scripted(429, {"error": {"type": "rate_limit_error"}}))
    with pytest.raises(RateLimitedError) as info:
        adapter.complete(req(), idempotency_key=K)
    assert info.value.retry_after_ms is None
    assert len(mock.requests) == 1
    assert sleeps == []


@pytest.mark.failure_injection
def test_retry_bounds_and_long_waits() -> None:
    adapter, mock, _ = make()
    for _ in range(3):
        mock.script.append(Scripted(429, {}, {"retry-after": "1"}))
    with pytest.raises(RateLimitedError):
        adapter.complete(req(), idempotency_key=K)
    assert len(mock.requests) == CAT.retry.max_in_call_retries + 1
    adapter2, mock2, _ = make()
    mock2.script.append(Scripted(429, {}, {"retry-after": "3600"}))
    with pytest.raises(RateLimitedError) as info:
        adapter2.complete(req(), idempotency_key=K)
    assert info.value.retry_after_ms == 3_600_000
    assert len(mock2.requests) == 1


@pytest.mark.failure_injection
@pytest.mark.parametrize(
    ("scripted", "error", "requests"),
    [
        (
            Scripted(529, {"error": {"type": "overloaded_error"}}, {"retry-after": "2"}),
            Upstream5xxError,
            1,
        ),
        (Scripted(500, {"error": {"type": "api_error"}}), Upstream5xxError, 1),
        (Scripted(504, {"error": {"type": "timeout_error"}}), Upstream5xxError, 1),
        (Scripted(401, {"error": {"type": "authentication_error"}}), AuthInvalidError, 1),
        (Scripted(402, {"error": {"type": "billing_error"}}), AuthInvalidError, 1),
        (Scripted(403, {"error": {"type": "permission_error"}}), AuthInvalidError, 1),
        (Scripted(404, {"error": {"type": "not_found_error"}}), ConfigInvalidError, 1),
        (Scripted(400, {"error": {"type": "invalid_request_error"}}), InputInvalidError, 1),
        (Scripted(413, b"not json"), InputInvalidError, 1),
        (Scripted(0, raise_exc=httpx.ReadTimeout("t")), CallTimeoutError, 1),
        (Scripted(0, raise_exc=httpx.RemoteProtocolError("x")), NetworkError, 1),
    ],
)
def test_error_mapping_without_in_call_resend(
    scripted: Scripted, error: type[Exception], requests: int
) -> None:
    adapter, mock, _ = make()
    mock.script.append(scripted)
    with pytest.raises(error) as info:
        adapter.complete(req(), idempotency_key=K)
    assert len(mock.requests) == requests
    if scripted.status == 529:
        assert getattr(info.value, "retry_after_ms", None) == 2000
        assert getattr(info.value, "upstream_code", None) == "overloaded_error"


@pytest.mark.failure_injection
def test_connect_failure_is_retried_then_raised() -> None:
    adapter, mock, _ = make()
    mock.script.append(Scripted(0, raise_exc=httpx.ConnectError("refused")))
    adapter.complete(req(), idempotency_key=K)
    assert len(mock.requests) == 2
    adapter2, mock2, _ = make()
    for _ in range(3):
        mock2.script.append(Scripted(0, raise_exc=httpx.ConnectTimeout("t")))
    with pytest.raises(NetworkError):
        adapter2.complete(req(), idempotency_key=K)


@pytest.mark.parametrize(("category", "billed"), [("bio", True), ("cyber", False), (None, False)])
def test_refusal_carries_usage_and_billing(category: str | None, billed: bool) -> None:
    adapter, mock, _ = make()
    usage = {"input_tokens": 1000, "output_tokens": 0}
    mock.script.append(
        Scripted(200, anthropic_message(stop_reason="refusal", usage=usage, category=category))
    )
    with pytest.raises(ProviderRefusalError) as info:
        adapter.complete(req(), idempotency_key=K)
    d = info.value.details
    assert d["billed"] is billed
    assert d["category"] == category
    assert d["usage"]["amount_micros"] == (2000 if billed else 0)
    assert d["usage"]["tokens_in"] == 1000
    assert d["usage"]["idempotency_key"] == K


def test_stop_reason_mapping_and_bad_bodies() -> None:
    adapter, mock, _ = make()
    mock.script.append(
        Scripted(200, anthropic_message(stop_reason="model_context_window_exceeded"))
    )
    assert adapter.complete(req(), idempotency_key=K).stop_reason == "max_tokens"
    for stop in ("tool_use", "pause_turn", "something_new"):
        a, m, _ = make()
        m.script.append(Scripted(200, anthropic_message(stop_reason=stop)))
        with pytest.raises(IncompleteOutputError):
            a.complete(req(), idempotency_key=K)
    a, m, _ = make()
    m.script.append(Scripted(200, {"type": "error"}))
    with pytest.raises(CorruptedOutputError):
        a.complete(req(), idempotency_key=K)
    a, m, _ = make()
    m.script.append(Scripted(200, {"nothing": True}))
    with pytest.raises(CorruptedOutputError):
        a.count_tokens(req(), idempotency_key=K)


def test_recorded_fixture_replay() -> None:
    def check(request: httpx.Request) -> None:
        assert request.headers["x-api-key"] == TEST_KEY_VALUE
        assert "temperature" not in json.loads(request.content)

    transport = RecordedTransport(Path(__file__).parent / "fixtures" / "anthropic_http", check)
    adapter, _, _ = make(transport=transport)
    out = adapter.complete(req(model="claude-haiku-5-5"), idempotency_key=K)
    assert out.text == "recorded reply"
    assert out.usage.external_request_id == "req_recorded01"
    assert out.usage.tokens_in == 21
    assert out.usage.tokens_out == 3
    assert out.usage.amount_micros == 4  # 21*0.1 + 3*0.5 = 3.6 micros, rounded up
    adapter.close()


def test_catalogue_validation(tmp_path: Path) -> None:
    from amw_adapters.real.catalogue import DEFAULT_CATALOGUE

    raw = json.loads(DEFAULT_CATALOGUE.read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(raw))
    bad["anthropic"]["models"]["claude-haiku-5-5"]["prices"].reverse()
    path = tmp_path / "c.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ConfigInvalidError) as info:
        load_catalogue(path)
    assert "fields" in info.value.details
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigInvalidError):
        load_catalogue(path)
    with pytest.raises(ConfigInvalidError):
        load_catalogue(tmp_path / "missing.json")
    for edit in ("overlap", "no_enabled", "bad_tag", "enabled_no_limit"):
        doc = json.loads(json.dumps(raw))
        el = doc["elevenlabs"]
        if edit == "overlap":
            el["forbidden_models"]["eleven_v3"] = "x"
        elif edit == "no_enabled":
            for m in el["models"].values():
                m["enabled"] = False
        elif edit == "bad_tag":
            el["emotion_audio_tags"] = {"WARM": "warm"}
        else:
            el["models"]["eleven_v4_turbo"]["enabled"] = True
        path.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(ConfigInvalidError):
            load_catalogue(path)


def test_every_catalogue_number_is_cited() -> None:
    """Every model row names its RESEARCH_LOG id and the id exists in the log."""
    log = (Path(__file__).resolve().parents[2] / "docs" / "v4" / "RESEARCH_LOG.md").read_text(
        encoding="utf-8"
    )
    cat = load_catalogue()
    sources = [m.source for m in cat.anthropic.models.values()]
    sources += [m.source for m in cat.elevenlabs.models.values()]
    for source in sources:
        ids = [token.strip(",;") for token in source.split() if token.startswith("PR-")]
        assert ids
        for rid in ids:
            assert f"| {rid} |" in log, rid
