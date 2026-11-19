"""One Protocol suite, run against the fake AND the real adapter on a mock transport.

The fake and the real adapter of a Protocol must behave the same for every caller-visible rule:
Protocol shape, ledger-ready ``CallUsage``, idempotent replay and conflict, typed 07 failures that
a retry under the same key recovers from, refusal mapping, capability-gated style controls.
No network (the autouse ``no_network`` fixture), no key (placeholder value only).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from amw_adapters.common import FailurePlan
from amw_adapters.llm import FakeLlmAdapter, LlmAdapter, LlmMessage, LlmRequest
from amw_adapters.llm.anthropic import AnthropicLlmAdapter
from amw_adapters.real.catalogue import InCallRetry, load_catalogue
from amw_adapters.real.secrets import SecretRef
from amw_adapters.tts import (
    ControlSupport,
    FakeTtsAdapter,
    TtsAdapter,
    TtsPace,
    TtsRequest,
    VoiceInfo,
    VoiceListRequest,
)
from amw_adapters.tts.elevenlabs import ElevenLabsTtsAdapter
from amw_core.enums import CostFigureKind, CostUnitKind
from amw_core.errors import (
    AmwError,
    IdempotencyConflictError,
    InputInvalidError,
    ProviderRefusalError,
    RateLimitedError,
    Upstream5xxError,
)
from amw_core.ids import ORG, make_idempotency_key
from tests.adapters.mock_providers import (
    ANTHROPIC_SECRET,
    ELEVENLABS_SECRET,
    TEST_ENV,
    MockAnthropic,
    MockElevenLabs,
    Scripted,
    anthropic_message,
)

pytestmark = pytest.mark.contract
ORG_ID = ORG.new()
NO_RETRY = InCallRetry(
    max_in_call_retries=0, max_in_call_wait_ms=0, retry_429_without_retry_after=False
)
CAT = load_catalogue()


def key(n: int) -> str:
    return make_idempotency_key(ORG_ID, "llm.call", ["tsk_conf", "step", n])


@dataclass
class Harness:
    name: str
    make: Callable[[list[str]], Any]
    """failure kinds, in order of the next new calls: ``rate_limited``, ``refusal``, ``5xx``."""
    billable: Callable[[Any], int]
    model: str


# --- LLM --------------------------------------------------------------------------------------

_FAKE_LLM_ERRORS: dict[str, Callable[[], AmwError]] = {
    "rate_limited": lambda: RateLimitedError("429", retry_after_ms=1000),
    "refusal": lambda: ProviderRefusalError("refused"),
    "5xx": lambda: Upstream5xxError("500"),
}


def _fake_llm(failures: list[str]) -> FakeLlmAdapter:
    return FakeLlmAdapter(failures=FailurePlan(sequence=[_FAKE_LLM_ERRORS[f]() for f in failures]))


def _real_llm(failures: list[str]) -> AnthropicLlmAdapter:
    mock = MockAnthropic()
    for f in failures:
        mock.script.append(
            {
                "rate_limited": Scripted(429, {"error": {"type": "rate_limit_error"}},
                                         {"retry-after": "1"}),
                "refusal": Scripted(
                    200, anthropic_message(stop_reason="refusal", category="cyber")
                ),
                "5xx": Scripted(500, {"error": {"type": "api_error"}}),
            }[f]
        )  # fmt: skip
    cat = CAT.anthropic.model_copy(update={"retry": NO_RETRY})
    adapter = AnthropicLlmAdapter(
        cat, SecretRef(ANTHROPIC_SECRET, TEST_ENV), transport=mock.transport()
    )
    adapter._mock = mock  # type: ignore[attr-defined]
    return adapter


LLM = [
    Harness("fake", _fake_llm, lambda a: a.engine.billable_calls, "fake-model"),
    Harness("anthropic", _real_llm, lambda a: a._mock.billable, "claude-haiku-5-5"),
]


def llm_req(h: Harness, system: str = "s", text: str = "hello world") -> LlmRequest:
    return LlmRequest(
        model=h.model,
        system=system,
        messages=(LlmMessage(role="user", content=text),),
        max_output_tokens=256,
        language="mr",
    )


@pytest.mark.parametrize("h", LLM, ids=lambda h: h.name)
def test_llm_protocol_and_usage(h: Harness) -> None:
    adapter = h.make([])
    assert isinstance(adapter, LlmAdapter)
    assert adapter.provider
    out = adapter.complete(llm_req(h), idempotency_key=key(1))
    u = out.usage
    assert u.figure_kind is CostFigureKind.ESTIMATE
    assert u.idempotency_key == key(1)
    assert u.provider == adapter.provider
    assert u.operation == "llm.completion"
    assert u.model == h.model
    assert u.currency == "USD"
    assert isinstance(u.amount_micros, int)
    assert u.amount_micros >= 0
    assert u.tokens_in is not None
    assert u.tokens_in > 0
    assert u.tokens_out is not None
    assert 0 < u.tokens_out <= 256
    assert u.language == "mr"
    assert out.stop_reason in ("end_turn", "max_tokens", "stop_sequence")
    assert out.text


@pytest.mark.parametrize("h", LLM, ids=lambda h: h.name)
def test_llm_replay_conflict_distinct(h: Harness) -> None:
    adapter = h.make([])
    first = adapter.complete(llm_req(h), idempotency_key=key(1))
    assert adapter.complete(llm_req(h), idempotency_key=key(1)) == first
    assert h.billable(adapter) == 1
    with pytest.raises(IdempotencyConflictError):
        adapter.complete(llm_req(h, system="other"), idempotency_key=key(1))
    adapter.complete(llm_req(h), idempotency_key=key(2))
    assert h.billable(adapter) == 2


@pytest.mark.parametrize("h", LLM, ids=lambda h: h.name)
def test_llm_invalid_key_rejected_before_any_call(h: Harness) -> None:
    adapter = h.make([])
    with pytest.raises(InputInvalidError):
        adapter.complete(llm_req(h), idempotency_key="not-a-key")
    assert h.billable(adapter) == 0


@pytest.mark.parametrize("h", LLM, ids=lambda h: h.name)
def test_llm_rate_limited_then_retry_same_key(h: Harness) -> None:
    adapter = h.make(["rate_limited"])
    with pytest.raises(RateLimitedError) as info:
        adapter.complete(llm_req(h), idempotency_key=key(1))
    assert info.value.retry_after_ms == 1000
    assert info.value.retryable
    assert adapter.complete(llm_req(h), idempotency_key=key(1)).usage.idempotency_key == key(1)
    assert h.billable(adapter) == 1


@pytest.mark.parametrize("h", LLM, ids=lambda h: h.name)
@pytest.mark.parametrize(
    ("kind", "error"), [("refusal", ProviderRefusalError), ("5xx", Upstream5xxError)]
)
def test_llm_typed_failures(h: Harness, kind: str, error: type[AmwError]) -> None:
    adapter = h.make([kind])
    with pytest.raises(error) as info:
        adapter.complete(llm_req(h), idempotency_key=key(1))
    assert info.value.retryable is (kind == "5xx")
    adapter.complete(llm_req(h), idempotency_key=key(1))


@pytest.mark.parametrize("h", LLM, ids=lambda h: h.name)
def test_llm_count_tokens_is_free(h: Harness) -> None:
    adapter = h.make([])
    out = adapter.count_tokens(llm_req(h), idempotency_key=key(3))
    assert out.tokens_in > 0
    assert out.usage.amount_micros == 0
    assert out.usage.operation == "llm.count_tokens"
    assert adapter.count_tokens(llm_req(h), idempotency_key=key(3)) == out


# --- TTS --------------------------------------------------------------------------------------

LIMIT: int = CAT.elevenlabs.models["eleven_v3"].max_chars_per_request or 0
assert LIMIT > 0


def _fake_tts(failures: list[str]) -> FakeTtsAdapter:
    return FakeTtsAdapter(
        failures=FailurePlan(sequence=[_FAKE_LLM_ERRORS[f]() for f in failures]),
        voices=(
            VoiceInfo(voice_ref="mrVoice1", name="Neutral Marathi", languages=("mr",)),
            VoiceInfo(voice_ref="enVoice1", name="Neutral English", languages=("en",)),
        ),
        pace_control=ControlSupport.NONE,
        emotion_control=ControlSupport.NONE,
        max_chars_per_request=LIMIT,
    )


def _real_tts(failures: list[str]) -> ElevenLabsTtsAdapter:
    mock = MockElevenLabs()
    for f in failures:
        mock.script.append(
            {
                "rate_limited": Scripted(429, {"detail": {"type": "rate_limit_error",
                                                          "code": "rate_limit_exceeded"}},
                                         {"retry-after": "1"}),
                "5xx": Scripted(503, {"detail": {"type": "service_unavailable"}}),
            }[f]
        )  # fmt: skip
    cat = CAT.elevenlabs.model_copy(
        update={"retry": NO_RETRY, "models": {"eleven_v3": CAT.elevenlabs.models["eleven_v3"]}}
    )
    adapter = ElevenLabsTtsAdapter(
        cat, SecretRef(ELEVENLABS_SECRET, TEST_ENV), transport=mock.transport()
    )
    adapter._mock = mock  # type: ignore[attr-defined]
    return adapter


TTS = [
    Harness("fake", _fake_tts, lambda a: a.engine.billable_calls, "eleven_v3"),
    Harness("elevenlabs", _real_tts, lambda a: a._mock.billable, "eleven_v3"),
]


def tts_req(h: Harness, text: str = "नमस्कार, आज आपण शिकूया.", **kw: Any) -> TtsRequest:
    return TtsRequest(text=text, voice_ref="mrVoice1", model=h.model, language="mr", **kw)


@pytest.mark.parametrize("h", TTS, ids=lambda h: h.name)
def test_tts_protocol_capabilities_usage(h: Harness) -> None:
    adapter = h.make([])
    assert isinstance(adapter, TtsAdapter)
    caps = adapter.capabilities()
    assert "mr" in caps.languages
    assert caps.max_chars_per_request == LIMIT
    assert caps.pace_control is ControlSupport.NONE
    req = tts_req(h)
    out = adapter.synthesize(req, idempotency_key=key(1))
    assert out.media_type == "audio/wav"
    assert out.sample_rate_hz == 48_000
    assert out.duration_ms > 0
    assert out.audio
    u = out.usage
    assert u.operation == "tts.synthesize"
    assert u.unit_kind is CostUnitKind.CHARACTERS
    assert u.units == u.chars_in == len(req.text)
    assert u.figure_kind is CostFigureKind.ESTIMATE
    assert u.currency == "USD"
    assert u.amount_micros >= 0
    assert u.language == "mr"


@pytest.mark.parametrize("h", TTS, ids=lambda h: h.name)
def test_tts_replay_conflict_invalid_key(h: Harness) -> None:
    adapter = h.make([])
    first = adapter.synthesize(tts_req(h), idempotency_key=key(1))
    assert adapter.synthesize(tts_req(h), idempotency_key=key(1)) == first
    with pytest.raises(IdempotencyConflictError):
        adapter.synthesize(tts_req(h, text="वेगळा मजकूर"), idempotency_key=key(1))
    with pytest.raises(InputInvalidError):
        adapter.synthesize(tts_req(h), idempotency_key="bad")
    assert h.billable(adapter) == 1


@pytest.mark.parametrize("h", TTS, ids=lambda h: h.name)
@pytest.mark.parametrize(
    ("kind", "error"), [("rate_limited", RateLimitedError), ("5xx", Upstream5xxError)]
)
def test_tts_temporary_failure_then_retry(h: Harness, kind: str, error: type[AmwError]) -> None:
    adapter = h.make([kind])
    with pytest.raises(error) as info:
        adapter.synthesize(tts_req(h), idempotency_key=key(1))
    assert info.value.retryable
    adapter.synthesize(tts_req(h), idempotency_key=key(1))
    assert h.billable(adapter) == 1


@pytest.mark.parametrize("h", TTS, ids=lambda h: h.name)
def test_tts_refuses_undeclared_control_and_oversize(h: Harness) -> None:
    adapter = h.make([])
    with pytest.raises(InputInvalidError):
        adapter.synthesize(tts_req(h, pace=TtsPace.SLOW), idempotency_key=key(1))
    with pytest.raises(InputInvalidError):
        adapter.synthesize(tts_req(h, text="क" * (LIMIT + 1)), idempotency_key=key(2))
    assert h.billable(adapter) == 0


@pytest.mark.parametrize("h", TTS, ids=lambda h: h.name)
def test_tts_list_voices_by_language(h: Harness) -> None:
    adapter = h.make([])
    voices = adapter.list_voices(VoiceListRequest(language="mr"), idempotency_key=key(5))
    assert [v.voice_ref for v in voices.voices] == ["mrVoice1"]
    assert voices.usage.amount_micros == 0
    every = adapter.list_voices(VoiceListRequest(), idempotency_key=key(6))
    assert {v.voice_ref for v in every.voices} == {"mrVoice1", "enVoice1"}
