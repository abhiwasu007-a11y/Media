"""ElevenLabs Create speech adapter for the Eleven v3 / v4 class (ADR-008; PR-04, PR-11, PR-12).

* Model allow-list from the catalogue: only models whose language list in the research log has
  Marathi AND whose character limit is documented are enabled (``eleven_v4``, ``eleven_v3``).
  Multilingual v2, Flash and Turbo v2.x are refused (``CONFIG_INVALID``); so is any unknown id.
  ``model_id`` is always sent, because the provider default is Multilingual v2 (PR-11).
* Request language: the primary subtag must be in the model's verified languages; it is sent as
  ``language_code`` (the provider would silently ignore an unsupported one, PR-11).
* Style controls (``TtsCapabilities``): pace is ``NATIVE`` only for a model whose catalogue entry
  has ``speed_control`` (then ``TtsRequest.pace`` is sent as ``voice_settings.speed`` from the
  catalogue ``pace_speed`` map; v4 has no speed slider, v3 is undocumented, PR-11); emotion is
  ``NATIVE`` only when the catalogue maps every ``TtsEmotion`` to an audio tag (owner / 3B
  listening test), else ``NONE``. A control the adapter
  does not declare (pace, emotion, pronunciation dictionary) is refused (``INPUT_INVALID``),
  never ignored. ``markup_delimiters`` come from the catalogue (audio tags, PR-12).
* Every paid request goes through the injected ``CallGuard`` (worst case before, real cost after).
* Pronunciation dictionary: ``pronunciation_dictionary_ref`` = ``<dictionary id>`` or
  ``<dictionary id>@<version id>`` -> one ``pronunciation_dictionary_locators`` entry.
* Output: ``wav_<sample_rate_hz>`` (18 section 5: 48 kHz); the bytes are checked to be a 16-bit
  PCM WAV at that rate (``AGENT.CORRUPTED_OUTPUT`` otherwise); ``duration_ms`` from its frames.
* Cost ESTIMATE = Unicode code points of the text actually sent (audio tag included, PR-12) x the
  catalogue price per 1K characters, rounded up.
* No in-adapter chunking: a text above the model limit is ``INPUT_INVALID`` (the caller splits by
  sentence, agent_07), so one key is always exactly one paid request.
"""

import io
import re
import wave
from collections.abc import Callable
from typing import Any, Final

import httpx

from amw_adapters.common import CallUsage
from amw_adapters.real.catalogue import ElevenLabsCatalogue, ElevenLabsModel
from amw_adapters.real.guard import CallGuard, PlannedCall, require_guard
from amw_adapters.real.http import (
    DEFAULT_BACKOFF,
    ProviderHttp,
    json_or_empty,
    retry_after_ms,
    status_error,
)
from amw_adapters.real.memory import CallMemory
from amw_adapters.real.secrets import SecretRef
from amw_adapters.tts.protocol import (
    OPERATION_LIST_VOICES,
    OPERATION_SYNTHESIZE,
    ControlSupport,
    TtsCapabilities,
    TtsEmotion,
    TtsRequest,
    TtsResult,
    VoiceInfo,
    VoiceList,
    VoiceListRequest,
)
from amw_core.config import RetryPolicySettings
from amw_core.enums import CostUnitKind
from amw_core.errors import (
    AmwError,
    ConfigInvalidError,
    CorruptedOutputError,
    InputInvalidError,
)

PROVIDER: Final = "elevenlabs"
_VOICE_ID = re.compile(r"^[A-Za-z0-9]{1,64}$")
_DICT_REF = re.compile(r"^(?P<id>[A-Za-z0-9]{1,64})(?:@(?P<version>[A-Za-z0-9]{1,64}))?$")


def _classify(response: httpx.Response) -> AmwError:
    detail = json_or_empty(response).get("detail")
    code = None
    if isinstance(detail, dict):
        raw = detail.get("code") or detail.get("type")
        code = str(raw) if raw else None
    return status_error(
        response.status_code, provider=PROVIDER, upstream_code=code,
        retry_after=retry_after_ms(response),
    )  # fmt: skip


def _primary(language: str) -> str:
    return language.split("-", 1)[0].lower()


class ElevenLabsTtsAdapter:
    """``TtsAdapter`` for ElevenLabs Create speech (``POST /v1/text-to-speech/{voice_id}``)."""

    def __init__(
        self,
        catalogue: ElevenLabsCatalogue,
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

    def _emotion_support(self) -> ControlSupport:
        tags = self._cat.emotion_audio_tags
        return (
            ControlSupport.NATIVE
            if all(e.value in tags for e in TtsEmotion)
            else ControlSupport.NONE
        )

    def capabilities(self) -> TtsCapabilities:
        """Conservative over every enabled model (a caller may pick any of them per request)."""
        models = list(self._cat.enabled_models.values())
        languages = set(models[0].languages)
        for m in models[1:]:
            languages &= set(m.languages)
        limits = [m.max_chars_per_request for m in models if m.max_chars_per_request is not None]
        pace = all(m.speed_control for m in models)
        return TtsCapabilities(
            pace_control=ControlSupport.NATIVE if pace else ControlSupport.NONE,
            emotion_control=self._emotion_support(),
            phoneme_support=all(m.ipa_inline for m in models),
            languages=tuple(sorted(languages)),
            max_chars_per_request=min(limits),
            markup_delimiters=self._cat.markup_delimiters,
        )

    def _check(self, request: TtsRequest) -> tuple[ElevenLabsModel, str, str]:
        model = self._cat.model(request.model)
        if _primary(request.language) not in model.languages:
            raise ConfigInvalidError(
                "language is not verified for this TTS model",
                details={"model": request.model, "language": request.language},
            )
        if not _VOICE_ID.match(request.voice_ref):
            raise InputInvalidError("voice_ref is not a provider voice id")
        if request.pace is not None and not (
            model.speed_control and request.pace.value in self._cat.pace_speed
        ):
            raise InputInvalidError(
                "this model declares no pace control", details={"model": request.model}
            )
        if request.pronunciation_dictionary_ref is not None and not model.pronunciation_dictionary:
            raise InputInvalidError(
                "this model declares no pronunciation dictionary support",
                details={"model": request.model},
            )
        text = request.text
        if request.emotion is not None:
            if self._emotion_support() is ControlSupport.NONE:
                raise InputInvalidError("this adapter has no emotion control")
            text = f"{self._cat.emotion_audio_tags[request.emotion.value]} {text}"
        assert model.max_chars_per_request is not None  # noqa: S101 - enabled => limit (catalogue)
        if len(text) > model.max_chars_per_request:
            raise InputInvalidError(
                "text exceeds max_chars_per_request",
                details={"model": request.model, "max": model.max_chars_per_request},
            )
        if request.sample_rate_hz not in self._cat.wav_sample_rates_hz:
            raise InputInvalidError(
                "sample rate has no WAV output format", details={"hz": request.sample_rate_hz}
            )
        return model, text, f"wav_{request.sample_rate_hz}"

    def _body(self, request: TtsRequest, text: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "text": text,
            "model_id": request.model,
            "language_code": _primary(request.language),
        }
        settings: dict[str, float | bool] = dict(self._cat.voice_settings or {})
        if request.pace is not None:  # _check: the model has speed_control and a mapped speed
            settings["speed"] = self._cat.pace_speed[request.pace.value]
        if settings:
            body["voice_settings"] = settings
        if request.pronunciation_dictionary_ref is not None:
            match = _DICT_REF.match(request.pronunciation_dictionary_ref)
            if match is None:
                raise InputInvalidError("pronunciation_dictionary_ref is not '<id>[@<version>]'")
            locator: dict[str, str] = {"pronunciation_dictionary_id": match["id"]}
            if match["version"]:
                locator["version_id"] = match["version"]
            body["pronunciation_dictionary_locators"] = [locator]
        return body

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult:
        digest, stored = self.memory.lookup(
            OPERATION_SYNTHESIZE, idempotency_key, request, TtsResult
        )
        if stored is not None:
            return stored
        try:
            result = self._synthesize(request, idempotency_key)
        except AmwError as exc:
            self.memory.failed(OPERATION_SYNTHESIZE, idempotency_key, exc.code)
            raise
        self.memory.store(OPERATION_SYNTHESIZE, idempotency_key, digest, result)
        return result

    def _synthesize(self, request: TtsRequest, key: str) -> TtsResult:
        model, text, output_format = self._check(request)
        body = self._body(request, text)
        characters = len(text)
        amount = -(-characters * model.price_micros_per_1k_chars // 1000)
        self._guard.before(
            PlannedCall(PROVIDER, OPERATION_SYNTHESIZE, amount, self._cat.currency, key)
        )
        headers = {
            "xi-api-key": self._secret.reveal(),
            "content-type": "application/json",
            "accept": "audio/wav",
        }
        outcome = self._http.send(
            "POST", f"/v1/text-to-speech/{request.voice_ref}", operation=OPERATION_SYNTHESIZE,
            headers=headers, timeout_ms=self._cat.synthesize_timeout_ms,
            json_body=body, params={"output_format": output_format},
        )  # fmt: skip
        audio = outcome.response.content
        request_id = outcome.response.headers.get("request-id")
        self._http.log.info(
            "provider.call",
            extra={
                "provider": PROVIDER,
                "operation": OPERATION_SYNTHESIZE,
                "model": request.model,
                "request_id": request_id,
                "attempts": outcome.attempts,
                "duration_ms": outcome.duration_ms,
                "characters": characters,
                "audio_bytes": len(audio),
                "amount_micros": amount,
            },
        )
        usage = CallUsage(
            provider=PROVIDER,
            operation=OPERATION_SYNTHESIZE,
            model=request.model,
            units=characters,
            unit_kind=CostUnitKind.CHARACTERS,
            chars_in=characters,
            language=request.language,
            amount_micros=amount,
            currency=self._cat.currency,
            price_ref=self._cat.price_ref,
            idempotency_key=key,
            external_request_id=request_id,
        )
        self._guard.after(usage)  # the audio was billed even if it turns out unusable
        frames, rate = _wav_facts(audio)
        if rate != request.sample_rate_hz:
            raise CorruptedOutputError("provider WAV sample rate differs from the request")
        return TtsResult(
            audio=audio,
            media_type="audio/wav",
            duration_ms=frames * 1000 // rate,
            sample_rate_hz=rate,
            usage=usage,
        )

    def list_voices(self, request: VoiceListRequest, *, idempotency_key: str) -> VoiceList:
        digest, stored = self.memory.lookup(
            OPERATION_LIST_VOICES, idempotency_key, request, VoiceList
        )
        if stored is not None:
            return stored
        try:
            self._guard.before(
                PlannedCall(PROVIDER, OPERATION_LIST_VOICES, 0, self._cat.currency, idempotency_key)
            )
            voices = self._list(request)
        except AmwError as exc:
            self.memory.failed(OPERATION_LIST_VOICES, idempotency_key, exc.code)
            raise
        usage = CallUsage(
            provider=PROVIDER,
            operation=OPERATION_LIST_VOICES,
            amount_micros=0,  # metadata, no characters synthesized
            currency=self._cat.currency,
            idempotency_key=idempotency_key,
        )
        result = VoiceList(voices=voices, usage=usage)
        self.memory.store(OPERATION_LIST_VOICES, idempotency_key, digest, result)
        return result

    def _list(self, request: VoiceListRequest) -> tuple[VoiceInfo, ...]:
        wanted = _primary(request.language) if request.language else None
        out: list[VoiceInfo] = []
        token: str | None = None
        for _page in range(self._cat.list_voices_max_pages):
            params: dict[str, str | int] = {"page_size": self._cat.list_voices_page_size}
            if token:
                params["next_page_token"] = token
            outcome = self._http.send(
                "GET", "/v2/voices", operation=OPERATION_LIST_VOICES,
                headers={"xi-api-key": self._secret.reveal(), "accept": "application/json"},
                timeout_ms=self._cat.list_timeout_ms, params=params,
            )  # fmt: skip
            data = json_or_empty(outcome.response)
            raw = data.get("voices")
            if not isinstance(raw, list):
                raise CorruptedOutputError("voice list missing", provider=PROVIDER)
            for voice in raw:
                info = _voice_info(voice)
                if info is not None and (wanted is None or wanted in info.languages):
                    out.append(info)
            token = data.get("next_page_token") if data.get("has_more") is True else None
            if not isinstance(token, str) or not token:
                break
        return tuple(out)


def _voice_info(voice: object) -> VoiceInfo | None:
    if not isinstance(voice, dict) or not isinstance(voice.get("voice_id"), str):
        return None
    langs: list[str] = []
    for entry in voice.get("verified_languages") or ():
        if isinstance(entry, dict) and isinstance(entry.get("language"), str):
            langs.append(_primary(entry["language"]))
    labels = voice.get("labels")
    if isinstance(labels, dict) and isinstance(labels.get("language"), str):
        langs.append(_primary(labels["language"]))
    name = voice.get("name")
    return VoiceInfo(
        voice_ref=voice["voice_id"],
        name=name if isinstance(name, str) else voice["voice_id"],
        languages=tuple(dict.fromkeys(langs)),
    )


def _wav_facts(audio: bytes) -> tuple[int, int]:
    """(frames, sample rate) of a non-empty 16-bit PCM WAV; ``CORRUPTED_OUTPUT`` otherwise."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            frames, rate, width = handle.getnframes(), handle.getframerate(), handle.getsampwidth()
    except wave.Error, EOFError:
        raise CorruptedOutputError("provider audio is not a WAV file", provider=PROVIDER) from None
    if width != 2 or frames == 0 or rate <= 0:
        raise CorruptedOutputError("provider audio is not non-empty 16-bit PCM", provider=PROVIDER)
    return frames, rate
