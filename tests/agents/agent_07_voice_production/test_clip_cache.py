"""CCR-269 (03 section 8 rule 5, cache clips): the clip name carries the SHA-256 of the canonical
TTS request; the audio SHA-256 is recorded in a sidecar; a cache read verifies the clip against
it (a mismatch is a miss plus a warning); a lost concurrent-miss race reuses the verified winner."""

import copy
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from amw_adapters.common import request_sha256
from amw_adapters.tts.protocol import TtsRequest, TtsResult
from amw_core.enums import OutputStatus
from amw_core.ids import Prefix, new_id
from tests.agents.agent_07_voice_production.support import (
    ToneTts,
    exec_ctx,
    tone_samples,
    wav_bytes,
)
from tests.agents.agent_07_voice_production.test_contracts import cases
from tests.agents.agent_07_voice_production.voice_world import VoiceWorld
from tests.agents.agent_07_voice_production.voice_world import build as build_voice

SECOND_ATTEMPT = "att_01939e5a-7c3b-7d1e-8a4f-0123456789a2"


def _voice(tmp: Path) -> VoiceWorld:
    case = next(x for x in cases("voice_synthesis") if x["case_id"] == "VS-01")
    return build_voice(copy.deepcopy(case), tmp)


def _clips(w: VoiceWorld) -> list[str]:
    return sorted(u for u in w.blobs.data if "/cache/agent_07/" in u and u.endswith(".wav"))


def _sidecar(uri: str) -> str:
    return uri[: -len(".wav")] + ".audio.json"


def _next_task(w: VoiceWorld) -> Any:
    nxt = w.task_input.model_copy(update={"task_id": new_id(Prefix.TASK)})
    return nxt, exec_ctx(nxt, SECOND_ATTEMPT)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_the_name_is_the_request_hash_and_the_sidecar_records_the_audio_hash(
    tmp_path: Path,
) -> None:
    w = _voice(tmp_path)
    assert w.run().status is OutputStatus.SUCCEEDED
    clips = _clips(w)
    assert clips
    request_hashes = {request_sha256(r) for r in w.tts.requests}
    for uri in clips:
        stem = uri.rsplit("/", 1)[1][: -len(".wav")]
        assert stem.rsplit("-", 1)[1] in request_hashes  # input address, not the audio hash
        assert _sha(w.blobs.data[uri]) not in uri
        side = json.loads(w.blobs.data[_sidecar(uri)])
        assert side["audio_sha256"] == _sha(w.blobs.data[uri])
        assert side["request_sha256"] == stem.rsplit("-", 1)[1]


def test_every_tts_request_field_is_in_the_key() -> None:
    """TtsRequest does carry pace, emotion and the pronunciation dictionary (the review thought
    it did not); request_sha256 hashes the whole model, so each one changes the clip name."""
    assert set(TtsRequest.model_fields) == {
        "text",
        "voice_ref",
        "model",
        "language",
        "sample_rate_hz",
        "pronunciation_dictionary_ref",
        "pace",
        "emotion",
    }
    base = TtsRequest(text="a", voice_ref="v", model="m", language="mr")
    pace = next(iter(type(base).model_fields["pace"].annotation.__args__[0]))  # type: ignore[union-attr]
    emo = next(iter(type(base).model_fields["emotion"].annotation.__args__[0]))  # type: ignore[union-attr]
    variants = [
        base.model_copy(update={"text": "b"}),
        base.model_copy(update={"voice_ref": "w"}),
        base.model_copy(update={"model": "n"}),
        base.model_copy(update={"language": "hi"}),
        base.model_copy(update={"sample_rate_hz": 16_000}),
        base.model_copy(update={"pronunciation_dictionary_ref": "d"}),
        base.model_copy(update={"pace": pace}),
        base.model_copy(update={"emotion": emo}),
    ]
    hashes = {request_sha256(base), *(request_sha256(v) for v in variants)}
    assert len(hashes) == len(variants) + 1


def test_a_verified_clip_is_reused_without_a_provider_call(tmp_path: Path) -> None:
    w = _voice(tmp_path)
    assert w.run().status is OutputStatus.SUCCEEDED
    calls = w.tts.invocations
    nxt, ctx = _next_task(w)
    out = w.stage.run(nxt, ctx)
    assert out.status is OutputStatus.SUCCEEDED
    assert w.tts.invocations == calls


def test_a_clip_whose_audio_differs_from_the_recorded_hash_is_a_miss_and_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    w = _voice(tmp_path)
    assert w.run().status is OutputStatus.SUCCEEDED
    calls = w.tts.invocations
    victim = _clips(w)[0]
    tampered = wav_bytes(tone_samples(777))  # another valid clip at the path
    w.blobs.data[victim] = tampered
    nxt, ctx = _next_task(w)
    with caplog.at_level(logging.WARNING, logger="agent_07"):
        out = w.stage.run(nxt, ctx)
    assert any(r.message == "voice.cache_unverified" for r in caplog.records)
    assert w.tts.invocations > calls  # a miss: the provider is called, the blob was not used
    # the tampered blob is never silently used: the write-once path is refused, not overwritten
    assert out.status is not OutputStatus.SUCCEEDED
    assert w.blobs.data[victim] == tampered  # never overwritten
    assert out.error is not None
    assert out.error.code == "AGENT.CORRUPTED_OUTPUT"


def test_a_clip_without_a_recorded_hash_is_a_miss_and_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    w = _voice(tmp_path)
    assert w.run().status is OutputStatus.SUCCEEDED
    calls = w.tts.invocations
    victim = _clips(w)[0]
    del w.blobs.data[_sidecar(victim)]
    nxt, ctx = _next_task(w)
    with caplog.at_level(logging.WARNING, logger="agent_07"):
        w.stage.run(nxt, ctx)
    assert any(
        r.message == "voice.cache_unverified" and r.reason == "no_recorded_hash"  # type: ignore[attr-defined]
        for r in caplog.records
    )
    assert w.tts.invocations > calls


class _RacingTts(ToneTts):
    """A non-deterministic provider: while this attempt's call is in flight another attempt
    stores its own (different) clip for the same request."""

    def __init__(self, plant: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.plant = plant

    def synthesize(self, request: TtsRequest, *, idempotency_key: str) -> TtsResult:
        result = super().synthesize(request, idempotency_key=idempotency_key)
        self.plant(request_sha256(request))
        return result


def _race(tmp_path: Path, *, record_sidecar: bool, honest: bool) -> tuple[VoiceWorld, Any, bytes]:
    w = _voice(tmp_path)
    assert w.run().status is OutputStatus.SUCCEEDED
    clips = _clips(w)
    first = {u: w.blobs.data[u] for u in clips}
    for uri in clips:  # back to "both attempts miss"
        del w.blobs.data[uri]
        del w.blobs.data[_sidecar(uri)]
    winner_audio = wav_bytes(tone_samples(3000))
    planted: list[str] = []

    def plant(request_hash: str) -> None:
        for uri in first:
            if uri.endswith(f"-{request_hash}.wav") and uri not in w.blobs.data and not planted:
                w.blobs.data[uri] = winner_audio
                if record_sidecar:
                    recorded = _sha(winner_audio if honest else b"something else")
                    w.blobs.data[_sidecar(uri)] = json.dumps(
                        {"request_sha256": request_hash, "audio_sha256": recorded}, sort_keys=True
                    ).encode()
                planted.append(uri)

    w.tts.__class__ = _RacingTts  # same fake, plus the in-flight competitor
    w.tts.plant = plant  # type: ignore[attr-defined]
    nxt, ctx = _next_task(w)
    return w, w.stage.run(nxt, ctx), winner_audio


def test_a_lost_race_reuses_the_verified_winner(tmp_path: Path) -> None:
    w, out, winner_audio = _race(tmp_path, record_sidecar=True, honest=True)
    assert out.status is OutputStatus.SUCCEEDED
    kept = [u for u in w.blobs.data if w.blobs.data[u] == winner_audio]
    assert len(kept) == 1  # the winner's clip stays; nothing was overwritten
    # the loser did not store a second clip for the same request
    names = [u for u in _clips(w) if u == kept[0]]
    assert names == kept


def test_a_lost_race_against_an_unverifiable_winner_is_corruption(tmp_path: Path) -> None:
    _, out, _ = _race(tmp_path, record_sidecar=False, honest=True)
    assert out.status is not OutputStatus.SUCCEEDED
    assert out.error is not None
    assert out.error.code == "AGENT.CORRUPTED_OUTPUT"
    _, out2, _ = _race(tmp_path / "b", record_sidecar=True, honest=False)
    assert out2.status is not OutputStatus.SUCCEEDED
    assert out2.error is not None
    assert out2.error.code == "AGENT.CORRUPTED_OUTPUT"
