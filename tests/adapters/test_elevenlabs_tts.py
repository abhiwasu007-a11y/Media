"""ElevenLabs adapter specifics: Marathi allow-list, wire format, WAV checks, cost, controls,
errors, voice listing. Mock transport and recorded fixtures only (no network, no key)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from amw_adapters.real.catalogue import ElevenLabsCatalogue, load_catalogue
from amw_adapters.real.secrets import SecretRef
from amw_adapters.tts import ControlSupport, TtsEmotion, TtsRequest, VoiceListRequest
from amw_adapters.tts.elevenlabs import ElevenLabsTtsAdapter
from amw_core.errors import (
    AuthInvalidError,
    ConfigInvalidError,
    CorruptedOutputError,
    InputInvalidError,
    RateLimitedError,
)
from amw_core.ids import ORG, make_idempotency_key
from tests.adapters.guards import cap_guard
from tests.adapters.mock_providers import (
    ELEVENLABS_SECRET,
    TEST_ENV,
    TEST_KEY_VALUE,
    MockElevenLabs,
    RecordedTransport,
    Scripted,
    wav_bytes,
)

pytestmark = pytest.mark.unit
CAT = load_catalogue().elevenlabs
K = make_idempotency_key(ORG.new(), "tts.synthesize", ["tsk_t", "seg", "ab" * 32, "voi"])
TEXT = "नमस्कार मित्रांनो"


def req(**kw: Any) -> TtsRequest:
    base: dict[str, Any] = {
        "text": TEXT,
        "voice_ref": "mrVoice1",
        "model": "eleven_v4",
        "language": "mr",
    }
    return TtsRequest(**{**base, **kw})


def make(
    mock: MockElevenLabs | None = None,
    cat: ElevenLabsCatalogue = CAT,
    transport: httpx.BaseTransport | None = None,
) -> tuple[ElevenLabsTtsAdapter, MockElevenLabs, list[float]]:
    mock = mock or MockElevenLabs()
    sleeps: list[float] = []
    adapter = ElevenLabsTtsAdapter(
        cat,
        SecretRef(ELEVENLABS_SECRET, TEST_ENV),
        guard=cap_guard("elevenlabs"),
        transport=transport or mock.transport(),
        sleep=sleeps.append,
        uniform=lambda: 0.0,
    )
    return adapter, mock, sleeps


@pytest.mark.parametrize(
    "model",
    [
        "eleven_multilingual_v2",
        "eleven_flash_v2_5",
        "eleven_turbo_v2_5",
        "eleven_v4_turbo",
        "made_up",
    ],
)
def test_models_outside_the_marathi_allow_list_are_refused(model: str) -> None:
    adapter, mock, _ = make()
    with pytest.raises(ConfigInvalidError) as info:
        adapter.synthesize(req(model=model), idempotency_key=K)
    assert info.value.details["model"] == model
    assert mock.requests == []


def test_language_must_be_verified_for_the_model() -> None:
    adapter, mock, _ = make()
    with pytest.raises(ConfigInvalidError):
        adapter.synthesize(req(language="ta"), idempotency_key=K)
    adapter.synthesize(req(language="mr-IN"), idempotency_key=K)
    assert json.loads(mock.requests[0].content)["language_code"] == "mr"


def test_wire_format_and_cost() -> None:
    adapter, mock, _ = make()
    out = adapter.synthesize(req(pronunciation_dictionary_ref="pd123@v7"), idempotency_key=K)
    sent = mock.requests[0]
    body = json.loads(sent.content)
    assert sent.url.path == "/v1/text-to-speech/mrVoice1"
    assert sent.url.params["output_format"] == "wav_48000"
    assert sent.headers["xi-api-key"] == TEST_KEY_VALUE
    assert body == {
        "text": TEXT,
        "model_id": "eleven_v4",
        "language_code": "mr",
        "pronunciation_dictionary_locators": [
            {"pronunciation_dictionary_id": "pd123", "version_id": "v7"}
        ],
    }
    chars = len(TEXT)
    assert out.usage.units == chars
    assert out.usage.amount_micros == -(-chars * 80_000 // 1000)
    assert out.usage.price_ref == "elevenlabs-api-pricing@PR-12"
    assert out.duration_ms == chars * 48_000 // 20 * 1000 // 48_000
    assert out.usage.external_request_id is not None
    adapter2, mock2, _ = make()
    adapter2.synthesize(
        req(pronunciation_dictionary_ref="pd123", sample_rate_hz=44_100), idempotency_key=K
    )
    body2 = json.loads(mock2.requests[0].content)
    assert body2["pronunciation_dictionary_locators"] == [{"pronunciation_dictionary_id": "pd123"}]
    assert mock2.requests[0].url.params["output_format"] == "wav_44100"


def test_cost_rounds_up() -> None:
    adapter, _, _ = make()
    out = adapter.synthesize(req(text="क"), idempotency_key=K)
    assert out.usage.amount_micros == 80


@pytest.mark.parametrize(
    "kw",
    [
        {"voice_ref": "../v1/user"},
        {"pronunciation_dictionary_ref": "bad ref!"},
        {"sample_rate_hz": 11_025},
        {"emotion": TtsEmotion.WARM},
    ],
)
def test_bad_inputs_refused_before_any_request(kw: dict[str, Any]) -> None:
    adapter, mock, _ = make()
    with pytest.raises(InputInvalidError):
        adapter.synthesize(req(**kw), idempotency_key=K)
    assert mock.requests == []


def test_emotion_only_with_a_complete_owner_tag_map() -> None:
    partial = CAT.model_copy(update={"emotion_audio_tags": {"WARM": "[warm]"}})
    adapter, _, _ = make(cat=partial)
    assert adapter.capabilities().emotion_control is ControlSupport.NONE
    full_map = {e.value: f"[{e.value.lower()}]" for e in TtsEmotion}
    adapter, mock, _ = make(cat=CAT.model_copy(update={"emotion_audio_tags": full_map}))
    assert adapter.capabilities().emotion_control is ControlSupport.NATIVE
    out = adapter.synthesize(req(emotion=TtsEmotion.WARM), idempotency_key=K)
    assert json.loads(mock.requests[0].content)["text"] == f"[warm] {TEXT}"
    assert out.usage.units == len(TEXT) + len("[warm] ")  # tags are billed (PR-12)


def test_capabilities_are_conservative_over_enabled_models() -> None:
    adapter, _, _ = make()
    caps = adapter.capabilities()
    assert caps.max_chars_per_request == 5000  # eleven_v3 limit (v4 is 10,000)
    assert caps.languages == ("en", "hi", "mr")
    assert caps.pace_control is ControlSupport.NONE
    assert caps.phoneme_support is False
    only_v4 = CAT.model_copy(update={"models": {"eleven_v4": CAT.models["eleven_v4"]}})
    v4, _, _ = make(cat=only_v4)
    assert v4.capabilities().max_chars_per_request == 10_000
    assert v4.capabilities().phoneme_support is True


def test_voice_settings_from_catalogue_are_sent() -> None:
    cat = CAT.model_copy(update={"voice_settings": {"stability": 0.5, "similarity_boost": 0.75}})
    adapter, mock, _ = make(cat=cat)
    adapter.synthesize(req(), idempotency_key=K)
    assert json.loads(mock.requests[0].content)["voice_settings"] == {
        "stability": 0.5,
        "similarity_boost": 0.75,
    }


@pytest.mark.parametrize(
    "content",
    [b"not audio", wav_bytes(0, 48_000), wav_bytes(100, 48_000, width=1), wav_bytes(100, 24_000)],
)
def test_audio_is_checked(content: bytes) -> None:
    adapter, mock, _ = make()
    mock.script.append(Scripted(200, content))
    with pytest.raises(CorruptedOutputError):
        adapter.synthesize(req(), idempotency_key=K)


@pytest.mark.failure_injection
@pytest.mark.parametrize(
    ("status", "detail", "error"),
    [
        (401, {"type": "authentication_error"}, AuthInvalidError),
        (402, {"type": "payment_required"}, AuthInvalidError),
        (404, {"type": "not_found", "code": "voice_not_found"}, ConfigInvalidError),
        (422, [{"loc": ["body"], "msg": "x", "type": "y"}], InputInvalidError),
    ],
)
def test_error_mapping(status: int, detail: object, error: type[Exception]) -> None:
    adapter, mock, _ = make()
    mock.script.append(Scripted(status, {"detail": detail}))
    with pytest.raises(error) as info:
        adapter.synthesize(req(), idempotency_key=K)
    if status == 404:
        assert getattr(info.value, "upstream_code", None) == "voice_not_found"
    assert len(mock.requests) == 1


@pytest.mark.failure_injection
def test_429_without_retry_after_backs_off_in_call() -> None:
    adapter, mock, sleeps = make()
    mock.script.append(Scripted(429, {"detail": {"code": "concurrent_limit_exceeded"}}))
    adapter.synthesize(req(), idempotency_key=K)
    assert len(mock.requests) == 2
    assert sleeps == [1.0]
    adapter2, mock2, _ = make()
    for _ in range(3):
        mock2.script.append(Scripted(429, {"detail": {"code": "rate_limit_exceeded"}}))
    with pytest.raises(RateLimitedError) as info:
        adapter2.synthesize(req(), idempotency_key=K)
    assert info.value.upstream_code == "rate_limit_exceeded"


def test_list_voices_paginates_and_reads_languages() -> None:
    voices = [
        {"voice_id": f"v{i}", "name": f"Voice {i}", "verified_languages": [{"language": "mr"}]}
        for i in range(3)
    ] + [{"voice_id": "nolang"}, {"name": "no id"}]
    cat = CAT.model_copy(update={"list_voices_page_size": 2})
    adapter, mock, _ = make(mock=MockElevenLabs(voices), cat=cat)
    out = adapter.list_voices(VoiceListRequest(language="mr"), idempotency_key=K)
    assert [v.voice_ref for v in out.voices] == ["v0", "v1", "v2"]
    assert len(mock.requests) == 3
    every = adapter.list_voices(VoiceListRequest(), idempotency_key=make_idempotency_key(
        ORG.new(), "tts.synthesize", ["x", "y", "cd" * 32, "z"]))  # fmt: skip
    assert "nolang" in [v.voice_ref for v in every.voices]
    bad, bad_mock, _ = make()
    bad_mock.script.append(Scripted(200, {"voices": "nope"}))
    with pytest.raises(CorruptedOutputError):
        bad.list_voices(VoiceListRequest(), idempotency_key=K)


def test_recorded_fixture_replay() -> None:
    transport = RecordedTransport(Path(__file__).parent / "fixtures" / "elevenlabs_http")
    adapter, _, _ = make(transport=transport)
    out = adapter.synthesize(req(), idempotency_key=K)
    assert out.duration_ms == 500
    assert out.usage.external_request_id == "elrecorded01"
    adapter.close()
