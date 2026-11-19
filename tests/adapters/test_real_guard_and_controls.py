"""Real adapters: preflight token, per-video hard stop (before the request), real-cost record,
and the ElevenLabs style controls (pace forwarded as speed, undeclared controls refused).
Mock transports only: no network, no key, no paid call."""

import json
import pickle
from typing import Any

import pytest

from amw_adapters.llm import LlmMessage, LlmRequest
from amw_adapters.llm.anthropic import AnthropicLlmAdapter, worst_case_micros
from amw_adapters.real.catalogue import (
    AnthropicModel,
    ElevenLabsCatalogue,
    TokenPrice,
    load_catalogue,
)
from amw_adapters.real.guard import PlannedCall, call_scope
from amw_adapters.real.secrets import SecretRef
from amw_adapters.tts import ControlSupport, TtsPace, TtsRequest
from amw_adapters.tts.elevenlabs import ElevenLabsTtsAdapter
from amw_core.enums import CostFigureKind
from amw_core.errors import (
    AmwError,
    BudgetExhaustedError,
    ConfigInvalidError,
    InputInvalidError,
    ProviderRefusalError,
)
from amw_core.ids import ORG, make_idempotency_key
from tests.adapters.guards import GuardedWorld, auth, cap_guard
from tests.adapters.mock_providers import (
    ANTHROPIC_SECRET,
    ELEVENLABS_SECRET,
    TEST_ENV,
    MockAnthropic,
    MockElevenLabs,
    Scripted,
    anthropic_message,
    wav_bytes,
)

pytestmark = pytest.mark.unit
CAT = load_catalogue()
TEXT = "नमस्कार मित्रांनो"
ORG_ID = ORG.new()


def key(n: int = 1, scope: str = "llm.call") -> str:
    return make_idempotency_key(ORG_ID, scope, ["tsk_g", "step", n])


def llm_request(text: str = "hello", **kw: Any) -> LlmRequest:
    base: dict[str, Any] = {
        "model": "claude-haiku-5-5",
        "system": "s",
        "messages": (LlmMessage(role="user", content=text),),
        "max_output_tokens": 100,
    }
    return LlmRequest(**{**base, **kw})


def tts_request(**kw: Any) -> TtsRequest:
    base: dict[str, Any] = {
        "text": TEXT,
        "voice_ref": "mrVoice1",
        "model": "eleven_v3",
        "language": "mr",
    }
    return TtsRequest(**{**base, **kw})


def llm(guard: Any, mock: MockAnthropic | None = None) -> tuple[AnthropicLlmAdapter, MockAnthropic]:
    mock = mock or MockAnthropic()
    return (
        AnthropicLlmAdapter(
            CAT.anthropic, SecretRef(ANTHROPIC_SECRET, TEST_ENV), guard=guard,
            transport=mock.transport(),
        ),
        mock,
    )  # fmt: skip


def tts(
    guard: Any, mock: MockElevenLabs | None = None, cat: ElevenLabsCatalogue = CAT.elevenlabs
) -> tuple[ElevenLabsTtsAdapter, MockElevenLabs]:
    mock = mock or MockElevenLabs()
    return (
        ElevenLabsTtsAdapter(
            cat, SecretRef(ELEVENLABS_SECRET, TEST_ENV), guard=guard, transport=mock.transport()
        ),
        mock,
    )  # fmt: skip


# ------------------------------------------------------------------ token: no preflight, no adapter
@pytest.mark.security
def test_a_token_cannot_be_built_copied_or_changed() -> None:
    token = auth("anthropic")
    with pytest.raises(AttributeError):
        token.per_video_cap_micros = 10**12
    with pytest.raises(TypeError):
        pickle.dumps(token)


@pytest.mark.security
def test_adapters_cannot_be_constructed_without_a_matching_guard() -> None:
    secret = SecretRef(ANTHROPIC_SECRET, TEST_ENV)
    with pytest.raises(TypeError):
        AnthropicLlmAdapter(CAT.anthropic, secret)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ElevenLabsTtsAdapter(CAT.elevenlabs, secret)  # type: ignore[call-arg]
    with pytest.raises(ConfigInvalidError):  # an object that only looks like a guard
        AnthropicLlmAdapter(CAT.anthropic, secret, guard=object())  # type: ignore[arg-type]
    with pytest.raises(ConfigInvalidError):  # a token for the other provider
        AnthropicLlmAdapter(CAT.anthropic, secret, guard=cap_guard("elevenlabs"))
    with pytest.raises(ConfigInvalidError):
        ElevenLabsTtsAdapter(CAT.elevenlabs, secret, guard=cap_guard("anthropic"))


# ------------------------------------------------------------------ worst-case estimate
def test_worst_case_is_an_upper_bound_of_the_real_cost() -> None:
    model = CAT.anthropic.model("claude-haiku-5-5")
    adapter, _ = llm(cap_guard("anthropic"))
    for text in ("hello", "नमस्कार मित्रांनो " * 40):
        request = llm_request(text, max_output_tokens=500)
        worst = worst_case_micros(model, request, CAT.anthropic.worst_case_overhead_tokens)
        result = adapter.complete(request, idempotency_key=key(len(text)))
        assert 0 < result.usage.amount_micros <= worst
    longer = worst_case_micros(model, llm_request(max_output_tokens=900), 256)
    assert longer > worst_case_micros(model, llm_request(max_output_tokens=100), 256)


def test_worst_case_takes_the_dearest_band_up_to_the_prompt_length() -> None:
    cheap = TokenPrice(
        max_prompt_tokens=300, input=1_000_000, cache_write_5m=0, cache_write_1h=0,
        cache_read=0, output=1_000_000,
    )  # fmt: skip
    dear = TokenPrice(
        max_prompt_tokens=None, input=9_000_000, cache_write_5m=0, cache_write_1h=0,
        cache_read=0, output=1_000_000,
    )  # fmt: skip
    model = AnthropicModel(source="t", max_output_tokens=1000, prices=(cheap, dear))
    short = worst_case_micros(model, llm_request("x", system=""), 0)
    assert short == 101  # (1 byte + 100 output tokens) at 1 micro per token
    assert worst_case_micros(model, llm_request("x" * 400, system=""), 0) == 3700  # 400 * 9 + 100


# ------------------------------------------------------------------ hard stop with the cap guard
def test_llm_call_above_the_cap_is_refused_before_any_request() -> None:
    adapter, mock = llm(cap_guard("anthropic", cap=10))
    with pytest.raises(BudgetExhaustedError):
        adapter.complete(llm_request(), idempotency_key=key())
    assert mock.requests == []
    assert mock.billable == 0


def test_tts_call_above_the_cap_is_refused_before_any_request() -> None:
    worst = -(-len(TEXT) * 80_000 // 1000)
    adapter, mock = tts(cap_guard("elevenlabs", cap=worst - 1))
    with pytest.raises(BudgetExhaustedError):
        adapter.synthesize(tts_request(), idempotency_key=key(scope="tts.synthesize"))
    assert mock.requests == []
    ok, mock2 = tts(cap_guard("elevenlabs", cap=worst))  # exactly the worst case fits
    ok.synthesize(tts_request(), idempotency_key=key(scope="tts.synthesize"))
    assert mock2.billable == 1


def test_the_cap_guard_counts_real_cost_after_each_call() -> None:
    guard = cap_guard("anthropic")
    adapter, _ = llm(guard)
    first = adapter.complete(llm_request(), idempotency_key=key(1))
    adapter.complete(llm_request("again"), idempotency_key=key(2))
    assert guard.spent_micros > first.usage.amount_micros > 0
    # a replay under the same key is served from memory: no new cost
    before = guard.spent_micros
    adapter.complete(llm_request(), idempotency_key=key(1))
    assert guard.spent_micros == before


def test_a_billed_refusal_and_unusable_audio_are_recorded_a_free_refusal_is_not() -> None:
    guard = cap_guard("anthropic")
    adapter, mock = llm(guard)
    refusal = anthropic_message(
        stop_reason="refusal", category="bio", usage={"input_tokens": 1000, "output_tokens": 2}
    )
    mock.script.append(Scripted(200, refusal))
    with pytest.raises(ProviderRefusalError):
        adapter.complete(llm_request(), idempotency_key=key(1))
    billed = guard.spent_micros
    assert billed > 0
    mock.script.append(Scripted(200, {**refusal, "stop_details": {"category": "other"}}))
    with pytest.raises(ProviderRefusalError):
        adapter.complete(llm_request(), idempotency_key=key(2))
    assert guard.spent_micros == billed
    tts_guard = cap_guard("elevenlabs")
    voice, eleven = tts(tts_guard)
    eleven.script.append(Scripted(200, b"not a wav", {"content-type": "audio/wav"}))
    with pytest.raises(AmwError):
        voice.synthesize(tts_request(), idempotency_key=key(3, "tts.synthesize"))
    assert tts_guard.spent_micros == -(-len(TEXT) * 80_000 // 1000)


# ------------------------------------------------------------------ the merged L1b guard
def test_budget_guard_records_real_cost_in_integer_micros() -> None:
    world = GuardedWorld()
    adapter, mock = llm(world.guard("anthropic"))
    with call_scope(world.ctx):
        result = adapter.complete(llm_request(), idempotency_key=key())
        adapter.complete(llm_request(), idempotency_key=key())  # replay: no second row
    rows = world.rows()
    assert len(rows) == 1
    entry = rows[0].entry  # type: ignore[attr-defined]
    assert entry.amount_micros == result.usage.amount_micros > 0
    assert isinstance(entry.amount_micros, int)
    assert entry.figure_kind is CostFigureKind.ESTIMATE
    assert (entry.provider, entry.currency, entry.job_id, entry.task_id) == (
        "anthropic", "USD", world.job, world.task,
    )  # fmt: skip
    assert entry.tokens_in == result.usage.tokens_in
    assert mock.billable == 1
    assert world.w.ledger.job_totals(world.w.tx, world.job).effective_micros == entry.amount_micros


def test_budget_guard_refuses_above_the_per_video_cap_before_the_request() -> None:
    world = GuardedWorld()
    world.spend(4_999_990)  # USD 4.99999 already spent on this video
    adapter, mock = llm(world.guard("anthropic"))
    with call_scope(world.ctx), pytest.raises(BudgetExhaustedError) as info:
        adapter.complete(llm_request(), idempotency_key=key())
    assert info.value.details["per_video_cap_micros"] == 5_000_000
    assert mock.requests == []
    assert len(world.rows()) == 1  # only the seeded row; nothing recorded for the refused call


def test_budget_guard_cap_is_the_preflight_cap_not_the_database_budget() -> None:
    world = GuardedWorld()  # the DB per-video budget is USD 5, the token's cap is lower
    adapter, mock = llm(world.guard("anthropic", cap=100))
    with call_scope(world.ctx), pytest.raises(BudgetExhaustedError):
        adapter.complete(llm_request(), idempotency_key=key())
    assert mock.requests == []


def test_budget_guard_spend_of_both_providers_counts_against_one_video() -> None:
    world = GuardedWorld()
    worst = -(-len(TEXT) * 80_000 // 1000)
    world.spend(5_000_000 - worst + 1, provider="anthropic")
    voice, mock = tts(world.guard("elevenlabs"))
    with call_scope(world.ctx), pytest.raises(BudgetExhaustedError):
        voice.synthesize(tts_request(), idempotency_key=key(scope="tts.synthesize"))
    assert mock.requests == []


def test_budget_guard_needs_a_scope_the_provider_gate_and_the_tenant() -> None:
    world = GuardedWorld()
    adapter, mock = llm(world.guard("anthropic"))
    with pytest.raises(ConfigInvalidError, match="call_scope"):  # outside any scope
        adapter.complete(llm_request(), idempotency_key=key())
    assert mock.requests == []
    no_gate = GuardedWorld(providers=("elevenlabs",))  # no ACTIVE anthropic limit row
    adapter2, mock2 = llm(no_gate.guard("anthropic"))
    with call_scope(no_gate.ctx), pytest.raises(BudgetExhaustedError):
        adapter2.complete(llm_request(), idempotency_key=key())
    assert mock2.requests == []
    other = GuardedWorld()  # a context of another tenant cannot use this world's job
    adapter3, mock3 = llm(world.guard("anthropic"))
    with call_scope(other.ctx), pytest.raises(AmwError):
        adapter3.complete(llm_request(), idempotency_key=key())
    assert mock3.requests == []
    assert world.rows() == []


def test_free_calls_pass_the_gate_but_record_nothing() -> None:
    world = GuardedWorld()
    adapter, mock = llm(world.guard("anthropic"))
    with call_scope(world.ctx):
        adapter.count_tokens(llm_request(), idempotency_key=key())
    assert mock.requests  # it went out
    assert world.rows() == []
    blocked = GuardedWorld(providers=())
    adapter2, mock2 = llm(blocked.guard("anthropic"))
    with call_scope(blocked.ctx), pytest.raises(BudgetExhaustedError):
        adapter2.count_tokens(llm_request(), idempotency_key=key())
    assert mock2.requests == []


def test_planned_call_outside_the_authorisation_is_refused() -> None:
    guard = cap_guard("anthropic")
    with pytest.raises(ConfigInvalidError):
        guard.before(PlannedCall("elevenlabs", "tts.synthesize", 1, "USD", key()))
    with pytest.raises(ConfigInvalidError):
        guard.before(PlannedCall("anthropic", "llm.completion", 1, "EUR", key()))
    with pytest.raises(InputInvalidError):
        guard.before(PlannedCall("anthropic", "llm.completion", -1, "USD", key()))


# ------------------------------------------------------------------ ElevenLabs controls
def _catalogue(**over: Any) -> ElevenLabsCatalogue:
    data = CAT.elevenlabs.model_dump()
    models = data["models"]
    for name, flags in over.pop("models", {}).items():
        models[name] = {**models[name], **flags}
    data.update(over)
    return ElevenLabsCatalogue.model_validate(data)


SPEEDS = {"SLOW": 0.8, "NORMAL": 1.0, "FAST": 1.15}


def sent_body(mock: MockElevenLabs) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(mock.requests[-1].content)
    return body


def test_pace_is_forwarded_as_provider_speed_when_the_model_has_speed_control() -> None:
    cat = _catalogue(
        pace_speed=SPEEDS,
        models={"eleven_v3": {"speed_control": True}, "eleven_v4": {"speed_control": True}},
    )
    adapter, mock = tts(cap_guard("elevenlabs"), cat=cat)
    assert adapter.capabilities().pace_control is ControlSupport.NATIVE
    for n, pace in enumerate(TtsPace):
        adapter.synthesize(tts_request(pace=pace), idempotency_key=key(n, "tts.synthesize"))
        assert sent_body(mock)["voice_settings"] == {"speed": SPEEDS[pace.value]}
    adapter.synthesize(tts_request(), idempotency_key=key(9, "tts.synthesize"))
    assert "voice_settings" not in sent_body(mock)  # no pace asked: the voice's own settings


def test_speed_is_merged_into_the_catalogue_voice_settings() -> None:
    cat = _catalogue(
        pace_speed=SPEEDS,
        voice_settings={"stability": 0.5},
        models={"eleven_v3": {"speed_control": True}, "eleven_v4": {"speed_control": True}},
    )
    adapter, mock = tts(cap_guard("elevenlabs"), cat=cat)
    adapter.synthesize(tts_request(pace=TtsPace.FAST), idempotency_key=key(1, "tts.synthesize"))
    assert sent_body(mock)["voice_settings"] == {"stability": 0.5, "speed": 1.15}


def test_pace_the_model_does_not_declare_is_refused_not_ignored() -> None:
    adapter, mock = tts(cap_guard("elevenlabs"))  # shipped catalogue: no speed control
    assert adapter.capabilities().pace_control is ControlSupport.NONE
    with pytest.raises(InputInvalidError):
        adapter.synthesize(tts_request(pace=TtsPace.SLOW), idempotency_key=key(1, "tts.synthesize"))
    mixed = _catalogue(pace_speed=SPEEDS, models={"eleven_v3": {"speed_control": True}})
    adapter2, mock2 = tts(cap_guard("elevenlabs"), cat=mixed)
    assert adapter2.capabilities().pace_control is ControlSupport.NONE  # conservative over models
    with pytest.raises(InputInvalidError):  # v4 has no speed control
        adapter2.synthesize(
            tts_request(model="eleven_v4", pace=TtsPace.SLOW),
            idempotency_key=key(2, "tts.synthesize"),
        )
    adapter2.synthesize(tts_request(pace=TtsPace.SLOW), idempotency_key=key(3, "tts.synthesize"))
    assert mock.requests == []
    assert len(mock2.requests) == 1  # only the v3 request went out


def test_pronunciation_dictionary_the_model_does_not_declare_is_refused() -> None:
    cat = _catalogue(models={"eleven_v3": {"pronunciation_dictionary": False}})
    adapter, mock = tts(cap_guard("elevenlabs"), cat=cat)
    with pytest.raises(InputInvalidError):
        adapter.synthesize(
            tts_request(pronunciation_dictionary_ref="dict1"),
            idempotency_key=key(1, "tts.synthesize"),
        )
    assert mock.requests == []
    adapter.synthesize(
        tts_request(model="eleven_v4", pronunciation_dictionary_ref="dict1"),
        idempotency_key=key(2, "tts.synthesize"),
    )
    assert "pronunciation_dictionary_locators" in sent_body(mock)


def test_capabilities_declare_the_markup_delimiters() -> None:
    adapter, _ = tts(cap_guard("elevenlabs"))
    assert adapter.capabilities().markup_delimiters == ("[", "]")


def test_a_catalogue_with_speed_control_needs_a_speed_for_every_pace() -> None:
    with pytest.raises(ValueError, match="speed"):
        _catalogue(models={"eleven_v3": {"speed_control": True}})
    with pytest.raises(ValueError, match="TtsPace"):
        _catalogue(pace_speed={"TURBO": 1.0})


def test_marathi_only_models_and_a_wav_reply_still_hold() -> None:
    adapter, mock = tts(cap_guard("elevenlabs"))
    mock.script.append(Scripted(200, wav_bytes(4800, 48000), {"content-type": "audio/wav"}))
    out = adapter.synthesize(
        tts_request(model="eleven_v4"), idempotency_key=key(1, "tts.synthesize")
    )
    assert out.duration_ms == 100
    with pytest.raises(ConfigInvalidError):
        adapter.synthesize(
            tts_request(model="eleven_multilingual_v2"), idempotency_key=key(2, "tts.synthesize")
        )
