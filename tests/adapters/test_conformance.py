"""Conformance suite run against every adapter fake (27 section 7.1: adapters ship with fakes).

Contract for every call: takes an idempotency key; returns ``CallUsage`` with ``ESTIMATE`` cost;
same key + same request replays without a new billable call; same key + different request is
``PERMANENT.IDEMPOTENCY_CONFLICT``; configured failures raise typed 07 errors; results are
deterministic; recorded fixtures override synthesized results; no network is touched.
"""

import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from amw_adapters.common import AdapterResult, FailurePlan, FakeEngine, FixtureStore
from amw_adapters.file_delivery import (
    DeliveryFile,
    DeliveryRequest,
    FakeFileDeliveryAdapter,
    FileDeliveryAdapter,
)
from amw_adapters.image import FakeImageAdapter, ImageAdapter, ImageRequest
from amw_adapters.library import LibraryLicenseRequest, LibrarySearchRequest
from amw_adapters.llm import FakeLlmAdapter, LlmAdapter, LlmMessage, LlmRequest
from amw_adapters.music import FakeMusicAdapter, MusicAdapter
from amw_adapters.stock_footage import FakeStockFootageAdapter, StockFootageAdapter
from amw_adapters.tts import FakeTtsAdapter, TtsAdapter, TtsRequest, VoiceListRequest
from amw_adapters.video_gen import FakeVideoGenAdapter, VideoGenAdapter, VideoGenRequest
from amw_adapters.web_fetch import FakeWebFetchAdapter, WebFetchAdapter, WebFetchRequest
from amw_core.enums import AspectRatio, CostFigureKind
from amw_core.errors import (
    ConfigInvalidError,
    IdempotencyConflictError,
    InputInvalidError,
    ProviderRefusalError,
    RateLimitedError,
)
from amw_core.ids import JOB, ORG, make_idempotency_key

FIXTURES = FixtureStore(Path(__file__).parent / "fixtures")
ORG_ID = ORG.new()
JOB_ID = JOB.new()


def key(n: int) -> str:
    return make_idempotency_key(ORG_ID, "llm.call", ["tsk_conformance", "step", n])


def llm_req(system: str = "s", text: str = "hello world") -> LlmRequest:
    return LlmRequest(
        model="fake-model",
        system=system,
        messages=(LlmMessage(role="user", content=text),),
        max_output_tokens=256,
    )


def delivery_req(name: str = "final.mp4") -> DeliveryRequest:
    uri = f"amw-blob://{ORG_ID}/jobs/{JOB_ID}/renders/x.mp4"
    return DeliveryRequest(
        org_id=ORG_ID,
        job_id=JOB_ID,
        deliverable_preset="yt_master_1080p",
        files=(
            DeliveryFile(
                name=name, uri=uri, sha256="ab" * 32, size_bytes=10, media_type="video/mp4"
            ),
        ),
    )


Call = Callable[[Any, str, str], AdapterResult]
"""(fake, idempotency key, variant) -> result; variant changes the request."""


@dataclass(frozen=True)
class Case:
    name: str
    factory: Callable[..., Any]
    protocol: type
    call: Call
    fixture_variant: str | None
    fixture_check: Callable[[AdapterResult], bool] | None


def _llm(f: FakeLlmAdapter, k: str, v: str) -> AdapterResult:
    return f.complete(llm_req(system=v), idempotency_key=k)


def _llm_count(f: FakeLlmAdapter, k: str, v: str) -> AdapterResult:
    return f.count_tokens(llm_req(text=f"count {v}"), idempotency_key=k)


def _tts(f: FakeTtsAdapter, k: str, v: str) -> AdapterResult:
    req = TtsRequest(text=f"namaskar {v}", voice_ref=v, model="fake-tts", language="mr")
    return f.synthesize(req, idempotency_key=k)


def _voices(f: FakeTtsAdapter, k: str, v: str) -> AdapterResult:
    return f.list_voices(VoiceListRequest(language=v), idempotency_key=k)


def _search(f: Any, k: str, v: str) -> AdapterResult:
    result: AdapterResult = f.search(LibrarySearchRequest(query=v), idempotency_key=k)
    return result


def _license(f: Any, k: str, v: str) -> AdapterResult:
    req = LibraryLicenseRequest(vendor_item_id=v, licence_ref="lic_x")
    result: AdapterResult = f.license(req, idempotency_key=k)
    return result


def _image(f: FakeImageAdapter, k: str, v: str) -> AdapterResult:
    req = ImageRequest(prompt=v, model="fake-img", width_px=1280, height_px=720)
    return f.generate(req, idempotency_key=k)


def _video(f: FakeVideoGenAdapter, k: str, v: str) -> AdapterResult:
    req = VideoGenRequest(
        prompt=v, model="fake-vid", duration_ms=3000, aspect_ratio=AspectRatio.R16_9
    )
    return f.generate(req, idempotency_key=k)


def _deliver(f: FakeFileDeliveryAdapter, k: str, v: str) -> AdapterResult:
    return f.deliver(delivery_req(name=f"{v.replace(' ', '_')}.mp4"), idempotency_key=k)


def _fetch(f: FakeWebFetchAdapter, k: str, v: str) -> AdapterResult:
    return f.fetch(
        WebFetchRequest(url=f"https://example.org/{v.replace(' ', '_')}"), idempotency_key=k
    )


CASES = [
    Case("llm.complete", FakeLlmAdapter, LlmAdapter, _llm, "fixture-system",
         lambda r: getattr(r, "text", None) == "recorded reply" and r.usage.tokens_cached_in == 8),
    Case("llm.count_tokens", FakeLlmAdapter, LlmAdapter, _llm_count, None, None),
    Case("tts.synthesize", FakeTtsAdapter, TtsAdapter, _tts, "fixture-voice",
         lambda r: getattr(r, "duration_ms", None) == 4321),
    Case("tts.list_voices", FakeTtsAdapter, TtsAdapter, _voices, None, None),
    Case("stock.search", FakeStockFootageAdapter, StockFootageAdapter, _search, "fixture query",
         lambda r: [i.vendor_item_id for i in getattr(r, "items", ())] == ["vendor-123"]),
    Case("stock.license", FakeStockFootageAdapter, StockFootageAdapter, _license, None, None),
    Case("music.search", FakeMusicAdapter, MusicAdapter, _search, "fixture query",
         lambda r: [i.vendor_item_id for i in getattr(r, "items", ())] == ["track-9"]),
    Case("music.license", FakeMusicAdapter, MusicAdapter, _license, None, None),
    Case("image.generate", FakeImageAdapter, ImageAdapter, _image, "fixture prompt",
         lambda r: r.usage.amount_micros == 4242),
    Case("video.generate", FakeVideoGenAdapter, VideoGenAdapter, _video, "fixture prompt",
         lambda r: getattr(r, "duration_ms", None) == 5000),
    Case("delivery.file", FakeFileDeliveryAdapter, FileDeliveryAdapter, _deliver, None, None),
    Case("web.fetch", FakeWebFetchAdapter, WebFetchAdapter, _fetch, "fixture",
         lambda r: getattr(r, "content", None) == b"recorded page"),
]  # fmt: skip
IDS = [c.name for c in CASES]
OPERATIONS = {
    "llm.complete": "llm.completion",
    "llm.count_tokens": "llm.count_tokens",
    "tts.synthesize": "tts.synthesize",
    "tts.list_voices": "tts.list_voices",
    "stock.search": "stock.search",
    "stock.license": "stock.license",
    "music.search": "music.search",
    "music.license": "music.license",
    "image.generate": "image.generate",
    "video.generate": "video.generate",
    "delivery.file": "delivery.file",
    "web.fetch": "web.fetch",
}


def _engine(fake: Any) -> FakeEngine:
    engine: FakeEngine = fake.engine
    return engine


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_satisfies_protocol(case: Case) -> None:
    fake: Any = case.factory()
    conforms = isinstance(fake, case.protocol)
    assert conforms
    assert fake.provider


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_usage_is_ledger_ready(case: Case) -> None:
    fake = case.factory()
    result = case.call(fake, key(1), "a")
    usage = result.usage
    assert usage.figure_kind is CostFigureKind.ESTIMATE
    assert usage.idempotency_key == key(1)
    assert usage.provider == fake.provider
    assert usage.amount_micros >= 0
    assert isinstance(usage.amount_micros, int)
    assert usage.currency == "USD"
    assert usage.operation == OPERATIONS[case.name]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_deterministic(case: Case) -> None:
    assert case.call(case.factory(), key(1), "a") == case.call(case.factory(), key(1), "a")


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_replay_same_key_same_request(case: Case) -> None:
    fake = case.factory()
    first = case.call(fake, key(1), "a")
    second = case.call(fake, key(1), "a")
    assert first == second
    engine = _engine(fake)
    assert engine.billable_calls == 1
    assert [c.outcome for c in engine.calls] == ["ok", "replayed"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_same_key_different_request_conflicts(case: Case) -> None:
    fake = case.factory()
    case.call(fake, key(1), "a")
    with pytest.raises(IdempotencyConflictError):
        case.call(fake, key(1), "b")


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_distinct_keys_are_distinct_calls(case: Case) -> None:
    fake = case.factory()
    case.call(fake, key(1), "a")
    case.call(fake, key(2), "a")
    assert _engine(fake).billable_calls == 2


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_invalid_key_rejected(case: Case) -> None:
    with pytest.raises(InputInvalidError):
        case.call(case.factory(), "not-a-key", "a")


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_sequenced_failure_then_retry_succeeds(case: Case) -> None:
    plan = FailurePlan(sequence=[RateLimitedError("429", retry_after_ms=1000)])
    fake = case.factory(failures=plan)
    with pytest.raises(RateLimitedError) as info:
        case.call(fake, key(1), "a")
    assert info.value.retry_after_ms == 1000
    result = case.call(fake, key(1), "a")
    assert result.usage.idempotency_key == key(1)
    assert [c.outcome for c in _engine(fake).calls] == ["TEMPORARY.RATE_LIMITED", "ok"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_failure_by_key(case: Case) -> None:
    plan = FailurePlan(by_key={key(7): ProviderRefusalError("refused")})
    fake = case.factory(failures=plan)
    case.call(fake, key(1), "a")
    with pytest.raises(ProviderRefusalError):
        case.call(fake, key(7), "a")
    case.call(fake, key(7), "a")


@pytest.mark.parametrize("case", [c for c in CASES if c.fixture_variant], ids=lambda c: c.name)
def test_recorded_fixture_overrides(case: Case) -> None:
    assert case.fixture_variant is not None
    assert case.fixture_check is not None
    with_fixture = case.call(case.factory(fixtures=FIXTURES), key(1), case.fixture_variant)
    assert case.fixture_check(with_fixture)
    without = case.call(case.factory(), key(1), case.fixture_variant)
    assert not case.fixture_check(without)


def test_network_is_blocked() -> None:
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("example.invalid", 443))


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_unknown_provider_rejected(case: Case) -> None:
    with pytest.raises(ConfigInvalidError):
        case.factory(provider="anthropic")
